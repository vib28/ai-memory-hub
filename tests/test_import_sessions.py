import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "import_sessions.py"


class SessionImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.vault.mkdir()
        self.input = Path(self.tmp.name) / "sessions.json"
        self.input.write_text(json.dumps({"sessions": [{
            "title": "Imported session",
            "project": "demo",
            "investigated": ["Reviewed a file"],
            "learned": ["The file contains a rule"],
            "completed": ["Recorded the result"],
            "next_steps": ["Verify the rule"],
        }]}), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, env=None):
        command = [sys.executable, str(SCRIPT), "--vault", str(self.vault),
                   "--input", str(self.input), "--writer", "codex", *args]
        result = subprocess.run(command, capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    def test_dry_run_does_not_write(self):
        result = self.run_script("--dry-run")
        assert result["status"] == "dry_run"
        assert result["would_import"] == 1
        assert not (self.vault / "sessions").exists()

    def test_review_import_is_verified_and_retry_is_duplicate(self):
        env = os.environ.copy()
        env["MEMORY_WRITE_MODE"] = "review"
        first = self.run_script(env=env)
        second = self.run_script(env=env)
        assert first["status"] == "complete"
        assert first["imported"] == 1
        assert second["status"] == "complete"
        assert second["imported"] == 1

    def test_malformed_input_fails_loudly(self):
        self.input.write_text(json.dumps({"sessions": [{"title": "missing sections"}]}), encoding="utf-8")
        command = [sys.executable, str(SCRIPT), "--vault", str(self.vault), "--input", str(self.input)]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 2
        assert "missing" in result.stdout


if __name__ == "__main__":
    unittest.main()
