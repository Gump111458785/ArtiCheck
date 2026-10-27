"""Build the dependency-free UI's archived demo data and API contract."""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import tempfile
from pathlib import Path

from articheck.cli import run_demo
from articheck.data import read_jsonl

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "web/dist"


def contract():
    string = {"type": "string"}
    error = {"description": "Request failed", "content": {"application/json": {"schema": {
        "type": "object", "required": ["error"], "properties": {"error": {"type": "object",
        "required": ["code", "message"], "properties": {"code": string, "message": string}}}}}}}
    endpoints = [
        ("/api/health", "get", "运行时能力", "返回运行模式与支持的 Planner。", None, {"mode": "runtime", "supported_planners": ["fixed"]}),
        ("/api/tasks", "get", "任务清单", "读取已注册任务及其主张清单。", None, {"items": [{"id": "sample-metric_average", "claim_count": 3}]}),
        ("/api/tasks", "post", "创建任务", "注册工作区内的任务文件，或复制可信样例并编辑主张。", {"sample_id": "metric_average", "title": "指标计算核查"}, {"id": "task-id", "claim_count": 3}),
        ("/api/runs", "get", "核查运行列表", "按创建时间倒序读取运行元数据。", None, {"items": [{"id": "run-id", "status": "completed"}]}),
        ("/api/runs", "post", "启动核查", "异步调用 Python review；HTTP 202 只表示任务已接收。", {"task_id": "sample-metric_average", "sandbox": "local", "planner": "fixed", "budget": {"max_tools": 8, "max_tokens": 32000, "max_seconds": 180, "max_usd": 1}}, {"id": "run-id", "status": "queued"}),
        ("/api/runs/{run_id}", "get", "运行详情", "返回真实状态、六角色阶段、判定、报告与反馈。", None, {"id": "run-id", "status": "completed", "report_id": "pipeline-report-id", "findings": [{"claim_id": "C1", "verdict": "issue", "evidence_ids": ["sha256"]}]}),
        ("/api/runs/{run_id}/events", "get", "执行事件流 · SSE", "每条 trace 带递增 sequence；支持 after 与 Last-Event-ID，终态发送 terminal。", None, {"sequence": 4, "kind": "tool", "evidence": {"id": "sha256", "success": True}}),
        ("/api/runs/{run_id}/cancel", "post", "停止运行", "取消 asyncio 核查任务；已完成的运行返回 409。", {}, {"id": "run-id", "status": "running"}),
        ("/api/runs/{run_id}/report", "get", "下载报告", "format=json 或 markdown；报告尚未生成时返回 409。", None, {"run_id": "pipeline-report-id", "stop_reason": "complete"}),
        ("/api/runs/{run_id}/trace", "get", "原始轨迹", "保留 pipeline 原始字段；sequence 为 HTTP 适配层追加的事件序号。", None, {"items": [{"sequence": 1, "kind": "preflight"}]}),
        ("/api/runs/{run_id}/feedback", "post", "提交人工纠正", "追加反馈记录，保留原始判定；此操作不直接触发训练。", {"claim_id": "C1", "label": 1, "reviewer": "reviewer-01", "reason": "独立重算后确认指标计算不一致"}, {"claim_id": "C1", "label": 1, "source": "human", "hard_sample": False}),
        ("/api/feedback", "get", "反馈与训练交接", "读取人工审查记录，用于后续困难样本筛选。", None, {"items": []}),
        ("/api/openapi.json", "get", "OpenAPI 契约", "导出完整本地 API 契约，供前后端联调。", None, {"openapi": "3.1.0"}),
    ]
    paths = {}
    for path, method, summary, desc, example, response in endpoints:
        status = "201" if path == "/api/tasks" and method == "post" or path.endswith("/feedback") and method == "post" else "202" if path == "/api/runs" and method == "post" else "200"
        operation = {"summary": summary, "description": desc, "operationId": method+"_"+path.replace("/", "_").replace("{", "").replace("}", ""),
                     "responses": {status: {"description": "Success", "content": {"application/json": {"schema": {"type": "object"}, "example": response}}}, "400": error, "403": error, "404": error, "409": error},
                     "x-ui-response": response, "x-ui-request": example}
        if "{run_id}" in path:
            operation["parameters"] = [{"name": "run_id", "in": "path", "required": True, "schema": string}]
        if path.endswith("/report"):
            operation["parameters"].append({"name": "format", "in": "query", "schema": {"type": "string", "enum": ["json", "markdown"], "default": "json"}})
            operation["responses"]["200"]["content"]["text/markdown"] = {"schema": {"type": "string"}}
        if path.endswith("/events"):
            operation["parameters"] += [{"name": "after", "in": "query", "schema": {"type": "integer", "minimum": 0}},
                                         {"name": "Last-Event-ID", "in": "header", "schema": {"type": "string"}}]
            operation["responses"]["200"]["content"] = {"text/event-stream": {"schema": {"type": "string"}, "example": 'id: 4\nevent: trace\ndata: {"sequence":4,"kind":"tool"}\n\n'}}
        if example is not None:
            schema = {"type": "object"}
            if path == "/api/runs":
                schema = {"$ref": "#/components/schemas/RunCreate"}
            elif path == "/api/tasks":
                schema = {"$ref": "#/components/schemas/TaskCreate"}
            elif path.endswith("/feedback"):
                schema = {"$ref": "#/components/schemas/FeedbackCreate"}
            operation["requestBody"] = {"required": True, "content": {"application/json": {"schema": schema, "example": example}}}
            operation.setdefault("parameters", []).append({"name": "X-ArtiCheck-Client", "in": "header", "required": True, "schema": {"type": "string", "const": "workbench"}})
        paths.setdefault(path, {})[method] = operation
    return {"openapi": "3.1.0", "info": {"title": "ArtiCheck Workbench API", "version": "0.1.0", "description": "Loopback-only runtime; archived demo replay does not execute artifacts."},
            "servers": [{"url": "http://127.0.0.1:8787"}], "paths": paths,
            "components": {"schemas": {
                "Claim": {"type": "object", "required": ["id", "text", "kind", "spec"], "properties": {"id": string, "text": string, "kind": {"enum": ["metric", "split_disjoint", "baseline_equal"]}, "spec": {"type": "object"}, "probe": {"type": ["array", "null"], "items": string}}},
                "TaskCreate": {"type": "object", "properties": {"title": {"type": "string", "maxLength": 200}, "sample_id": {"enum": ["clean", "metric_average", "split_leakage", "baseline_budget"]}, "task_path": string, "claims": {"type": "array", "minItems": 1, "maxItems": 100, "items": {"$ref": "#/components/schemas/Claim"}}}, "oneOf": [{"required": ["sample_id"]}, {"required": ["task_path"]}]},
                "RunCreate": {"type": "object", "required": ["task_id"], "properties": {"task_id": string, "planner": {"const": "fixed"}, "sandbox": {"enum": ["docker", "local"], "default": "docker"}, "budget": {"type": "object", "additionalProperties": False, "properties": {"max_tools": {"type": "integer", "minimum": 0, "maximum": 50}, "max_tokens": {"type": "integer", "minimum": 0, "maximum": 200000}, "max_seconds": {"type": "number", "minimum": 0, "maximum": 600}, "max_usd": {"type": "number", "minimum": 0, "maximum": 100}}}}},
                "FeedbackCreate": {"type": "object", "required": ["claim_id", "label", "reviewer", "reason"], "properties": {"claim_id": string, "label": {"type": "integer", "enum": [0, 1]}, "reviewer": {"type": "string", "minLength": 1}, "reason": {"type": "string", "minLength": 1}}},
                "RunStatus": {"enum": ["queued", "running", "completed", "failed", "cancelled"]},
                "Finding": {"type": "object", "required": ["claim_id", "verdict", "score", "reason", "evidence_ids"], "properties": {"claim_id": string, "verdict": {"enum": ["supported", "issue", "inconclusive"]}, "score": {"type": "number", "minimum": 0, "maximum": 1}, "reason": string, "evidence_ids": {"type": "array", "items": string}}}
            }}}


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        directory = Path(tmp) / "demo"
        with contextlib.redirect_stdout(io.StringIO()):
            asyncio.run(run_demo(ROOT / "examples", directory, "local"))
        samples = []
        for sample in ("metric_average", "split_leakage", "baseline_budget", "clean"):
            task = json.loads((directory / "fixtures" / sample / "task.json").read_text())
            task["repo"] = "artifact"
            report = json.loads((directory / sample / "report.json").read_text())
            # Client-facing fixtures contain only synthetic artifact data.
            for evidence in report["evidence"]:
                evidence["provenance"].pop("sandbox", None)
            events = read_jsonl(directory / sample / "trace.jsonl")
            for event in events:
                if event["kind"] == "tool":
                    event["evidence"]["provenance"].pop("sandbox", None)
            samples.append({"sample_id": sample, "manifest": task, "report": report, "events": events})
        (DEST / "demo.json").write_text(json.dumps({"source": "archived_trusted_fixture_runs", "samples": samples}, ensure_ascii=False, indent=2)+"\n")
    (DEST / "openapi.json").write_text(json.dumps(contract(), ensure_ascii=False, indent=2)+"\n")
    print("Built 4 archived sample runs and OpenAPI contract")


if __name__ == "__main__":
    main()
