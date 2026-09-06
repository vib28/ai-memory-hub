from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from memory_hub.hooks import HookConfigError, install_hook, uninstall_hook


class HookConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_preserves_unrelated_settings_and_creates_backup(self):
        self.settings.write_text(json.dumps({"theme": "dark", "hooks": {"PostToolUse": [{"command": "other"}]}}), encoding="utf-8")
        result = install_hook(self.settings, event="PostToolUse", command="ai-memory-hook", args=["--source", "test"])
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "installed")
        self.assertTrue(Path(result["backup"]).exists())
        self.assertEqual(config["theme"], "dark")
        self.assertEqual(config["hooks"]["PostToolUse"][0]["command"], "other")
        self.assertEqual(sum(item.get("ai_memory_hub_managed", False) for item in config["hooks"]["PostToolUse"]), 1)

    def test_repeat_install_is_idempotent(self):
        first = install_hook(self.settings, event="PostToolUse", command="ai-memory-hook")
        second = install_hook(self.settings, event="PostToolUse", command="ai-memory-hook")
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(first["status"], "installed")
        self.assertEqual(second["status"], "already_installed")
        self.assertEqual(len(config["hooks"]["PostToolUse"]), 1)

    def test_uninstall_removes_only_managed_entries(self):
        self.settings.write_text(json.dumps({"hooks": {"PostToolUse": [{"command": "other"}]}}), encoding="utf-8")
        install_hook(self.settings, event="PostToolUse", command="ai-memory-hook")
        result = uninstall_hook(self.settings)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "removed")
        self.assertTrue(Path(result["backup"]).exists())
        self.assertEqual(config["hooks"]["PostToolUse"], [{"command": "other"}])

    def test_uninstall_is_safe_noop(self):
        self.settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        result = uninstall_hook(self.settings)
        self.assertEqual(result["status"], "not_found")
        self.assertEqual(list(self.settings.parent.glob("settings.json.bak-*")), [])

    def test_malformed_json_is_backed_up_and_not_overwritten(self):
        original = "{not json"
        self.settings.write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(HookConfigError, "backup created"):
            install_hook(self.settings, event="PostToolUse", command="ai-memory-hook")
        self.assertEqual(self.settings.read_text(encoding="utf-8"), original)
        self.assertEqual(len(list(self.settings.parent.glob("settings.json.bak-*"))), 1)


if __name__ == "__main__":
    unittest.main()
