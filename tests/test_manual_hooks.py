"""Tests for the extensible manual hook system (unsupported clients)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory_hub.hooks import (install_hook, uninstall_hook, HookConfigError)


class ManualHookTests(unittest.TestCase):
    """Tests for the generic/manual hook install path used by unsupported clients."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_manual_hook_install_creates_valid_json_structure(self):
        """Install a manual hook into an empty settings file."""
        result = install_hook(
            self.settings,
            event="PostToolUse",
            command="C:/Tools/ai-memory-hub/.venv/Scripts/ai-memory-hook.exe",
            args=["--client", "opencode"],
        )
        self.assertEqual(result["status"], "installed")
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertIn("hooks", config)
        self.assertIn("PostToolUse", config["hooks"])
        hook_entry = config["hooks"]["PostToolUse"][0]
        self.assertEqual(hook_entry["ai_memory_hub_managed"], True)
        self.assertEqual(hook_entry["command"], "C:/Tools/ai-memory-hub/.venv/Scripts/ai-memory-hook.exe")

    def test_manual_hook_install_preserves_existing_content(self):
        """Manual hook must not disturb existing settings."""
        self.settings.write_text(
            json.dumps({"theme": "dark", "model": "claude-sonnet-4-20250514"}),
            encoding="utf-8",
        )
        install_hook(
            self.settings,
            event="PostToolUse",
            command="ai-memory-hook.exe",
            args=["--client", "opencode"],
        )
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(config["theme"], "dark")
        self.assertEqual(config["model"], "claude-sonnet-4-20250514")

    def test_manual_hook_uninstall_removes_only_managed(self):
        """Remove only the manual hook entry, leave others."""
        self.settings.write_text(
            json.dumps({
                "hooks": {
                    "PostToolUse": [
                        {"type": "command", "command": "user-pre-hook"},
                    ]
                }
            }),
            encoding="utf-8",
        )
        install_hook(
            self.settings,
            event="PostToolUse",
            command="ai-memory-hook.exe",
            args=["--client", "opencode"],
        )
        result = uninstall_hook(self.settings, command="ai-memory-hook.exe")
        self.assertEqual(result["status"], "removed")
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        # User hook preserved
        self.assertEqual(len(config["hooks"]["PostToolUse"]), 1)
        self.assertEqual(config["hooks"]["PostToolUse"][0]["command"], "user-pre-hook")

    def test_manual_hook_is_idempotent(self):
        """Installing twice produces no duplicate entries."""
        command = "ai-memory-hook.exe"
        args = ["--client", "opencode"]
        install_hook(self.settings, event="PostToolUse", command=command, args=args)
        result = install_hook(self.settings, event="PostToolUse", command=command, args=args)
        self.assertEqual(result["status"], "already_installed")
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        managed = [h for h in config["hooks"]["PostToolUse"] if h.get("ai_memory_hub_managed")]
        self.assertEqual(len(managed), 1)

    def test_manual_hook_single_managed_entry_per_event(self):
        """The simple JSON format supports one managed hook per event.

        Installing a second managed hook on the same event replaces the first.
        For multiple clients, use different events or the nested/claude format.
        """
        install_hook(
            self.settings,
            event="PostToolUse",
            command="ai-memory-hook.exe",
            args=["--client", "opencode"],
        )
        install_hook(
            self.settings,
            event="PostToolUse",
            command="ai-memory-hook.exe",
            args=["--client", "continue"],
        )
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        managed = [h for h in config["hooks"]["PostToolUse"] if h.get("ai_memory_hub_managed")]
        # Only one managed entry per event in simple JSON format
        self.assertEqual(len(managed), 1)
        # The second install replaced the first (command stays the same exe, args are replaced)
        self.assertEqual(managed[0]["command"], "ai-memory-hook.exe")

    def test_manual_hook_different_events(self):
        """A single client can have hooks on multiple lifecycle events."""
        install_hook(
            self.settings,
            event="PostToolUse",
            command="ai-memory-hook.exe",
            args=["--client", "opencode"],
        )
        install_hook(
            self.settings,
            event="SessionStart",
            command="ai-memory-hook.exe",
            args=["--client", "opencode"],
        )
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertIn("PostToolUse", config["hooks"])
        self.assertIn("SessionStart", config["hooks"])
        self.assertTrue(any(h.get("ai_memory_hub_managed") for h in config["hooks"]["PostToolUse"]))
        self.assertTrue(any(h.get("ai_memory_hub_managed") for h in config["hooks"]["SessionStart"]))

    def test_manual_hook_uninstall_nonexistent_is_safe(self):
        """Removing a hook that was never installed is a safe no-op."""
        self.settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        result = uninstall_hook(self.settings, command="ai-memory-hook.exe")
        self.assertEqual(result["status"], "not_found")
        # No backup should be created when nothing changes
        backups = list(self.settings.parent.glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 0)

    def test_manual_hook_backup_created_on_install(self):
        """Backup file is created before modifying settings."""
        self.settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        install_hook(
            self.settings,
            event="PostToolUse",
            command="ai-memory-hook.exe",
            args=["--client", "opencode"],
        )
        backups = list(self.settings.parent.glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 1)


if __name__ == "__main__":
    unittest.main()
