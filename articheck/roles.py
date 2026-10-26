from __future__ import annotations

import math
import os
import shutil
from dataclasses import asdict
from pathlib import Path

from .schema import Claim, Evidence, Finding, Task


class LiteratureReader:
    async def run(self, task: Task):
        # MVP consumes a human-reviewed manifest; upstream can supply PDF extraction.
        return {"claims": [asdict(c) for c in task.claims], "paper_text": task.paper_text,
                "extraction": "manifest", "source": "human_review_required"}


class CodeInspector:
    async def run(self, task: Task):
        files = [str(p.relative_to(task.repo)) for p in task.repo.rglob("*") if p.is_file()]
        return {"files": sorted(files), "probe": task.probe,
                "note": "Inventory only; filenames are not scientific evidence"}


class ExperimentRunner:
    def __init__(self, sandbox, cache, budget, repo_hash):
        self.sandbox, self.cache, self.budget, self.repo_hash = sandbox, cache, budget, repo_hash

    async def run(self, task: Task, probe: list[str] | None = None):
        identity = await self.sandbox.identity()
        argv = probe or task.probe
        if self.sandbox.mode == "local":
            executable = shutil.which(argv[0], path=os.defpath)
            if executable:
                stat = Path(executable).resolve().stat()
                identity["executable"] = {"path": executable, "mtime_ns": stat.st_mtime_ns, "size": stat.st_size}
        key = self.cache.key(self.repo_hash, argv, identity)
        cached = self.cache.get(key) if task.cacheable else None
        if cached is not None:
            return Evidence(key, "artifact_probe", cached["success"], cached,
                            {"cache_hit": True, "repo_sha256": self.repo_hash, "sandbox": identity})
        self.budget.tool()
        value = await self.sandbox.execute(task.repo, argv)
        # Failure/transient output is not cached.
        if value["success"] and task.cacheable:
            self.cache.put(key, value)
        return Evidence(key, "artifact_probe", value["success"], value,
                        {"cache_hit": False, "repo_sha256": self.repo_hash, "sandbox": identity})


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


class CrossAuditor:
    def check(self, claim: Claim, evidence: Evidence | None) -> Finding:
        if evidence is None or not evidence.success:
            return Finding(claim.id, "inconclusive", 0, "No successful execution evidence")
        payload = evidence.payload.get("payload", {})
        spec = claim.spec
        try:
            if claim.kind == "metric":
                actual = payload[spec["key"]]
                if not finite_number(actual):
                    raise ValueError("Metric is not finite")
                issue = abs(actual - spec["expected"]) > spec["tolerance"]
                reason = f"Observed {actual}; expected {spec['expected']} ± {spec['tolerance']}"
            elif claim.kind == "split_disjoint":
                train, test = payload[spec["train_key"]], payload[spec["test_key"]]
                if not isinstance(train, list) or not isinstance(test, list) or not train or not test:
                    raise ValueError("Nonempty split ID arrays required")
                overlap = set(train) & set(test)
                issue = bool(overlap)
                reason = f"Train/test overlap: {len(overlap)} IDs"
            else:
                method, baseline = payload[spec["method_key"]], payload[spec["baseline_key"]]
                if not finite_number(method) or not finite_number(baseline) or min(method, baseline) <= 0:
                    raise ValueError("Positive numeric training budgets required")
                issue = method != baseline
                reason = f"Method steps={method}; baseline steps={baseline}"
        except (KeyError, TypeError, ValueError) as exc:
            return Finding(claim.id, "inconclusive", 0, f"Missing/invalid evidence: {exc}", [evidence.id])
        # These scores are rule outputs, not empirical confidence estimates.
        return Finding(claim.id, "issue" if issue else "supported", 1.0 if issue else 0.0,
                       reason + "; result limited to supplied probe", [evidence.id])


class Reporter:
    @staticmethod
    def markdown(report: dict) -> str:
        lines = [f"# ArtiCheck — {report['paper_id']}", "", f"Run: `{report['run_id']}`",
                 f"Policy: `{report['policy']}`; execution mode: `{report['sandbox']}`", "",
                 "Verdicts apply only to supplied claims and probe evidence. A successful probe is not full paper reproduction.", "",
                 "| Claim | Verdict | Evidence | Reason |", "|---|---|---|---|"]
        def cell(value):
            return str(value).replace("|", "\\|").replace("\n", " ")
        for row in report["findings"]:
            lines.append("| " + " | ".join(cell(v) for v in [row["claim_id"], row["verdict"],
                         ", ".join(row["evidence_ids"]), row["reason"]]) + " |")
        lines += ["", f"Stop reason: {report['stop_reason']}",
                  f"Tool calls: {report['usage']['tools']}; model tokens: {report['usage']['tokens']}; "
                  f"configured API cost: ${report['usage']['usd']:.6f}", "",
                  "Cost excludes GPU rental and infrastructure. No trained-model benchmark is claimed."]
        return "\n".join(lines) + "\n"
