import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryCandidate
from memory_hub.dashboard import HTML, memory_rows_for_dashboard

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
        self.assertIn("a.memory_id<b.memory_id?-1:a.memory_id>b.memory_id?1:0", HTML)

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

if __name__ == "__main__":
    unittest.main()
