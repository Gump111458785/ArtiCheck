from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from .planner import FixedPlanner, observation
from .roles import LiteratureReader, CodeInspector, ExperimentRunner, CrossAuditor, Reporter
from .runtime import Budget, BudgetExceeded, Node, ResultCache, repo_digest, run_dag
from .sandbox import Sandbox
from .schema import Task, dump
from .trace import TraceWriter


async def review(task: Task, output: Path, sandbox=None, planner=None, budget=None, cache_root=None):
    sandbox, planner, budget = sandbox or Sandbox(), planner or FixedPlanner(), budget or Budget()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "report.json").exists() or (output / "trace.jsonl").exists():
        raise ValueError("Use a fresh output directory; review records are immutable")
    run_id = uuid.uuid4().hex
    trace = TraceWriter(output / "trace.jsonl", run_id)
    started = time.monotonic()
    snapshot = repo_digest(task.repo)
    async def literature(_):
        return await LiteratureReader().run(task)
    async def inspect(_):
        return await CodeInspector().run(task)
    preflight = await run_dag([Node("literature", (), literature), Node("code", (), inspect)])
    trace.write("preflight", data=preflight, repo_sha256=snapshot)
    cache = ResultCache(cache_root or output.parent / ".cache")
    runner = ExperimentRunner(sandbox, cache, budget, snapshot)
    auditor, checked, findings = CrossAuditor(), set(), {}
    evidence, stop_reason = None, "complete"
    evidence_by_probe = {}
    by_id = {c.id: c for c in task.claims}
    try:
        # Timeout wraps model calls, preflight inventory already completed.
        async def loop():
            nonlocal evidence, stop_reason
            for turn in range(len(task.claims) + 1):
                budget.check()
                obs = observation(task.claims, checked, budget.max_tools - budget.tools,
                                  [asdict(f) for f in findings.values()])
                action = await planner.choose(obs, budget, trace)
                trace.write("decision", turn=turn, observation=obs, action=action)
                if action["action"] == "stop":
                    stop_reason = "planner_stop" if len(checked) < len(task.claims) else "complete"
                    break
                claim_id = action["claim_id"]
                if claim_id not in by_id or claim_id in checked:
                    raise ValueError("Invalid planner claim selection")
                probe = by_id[claim_id].probe or task.probe
                probe_key = tuple(probe)
                if probe_key not in evidence_by_probe:
                    evidence = await runner.run(task, probe)
                    evidence_by_probe[probe_key] = evidence
                    trace.write("tool", evidence=asdict(evidence))
                evidence = evidence_by_probe[probe_key]
                findings[claim_id] = auditor.check(by_id[claim_id], evidence)
                checked.add(claim_id)
                trace.write("audit", finding=asdict(findings[claim_id]))
        remaining = budget.max_seconds - (time.monotonic() - budget.started)
        if remaining <= 0:
            raise BudgetExceeded("wall-clock budget exceeded")
        await asyncio.wait_for(loop(), timeout=remaining)
    except (BudgetExceeded, asyncio.TimeoutError) as exc:
        stop_reason = f"budget_exhausted: {exc}"
    except (RuntimeError, ValueError, OSError, KeyError) as exc:
        stop_reason = f"execution_error: {type(exc).__name__}: {exc}"
    for claim in task.claims:
        if claim.id not in findings:
            findings[claim.id] = auditor.check(claim, None)
    changed = repo_digest(task.repo) != snapshot
    if changed:
        stop_reason = "artifact_changed_during_run"
        findings = {c.id: auditor.check(c, None) for c in task.claims}
    report = {"schema_version": 1, "run_id": run_id, "paper_id": task.paper_id, "repo_id": task.repo_id,
              "repo_sha256": snapshot, "policy": type(planner).__name__, "sandbox": sandbox.mode,
              "findings": [asdict(findings[c.id]) for c in task.claims],
              "evidence": [asdict(e) for e in evidence_by_probe.values()], "stop_reason": stop_reason,
              "elapsed_seconds": time.monotonic() - started,
              "usage": {"tools": budget.tools, "tokens": budget.tokens, "usd": budget.usd}}
    dump(output / "report.json", report)
    (output / "report.md").write_text(Reporter.markdown(report))
    trace.write("complete", report=report)
    return report
