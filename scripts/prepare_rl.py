"""Convert label JSONL + task manifests to verl parquet; no label in prompt."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from articheck.data import group_split, read_jsonl
from articheck.planner import messages_for, observation
from articheck.schema import Task


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, nargs="+", required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    args = parser.parse_args()
    from datasets import Dataset
    truth = read_jsonl(args.labels)
    rows = []
    for path in args.tasks:
        task = Task.load(path)
        labels = {r["claim_id"]: r["label"] for r in truth
                  if r["repo_id"] == task.repo_id and r["paper_id"] == task.paper_id}
        if set(labels) != {c.id for c in task.claims}:
            raise ValueError(f"Incomplete labels for {task.paper_id}")
        rows.append({"repo_id": task.repo_id, "data_source": "articheck", "agent_name": "articheck",
                     "prompt": messages_for(observation(task.claims, set(), 2)),
                     "ability": "artifact_pre_review",
                     "reward_model": {"style": "rule", "ground_truth": json.dumps(labels)},
                     "extra_info": {"task_path": str(path.resolve()), "sandbox": args.sandbox,
                                    "cache_root": str((args.output / "probe_cache").resolve())}})
    args.output.mkdir(parents=True, exist_ok=True)
    for name, split in group_split(rows).items():
        if split:
            Dataset.from_list(split).to_parquet(str(args.output / f"{name}.parquet"))
        else:
            print(f"WARNING: empty {name} split; add independent original repositories")


if __name__ == "__main__":
    main()
