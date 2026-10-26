from __future__ import annotations

import json
from pathlib import Path

from ..schema import dump

UPSTREAM = "https://github.com/1a1a11a/2026_paper_reproduce"
UPSTREAM_COMMIT = "dffac1885dbca1aff9b28d79916140b8af71dedf"


def import_report(source: Path, output: Path):
    raw = json.loads(source.read_text())
    mapping = {"reproduced": "supported", "partially_reproduced": "inconclusive",
               "not_reproduced": "inconclusive", "not_attempted": "inconclusive"}
    # A failed reproduction is NOT automatically a scientific defect accusation.
    claims = raw.get("claim_verdicts", [])
    findings = []
    for i, claim in enumerate(claims, 1):
        status = claim["status"]
        if status not in mapping:
            raise ValueError("Unknown upstream claim status")
        findings.append({"claim_id": f"upstream-{i}", "text": claim["claim"],
                         "verdict": mapping[status], "score": 0.0,
                         "reason": claim.get("notes", ""), "upstream_status": status,
                         "unverified_evidence": claim.get("evidence", [])})
    result = {"schema_version": 1, "source": UPSTREAM, "reference_commit": UPSTREAM_COMMIT,
              "actual_upstream_commit": raw.get("articheck_upstream_commit", "unknown"),
              "paper": raw.get("paper", {}), "repository": raw.get("repository", {}),
              "findings": findings, "import_only": True,
              "note": "Imported assertions require independent evidence validation before training/evaluation"}
    dump(output, result)
    return result
