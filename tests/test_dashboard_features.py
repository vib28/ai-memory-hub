import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from pathlib import Path

from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryCandidate
from memory_hub.dashboard import HTML, DashboardHandler, memory_rows_for_dashboard

class DashboardFeatureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_review_queue_approve(self):
        queued = self.manager.queue(MemoryCandidate(
            text="Prefers tables for direct product comparisons.",
            kind="preference",
            tag="preference",
            subject="response-format",
            writer="chatgpt",
        ))
        self.assertEqual(queued["status"], "queued")
        pid = queued["proposal"]["proposal_id"]
        approved = self.manager.approve(pid)
        self.assertEqual(approved["status"], "stored")
        self.assertEqual(len(self.manager.list_pending()), 0)

    def test_proposal_history_includes_non_pending_outcomes(self):
        queued = self.manager.queue(MemoryCandidate(
            text="A proposal that was rejected.", kind="preference", tag="preference",
            subject="history-check", writer="chatgpt",
        ))
        self.manager.reject(queued["proposal"]["proposal_id"])
        history = self.manager.list_proposal_history()
        self.assertEqual(history[0]["status"], "rejected")
        self.assertEqual(self.manager.list_pending(), [])
        self.assertIn("/api/pending?history=1", HTML)
        self.assertIn("Review &amp; history", HTML)
        self.assertIn("reviewStatuses=['pending','rejected','approved']", HTML)
        self.assertNotIn("Possible update", HTML)

    def test_edit(self):
        stored = self.manager.propose(MemoryCandidate(
            text="Uses Python for automation.",
            kind="preference",
            tag="preference",
            subject="coding",
            writer="chatgpt",
        ))
        mid = stored["memory"]["memory_id"]
        updated = self.manager.edit(mid, "Prefers Python for automation scripts.")
        self.assertEqual(updated["status"], "updated")
        self.assertEqual(self.manager.index.by_id(mid)["text"], "Prefers Python for automation scripts.")

    def test_conflict_resolution(self):
        a = self.manager.propose(MemoryCandidate(
            text="Uses Windows as primary development OS.",
            kind="profile",
            tag="stated",
            subject="primary-os",
            writer="claude",
        ))
        b = self.manager.propose(MemoryCandidate(
            text="Uses Fedora Linux as primary development OS.",
            kind="profile",
            tag="stated",
            subject="primary-os",
            writer="chatgpt",
        ))
        conflicts = self.manager.conflicts()
        self.assertTrue(conflicts)
        result = self.manager.resolve_conflict(b["memory"]["memory_id"])
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(self.manager.index.by_id(a["memory"]["memory_id"])["tag"], "superseded")

    def test_dashboard_marks_only_the_newest_group_entry(self):
        self.assertIn("memoryCard(item,item.is_most_recent)", HTML)
        self.assertIn("${isMostRecent?'<span class=\"recent-badge\">🕐 Most recent</span>':''}", HTML)
        self.assertIn("<span class=\"meta\" style=\"margin:0\">${formatWhen(r.date)}</span>", HTML)
        self.assertIn("const key = isProject ? `project:${r.path}` : `${r.kind}:${r.subject || 'general'}`;", HTML)
        self.assertIn("a.memory_id>b.memory_id?-1:a.memory_id<b.memory_id?1:0", HTML)

    def test_dashboard_recency_uses_the_full_canonical_project_group(self):
        with patch("memory_hub.manager.now_stamp", side_effect=["2026-09-05T14:30:00", "2026-09-05T14:30:01"]):
            older = self.manager.propose(MemoryCandidate(
                text="Vintageonly project note.", kind="project", tag="stated",
                subject="widget-app", writer="chatgpt",
            ))["memory"]
            newer = self.manager.propose(MemoryCandidate(
                text="Newer project note.", kind="project", tag="stated",
                subject="widget-app-ui", writer="chatgpt",
            ))["memory"]
        all_rows = {row["memory_id"]: row for row in memory_rows_for_dashboard(self.manager)}
        self.assertEqual(all_rows[older["memory_id"]]["path"], all_rows[newer["memory_id"]]["path"])
        self.assertFalse(all_rows[older["memory_id"]]["is_most_recent"])
        self.assertTrue(all_rows[newer["memory_id"]]["is_most_recent"])
        older_search = memory_rows_for_dashboard(self.manager, "Vintageonly")
        self.assertEqual(len(older_search), 1)
        self.assertFalse(older_search[0]["is_most_recent"])

class DashboardOriginProtectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

        DashboardHandler.manager = self.manager
        DashboardHandler.launch_token = "test-token"
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), DashboardHandler)
        DashboardHandler.allowed_hosts = frozenset({f"127.0.0.1:{self.httpd.server_address[1]}"})
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.httpd.shutdown()
        self.thread.join(timeout=5)
        self.httpd.server_close()
        self.manager.close()
        self.tmp.cleanup()

    def _post(self, path, headers, payload=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1])
        conn.request("POST", path, body=json.dumps(payload or {}), headers=headers)
        resp = conn.getresponse()
        status, body = resp.status, resp.read()
        conn.close()
        return status, body

    def test_post_without_launch_token_is_rejected(self):
        status, _ = self._post("/api/conflict/resolve", {"Host": f"127.0.0.1:{self.httpd.server_address[1]}"})
        self.assertEqual(status, 403)

    def test_post_with_foreign_origin_is_rejected(self):
        headers = {
            "Host": f"127.0.0.1:{self.httpd.server_address[1]}",
            "X-Launch-Token": "test-token",
            "Origin": "http://evil.example",
        }
        status, _ = self._post("/api/conflict/resolve", headers)
        self.assertEqual(status, 403)

    def test_get_with_foreign_host_is_rejected(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1])
        conn.request("GET", "/api/memories", headers={"Host": "evil.example:1234"})
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()
        self.assertEqual(status, 403)

    def test_post_with_correct_token_and_host_is_accepted(self):
        headers = {
            "Host": f"127.0.0.1:{self.httpd.server_address[1]}",
            "X-Launch-Token": "test-token",
        }
        status, body = self._post("/api/conflict/resolve", headers, {"keep_id": "does-not-exist"})
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "not_found")

if __name__ == "__main__":
    unittest.main()
