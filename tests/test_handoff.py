from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from memory_hub.handoff import build_handoff
from memory_hub.hooks import install_claude_hook, install_codex_hook
from memory_hub.manager import MemoryManager


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        self.manager = MemoryManager(self.vault)
        self.manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def _checkpoint(self, *, model: str, group: str, title: str, sequence: int = 1,
                    project: str = "handoff-demo") -> None:
        result = self.manager.propose_session({
            "model": model,
            "title": title,
            "date": "2026-09-09T10:00:00",
            "project": project,
            "investigated": ["Reviewed the continuity boundary"],
            "learned": ["The decision is to keep startup restoration local"],
            "completed": ["Verified the checkpoint write"],
            "next_steps": ["Resume the integration test"],
            "session_group_id": group,
            "checkpoint_id": f"checkpoint-{group}-{sequence}",
            "sequence": sequence,
            "entry_type": "checkpoint",
            "source_client": model,
            "worktree": str(self.tmp.name),
            "changed_files": ["src/worker.py", "tests/test_handoff.py"],
            "host_session_finalized": True,
        })
        assert result["status"] in {"stored", "stored_without_project_link"}

    def test_claude_to_codex_process_fixture_injects_bounded_quoted_context(self):
        self._checkpoint(model="claude", group="claude-codex", title="Restore the handoff")
        payload = {"session_id": "codex-fixture", "cwd": self.tmp.name, "source": "startup"}
        result = subprocess.run(
            [sys.executable, "-m", "memory_hub.handoff", "--vault", str(self.vault), "--client", "codex",
             "--max-chars", "1800"],
            input=json.dumps(payload), text=True, capture_output=True, check=True,
        )
        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert output["status"] == "ok"
        assert len(context) <= 1800
        assert "Restore the handoff" in context
        assert "src/worker.py" in context
        assert "Verified the checkpoint write" in context
        assert "Resume the integration test" in context
        assert "quoted-evidence" in context
        tiny = build_handoff(self.vault, payload=payload, client="codex", max_chars=200)
        assert tiny["packet_chars"] <= 200

    def test_malformed_max_chars_env_degrades_instead_of_crashing(self):
        """#75: MEMORY_HANDOFF_MAX_CHARS is read while argparse builds the parser, outside
        the try block whose entire purpose is "startup context must never block the host
        client". A non-numeric value must still exit 0 with an unavailable packet, not a
        traceback.
        """
        env = dict(os.environ, MEMORY_HANDOFF_MAX_CHARS="6k")
        result = subprocess.run(
            [sys.executable, "-m", "memory_hub.handoff", "--vault", str(self.vault), "--client", "codex"],
            input=json.dumps({"session_id": "malformed-env", "cwd": self.tmp.name, "source": "startup"}),
            text=True, capture_output=True, env=env,
        )
        assert result.returncode == 0, result.stderr
        output = json.loads(result.stdout)
        assert output["status"] in {"ok", "empty", "unavailable"}

    def test_codex_to_claude_fixture_reads_without_network_dependencies(self):
        self._checkpoint(model="codex", group="codex-claude", title="Continue from Codex")
        result = build_handoff(
            self.vault,
            payload={"session_id": "claude-fixture", "cwd": self.tmp.name, "source": "resume"},
            client="claude",
            now=datetime(2026, 9, 9, 10, 5, tzinfo=timezone.utc),
            max_chars=1800,
        )
        assert result["status"] == "ok"
        assert result["client"] == "claude"
        assert "Continue from Codex" in result["packet"]
        assert result["groups"][0]["source_client"] == "codex"
        assert result["groups"][0]["checkpoint_age_seconds"] >= 0
        assert result["pending_evidence"]

    def test_ambiguous_active_groups_are_kept_separate(self):
        self._checkpoint(model="claude", group="task-one", title="First task")
        self._checkpoint(model="codex", group="task-two", title="Second task")
        result = build_handoff(self.vault, payload={"project": "handoff-demo"}, client="codex")
        assert result["ambiguous"]
        assert {group["session_group_id"] for group in result["groups"]} == {"task-one", "task-two"}
        assert "listed separately" in result["packet"]
        assert "First task" in result["packet"]
        assert "Second task" in result["packet"]

    def test_session_start_installers_preserve_siblings_and_use_supported_event(self):
        claude_settings = Path(self.tmp.name) / "claude-settings.json"
        codex_settings = Path(self.tmp.name) / "codex-hooks.json"
        claude_settings.write_text(json.dumps({"theme": "dark", "hooks": {"PostToolUse": [{"command": "other"}]}}), encoding="utf-8")
        codex_settings.write_text(json.dumps({"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other"}]}]}}), encoding="utf-8")
        handoff_command = "C:/Program Files/AI Memory/ai-memory-handoff.exe"
        install_claude_hook(claude_settings, event="SessionStart", command=handoff_command)
        install_codex_hook(codex_settings, event="SessionStart", command=handoff_command,
                           additional_context_limit=3000)
        claude = json.loads(claude_settings.read_text(encoding="utf-8"))
        codex = json.loads(codex_settings.read_text(encoding="utf-8"))
        assert "PostToolUse" in claude["hooks"]
        assert claude["hooks"]["SessionStart"][0]["hooks"][0]["command"] == handoff_command
        assert codex["hooks"]["SessionStart"][0]["hooks"][0]["command"] == handoff_command
        assert codex["hooks"]["SessionStart"][0]["hooks"][0]["additionalContextLimit"] == 3000


if __name__ == "__main__":
    unittest.main()
