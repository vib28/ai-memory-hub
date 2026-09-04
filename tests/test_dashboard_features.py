import tempfile
import unittest
from pathlib import Path

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

if __name__ == "__main__":
    unittest.main()
