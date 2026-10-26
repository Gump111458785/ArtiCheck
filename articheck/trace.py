from __future__ import annotations

import json
import math
from pathlib import Path


class TraceWriter:
    def __init__(self, path: Path, run_id: str):
        self.path, self.run_id = path, run_id
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, kind: str, **fields):
        row = {"schema_version": 1, "run_id": self.run_id, "kind": kind, **fields}
        with self.path.open("a") as file:
            file.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n")


def validate_tokens(row: dict):
    prompt, response, probs = (row.get(k) for k in ("prompt_ids", "response_ids", "behavior_logprobs"))
    if not prompt or not response or not probs or len(response) != len(probs):
        raise ValueError("Training requires native prompt/response IDs and aligned behavior log-probs")
    if not all(type(x) is int and x >= 0 for x in prompt + response):
        raise ValueError("Invalid native token IDs")
    if not all(isinstance(x, (int, float)) and math.isfinite(x) and x <= 1e-6 for x in probs):
        raise ValueError("Invalid behavior log-probs")
    if row.get("token_source") != "native" or not row.get("policy_version"):
        raise ValueError("Training requires native provenance and a policy version")
