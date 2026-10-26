from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from .schema import dump


DEFECTS = ("metric_average", "split_leakage", "baseline_budget")


def inject(source: Path, destination: Path, defect: str, repo_id: str) -> list[dict]:
    """Controlled fixture adapter. Never patch arbitrary repositories heuristically.

    External repos need their own validated injector/probe adapter.
    Labels are kept OUTSIDE the artifact and outside planner observations.
    """
    if defect not in (*DEFECTS, "clean"):
        raise ValueError("Unknown defect")
    if destination.exists():
        raise ValueError("Injection target must not exist")
    task_raw = json.loads((source / "task.json").read_text())
    artifact = (source / task_raw["repo"]).resolve()
    config = json.loads((artifact / "experiment.json").read_text())
    if config.get("metric_average") != "macro" or set(config["train_ids"]) & set(config["test_ids"]) \
            or config["method_steps"] != config["baseline_steps"]:
        raise ValueError("Injection source must be the known clean fixture")
    destination.mkdir(parents=True)
    shutil.copytree(artifact, destination / "artifact", ignore=shutil.ignore_patterns("__pycache__"))
    if defect == "metric_average":
        config["metric_average"] = "micro"
    elif defect == "split_leakage":
        config["test_ids"][0] = config["train_ids"][0]
    elif defect == "baseline_budget":
        config["baseline_steps"] = max(1, config["method_steps"] // 10)
    dump(destination / "artifact" / "experiment.json", config)
    # repo_id is the original repository lineage, NOT the injected variant.
    task_raw.update(repo="artifact", repo_id=repo_id, paper_id=f"{repo_id}-{defect}")
    dump(destination / "task.json", task_raw)
    mapping = {"metric_average": "metric", "split_leakage": "split_disjoint", "baseline_budget": "baseline_equal"}
    labels = [{"repo_id": repo_id, "paper_id": task_raw["paper_id"], "claim_id": c["id"],
               "label": int(c["kind"] == mapping.get(defect)), "defect": defect}
              for c in task_raw["claims"]]
    return labels


def split_for_repo(repo_id: str, seed="articheck-v1", train=.8, validation=.1):
    if not 0 <= train <= 1 or not 0 <= validation <= 1 or train + validation > 1:
        raise ValueError("Invalid split fractions")
    fraction = int(hashlib.sha256(f"{seed}:{repo_id}".encode()).hexdigest(), 16) / 2**256
    return "train" if fraction < train else "validation" if fraction < train + validation else "test"


def group_split(rows: list[dict], seed="articheck-v1"):
    if any(not row.get("repo_id") for row in rows):
        raise ValueError("Original repository lineage repo_id is required")
    groups = {"train": [], "validation": [], "test": []}
    for row in rows:
        groups[split_for_repo(row["repo_id"], seed)].append(row)
    return groups


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def export_sft(trace_paths: list[Path], approval_path: Path, output: Path):
    """Only export externally accepted teacher episodes; acceptance isn't self-reported.

    approval JSONL: run_id, accepted, reviewer, source ('human'/'rule'), teacher_model.
    Rules/people must score factual correctness using held-out ground truth first.
    """
    approvals = {}
    for row in read_jsonl(approval_path):
        if row["run_id"] in approvals:
            raise ValueError("Duplicate approval run_id")
        approvals[row["run_id"]] = row
    samples = []
    for path in trace_paths:
        for row in read_jsonl(path):
            approval = approvals.get(row.get("run_id"), {})
            if row.get("kind") != "model" or row.get("role") != "planner" or approval.get("accepted") is not True:
                continue
            if not approval.get("reviewer") or approval.get("source") not in {"human", "rule"}:
                raise ValueError("Acceptance requires reviewer and source")
            if row.get("model") != approval.get("teacher_model") or row.get("finish_reason") != "stop":
                continue
            from .planner import parse_action
            obs = json.loads(row["messages"][-1]["content"])
            parse_action(row["text"], obs)
            samples.append({"messages": row["messages"] + [{"role": "assistant", "content": row["text"]}],
                            "run_id": row["run_id"], "teacher_model": row["model"],
                            "acceptance": approval})
    write_jsonl(output, samples)
    return len(samples)
