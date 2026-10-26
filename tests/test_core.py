from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from articheck.adapters.upstream import import_report
from articheck.data import DEFECTS, export_sft, group_split, inject, read_jsonl, write_jsonl
from articheck.evaluation import metrics, select_threshold
from articheck.llm import OpenAIPlannerClient
from articheck.pipeline import review
from articheck.planner import messages_for, observation, parse_action
from articheck.roles import CrossAuditor
from articheck.runtime import Budget, BudgetExceeded, Node, ResultCache, repo_digest, run_dag
from articheck.sandbox import Sandbox
from articheck.schema import Claim, Evidence, Task, dump
from articheck.trace import TraceWriter, validate_tokens
from articheck.training.export import export_rl, token_batches
from articheck.training.objective import clipped_importance_weight, dynamic_groups, reward

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_all_injected_defects_and_clean_end_to_end(self):
        from articheck.cli import run_demo
        asyncio.run(run_demo(EXAMPLES, self.root / "demo", "local"))
        results = json.loads((self.root / "demo/metrics.json").read_text())
        self.assertEqual((results["tp"], results["fp"], results["tn"], results["fn"]), (3, 0, 9, 0))
        for defect in ("clean", *DEFECTS):
            report = json.loads((self.root / "demo" / defect / "report.json").read_text())
            self.assertEqual(report["usage"]["tools"], 1)
            self.assertEqual(report["stop_reason"], "complete")
            trace = read_jsonl(self.root / "demo" / defect / "trace.jsonl")
            self.assertFalse(any(row["kind"] == "model" for row in trace))

    def test_group_split_keeps_all_repository_variants_together(self):
        rows = [{"repo_id": f"repo-{i}", "variant": j} for i in range(100) for j in range(4)]
        groups = group_split(rows)
        sets = [{r["repo_id"] for r in value} for value in groups.values()]
        self.assertTrue(all(not a & b for i, a in enumerate(sets) for b in sets[i+1:]))
        self.assertEqual(sum(map(len, groups.values())), 400)
        self.assertEqual(groups, group_split(rows))

    def test_metrics_hand_computed(self):
        rows = [{"label": 1, "score": .8}, {"label": 1, "score": .2},
                {"label": 0, "score": .7}, {"label": 0, "score": .1}]
        result = metrics(rows)
        self.assertEqual(result["macro_f1"], .5)
        self.assertEqual(result["false_positive_rate"], .5)
        self.assertEqual(result["issue_recall"], .5)
        calibrated = select_threshold(rows, 0)
        self.assertEqual(calibrated["false_positive_rate"], 0)
        self.assertEqual(calibrated["issue_recall"], .5)

    def test_calibration_requires_both_classes(self):
        with self.assertRaises(ValueError):
            select_threshold([{"label": 0, "score": 0}])
        with self.assertRaises(ValueError):
            metrics([{"label": 0, "score": float("nan")}])

    def test_missing_failed_or_invalid_evidence_never_accuses(self):
        claim = Task.load(EXAMPLES / "task.json").claims[0]
        auditor = CrossAuditor()
        for evidence in (None, Evidence("E1", "probe", False, {}),
                         Evidence("E2", "probe", True, {"payload": {"macro_f1": float("nan")}})):
            self.assertEqual(auditor.check(claim, evidence).verdict, "inconclusive")

    def test_empty_split_is_inconclusive(self):
        claim = Task.load(EXAMPLES / "task.json").claims[1]
        result = CrossAuditor().check(claim, Evidence("E", "probe", True, {"payload": {"train_ids": [], "test_ids": []}}))
        self.assertEqual(result.verdict, "inconclusive")

    def test_budget_exhaustion_leaves_unknown_claims(self):
        result = asyncio.run(review(Task.load(EXAMPLES / "task.json"), self.root / "run",
                                    Sandbox("local"), budget=Budget(max_tools=0)))
        self.assertTrue(result["stop_reason"].startswith("budget_exhausted"))
        self.assertTrue(all(f["verdict"] == "inconclusive" for f in result["findings"]))

    def test_stop_early_does_not_mark_unchecked_claims_supported(self):
        class StopPlanner:
            async def choose(self, *args):
                return {"action": "stop"}
        result = asyncio.run(review(Task.load(EXAMPLES / "task.json"), self.root / "run",
                                    Sandbox("local"), StopPlanner()))
        self.assertEqual(result["stop_reason"], "planner_stop")
        self.assertTrue(all(f["verdict"] == "inconclusive" for f in result["findings"]))

    def test_cache_hit_and_content_invalidation(self):
        target = self.root / "fixture"
        inject(EXAMPLES, target, "clean", "repo")
        task = Task.load(target / "task.json")
        one = asyncio.run(review(task, self.root / "one", Sandbox("local")))
        two = asyncio.run(review(task, self.root / "two", Sandbox("local")))
        self.assertEqual(one["usage"]["tools"], 1)
        self.assertEqual(two["usage"]["tools"], 0)
        self.assertTrue(two["evidence"][0]["provenance"]["cache_hit"])
        config = json.loads((task.repo / "experiment.json").read_text())
        config["baseline_steps"] = 10
        dump(task.repo / "experiment.json", config)
        three = asyncio.run(review(task, self.root / "three", Sandbox("local")))
        self.assertEqual(three["usage"]["tools"], 1)
        self.assertEqual(three["findings"][2]["verdict"], "issue")

    def test_cache_identity_includes_image_and_command(self):
        self.assertNotEqual(ResultCache.key("x", ["a"], {"image_id": "1"}),
                            ResultCache.key("x", ["a"], {"image_id": "2"}))
        self.assertNotEqual(ResultCache.key("x", ["a"], {}), ResultCache.key("x", ["b"], {}))

    def test_duplicate_claims_rejected(self):
        raw = json.loads((EXAMPLES / "task.json").read_text())
        raw["repo"] = str(EXAMPLES / "toy_artifact")
        raw["claims"].append(raw["claims"][0])
        dump(self.root / "task.json", raw)
        with self.assertRaises(ValueError):
            Task.load(self.root / "task.json")

    def test_dag_parallel_dependencies_and_cycle_validation(self):
        async def first(_):
            return 2
        async def last(values):
            return values["a"] + values["b"]
        result = asyncio.run(run_dag([Node("a", (), first), Node("b", (), first), Node("c", ("a", "b"), last)]))
        self.assertEqual(result["c"], 4)
        with self.assertRaises(ValueError):
            asyncio.run(run_dag([Node("a", ("b",), first), Node("b", ("a",), first)]))

    def test_injection_refuses_to_overwrite(self):
        with self.assertRaises(ValueError):
            inject(EXAMPLES, self.root, "clean", "repo")

    def test_observation_has_no_ground_truth(self):
        obs = observation(Task.load(EXAMPLES / "task.json").claims, set(), 2)
        self.assertFalse({"labels", "ground_truth", "defect", "repo_id"} & obs.keys())
        with self.assertRaises(ValueError):
            parse_action('{"action":"check","claim_id":"UNKNOWN"}', obs)
        with self.assertRaises(ValueError):
            parse_action('{"action":"shell","command":"echo hi"}', obs)

    def test_symlink_snapshot_rejected(self):
        (self.root / "link").symlink_to(EXAMPLES / "task.json")
        with self.assertRaises(ValueError):
            repo_digest(self.root)

    def test_upstream_failure_is_not_defect(self):
        dump(self.root / "base.json", {"claim_verdicts": [{"claim": "A", "status": "not_reproduced"}]})
        imported = import_report(self.root / "base.json", self.root / "import.json")
        self.assertEqual(imported["findings"][0]["verdict"], "inconclusive")
        self.assertTrue(imported["import_only"])

    def test_feedback_preserves_original_and_marks_hard_samples(self):
        from articheck.feedback import record_feedback
        dump(self.root / "report.json", {"run_id": "r", "paper_id": "p", "repo_id": "repo",
             "findings": [{"claim_id": "C", "verdict": "issue"}]})
        row = record_feedback(self.root / "report.json", self.root / "feedback.jsonl", "C", 0, "human", "Recomputed independently")
        self.assertTrue(row["hard_sample"])
        self.assertEqual(row["previous_verdict"], "issue")
        self.assertEqual(json.loads((self.root / "report.json").read_text())["findings"][0]["verdict"], "issue")

    def test_distinct_claim_probes_obey_shared_tool_budget(self):
        task = Task.load(EXAMPLES / "task.json")
        task.cacheable = False
        task.claims[1].probe = ["python3", "-c", 'print("{}")']
        result = asyncio.run(review(task, self.root / "run", Sandbox("local"), budget=Budget(max_tools=1)))
        self.assertEqual(result["usage"]["tools"], 1)
        self.assertEqual(result["findings"][0]["verdict"], "supported")
        self.assertTrue(all(f["verdict"] == "inconclusive" for f in result["findings"][1:]))

    def test_stochastic_task_does_not_read_result_cache(self):
        task = Task.load(EXAMPLES / "task.json")
        task.cacheable = False
        one = asyncio.run(review(task, self.root / "one", Sandbox("local")))
        two = asyncio.run(review(task, self.root / "two", Sandbox("local")))
        self.assertEqual(one["usage"]["tools"], 1)
        self.assertEqual(two["usage"]["tools"], 1)

    def test_unavailable_tokens_cannot_be_exported_as_rl(self):
        row = {"kind": "model", "role": "planner", "prompt_ids": None, "response_ids": None}
        write_jsonl(self.root / "trace.jsonl", [row])
        with self.assertRaises(ValueError):
            export_rl([self.root / "trace.jsonl"], self.root / "out.jsonl")

    def test_native_token_validation(self):
        row = {"prompt_ids": [1], "response_ids": [2, 3], "behavior_logprobs": [-.1, -.2],
               "token_source": "native", "policy_version": "sha123"}
        validate_tokens(row)
        with self.assertRaises(ValueError):
            validate_tokens({**row, "behavior_logprobs": [-.1]})

    def test_sft_export_requires_external_acceptance(self):
        obs = observation(Task.load(EXAMPLES / "task.json").claims, set(), 2)
        row = {"run_id": "R1", "kind": "model", "role": "planner", "model": "teacher",
               "messages": messages_for(obs), "text": '{"action":"stop"}', "finish_reason": "stop"}
        write_jsonl(self.root / "trace", [row])
        write_jsonl(self.root / "approvals", [])
        self.assertEqual(export_sft([self.root / "trace"], self.root / "approvals", self.root / "sft"), 0)
        write_jsonl(self.root / "approvals", [{"run_id": "R1", "accepted": True, "source": "human",
                                               "reviewer": "reviewer1", "teacher_model": "teacher"}])
        self.assertEqual(export_sft([self.root / "trace"], self.root / "approvals", self.root / "sft"), 1)

    def test_reward_penalizes_false_accusations_and_missing_labels(self):
        good = reward([{"claim_id": "C", "verdict": "supported"}], {"C": 0})
        false = reward([{"claim_id": "C", "verdict": "issue"}], {"C": 0})
        self.assertGreater(good, false)
        with self.assertRaises(ValueError):
            reward([], {"C": 0})
        self.assertEqual(clipped_importance_weight(10, -10, 2), 2)
        self.assertEqual(dynamic_groups([[{"reward": 1}, {"reward": 1}], [{"reward": 0}, {"reward": 1}]]),
                         [[{"reward": 0}, {"reward": 1}]])

    def test_token_budget_batching(self):
        row = {"prompt_ids": [1, 2], "response_ids": [3]}
        self.assertEqual([len(x) for x in token_batches([row]*3, 6)], [2, 1])
        with self.assertRaises(ValueError):
            list(token_batches([row], 2))

    def test_local_sandbox_filters_environment_and_failure(self):
        with patch.dict(os.environ, {"SECRET_EXAMPLE": "do-not-leak"}):
            result = asyncio.run(Sandbox("local").execute(self.root, [sys.executable, "-c",
                'import os,json; print(json.dumps({"secret":os.getenv("SECRET_EXAMPLE")}))']))
        self.assertTrue(result["success"])
        self.assertIsNone(result["payload"]["secret"])
        failure = asyncio.run(Sandbox("local").execute(self.root, [sys.executable, "-c", "raise SystemExit(1)"]))
        self.assertFalse(failure["success"])

    def test_local_timeout_and_overflow(self):
        result = asyncio.run(Sandbox("local", timeout=.1).execute(self.root, [sys.executable, "-c", "import time; time.sleep(5)"]))
        self.assertTrue(result["timed_out"])
        result = asyncio.run(Sandbox("local", output_limit=100).execute(self.root, [sys.executable, "-c", 'print("x"*1000)']))
        self.assertTrue(result["output_overflow"])
        self.assertFalse(result["success"])

    def test_docker_flags_and_no_shell_interpolation(self):
        argv = Sandbox().docker_command(self.root, ["python3", "probe.py", "$(bad)"], "test")
        for flag in ("--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges"):
            self.assertIn(flag, argv)
        self.assertEqual(argv[-1], "$(bad)")
        self.assertNotIn("--privileged", argv)

    def test_native_client_passes_server_ids_without_retokenizing(self):
        client = OpenAIPlannerClient("http://localhost:8000/v1", "model", "sha", native=True)
        requests = []
        def post(path, data):
            requests.append((path, data))
            if path == "../tokenize":
                return {"tokens": [11, 12]}
            return {"choices": [{"text": '{"action":"stop"}', "token_ids": [13],
                                 "logprobs": {"token_logprobs": [-.2]}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 1}}
        client.post = post
        budget = Budget(max_tokens=1000)
        trace = TraceWriter(self.root / "trace", "run")
        reply = asyncio.run(client.complete([{"role": "user", "content": "hello"}], budget, trace))
        self.assertEqual(requests[1][1]["prompt"], [11, 12])
        self.assertEqual(reply.metadata["response_ids"], [13])
        self.assertEqual(budget.tokens, 3)


if __name__ == "__main__":
    unittest.main()
