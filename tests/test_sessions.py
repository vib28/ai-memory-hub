import tempfile
import unittest
from pathlib import Path

from memory_hub.manager import MemoryManager


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        self.manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_session_path_block_fts_and_project_link(self):
        result = self.manager.propose_session({
            "model": "codex", "title": "autotradag", "date": "2026-09-06T23:00:00",
            "project": "ai-memory-hub", "investigated": ["FTS indexing"],
            "learned": ["Session blocks need stable IDs"], "completed": ["Implemented sessions"],
            "next_steps": ["Add tests"],
        })
        self.assertEqual(result["status"], "stored")
        memory = result["memory"]
        self.assertEqual(memory["path"], "/sessions/codex.md")
        content = self.manager.read("/sessions/codex.md")
        self.assertIn("## codex-autotradag-2026-09-06-230000", content)
        self.assertIn("### Investigated", content)
        self.assertIn("#codex #2026-09-06", content)
        self.assertTrue(any(r["memory_id"] == memory["memory_id"] for r in self.manager.search("stable IDs")))
        project = result["project"]["memory"]
        self.assertEqual(project["path"], "/projects/ai-memory-hub.md")
        self.assertIn(f"[[{memory['subject']}]]", self.manager.read(project["path"]))

    def test_review_approval_preserves_session_sections(self):
        result = self.manager.propose_session({
            "model": "gemini", "title": "review", "investigated": ["One thing"],
            "learned": ["Another thing"], "completed": ["A task"], "next_steps": ["More work"],
        }, write_mode="review")
        self.assertEqual(result["status"], "queued")
        approved = self.manager.approve(result["proposal"]["proposal_id"])
        self.assertEqual(approved["status"], "stored")
        self.assertIn("### Next Steps", self.manager.read("/sessions/gemini.md"))


if __name__ == "__main__":
    unittest.main()
