from __future__ import annotations

from pathlib import Path

from ..data import read_jsonl, write_jsonl
from ..trace import validate_tokens


def export_rl(traces: list[Path], output: Path):
    rows = []
    for path in traces:
        for row in read_jsonl(path):
            if row.get("kind") != "model" or row.get("role") != "planner":
                continue
            validate_tokens(row)
            rows.append({k: row[k] for k in ("run_id", "policy_version", "prompt_ids", "response_ids", "behavior_logprobs")})
    write_jsonl(output, rows)
    return len(rows)


def token_batches(rows: list[dict], max_tokens: int):
    """Greedy batching, rejects oversize samples instead of silent truncation."""
    if max_tokens <= 0:
        raise ValueError("Positive token budget required")
    batch, size = [], 0
    for row in rows:
        length = len(row["prompt_ids"]) + len(row["response_ids"])
        if length > max_tokens:
            raise ValueError("Sample exceeds batch token budget")
        if size + length > max_tokens:
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += length
    if batch:
        yield batch
