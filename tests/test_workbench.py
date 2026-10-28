from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from articheck.workbench import APIError, ROOT, Workbench, handler_for


class WorkbenchTests(unittest.TestCase):
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
