import tempfile
import unittest
from pathlib import Path

from memory_hub.manager import MemoryManager


class PatternTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = MemoryManager(Path(self.tmp.name) / "vault")
        self.manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def test_first_match_writes_linked_project_and_global_preference(self):
        result = self.manager.propose_pattern_match("regression", "A regression was fixed.",
                                                   "Add a regression test.", "demo-project", writer="codex")
        assert result["status"] == "stored"
        assert result["label"] == "first occurrence"
        assert "[[demo-project]]" in self.manager.read("/preferences.md")
        assert "[[demo-project]]" in self.manager.read("/projects/demo-project.md")

    def test_review_match_is_atomic_and_labeled(self):
        result = self.manager.propose_pattern_match("regression", "A bug was fixed.",
                                                   "Check regression coverage.", "demo-project",
                                                   write_mode="review", writer="codex")
        assert result["label"] == "first occurrence"
        approved = self.manager.approve(result["proposal"]["proposal_id"])
        assert approved["status"] == "stored"
        assert len(self.manager.search("regression coverage")) == 1

    def test_rejected_preference_half_writes_neither_half(self):
        """A pattern is its two linked halves. Committing one and failing the other
        leaves an orphaned project fact whose rule never existed (#23)."""
        secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"
        result = self.manager.propose_pattern_match("regression", "A regression was fixed.",
                                                    secret, "atomic-demo", writer="codex")
        assert result["status"] == "rejected"
        assert result["half"] == "preference"
        assert result.get("reason") is not None
        assert not (self.manager.vault.root / "projects" / "atomic-demo.md").exists()

    def test_rejected_project_half_writes_neither_half(self):
        secret = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcdef"
        result = self.manager.propose_pattern_match("regression", secret,
                                                    "Add a regression test.", "atomic-demo2",
                                                    writer="codex")
        assert result["status"] == "rejected"
        assert result["half"] == "project"
        assert "[[atomic-demo2]]" not in self.manager.read("/preferences.md")

    def test_unknown_pattern_is_rejected_with_reason(self):
        result = self.manager.propose_pattern_match("nosuchpattern", "fact", "rule", "demo")
        assert result["status"] == "rejected"
        assert "unknown pattern" in result["reason"]

    def test_malformed_pattern_is_rejected_loudly(self):
        path = self.manager.vault.root / "patterns.md"
        path.write_text(
            "## broken\nTrigger: regression\nProject fact: record it\n",
            encoding="utf-8",
        )
        result = self.manager.propose_pattern_match(
            "broken", "fact", "rule", "demo", writer="codex"
        )
        assert result["status"] == "rejected"
        assert "preference rule" in result["reason"]

    def test_later_match_is_confirmed_and_updates_preference(self):
        first = self.manager.propose_pattern_match("regression", "First regression.",
                                                   "Check regression coverage.", "demo-project", writer="codex")
        assert first["label"] == "first occurrence"
        second = self.manager.propose_pattern_match("regression", "Second regression.",
                                                    "Check regression coverage.", "demo-project", writer="codex")
        assert second["label"] == "confirmed pattern"
        assert second["preference"]["status"] == "stored"


if __name__ == "__main__":
    unittest.main()
