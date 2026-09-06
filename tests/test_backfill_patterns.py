import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "backfill_patterns.py"
TEMPLATE = ROOT / "vault_template"


class BackfillPatternTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.vault.mkdir()
        (self.vault / "patterns.md").write_text(
            "## regression\nTrigger: regression, bug\n"
            "Project fact: record the cause\n"
            "Preference rule: Add a regression check\n",
            encoding="utf-8",
        )
        projects = self.vault / "projects"
        projects.mkdir()
        (projects / "demo.md").write_text("# Demo\n\nA bug was fixed.\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, env=None):
        command = [sys.executable, str(SCRIPT), "--vault", str(self.vault), *args]
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_dry_run_writes_nothing(self):
        result = self.run_script("--dry-run")
        self.assertEqual(result["status"], "dry_run")
        self.assertEqual(result["would_propose"], 1)
        self.assertFalse((self.vault / "preferences.md").exists())

    def test_review_mode_uses_public_tool_and_is_idempotent(self):
        env = os.environ.copy()
        env["MEMORY_WRITE_MODE"] = "review"
        first = self.run_script(env=env)
        second = self.run_script(env=env)
        self.assertEqual(first["queued"], 1)
        self.assertEqual(second["queued"], 0)
        self.assertEqual(second["skipped"], 1)

    def test_malformed_pattern_fails_without_fallback(self):
        (self.vault / "patterns.md").write_text(
            "## regression\nTrigger: regression\nProject fact: record it\n",
            encoding="utf-8",
        )
        command = [sys.executable, str(SCRIPT), "--vault", str(self.vault)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("preference rule", result.stdout)


if __name__ == "__main__":
    unittest.main()
