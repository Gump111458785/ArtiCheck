from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from .data import DEFECTS, export_sft, group_split, inject, read_jsonl, write_jsonl
from .evaluation import join_report, metrics, select_threshold
from .pipeline import review
from .planner import FixedPlanner, ModelPlanner
from .runtime import Budget
from .sandbox import Sandbox
from .schema import Task, dump


def main():
    parser = argparse.ArgumentParser(description="ArtiCheck artifact pre-review MVP")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Review a manifest and local artifact snapshot")
    run.add_argument("--task", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    run.add_argument("--image", default="python:3.11-slim")
    run.add_argument("--planner", choices=["fixed", "model"], default="fixed")
    run.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    run.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    run.add_argument("--policy-version", default="untrained-base")
    run.add_argument("--native-tokens", action="store_true")
    run.add_argument("--max-tools", type=int, default=8)
    run.add_argument("--max-tokens", type=int, default=32000)
    run.add_argument("--max-seconds", type=float, default=180)
    run.add_argument("--max-usd", type=float, default=1)
    run.add_argument("--input-price", type=float, default=0, help="USD per million input tokens")
    run.add_argument("--output-price", type=float, default=0, help="USD per million output tokens")

    demo = sub.add_parser("demo", help="Run clean + 3 controlled injected fixtures")
    demo.add_argument("--output", type=Path, required=True)
    demo.add_argument("--sandbox", choices=["docker", "local"], default="docker")
    demo.add_argument("--examples", type=Path, default=Path(__file__).resolve().parents[1] / "examples")

    inj = sub.add_parser("inject", help="Inject one known defect into a compatible clean fixture")
    inj.add_argument("--source", type=Path, required=True)
    inj.add_argument("--output", type=Path, required=True)
    inj.add_argument("--repo-id", required=True, help="Original repository lineage, shared by all variants")
    inj.add_argument("--defect", choices=["clean", *DEFECTS], required=True)

    split = sub.add_parser("split", help="Split JSONL by original repository lineage")
    split.add_argument("--input", type=Path, required=True)
    split.add_argument("--output", type=Path, required=True)
    split.add_argument("--seed", default="articheck-v1")

    evaluate = sub.add_parser("evaluate", help="Evaluate label+score JSONL with a frozen threshold")
    evaluate.add_argument("--input", type=Path, required=True)
    evaluate.add_argument("--threshold", type=float, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    calibrate = sub.add_parser("calibrate", help="Select threshold on VALIDATION rows only")
    calibrate.add_argument("--validation", type=Path, required=True)
    calibrate.add_argument("--max-fpr", type=float, default=.05)
    calibrate.add_argument("--output", type=Path, required=True)

    upstream = sub.add_parser("import-upstream", help="Import a baseline JSON report without copying its source")
    upstream.add_argument("--input", type=Path, required=True)
    upstream.add_argument("--output", type=Path, required=True)
    export = sub.add_parser("export-sft", help="Export reviewed teacher planner turns")
    export.add_argument("--traces", type=Path, nargs="+", required=True)
    export.add_argument("--approvals", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    rl = sub.add_parser("export-rl", help="Export only native token-aligned planner trajectories")
    rl.add_argument("--traces", type=Path, nargs="+", required=True)
    rl.add_argument("--output", type=Path, required=True)
    feedback = sub.add_parser("feedback", help="Record a human correction as a hard-sample candidate")
    feedback.add_argument("--report", type=Path, required=True)
    feedback.add_argument("--output", type=Path, required=True)
    feedback.add_argument("--claim-id", required=True)
    feedback.add_argument("--label", type=int, choices=[0, 1], required=True)
    feedback.add_argument("--reviewer", required=True)
    feedback.add_argument("--reason", required=True)

    args = parser.parse_args()
    if args.command == "run":
        planner = FixedPlanner()
        if args.planner == "model":
            from .llm import OpenAIPlannerClient
            planner = ModelPlanner(OpenAIPlannerClient(args.base_url, args.model, args.policy_version,
                                                      args.native_tokens, args.input_price, args.output_price))
        budget = Budget(args.max_tools, args.max_tokens, args.max_seconds, args.max_usd)
        result = asyncio.run(review(Task.load(args.task), args.output, Sandbox(args.sandbox, args.image), planner, budget))
        print(json.dumps({"report": str(args.output / "report.md"), "stop_reason": result["stop_reason"]}))
        if result["stop_reason"].startswith("execution_error"):
            raise SystemExit(2)
    elif args.command == "demo":
        asyncio.run(run_demo(args.examples, args.output, args.sandbox))
    elif args.command == "inject":
        labels = inject(args.source, args.output, args.defect, args.repo_id)
        write_jsonl(args.output / "labels.jsonl", labels)
    elif args.command == "split":
        for name, rows in group_split(read_jsonl(args.input), args.seed).items():
            write_jsonl(args.output / f"{name}.jsonl", rows)
    elif args.command == "evaluate":
        dump(args.output, metrics(read_jsonl(args.input), args.threshold))
    elif args.command == "calibrate":
        dump(args.output, select_threshold(read_jsonl(args.validation), args.max_fpr))
    elif args.command == "import-upstream":
        from .adapters.upstream import import_report
        import_report(args.input, args.output)
    elif args.command == "export-sft":
        print(f"Exported {export_sft(args.traces, args.approvals, args.output)} planner turns")
    elif args.command == "export-rl":
        from .training.export import export_rl
        print(f"Exported {export_rl(args.traces, args.output)} native planner turns")
    elif args.command == "feedback":
        from .feedback import record_feedback
        record_feedback(args.report, args.output, args.claim_id, args.label, args.reviewer, args.reason)


async def run_demo(examples: Path, output: Path, sandbox="docker"):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Demo output must be empty")
    scores, labels = [], []
    for defect in ("clean", *DEFECTS):
        root = output / "fixtures" / defect
        truth = inject(examples, root, defect, repo_id="toy-artifact-v1")
        report = await review(Task.load(root / "task.json"), output / defect,
                              Sandbox(sandbox), cache_root=output / ".cache")
        labels.extend(truth)
        scores.extend(join_report(truth, report))
    write_jsonl(output / "labels.jsonl", labels)
    write_jsonl(output / "scores.jsonl", scores)
    summary = {"scope": "Synthetic smoke test only; not a held-out paper benchmark", **metrics(scores)}
    dump(output / "metrics.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
