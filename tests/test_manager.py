import tempfile
import unittest
from pathlib import Path

from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryCandidate

class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        template = Path(__file__).resolve().parent.parent / "vault_template"
        self.manager.initialize(template)

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_store_search_duplicate_forget(self):
        result = self.manager.propose(MemoryCandidate(
            text="Prefers concise answers first.",
            kind="preference",
            tag="preference",
            subject="response-style",
            writer="chatgpt",
        ))
        self.assertEqual(result["status"], "stored")
        mid = result["memory"]["memory_id"]

        search = self.manager.search("concise answers")
        self.assertTrue(any(r["memory_id"] == mid for r in search))

        dup = self.manager.propose(MemoryCandidate(
            text="Prefers concise answers first.",
            kind="preference",
            tag="preference",
            subject="response-style",
            writer="claude",
        ))
        self.assertEqual(dup["status"], "duplicate")

        forgotten = self.manager.forget(mid)
        self.assertEqual(forgotten["status"], "forgotten")
        self.assertIsNone(self.manager.index.by_id(mid))

    def test_secret_rejected(self):
        result = self.manager.propose(MemoryCandidate(
            text="My API key = sk-abcdefghijklmnopqrstuvwxyz123456",
            kind="profile",
            tag="stated",
            subject="credentials",
            writer="chatgpt",
        ))
        self.assertEqual(result["status"], "rejected")

    def test_supersede(self):
        old = self.manager.propose(MemoryCandidate(
            text="Uses Windows as the primary development OS.",
            kind="profile",
            tag="stated",
            subject="operating-system",
            writer="claude",
        ))
        old_id = old["memory"]["memory_id"]

        new = self.manager.supersede(old_id, MemoryCandidate(
            text="Uses Fedora Linux as the primary development OS.",
            kind="profile",
            tag="stated",
            subject="operating-system",
            writer="chatgpt",
        ))
        self.assertEqual(new["status"], "stored")
        self.assertEqual(self.manager.index.by_id(old_id)["tag"], "superseded")

    def test_audit_healthy(self):
        self.manager.propose(MemoryCandidate(
            text="Prefers Python for small automation tools.",
            kind="preference",
            tag="preference",
            subject="coding",
            writer="chatgpt",
        ))
        audit = self.manager.audit()
        self.assertTrue(audit["healthy"], audit)

if __name__ == "__main__":
    unittest.main()
