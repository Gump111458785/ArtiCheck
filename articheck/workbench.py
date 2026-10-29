"""Loopback-only API adapter for the ArtiCheck workbench; no extra dependencies."""
from __future__ import annotations

import argparse
import asyncio
import json
import hashlib
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse, quote
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from .data import DEFECTS, inject, read_jsonl
from .environment import collect_environment
from .reproduction.audit import audit_plan
from .feedback import record_feedback
from .pipeline import review
from .runtime import Budget
from .sandbox import Sandbox
from .schema import Claim, Task, dump

ROOT = Path(__file__).resolve().parents[1]
STAGES = ["literature", "code", "planner", "experiment", "audit", "report"]
TERMINAL = {"completed", "failed", "cancelled"}


def now():
    return datetime.now(timezone.utc).isoformat()


class APIError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def inspect_github_repository(body):
    parsed = urlparse(str(body.get("repository_url", "")))
    parts = parsed.path.rstrip("/").removesuffix(".git").strip("/").split("/")
    if (parsed.scheme != "https" or parsed.netloc.lower() != "github.com" or len(parts) != 2
            or not re.fullmatch(r"[A-Za-z0-9-]+", parts[0]) or not re.fullmatch(r"[\w.-]+", parts[1])
            or parts[1] in {".", ".."}):
        raise APIError("请使用 https://github.com/作者/仓库 格式")
    owner, name = parts
    base = f"https://api.github.com/repos/{owner}/{name}"
    def get(path):
        try:
            request = Request(base + path, headers={"Accept": "application/vnd.github+json", "User-Agent": "ArtiCheck-Workbench"})
            with urlopen(request, timeout=8) as response:
                payload = response.read(5_000_001)
            if len(payload) > 5_000_000:
                raise APIError("仓库目录过大，请只导入本次实验所需的代码 ZIP", 413)
            value = json.loads(payload)
            if not isinstance(value, dict):
                raise APIError("GitHub 返回了无效的目录信息", 502)
            return value
        except APIError:
            raise
        except HTTPError as exc:
            raise APIError("GitHub 请求受限或仓库不可公开读取，请改用代码 ZIP", 502) from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise APIError("GitHub 目录读取失败，请稍后重试或导入代码 ZIP", 502) from exc
    meta = get("")
    branch = meta.get("default_branch")
    if not isinstance(branch, str) or not 1 <= len(branch) <= 255:
        raise APIError("GitHub 未返回有效的默认分支", 502)
    commit = get("/commits/" + quote(branch, safe="")).get("sha", "")
    if not re.fullmatch(r"[0-9a-f]{40,64}", commit):
        raise APIError("GitHub 未返回有效的提交版本", 502)
    tree = get("/git/trees/" + commit + "?recursive=1")
    files = [{"path": item["path"], "size": item.get("size"), "git_blob_sha": item.get("sha")} for item in tree.get("tree", []) if item.get("type") == "blob"]
    if tree.get("truncated") or len(files) > 5000 or not files:
        raise APIError("目录不完整、为空或超过 5000 个文件，请导入实验代码 ZIP", 413)
    return {"kind": "github", "name": f"{owner}/{name}", "url": f"https://github.com/{owner}/{name}",
            "branch": branch, "commit": commit, "files": files, "fetched_at": now()}


class Workbench:
    def __init__(self, workspace: Path, storage: Path, examples: Path | None = None):
        self.workspace, self.storage = workspace.resolve(), storage.resolve()
        self.storage.mkdir(parents=True, exist_ok=True)
        self.examples = (examples or ROOT / "examples").resolve()
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="articheck")
        self.tasks, self.runs, self.controls = {}, {}, {}
        self.feedback_file = self.storage / "feedback.jsonl"
        self._restore()
        for sample in ("metric_average", "split_leakage", "baseline_budget", "clean"):
            task_id = "sample-" + sample
            if task_id not in self.tasks:
                directory = self.storage / "samples" / sample
                if not directory.exists():
                    inject(self.examples, directory, sample, "toy-artifact-v1")
                title = {"clean": "Clean artifact · 正常对照", "metric_average": "Macro F1 · 指标计算核查",
                         "split_leakage": "Data split · 数据划分核查", "baseline_budget": "Baseline · 训练预算核查"}[sample]
                self._register(task_id, directory / "task.json", title, True, sample)

    def _restore(self):
        for path in (self.storage / "tasks").glob("*/meta.json"):
            meta = json.loads(path.read_text())
            if Path(meta["manifest_path"]).exists():
                self.tasks[meta["id"]] = meta
        for path in (self.storage / "runs").glob("*/run.json"):
            row = json.loads(path.read_text())
            if row["status"] not in TERMINAL:
                row.update(status="failed", error="Runtime restarted before completion", finished_at=now())
                dump(path, row)
            self.runs[row["id"]] = row

    def _register(self, task_id, manifest: Path, title, trusted=False, sample=None):
        task = Task.load(manifest)
        meta = {"id": task_id, "title": title or task.paper_id, "paper_id": task.paper_id,
                "repo_id": task.repo_id, "manifest_path": str(manifest.resolve()), "trusted_sample": trusted,
                "sample_id": sample, "created_at": now(), "claim_count": len(task.claims)}
        self.tasks[task_id] = meta
        dump(self.storage / "tasks" / task_id / "meta.json", meta)
        return self.get_task(task_id)

    def get_task(self, task_id):
        with self.lock:
            if task_id not in self.tasks:
                raise APIError("Task not found", 404)
            meta = dict(self.tasks[task_id])
        raw = json.loads(Path(meta["manifest_path"]).read_text())
        meta.pop("manifest_path")
        return {**meta, "manifest": raw}

    def create_task(self, body):
        with self.lock:
            if len(self.tasks) >= 100:
                raise APIError("Task limit reached", 409)
            sample = body.get("sample_id")
            if sample is not None and "task_path" in body:
                raise APIError("Choose sample_id or task_path, not both")
            if sample in (*DEFECTS, "clean"):
                original = self.get_task("sample-" + sample)
                raw = dict(original["manifest"])
                raw["repo"] = str(Task.load(Path(self.tasks[original["id"]]["manifest_path"])).repo)
                trusted = True
            else:
                path = (self.workspace / body.get("task_path", "")).resolve()
                if not path.is_relative_to(self.workspace) or not path.is_file():
                    raise APIError("task_path must identify a manifest inside the configured workspace")
                source = Task.load(path)
                if body.get("manifest_sha256") and hashlib.sha256(path.read_bytes()).hexdigest() != body["manifest_sha256"]:
                    raise APIError("Manifest changed; run preflight again", 409)
                if not source.repo.is_relative_to(self.workspace):
                    raise APIError("Artifact must be inside the configured workspace")
                raw = json.loads(path.read_text())
                raw["repo"] = str(source.repo)
                trusted = False
            if "paper_id" in body:
                if not isinstance(body["paper_id"], str) or not 1 <= len(body["paper_id"]) <= 200:
                    raise APIError("paper_id must contain 1–200 characters")
                raw["paper_id"] = body["paper_id"]
            if "paper_text" in body:
                if not isinstance(body["paper_text"], str) or len(body["paper_text"]) > 120000:
                    raise APIError("paper_text must be text up to 120000 characters")
                raw["paper_text"] = body["paper_text"]
            if "claims" in body:
                if not isinstance(body["claims"], list) or not 1 <= len(body["claims"]) <= 100:
                    raise APIError("Provide 1–100 claims")
                # The browser can edit claim specs; sample probes remain trusted/immutable.
                allowed_probes = {json.dumps(c.get("probe")) for c in raw["claims"]}
                for claim in body["claims"]:
                    Claim(**claim)
                    if trusted and json.dumps(claim.get("probe")) not in allowed_probes:
                        raise APIError("Sample probe commands cannot be changed")
                raw["claims"] = body["claims"]
            task_id = uuid.uuid4().hex
            path = self.storage / "tasks" / task_id / "task.json"
            dump(path, raw)
            return self._register(task_id, path, str(body.get("title", ""))[:200], trusted, sample)

    def preflight(self, body):
        path = (self.workspace / str(body.get("task_path", ""))).resolve()
        if not path.is_relative_to(self.workspace) or not path.is_file():
            raise APIError("task_path must identify a manifest inside the workspace")
        task = Task.load(path)
        if not task.repo.is_relative_to(self.workspace):
            raise APIError("Artifact must be inside the workspace")
        raw = json.loads(path.read_text())
        files = []
        for directory, names, filenames in os.walk(task.repo, followlinks=False):
            names[:] = [name for name in names if name not in {".git", ".venv", "node_modules", "__pycache__"}]
            for filename in filenames:
                item = Path(directory) / filename
                if item.is_file() and not item.is_symlink():
                    files.append(item.relative_to(task.repo).as_posix())
                if len(files) >= 2500:
                    break
            if len(files) >= 2500:
                break
        docker = shutil.which("docker")
        reachable = False
        if docker:
            try:
                result = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"], capture_output=True, timeout=3)
                reachable = result.returncode == 0
            except (OSError, subprocess.TimeoutExpired):
                pass
        resources = body.get("resources", {})
        if not isinstance(resources, dict):
            raise APIError("resources must be an object")
        checks = [{"id": "manifest", "label": "执行规范", "status": "ready", "detail": str(path.relative_to(self.workspace))},
                  {"id": "repository", "label": "本地代码目录", "status": "ready", "detail": task.repo.relative_to(self.workspace).as_posix()},
                  {"id": "docker", "label": "Docker 执行环境", "status": "ready" if reachable else "blocked", "detail": "服务可连接" if reachable else "需要安装并启动 Docker"}]
        for key, label in (("data", "数据集"), ("weights", "模型权重")):
            required = resources.get(key+"_required", False)
            if type(required) is not bool:
                raise APIError("Resource requirement must be boolean")
            value = str(resources.get(key+"_path", "")).strip()
            target = (self.workspace / value).resolve() if value else None
            present = bool(target and target.is_relative_to(self.workspace) and target.exists())
            checks.append({"id": key, "label": label, "status": "ready" if not required or present else "blocked",
                           "detail": "本范围无需该材料" if not required else value if present else "工作区内尚未找到所需路径"})
        return {"manifest_path": path.relative_to(self.workspace).as_posix(), "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "manifest": raw, "paper_id": task.paper_id, "repo_id": task.repo_id, "probe": task.probe,
                "files": files, "checks": checks, "can_execute": all(c["status"] == "ready" for c in checks)}

    def start_run(self, body):
        with self.lock:
            if len(self.runs) >= 200:
                raise APIError("Run limit reached", 409)
            task_id = body.get("task_id")
            task = self.get_task(task_id)
            mode = body.get("sandbox", "docker")
            if mode not in {"docker", "local"}:
                raise APIError("Unknown sandbox")
            if mode == "local" and not task["trusted_sample"]:
                raise APIError("Local execution is restricted to bundled trusted samples", 403)
            if body.get("planner", "fixed") != "fixed":
                raise APIError("This API version exposes only the fixed planner")
            limits = body.get("budget", {})
            allowed = {"max_tools", "max_tokens", "max_seconds", "max_usd"}
            if not isinstance(limits, dict) or any(type(v) not in (int, float) or not math.isfinite(v) for v in limits.values()):
                raise APIError("Budgets must be finite numbers")
            if any(k in limits and type(limits[k]) is not int for k in ("max_tools", "max_tokens")):
                raise APIError("Tool and token budgets must be integers")
            if set(limits) - allowed:
                raise APIError("Unknown budget field")
            try:
                budget = Budget(**limits)
            except (TypeError, ValueError) as exc:
                raise APIError(str(exc)) from exc
            if budget.max_seconds > 600 or budget.max_tools > 50 or budget.max_tokens > 200000 or budget.max_usd > 100:
                raise APIError("Workbench budget exceeds allowed limits")
            run_id = uuid.uuid4().hex
            row = {"id": run_id, "task_id": task_id, "title": task["title"], "status": "queued",
                   "created_at": now(), "finished_at": None, "sandbox": mode, "planner": "fixed",
                   "budget": {k: getattr(budget, k) for k in allowed}, "error": None,
                   "report_id": None}
            self.runs[run_id] = row
            dump(self.storage / "runs" / run_id / "run.json", row)
            self.controls[run_id] = {"cancel": threading.Event()}
            self.pool.submit(self._execute, run_id)
            return dict(row)

    def _execute(self, run_id):
        loop = asyncio.new_event_loop()
        with self.lock:
            row, control = self.runs[run_id], self.controls[run_id]
            if control["cancel"].is_set():
                self.controls.pop(run_id, None)
                loop.close()
                return
            row["status"] = "running"
            control["loop"] = loop
            directory = self.storage / "runs" / run_id
            task = Task.load(Path(self.tasks[row["task_id"]]["manifest_path"]))
            coro = review(task, directory, Sandbox(row["sandbox"]), budget=Budget(**row["budget"]),
                          cache_root=self.storage / "probe_cache")
            future = loop.create_task(coro)
            control["future"] = future
            dump(directory / "run.json", row)
        try:
            report = loop.run_until_complete(future)
            with self.lock:
                row["report_id"] = report["run_id"]
                reason = report["stop_reason"]
                row["status"] = "failed" if reason.startswith("execution_error") else "completed"
                row["error"] = reason if row["status"] == "failed" else None
        except asyncio.CancelledError:
            with self.lock:
                row["status"] = "cancelled"
        except Exception as exc:
            with self.lock:
                row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        finally:
            with self.lock:
                row["finished_at"] = now()
                dump(directory / "run.json", row)
                self.controls.pop(run_id, None)
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.close()

    def cancel(self, run_id):
        with self.lock:
            if run_id not in self.runs:
                raise APIError("Run not found", 404)
            row = self.runs[run_id]
            if row["status"] in TERMINAL:
                raise APIError("Run is already terminal", 409)
            control = self.controls[run_id]
            control["cancel"].set()
            if "future" in control:
                control["loop"].call_soon_threadsafe(control["future"].cancel)
            else:
                row.update(status="cancelled", finished_at=now())
                dump(self.storage / "runs" / run_id / "run.json", row)
            return dict(row)

    def trace(self, run_id):
        if run_id not in self.runs:
            raise APIError("Run not found", 404)
        path = self.storage / "runs" / run_id / "trace.jsonl"
        rows = []
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue  # a writer may still be appending the last line
        return [{"sequence": i+1, **row} for i, row in enumerate(rows)]

    def get_run(self, run_id):
        with self.lock:
            if run_id not in self.runs:
                raise APIError("Run not found", 404)
            row = dict(self.runs[run_id])
        path = self.storage / "runs" / run_id / "report.json"
        try:
            report = json.loads(path.read_text()) if path.exists() else None
        except json.JSONDecodeError:
            report = None  # A concurrent writer may not have flushed the new report yet.
        events = self.trace(run_id)
        findings = report["findings"] if report else [e["finding"] for e in events if e["kind"] == "audit"]
        stages = {name: "pending" for name in STAGES}
        if any(e["kind"] == "preflight" for e in events):
            stages.update(literature="completed", code="completed", planner="running")
        if any(e["kind"] == "tool" for e in events):
            stages.update(experiment="completed", audit="running")
        if row["status"] == "completed":
            stages = {name: "completed" for name in STAGES}
        elif row["status"] in {"failed", "cancelled"}:
            for name in STAGES:
                if stages[name] in {"running", "pending"}:
                    stages[name] = row["status"]
        feedback = read_jsonl(self.feedback_file) if self.feedback_file.exists() else []
        return {**row, "report": report, "findings": findings, "stages": stages, "events": events,
                "feedback": [f for f in feedback if report and f["run_id"] == report["run_id"]]}

    def add_feedback(self, run_id, body):
        with self.lock:
            row = self.get_run(run_id)
            if row["report"] is None:
                raise APIError("Feedback requires a completed report", 409)
            if type(body.get("label")) is not int or body["label"] not in (0, 1):
                raise APIError("label must be integer 0 or 1")
            try:
                return record_feedback(self.storage / "runs" / run_id / "report.json", self.feedback_file,
                                       body["claim_id"], body["label"], body["reviewer"], body["reason"])
            except (ValueError, KeyError) as exc:
                raise APIError(str(exc)) from exc

    def close(self):
        for run_id in list(self.controls):
            try:
                self.cancel(run_id)
            except APIError:
                pass
        self.pool.shutdown(wait=True)


def handler_for(app: Workbench, static_root: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send_json(self, value, status=200):
            self.send_bytes(json.dumps(value, ensure_ascii=False, allow_nan=False).encode(), "application/json", status)

        def send_bytes(self, value, content_type, status=200, filename=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Content-Length", str(len(value)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            if filename:
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(value)

        def safe(self, mutation=False):
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in hosts:
                raise APIError("Invalid Host", 403)
            if mutation:
                origin = self.headers.get("Origin")
                if origin and origin not in {"http://"+host for host in hosts}:
                    raise APIError("Cross-origin writes are disabled", 403)
                if self.headers.get("X-ArtiCheck-Client") != "workbench":
                    raise APIError("Missing workbench client header", 403)

        def do_GET(self):
            try:
                self.safe()
                path = urlparse(self.path)
                parts = path.path.strip("/").split("/")
                if path.path == "/api/health":
                    return self.send_json({"service": "articheck", "version": 1, "mode": "runtime",
                                           "supported_planners": ["fixed"], "local_samples_only": True})
                if path.path == "/api/tasks":
                    return self.send_json({"items": [app.get_task(key) for key in list(app.tasks)]})
                if path.path == "/api/runs":
                    return self.send_json({"items": sorted([dict(r) for r in app.runs.values()],
                                                           key=lambda r: r["created_at"], reverse=True)})
                if path.path == "/api/feedback":
                    return self.send_json({"items": read_jsonl(app.feedback_file) if app.feedback_file.exists() else []})
                if path.path == "/api/openapi.json":
                    return self.send_bytes((static_root / "openapi.json").read_bytes(), "application/json")
                if len(parts) >= 3 and parts[:2] == ["api", "runs"]:
                    run_id = parts[2]
                    row = app.get_run(run_id)
                    if len(parts) == 3:
                        return self.send_json(row)
                    if parts[3] == "trace":
                        return self.send_json({"items": row["events"]})
                    if parts[3] == "report":
                        if row["report"] is None:
                            raise APIError("Report is not ready", 409)
                        markdown = parse_qs(path.query).get("format", ["json"])[0] == "markdown"
                        filename = "report.md" if markdown else "report.json"
                        data = (app.storage / "runs" / run_id / filename).read_bytes()
                        return self.send_bytes(data, "text/markdown" if markdown else "application/json", filename=filename)
                    if parts[3] == "events":
                        return self.event_stream(run_id, path.query)
                if path.path.startswith("/api/"):
                    raise APIError("Endpoint not found", 404)
                relative = path.path.lstrip("/") or "index.html"
                target = (static_root / relative).resolve()
                if not target.is_relative_to(static_root.resolve()) or not target.is_file():
                    raise APIError("Resource not found", 404)
                mime = {".html": "text/html", ".js": "application/javascript", ".css": "text/css",
                        ".json": "application/json", ".svg": "image/svg+xml",
                        ".woff2": "font/woff2", ".mjs": "application/javascript",
                        ".pdf": "application/pdf", ".zip": "application/zip", ".wasm": "application/wasm", ".pfb": "application/octet-stream",
                        ".ttf": "font/ttf"}.get(target.suffix, "text/plain")
                self.send_bytes(target.read_bytes(), mime)
            except (APIError, ValueError, KeyError) as exc:
                self.send_json({"error": {"code": "request_error", "message": str(exc)}}, getattr(exc, "status", 400))
            except (BrokenPipeError, ConnectionResetError):
                pass

        def event_stream(self, run_id, query):
            last = int(parse_qs(query).get("after", [self.headers.get("Last-Event-ID", "0")])[0])
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            started = time.monotonic()
            while time.monotonic() - started < 25:
                row = app.get_run(run_id)
                for event in row["events"]:
                    if event["sequence"] > last:
                        payload = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f"id: {event['sequence']}\nevent: trace\ndata: {payload}\n\n".encode())
                        last = event["sequence"]
                if row["status"] in TERMINAL:
                    self.wfile.write(f"event: terminal\ndata: {json.dumps({'status': row['status']})}\n\n".encode())
                    self.wfile.flush()
                    return
                self.wfile.write(b": heartbeat\n\n")
                self.wfile.flush()
                time.sleep(.25)

        def do_POST(self):
            try:
                self.safe(True)
                length = int(self.headers.get("Content-Length", 0))
                if not 1 <= length <= 256000:
                    raise APIError("JSON body required; maximum 256 KB", 413)
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise APIError("JSON object required")
                path = urlparse(self.path).path
                parts = path.strip("/").split("/")
                if path == "/api/tasks":
                    return self.send_json(app.create_task(body), 201)
                if path == "/api/reproduction/audit":
                    plan_path = (app.workspace / str(body.get("plan_path", ""))).resolve()
                    if not plan_path.is_relative_to(app.workspace) or not plan_path.is_file():
                        raise APIError("plan_path must identify a reproduction plan inside the workspace")
                    return self.send_json(audit_plan(plan_path, workspace=app.workspace, imported=body.get("imported_snapshot")))
                if path == "/api/environment/inspect":
                    report = collect_environment(app.workspace)
                    report["executor"] = {"mode": "docker_probe", "gpu_enabled": False, "memory_limit_bytes": 1073741824, "cpu_limit": 1, "max_seconds": 600}
                    return self.send_json(report)
                if path == "/api/preflight":
                    return self.send_json(app.preflight(body))
                if path == "/api/repositories/inspect":
                    return self.send_json(inspect_github_repository(body))
                if path == "/api/runs":
                    return self.send_json(app.start_run(body), 202)
                if len(parts) == 4 and parts[:2] == ["api", "runs"]:
                    if parts[3] == "cancel":
                        return self.send_json(app.cancel(parts[2]))
                    if parts[3] == "feedback":
                        return self.send_json(app.add_feedback(parts[2], body), 201)
                raise APIError("Endpoint not found", 404)
            except (APIError, ValueError, KeyError, TypeError, OSError) as exc:
                self.send_json({"error": {"code": "request_error", "message": str(exc)}}, getattr(exc, "status", 400))
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Run the local ArtiCheck workbench")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument("--storage", type=Path, default=Path("runs/workbench"))
    parser.add_argument("--static", type=Path, default=ROOT / "web/dist")
    args = parser.parse_args()
    app = Workbench(args.workspace, args.storage)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(app, args.static))
    print(f"ArtiCheck Workbench: http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.close()


if __name__ == "__main__":
    main()
