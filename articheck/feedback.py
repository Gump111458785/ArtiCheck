from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .data import read_jsonl, write_jsonl


def record_feedback(report_path: Path, output: Path, claim_id: str, label: int, reviewer: str, reason: str):
    report = json.loads(report_path.read_text())
    finding = next((f for f in report["findings"] if f["claim_id"] == claim_id), None)
    if finding is None or label not in (0, 1) or not reviewer.strip() or not reason.strip():
        raise ValueError("Existing claim, binary label, reviewer and correction reason are required")
    row = {"run_id": report["run_id"], "paper_id": report["paper_id"], "repo_id": report["repo_id"],
           "claim_id": claim_id, "label": label, "previous_verdict": finding["verdict"],
           "reviewer": reviewer, "reason": reason, "source": "human",
           "timestamp": datetime.now(timezone.utc).isoformat(),
           "hard_sample": (finding["verdict"] == "issue") != bool(label) or finding["verdict"] == "inconclusive"}
    rows = read_jsonl(output) if output.exists() else []
    rows.append(row)
    write_jsonl(output, rows)
    return row
