import http.client
import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from memory_hub.dashboard import (
    HTML,
    DashboardHandler,
    _pending_rows_for_dashboard,
    memory_rows_for_dashboard,
)
from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryCandidate


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
        assert queued["status"] == "queued"
        pid = queued["proposal"]["proposal_id"]
        approved = self.manager.approve(pid)
        assert approved["status"] == "stored"
        assert len(self.manager.list_pending()) == 0

    def test_proposal_history_includes_non_pending_outcomes(self):
        queued = self.manager.queue(MemoryCandidate(
            text="A proposal that was rejected.", kind="preference", tag="preference",
            subject="history-check", writer="chatgpt",
        ))
        self.manager.reject(queued["proposal"]["proposal_id"])
        history = self.manager.list_proposal_history()
        assert history[0]["status"] == "rejected"
        assert self.manager.list_pending() == []
        assert "/api/pending?history=1" in HTML
        assert "Review &amp; history" in HTML
        assert "reviewStatuses=['pending','rejected','approved']" in HTML
        assert "Possible update" not in HTML

    def test_pending_session_proposal_exposes_structured_payload(self):
        """#38: a queued session_write's review-queue row should carry its
        four sections as a real object, not only the flattened `text` string
        the card previously had to render as one paragraph."""
        result = self.manager.propose_session({
            "model": "claude", "title": "demo", "date": None, "project": None,
            "investigated": ["Read the docs"], "learned": ["The gap was real"],
            "completed": ["Shipped the fix"], "next_steps": ["Write tests"],
        }, write_mode="review")
        assert result["status"] == "queued"
        rows = _pending_rows_for_dashboard(self.manager.list_pending())
        assert len(rows) == 1
        payload = rows[0]["payload"]
        assert payload["type"] == "session"
        assert payload["data"]["investigated"] == ["Read the docs"]
        assert payload["data"]["next_steps"] == ["Write tests"]

    def test_pending_pattern_proposal_exposes_structured_payload(self):
        result = self.manager.propose_pattern_match(
            "regression", "A prior change caused a regression.",
            "Add a regression check.", "demo-subject", write_mode="review", writer="claude",
        )
        assert result["status"] == "queued"
        rows = _pending_rows_for_dashboard(self.manager.list_pending())
        assert len(rows) == 1
        payload = rows[0]["payload"]
        assert payload["type"] == "pattern"
        assert payload["project_fact_text"] == "A prior change caused a regression."

    def test_ordinary_proposal_has_no_payload_backward_compatible(self):
        """Every proposal that existed before #38, and every non-session/
        non-pattern kind, must render exactly as before: payload stays None,
        and the card falls back to the flat text field."""
        self.manager.queue(MemoryCandidate(
            text="An ordinary preference.", kind="preference", tag="preference",
            subject="plain", writer="chatgpt",
        ))
        rows = _pending_rows_for_dashboard(self.manager.list_pending())
        assert len(rows) == 1
        assert rows[0]["payload"] is None
        assert rows[0]["text"] == "An ordinary preference."

    def test_pending_rows_never_raise_on_malformed_payload(self):
        rows = [{"payload": "{not valid json"}, {"payload": None}, {}]
        result = _pending_rows_for_dashboard(rows)
        assert [r["payload"] for r in result] == [None, None, None]

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
        assert updated["status"] == "updated"
        assert self.manager.index.by_id(mid)["text"] == "Prefers Python for automation scripts."

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
        assert conflicts
        result = self.manager.resolve_conflict(b["memory"]["memory_id"])
        assert result["status"] == "resolved"
        assert self.manager.index.by_id(a["memory"]["memory_id"])["tag"] == "superseded"

    def test_dashboard_marks_only_the_newest_group_entry(self):
        assert "r.is_most_recent?' · Latest in group':''" in HTML
        assert "esc(r.date)" in HTML
        # Grouping key/label moved server-side into _dashboard_group() (#35), so
        # they cover shared-file kinds (preference, profile) resolved through the
        # entity-aliases.md registry, not just project. The JS now consumes the
        # server-computed fields directly rather than recomputing its own key.
        assert "new Set(rows.map(r=>r.group_key))" in HTML
        assert "r.subject||r.group_label" in HTML

    def test_dashboard_exposes_composable_date_filter(self):
        for control in ('date-on', 'date-from', 'date-to', 'clear-date', 'date-filter-status'):
            assert f'id="{control}"' in HTML
        assert 'function dateFilter()' in HTML
        assert 'matchesDate(r,date)' in HTML

    def test_dashboard_recency_uses_the_full_canonical_project_group(self):
        with patch("memory_hub.manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 5, 14, 30, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            older = self.manager.propose(MemoryCandidate(
                text="Vintageonly project note.", kind="project", tag="stated",
                subject="widget-app", writer="chatgpt", entity_id="widget-app",
            ))["memory"]
        with patch("memory_hub.manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 5, 14, 30, 1, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            newer = self.manager.propose(MemoryCandidate(
                text="Newer project note.", kind="project", tag="stated",
                subject="widget-app-ui", writer="chatgpt", entity_id="widget-app",
            ))["memory"]
        all_rows = {row["memory_id"]: row for row in memory_rows_for_dashboard(self.manager)}
        assert all_rows[older["memory_id"]]["path"] == all_rows[newer["memory_id"]]["path"]
        assert not all_rows[older["memory_id"]]["is_most_recent"]
        assert all_rows[newer["memory_id"]]["is_most_recent"]
        older_search = memory_rows_for_dashboard(self.manager, "Vintageonly")
        assert len(older_search) == 1
        assert not older_search[0]["is_most_recent"]

    def test_dashboard_groups_linked_preferences_by_resolved_entity(self):
        """#35: preference has no per-file identity to group by (every subject
        shares /preferences.md), so grouping must resolve through the
        entity-aliases.md registry -- proving the point the project test above
        makes, for the shared-file case entity_alias_link exists for."""
        with patch("memory_hub.manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 5, 14, 30, 0, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            older = self.manager.propose(MemoryCandidate(
                text="Ask before making destructive changes.", kind="preference",
                tag="preference", subject="git-safety", writer="claude",
            ))["memory"]
        with patch("memory_hub.manager.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 9, 5, 14, 30, 1, tzinfo=timezone.utc)
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            newer = self.manager.propose(MemoryCandidate(
                text="Confirm before any destructive git operation.", kind="preference",
                tag="preference", subject="git-safety-checks", writer="codex",
            ))["memory"]
        before_rows = {row["memory_id"]: row for row in memory_rows_for_dashboard(self.manager)}
        assert before_rows[older["memory_id"]]["group_key"] != before_rows[newer["memory_id"]]["group_key"]

        self.manager.entity_alias_link("preference", "git-safety-checks", "git-safety", apply=True)
        after_rows = {row["memory_id"]: row for row in memory_rows_for_dashboard(self.manager)}
        assert after_rows[older["memory_id"]]["group_key"] == after_rows[newer["memory_id"]]["group_key"]
        assert after_rows[older["memory_id"]]["group_label"] == "git-safety"
        assert not after_rows[older["memory_id"]]["is_most_recent"]
        assert after_rows[newer["memory_id"]]["is_most_recent"]
        # Nothing about the underlying entries changed -- only the grouping view.
        assert after_rows[older["memory_id"]]["subject"] == "git-safety"
        assert after_rows[newer["memory_id"]]["subject"] == "git-safety-checks"

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
        assert status == 403

    def test_post_with_foreign_origin_is_rejected(self):
        headers = {
            "Host": f"127.0.0.1:{self.httpd.server_address[1]}",
            "X-Launch-Token": "test-token",
            "Origin": "http://evil.example",
        }
        status, _ = self._post("/api/conflict/resolve", headers)
        assert status == 403

    def test_get_with_foreign_host_is_rejected(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1])
        conn.request("GET", "/api/memories", headers={"Host": "evil.example:1234"})
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()
        assert status == 403

    def test_post_with_correct_token_and_host_is_accepted(self):
        headers = {
            "Host": f"127.0.0.1:{self.httpd.server_address[1]}",
            "X-Launch-Token": "test-token",
        }
        status, body = self._post("/api/conflict/resolve", headers, {"keep_id": "does-not-exist"})
        assert status == 200
        assert json.loads(body)["status"] == "not_found"

if __name__ == "__main__":
    unittest.main()
