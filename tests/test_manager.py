import tempfile
import unittest
from pathlib import Path

from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryCandidate, MemoryRecord

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
        key_like_value = "sk-" + "abcdefghijklmnopqrstuvwxyz123456"
        result = self.manager.propose(MemoryCandidate(
            text=f"My API key = {key_like_value}",
            kind="profile",
            tag="stated",
            subject="credentials",
            writer="chatgpt",
        ))
        self.assertEqual(result["status"], "rejected")

    def test_codex_writer_is_preserved(self):
        result = self.manager.propose(MemoryCandidate(
            text="Uses Codex for local development work.",
            kind="project",
            tag="stated",
            subject="development-tooling",
            writer="codex",
        ))
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["memory"]["writer"], "codex")

    def test_qwen_writer_is_preserved(self):
        result = self.manager.propose(MemoryCandidate(
            text="Uses Qwen for local development work.",
            kind="project",
            tag="stated",
            subject="development-tooling",
            writer="qwen",
        ))
        self.assertEqual(result["status"], "stored")
        self.assertEqual(result["memory"]["writer"], "qwen")

    def test_new_entry_timestamp_and_subject_survive_reindex(self):
        first = self.manager.propose(MemoryCandidate(
            text="Uses Windows as the primary development OS.",
            kind="profile",
            tag="stated",
            subject="primary-development-os",
            writer="chatgpt",
        ))
        second = self.manager.propose(MemoryCandidate(
            text="Uses English for technical communication.",
            kind="profile",
            tag="stated",
            subject="technical-language",
            writer="chatgpt",
        ))
        self.assertRegex(first["memory"]["date"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
        self.manager.reindex()
        self.assertEqual(self.manager.index.by_id(first["memory"]["memory_id"])["subject"], "primary-development-os")
        self.assertEqual(self.manager.index.by_id(second["memory"]["memory_id"])["subject"], "technical-language")
        self.assertEqual(self.manager.conflicts(), [])

    def test_edit_normalizes_a_legacy_subject_for_reindex(self):
        memory_id = "legacy-subject"
        path = self.vault / "profile.md"
        path.write_text(
            "---\ntype: profile\n---\n\n"
            "- [stated] Uses Windows. <!-- mem:legacy-subject source:chatgpt date:2026-09-04 -->\n",
            encoding="utf-8",
        )
        self.manager.index.upsert(MemoryRecord(
            memory_id, "/profile.md", "Uses Windows.", "profile", "stated",
            "Primary Development OS", "chatgpt", "2026-09-04",
        ))
        self.assertEqual(self.manager.edit(memory_id, "Uses Windows for development.")["status"], "updated")
        self.manager.reindex()
        self.assertEqual(self.manager.index.by_id(memory_id)["subject"], "primary-development-os")

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

    def test_reserved_target_path_is_rejected(self):
        for reserved in ("/MEMORY.md", "/AI_INSTRUCTIONS.md", "ai_instructions.md"):
            result = self.manager.propose(MemoryCandidate(
                text="Attempt to plant instructions for all connected tools.",
                kind="topic",
                tag="stated",
                subject="whatever",
                writer="other",
                target_path=reserved,
            ))
            self.assertEqual(result["status"], "rejected", reserved)
            self.assertIn("reserved", result["reason"])

    def test_near_duplicate_update_is_surfaced_not_silently_dropped(self):
        first = self.manager.propose(MemoryCandidate(
            text="Uses Python 3.11 for local development.",
            kind="profile",
            tag="stated",
            subject="python-version",
            writer="chatgpt",
        ))
        self.assertEqual(first["status"], "stored")

        near = self.manager.propose(MemoryCandidate(
            text="Uses Python 3.12 for local development.",
            kind="profile",
            tag="stated",
            subject="python-version",
            writer="chatgpt",
        ))
        self.assertEqual(near["status"], "possible_update")
        self.assertEqual(near["memory"]["memory_id"], first["memory"]["memory_id"])

        applied = self.manager.supersede(near["memory"]["memory_id"], MemoryCandidate(
            text="Uses Python 3.12 for local development.",
            kind="profile",
            tag="stated",
            subject="python-version",
            writer="chatgpt",
        ))
        self.assertEqual(applied["status"], "stored")
        self.assertEqual(self.manager.index.by_id(first["memory"]["memory_id"])["tag"], "superseded")

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
