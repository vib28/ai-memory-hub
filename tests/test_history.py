from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from memory_hub.history import commit_vault_change, history_status, initialize_history


class VaultHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "vault"
        self.root.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_initialize_is_opt_in_idempotent_and_ignores_disposable_files(self):
        first = initialize_history(self.root)
        second = initialize_history(self.root)
        self.assertEqual(first["status"], "initialized")
        self.assertEqual(second["status"], "already_initialized")
        ignore = (self.root / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".memory_index.sqlite3", ignore)
        self.assertIn("*.lock", ignore)
        self.assertTrue((self.root / ".git").exists())

    def test_commit_contains_session_id_and_excludes_index_artifacts(self):
        initialize_history(self.root)
        (self.root / "sessions.md").write_text("session one\n", encoding="utf-8")
        (self.root / ".memory_index.sqlite3").write_text("not source\n", encoding="utf-8")
        result = commit_vault_change(self.root, "session-123", ["/sessions.md", "/.memory_index.sqlite3"])
        self.assertEqual(result["status"], "committed")
        log = subprocess.check_output(["git", "-C", str(self.root), "log", "-1", "--format=%s"], text=True).strip()
        self.assertIn("session-123", log)
        tracked = subprocess.check_output(["git", "-C", str(self.root), "ls-files"], text=True)
        self.assertIn("sessions.md", tracked)
        self.assertNotIn(".memory_index.sqlite3", tracked)
        self.assertTrue(history_status(self.root)["enabled"])

    def test_uninitialized_vault_does_not_commit(self):
        result = commit_vault_change(self.root, "s1", ["file.md"])
        self.assertEqual(result["status"], "disabled")


if __name__ == "__main__":
    unittest.main()
