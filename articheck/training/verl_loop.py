"""Original adapter targeting verl commit 0bd668c1aa7b63c5f174f7dcb1c5de12e0c74a0b.

Uses verl public Continuous Token APIs. GPU execution is not validated here.
Only planner generations receive loss; artifact observations receive zero mask.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict
from pathlib import Path
from uuid import uuid4

from verl.experimental.agent_loop.agent_loop import AgentLoopBase, AgentLoopOutput

from ..planner import observation, parse_action
from ..roles import CrossAuditor, ExperimentRunner
from ..runtime import Budget, ResultCache, repo_digest
from ..sandbox import Sandbox
from ..schema import Task
from .objective import reward


class ArtiCheckAgentLoop(AgentLoopBase):
    async def run(self, sampling_params: dict, **kwargs):
        extra = kwargs["extra_info"]
        task = Task.load(Path(extra["task_path"]))
        labels = json.loads(kwargs["reward_model"]["ground_truth"])
        # Labels are consulted only by the terminal reward function below.
        messages = [dict(m) for m in kwargs["raw_prompt"]]
        initial = await self.ct_build_initial_tokens(messages)
        runtime_ids, mask, logprobs = list(initial), [], []
        checked, findings = set(), {}
        budget = Budget(max_tools=2, max_seconds=120)
        sandbox = Sandbox(extra.get("sandbox", "docker"), timeout=30)
        runner = ExperimentRunner(sandbox, ResultCache(Path(extra["cache_root"])), budget, repo_digest(task.repo))
        auditor, evidence_by_probe = CrossAuditor(), {}
        request_id, failure = uuid4().hex, None
        turns = 0
        try:
            for _ in range(len(task.claims) + 1):
                budget.check()
                obs = observation(task.claims, checked, budget.max_tools-budget.tools,
                                  [asdict(f) for f in findings.values()])
                remaining = self.rollout_config.response_length - len(mask)
                if remaining < 32:
                    break
                params = {**sampling_params, "max_tokens": min(256, remaining), "logprobs": 1}
                remaining_seconds = budget.max_seconds - (time.monotonic() - budget.started)
                generated = await asyncio.wait_for(self.server_manager.generate(
                    request_id=request_id, prompt_ids=runtime_ids, sampling_params=params), remaining_seconds)
                if not generated.token_ids or generated.log_probs is None \
                        or len(generated.token_ids) != len(generated.log_probs):
                    raise ValueError("verl sampler must return native token IDs and aligned log-probs")
                merged, mask, logprobs = await self.ct_merge_assistant_token(
                    runtime_ids, generated.token_ids, mask, logprobs,
                    assistant_logprobs=generated.log_probs)
                runtime_ids = merged.token_ids
                text = self.tokenizer.decode(generated.token_ids, skip_special_tokens=True)
                messages.append({"role": "assistant", "content": text})
                turns += 1
                action = parse_action(text, obs)
                if action["action"] == "stop":
                    break
                claim = next(c for c in task.claims if c.id == action["claim_id"])
                probe_key = tuple(claim.probe or task.probe)
                if probe_key not in evidence_by_probe:
                    evidence_by_probe[probe_key] = await runner.run(task, list(probe_key))
                evidence = evidence_by_probe[probe_key]
                finding = auditor.check(claim, evidence)
                findings[claim.id] = finding
                checked.add(claim.id)
                updated = messages + [{"role": "user", "content": json.dumps({
                    "observation": observation(task.claims, checked, budget.max_tools-budget.tools,
                                               [asdict(f) for f in findings.values()]),
                    "last_finding": asdict(finding)})}]
                merged, mask, logprobs = await self.ct_merge_context_msg(
                    messages, updated, runtime_ids, mask, logprobs)
                runtime_ids, messages = merged.token_ids, updated
        except (ValueError, RuntimeError, OSError, asyncio.TimeoutError) as exc:
            failure = str(exc)
        for claim in task.claims:
            if claim.id not in findings:
                findings[claim.id] = auditor.check(claim, None)
        score = reward([asdict(f) for f in findings.values()], labels, budget.tools, sum(mask))
        if failure:
            score -= 1
        if len(mask) > self.rollout_config.response_length:
            # Truncate only the training tensor, penalize interrupted episodes.
            score -= 1
        response_length = min(len(mask), self.rollout_config.response_length)
        prompt_length = len(runtime_ids) - len(mask)
        if response_length == 0:
            raise ValueError("No planner token generated; cannot construct trainable trajectory")
        return AgentLoopOutput(
            prompt_ids=runtime_ids[:prompt_length],
            response_ids=runtime_ids[prompt_length:prompt_length+response_length],
            response_mask=mask[:response_length], response_logprobs=logprobs[:response_length],
            reward_score=score, num_turns=turns*2, metrics={"tool_calls": 0.0},
            extra_fields={"findings": [asdict(f) for f in findings.values()], "failure": failure,
                          "policy_scope": "planner_only"})
