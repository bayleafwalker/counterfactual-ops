import http.client
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

from counterfactual_ops.model import load
from counterfactual_ops.web import Application, make_server


ROOT = Path(__file__).resolve().parents[1]


class WebApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / "counterfactual_ops", self.root / "counterfactual_ops", ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(ROOT / "examples", self.root / "examples")
        self.command("git", "init", "-b", "main")
        self.command("git", "config", "user.email", "web-tests@example.invalid")
        self.command("git", "config", "user.name", "Web Tests")
        self.command("git", "add", ".")
        self.command("git", "commit", "-m", "Commit web fixture")
        self.server = make_server(self.root, self.root / "evidence", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def command(self, *args):
        return subprocess.run(args, cwd=self.root, check=True, capture_output=True, text=True)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=15)
        payload = None if body is None else json.dumps(body)
        request_headers = dict(headers or {})
        if body is not None:
            request_headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=payload, headers=request_headers)
        response = connection.getresponse()
        data = response.read()
        content_type = response.getheader("Content-Type", "")
        connection.close()
        value = json.loads(data) if content_type.startswith("application/json") else data
        return response.status, value, content_type

    def test_dashboard_and_decision_detail_use_real_assessment(self):
        status, overview, _ = self.request("GET", "/api/v1/overview")
        self.assertEqual(status, 200)
        self.assertEqual(overview["counts"]["decisions"], 5)
        split = next(item for item in overview["decisions"] if item["id"] == "enable-replay")
        self.assertEqual(split["status"], "unresolved")
        status, detail, _ = self.request("GET", "/api/v1/decisions/enable-replay")
        self.assertEqual(status, 200)
        self.assertEqual(detail["assessment"]["next_experiments"][0], "normal")
        self.assertEqual(len(detail["experiments"]), 4)

    def test_static_application_is_served_with_security_policy(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request("GET", "/")
        response = connection.getresponse()
        page = response.read().decode()
        self.assertEqual(response.status, 200)
        self.assertIn("Counterfactual Ops", page)
        self.assertIn("default-src 'self'", response.getheader("Content-Security-Policy"))
        connection.close()
        status, script, content_type = self.request("GET", "/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", content_type)
        self.assertIn(b"/api/v1/overview", script)

    def test_api_executes_committed_experiment_and_downloads_artifact(self):
        status, result, _ = self.request("POST", "/api/v1/runs", {"decision": "enable-replay", "experiment": "crash-gap"})
        self.assertEqual(status, 201)
        self.assertIn("plan", result)
        status, detail, _ = self.request("GET", "/api/v1/decisions/enable-replay")
        self.assertEqual(status, 200)
        self.assertEqual(detail["assessment"]["status"], "counterexample")
        status, events, _ = self.request("GET", "/api/v1/events?decision=enable-replay")
        result_event = next(event for event in events["events"] if event["kind"] == "result")
        ref = result_event["data"]["artifacts"][0]
        status, artifact, content_type = self.request("GET", f"/api/v1/artifacts/{ref}")
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/vnd.sqlite3")
        self.assertTrue(artifact.startswith(b"SQLite format 3"))

    def test_created_decision_is_validated_and_cannot_run_before_commit(self):
        decision = load(self.root / "examples/02-atomic.json")
        decision["id"] = "web-created-decision"
        status, created, _ = self.request("POST", "/api/v1/decisions", decision)
        self.assertEqual(status, 201)
        self.assertEqual(created["state"], "uncommitted")
        self.assertTrue((self.root / created["path"]).is_file())
        status, error, _ = self.request("POST", "/api/v1/runs", {"decision": decision["id"], "experiment": "normal"})
        self.assertEqual(status, 400)
        self.assertIn("commit decisions/web-created-decision.json", error["error"])

    def test_decision_creation_rejects_unsafe_id_and_overwrite(self):
        decision = load(self.root / "examples/02-atomic.json")
        decision["id"] = "../escape"
        status, error, _ = self.request("POST", "/api/v1/decisions", decision)
        self.assertEqual(status, 400)
        self.assertIn("filesystem-safe", error["error"])
        decision["id"] = "enable-atomic-replay"
        status, error, _ = self.request("POST", "/api/v1/decisions", decision)
        self.assertEqual(status, 400)
        self.assertIn("already exists", error["error"])

    def test_mutations_reject_cross_origin_and_non_json(self):
        status, error, _ = self.request(
            "POST", "/api/v1/runs", {"decision": "enable-replay"},
            {"Origin": "https://attacker.invalid"},
        )
        self.assertEqual(status, 400)
        self.assertIn("cross-origin", error["error"])
        status, error, _ = self.request(
            "POST", "/api/v1/runs", headers={"Content-Type": "text/plain"}, body=None,
        )
        self.assertEqual(status, 400)
        self.assertIn("Content-Type", error["error"])

    def test_annotation_is_linked_into_decision_timeline(self):
        _, result, _ = self.request("POST", "/api/v1/runs", {"decision": "enable-replay", "experiment": "normal"})
        status, event, _ = self.request("POST", "/api/v1/annotations", {
            "kind": "unexpected", "target": result["plan"], "note": "Unexpected operator delay",
        })
        self.assertEqual(status, 201)
        self.assertEqual(event["data"]["explanation_status"], "observed-discrepancy")
        _, timeline, _ = self.request("GET", "/api/v1/events?decision=enable-replay")
        self.assertIn(event["id"], {item["id"] for item in timeline["events"]})
        status, resolution, _ = self.request("POST", "/api/v1/annotations", {
            "kind": "resolution", "target": event["id"], "choice": "keep-manual-recovery",
            "note": "Keep recovery manual while investigating delay",
        })
        self.assertEqual(status, 201)
        self.assertEqual(resolution["data"]["target"], event["id"])

    def test_run_mode_and_annotation_shapes_are_strict(self):
        status, error, _ = self.request("POST", "/api/v1/runs", {
            "decision": "enable-replay", "experiment": "normal", "all": True,
        })
        self.assertEqual(status, 400)
        self.assertIn("mutually exclusive", error["error"])
        status, error, _ = self.request("POST", "/api/v1/annotations", {
            "kind": "unexpected", "target": "missing", "note": "note", "choice": "extra",
        })
        self.assertEqual(status, 400)
        self.assertIn("exactly", error["error"])

    def test_loopback_binding_is_enforced(self):
        with self.assertRaisesRegex(ValueError, "loopback"):
            make_server(self.root, self.root / "other", host="0.0.0.0", port=0)

    def test_invalid_decision_is_visible_as_an_api_error(self):
        directory = self.root / "decisions"
        directory.mkdir()
        (directory / "broken.json").write_text('{"schema":"wrong"}')
        status, error, _ = self.request("GET", "/api/v1/overview")
        self.assertEqual(status, 400)
        self.assertIn("invalid decision decisions/broken.json", error["error"])


if __name__ == "__main__":
    unittest.main()
