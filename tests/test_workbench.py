from __future__ import annotations

import asyncio
import json
import hashlib
import io
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from articheck.workbench import APIError, ROOT, Workbench, handler_for, inspect_github_repository


class WorkbenchTests(unittest.TestCase):
    def test_repository_inspection_is_public_only_and_pins_tree_revision(self):
        sha = "a" * 40
        responses = [{"default_branch": "main"}, {"sha": sha},
                     {"truncated": False, "tree": [{"type": "blob", "path": "README.md", "size": 12}]}]
        with patch("articheck.workbench.urlopen", side_effect=[io.BytesIO(json.dumps(r).encode()) for r in responses]) as get:
            result = inspect_github_repository({"repository_url": "https://github.com/owner/repo"})
        self.assertEqual(result["commit"], sha)
        self.assertEqual(result["files"][0]["path"], "README.md")
        self.assertEqual(get.call_args_list[2].args[0].full_url, f"https://api.github.com/repos/owner/repo/git/trees/{sha}?recursive=1")
        self.assertNotIn("Authorization", get.call_args_list[0].args[0].headers)

    def test_repository_url_cannot_target_other_hosts_or_api_families(self):
        with patch("articheck.workbench.urlopen") as get:
            for url in ("http://github.com/a/b", "https://localhost/a/b", "https://github.com/a/b/issues", "https://github.com/a/..", "https://u:p@github.com/a/b"):
                with self.assertRaises(APIError):
                    inspect_github_repository({"repository_url": url})
            get.assert_not_called()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Workbench(ROOT, Path(self.tmp.name) / "state")

    def tearDown(self):
        self.app.close()
        self.tmp.cleanup()

    def finish(self, run_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = self.app.get_run(run_id)
            if row["status"] in {"completed", "failed", "cancelled"}:
                return row
            time.sleep(.02)
        self.fail("Run did not reach a terminal state")

    def test_real_review_matches_claims_and_evidence(self):
        accepted = self.app.start_run({"task_id": "sample-metric_average", "sandbox": "local"})
        self.assertEqual(accepted["status"], "queued")
        row = self.finish(accepted["id"])
        self.assertEqual(row["status"], "completed")
        self.assertEqual([f["verdict"] for f in row["findings"]], ["issue", "supported", "supported"])
        self.assertEqual(row["report_id"], row["report"]["run_id"])
        self.assertNotEqual(row["id"], row["report_id"])
        self.assertTrue(all(s == "completed" for s in row["stages"].values()))
        self.assertEqual([e["sequence"] for e in row["events"]], list(range(1, len(row["events"])+1)))

    def test_custom_expected_value_is_used_by_python(self):
        task = self.app.get_task("sample-metric_average")
        claims = task["manifest"]["claims"]
        claims[0]["spec"]["expected"] = 5/6
        created = self.app.create_task({"sample_id": "metric_average", "title": "Edited expectation", "claims": claims})
        run = self.app.start_run({"task_id": created["id"], "sandbox": "local"})
        result = self.finish(run["id"])
        self.assertEqual(result["findings"][0]["verdict"], "supported")
        self.assertEqual(result["title"], "Edited expectation")

    def test_sample_cannot_replace_probe(self):
        claims = self.app.get_task("sample-clean")["manifest"]["claims"]
        claims[0]["probe"] = ["python3", "-c", "print('untrusted')"]
        with self.assertRaises(APIError):
            self.app.create_task({"sample_id": "clean", "claims": claims})

    def test_import_is_workspace_scoped_and_docker_only(self):
        with self.assertRaises(APIError):
            self.app.create_task({"sample_id": "clean", "task_path": "examples/task.json"})
        with self.assertRaises(APIError):
            self.app.create_task({"task_path": "/etc/passwd"})
        task = self.app.create_task({"task_path": "examples/task.json", "title": "Imported"})
        with self.assertRaises(APIError) as cm:
            self.app.start_run({"task_id": task["id"], "sandbox": "local"})
        self.assertEqual(cm.exception.status, 403)

    def test_feedback_is_append_only_and_report_is_immutable(self):
        run = self.app.start_run({"task_id": "sample-metric_average", "sandbox": "local"})
        before = self.finish(run["id"])["report"]
        feedback = self.app.add_feedback(run["id"], {"claim_id": "C1", "label": 0,
                                                   "reviewer": "test-reviewer", "reason": "Independent re-evaluation"})
        after = self.app.get_run(run["id"])
        self.assertTrue(feedback["hard_sample"])
        self.assertEqual(before, after["report"])
        self.assertEqual(len(after["feedback"]), 1)
        self.assertEqual(feedback["run_id"], after["report_id"])

    def test_budget_errors_and_unknown_planner(self):
        for body in ({"budget": {"max_seconds": float("nan")}}, {"budget": {"max_seconds": 601}},
                     {"budget": {"max_tools": 1.5}}, {"budget": {"invalid": 1}}, {"planner": "grpo"}):
            with self.assertRaises(APIError):
                self.app.start_run({"task_id": "sample-clean", **body})

    def test_state_persists_and_completed_run_cannot_cancel(self):
        run = self.app.start_run({"task_id": "sample-clean", "sandbox": "local"})
        self.finish(run["id"])
        with self.assertRaises(APIError) as cm:
            self.app.cancel(run["id"])
        self.assertEqual(cm.exception.status, 409)
        second = Workbench(ROOT, self.app.storage)
        try:
            self.assertEqual(second.get_run(run["id"])["status"], "completed")
        finally:
            second.close()

    def test_running_review_can_be_cancelled(self):
        ready = threading.Event()
        async def blocked(*args, **kwargs):
            ready.set()
            await asyncio.sleep(20)
        with patch("articheck.workbench.review", blocked):
            run = self.app.start_run({"task_id": "sample-clean", "sandbox": "local"})
            self.assertTrue(ready.wait(3))
            self.app.cancel(run["id"])
            row = self.finish(run["id"])
            self.assertEqual(row["status"], "cancelled")
            self.assertIsNone(row["report"])

    def test_preflight_checks_manifest_resources_and_unavailable_docker(self):
        with patch("articheck.workbench.shutil.which", return_value=None):
            result = self.app.preflight({"task_path": "examples/task.json", "resources": {"data_required": True, "data_path": "missing-data"}})
        self.assertFalse(result["can_execute"])
        checks = {c["id"]: c for c in result["checks"]}
        self.assertEqual(checks["docker"]["status"], "blocked")
        self.assertEqual(checks["data"]["status"], "blocked")
        self.assertIn("probe.py", result["files"])
        self.assertEqual(len(result["manifest_sha256"]), 64)

    def test_preflight_is_scoped_and_does_not_execute_artifact_commands(self):
        for path in ("/etc/passwd", "../task.json", ""):
            with self.assertRaises(APIError):
                self.app.preflight({"task_path": path})
        with patch("articheck.workbench.shutil.which", return_value=None), patch("articheck.workbench.subprocess.run") as run:
            self.app.preflight({"task_path": "examples/task.json"})
            run.assert_not_called()

    def test_preflight_ready_with_available_docker_and_required_resource_path(self):
        with patch("articheck.workbench.shutil.which", return_value="/docker"), patch("articheck.workbench.subprocess.run") as run:
            run.return_value.returncode = 0
            result = self.app.preflight({"task_path": "examples/task.json", "resources": {"data_required": True, "data_path": "examples"}})
        self.assertTrue(result["can_execute"])
        self.assertEqual(run.call_args.args[0], ["/docker", "info", "--format", "{{.ServerVersion}}"])

    def test_uploaded_paper_provenance_is_attached_to_created_task(self):
        task = self.app.create_task({"task_path": "examples/task.json", "paper_id": "pdf-sha256:abc", "paper_text": "Page 1: verified quote"})
        self.assertEqual(task["paper_id"], "pdf-sha256:abc")
        self.assertEqual(task["manifest"]["paper_text"], "Page 1: verified quote")

    def test_changed_manifest_digest_is_rejected_before_task_creation(self):
        digest = hashlib.sha256((ROOT / "examples/task.json").read_bytes()).hexdigest()
        with self.assertRaises(APIError) as cm:
            self.app.create_task({"task_path": "examples/task.json", "manifest_sha256": digest[:-1] + ("0" if digest[-1] != "0" else "1")})
        self.assertEqual(cm.exception.status, 409)


class HTTPContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.app = Workbench(ROOT, Path(cls.tmp.name) / "state")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(cls.app, ROOT / "web/dist"))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.app.close()
        cls.tmp.cleanup()

    def test_reproduction_audit_reads_actual_files_without_execution(self):
        from test_reproduction import fixture
        root = Path(self.tmp.name) / "reproduction"
        root.mkdir()
        path, plan, repo = fixture(root)
        # This test server's workspace is set in setUpClass.
        original = self.app.workspace
        self.app.workspace = root.resolve()
        try:
            with self.call("/api/reproduction/audit", {"plan_path": "plan.json"}) as response:
                result = json.load(response)
            self.assertEqual(result["format"], "articheck-reproduction-audit-v1")
            self.assertEqual(result["blocking_failures"], 0)
            self.assertTrue(any(c["code"] == "regression:hyperparameters" for c in result["checks"]))
            self.assertFalse((root / "run").exists())
            with self.assertRaises(urllib.error.HTTPError) as failure:
                self.call("/api/reproduction/audit", {"plan_path": "../outside.json"})
            self.assertEqual(failure.exception.code, 400)
        finally:
            self.app.workspace = original

    def test_reproduction_jobs_require_audit_bindings_and_are_idempotent(self):
        from test_reproduction import fixture
        root = Path(self.tmp.name) / "reproduction-jobs"
        root.mkdir()
        path, plan, repo = fixture(root)
        original = self.app.workspace
        self.app.workspace = root.resolve()
        try:
            with self.call("/api/reproduction/audit", {"plan_path": "plan.json"}) as response:
                audit = json.load(response)
            with self.assertRaises(urllib.error.HTTPError):
                self.call("/api/reproduction/runs", {"audit_token": audit["audit_token"], "sandbox": "local"})
            with self.call("/api/reproduction/runs", {"audit_token": audit["audit_token"]}) as response:
                self.assertEqual(response.status, 202)
                job = json.load(response)
            with self.call("/api/reproduction/runs", {"audit_token": audit["audit_token"]}) as response:
                self.assertEqual(json.load(response)["id"], job["id"])
            # Docker discovery can be slow on a shared runner. Check the terminal
            # contract without making five-second startup latency a requirement.
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                with self.call("/api/reproduction/runs/"+job["id"]) as response:
                    state=json.load(response)
                if state["status"] in ("failed","completed","cancelled"):break
                time.sleep(.05)
            # This fixture has no Dockerfile: the job must fail before any artifact stage.
            self.assertEqual(state["status"],"failed",state)
            with self.call("/api/reproduction/runs/"+job["id"]+"/report") as response:
                report=json.load(response)
            self.assertEqual(report["runs"],[])
            self.assertFalse(report["levels"]["run"])
            # Role events come from the executor's roles.jsonl, including for a run that stops early.
            with self.call("/api/reproduction/runs/"+job["id"]+"/roles") as response:
                roles=json.load(response)
            self.assertTrue(roles["available"])
            self.assertEqual(roles["policy"]["Planner"],"frozen_plan")
            names=[(e["role"],e["event"]) for e in roles["events"]]
            self.assertIn(("CodeInspector","audit"),names)
            self.assertNotIn(("ExperimentRunner","stage"),names)
            self.assertEqual(names[-1],("Reporter","report"))
            self.assertEqual(next(e for e in roles["events"] if e["event"]=="stop")["status"],"fail")
            with self.assertRaises(urllib.error.HTTPError):
                self.call("/api/reproduction/runs/"+"0"*32+"/roles")
        finally:
            self.app.workspace=original
            self.app.reproduction.workspace=original

    def test_reproduction_plan_edits_and_wrong_project_paper_block_start(self):
        from test_reproduction import fixture
        root=Path(self.tmp.name)/"reproduction-stale"
        root.mkdir();path,plan,repo=fixture(root)
        original=self.app.workspace;self.app.workspace=root.resolve()
        try:
            with self.call("/api/reproduction/audit",{"plan_path":"plan.json"}) as response:
                token=json.load(response)["audit_token"]
            path.write_text(path.read_text()+"\n")
            with self.assertRaises(urllib.error.HTTPError):
                self.call("/api/reproduction/runs",{"audit_token":token})
            with self.call("/api/reproduction/audit",{"plan_path":"plan.json","paper_sha256":"0"*64}) as response:
                audit=json.load(response)
            self.assertTrue(any(c["code"]=="project_paper_binding" and c["status"]=="fail" for c in audit["checks"]))
            with self.assertRaises(urllib.error.HTTPError):
                self.call("/api/reproduction/runs",{"audit_token":audit["audit_token"]})
        finally:
            self.app.workspace=original
            self.app.reproduction.workspace=original

    def test_project_cannot_start_a_plan_without_its_pdf_digest(self):
        from test_reproduction import fixture
        root=Path(self.tmp.name)/"reproduction-no-pdf"
        root.mkdir();fixture(root)
        original=self.app.workspace;self.app.workspace=root.resolve()
        try:
            with self.call("/api/reproduction/audit",{"plan_path":"plan.json","project_id":"current-paper"}) as response:
                audit=json.load(response)
            self.assertTrue(any(c["code"]=="project_paper_binding" and c["status"]=="unknown" for c in audit["checks"]))
            with self.assertRaises(urllib.error.HTTPError):
                self.call("/api/reproduction/runs",{"audit_token":audit["audit_token"]})
        finally:
            self.app.workspace=original;self.app.reproduction.workspace=original

    def test_environment_snapshot_is_explicit_guarded_and_discloses_executor_limits(self):
        with patch("articheck.workbench.collect_environment", return_value={"format":"articheck-environment-v1", "gpus":None}) as collect:
            with self.call("/api/environment/inspect", {}) as response:
                report=json.load(response)
        self.assertEqual(report["format"], "articheck-environment-v1")
        self.assertFalse(report["executor"]["gpu_enabled"])
        self.assertEqual(report["executor"]["memory_limit_bytes"], 1073741824)
        collect.assert_called_once_with(self.app.workspace)

    def call(self, path, body=None, headers=None):
        h = {"X-ArtiCheck-Client": "workbench", "Content-Type": "application/json"}
        h.update(headers or {})
        req = urllib.request.Request(self.origin + path, data=json.dumps(body).encode() if body is not None else None, headers=h)
        return urllib.request.urlopen(req, timeout=4)

    def test_health_static_and_contract(self):
        self.assertEqual(json.load(self.call("/api/health"))["mode"], "runtime")
        self.assertIn(b"ArtiCheck", self.call("/").read())
        font = self.call("/fonts/ibm-plex-sans-latin.woff2")
        self.assertEqual(font.headers.get_content_type(), "font/woff2")
        self.assertEqual(font.read(4), b"wOF2")
        self.assertEqual(self.call("/intake.mjs").headers.get_content_type(), "application/javascript")
        self.assertEqual(self.call("/samples/articheck-method-note.pdf").read(5), b"%PDF-")
        contract = json.load(self.call("/api/openapi.json"))
        self.assertEqual(contract["openapi"], "3.1.0")
        self.assertIn("/api/runs/{run_id}/feedback", contract["paths"])
        self.assertEqual(contract["components"]["schemas"]["RunStatus"]["enum"],
                         ["queued", "running", "completed", "failed", "cancelled"])

    def test_cross_origin_and_missing_client_header_rejected(self):
        for headers in ({"Origin": "https://untrusted.example"}, {"X-ArtiCheck-Client": ""}, {"Host": "untrusted.example"}):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                self.call("/api/tasks", {"sample_id": "clean"}, headers)
            self.assertEqual(cm.exception.code, 403)

    def test_preflight_http_contract_reports_real_checks_without_starting_run(self):
        with patch("articheck.workbench.shutil.which", return_value=None):
            result = json.load(self.call("/api/preflight", {"task_path": "examples/task.json"}))
        self.assertFalse(result["can_execute"])
        self.assertEqual(result["manifest"]["claims"][0]["id"], "C1")
        self.assertIn("manifest_sha256", result)
        self.assertTrue(any(c["id"] == "docker" and c["status"] == "blocked" for c in result["checks"]))

    def test_full_http_review_feedback_download_and_events(self):
        task = json.load(self.call("/api/tasks", {"sample_id": "split_leakage", "title": "HTTP fixture"}))
        response = self.call("/api/runs", {"task_id": task["id"], "sandbox": "local"})
        self.assertEqual(response.status, 202)
        run = json.load(response)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            detail = json.load(self.call("/api/runs/" + run["id"]))
            if detail["status"] == "completed":
                break
            time.sleep(.02)
        self.assertEqual(detail["findings"][1]["verdict"], "issue")
        feedback = json.load(self.call(f"/api/runs/{run['id']}/feedback", {
            "claim_id": "C2", "label": 1, "reviewer": "http-test", "reason": "Checked split IDs"}))
        self.assertEqual(feedback["claim_id"], "C2")
        report = self.call(f"/api/runs/{run['id']}/report?format=markdown")
        self.assertIn('attachment;', report.headers["Content-Disposition"])
        self.assertIn(b"C2", report.read())
        events = self.call(f"/api/runs/{run['id']}/events?after=1").read().decode()
        self.assertIn("event: trace", events)
        self.assertIn("event: terminal", events)
        self.assertNotIn("id: 1\n", events)

    def test_unknown_route_uses_json_error(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self.call("/api/missing")
        self.assertEqual(cm.exception.code, 404)
        error = json.load(cm.exception)
        self.assertIn("message", error["error"])


if __name__ == "__main__":
    unittest.main()


class GeneratedContractTests(unittest.TestCase):
    def test_generated_contract_matches_the_served_contract(self):
        from scripts.build_workbench import contract
        source = Path(__file__).resolve().parents[1]/'web/dist/openapi.json'
        self.assertEqual(contract(), json.loads(source.read_text()))
