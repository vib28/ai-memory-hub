from __future__ import annotations

import json
import tempfile
import tomllib
import unittest
from pathlib import Path

from memory_hub.hooks import (HookConfigError, install_codex_hook, install_hook,
                              install_nested_hook, install_toml_hook, uninstall_codex_hook,
                              uninstall_hook, uninstall_nested_hook, uninstall_toml_hook)


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

    def test_nested_hook_preserves_unrelated_groups(self):
        self.settings.write_text(json.dumps({"theme": "dark", "hooks": {
            "AfterTool": [{"matcher": "Other", "hooks": [{"type": "command", "command": "other"}]}]
        }}), encoding="utf-8")
        result = install_nested_hook(self.settings, event="AfterTool", command="ai-memory-hook")
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "installed")
        self.assertEqual(config["theme"], "dark")
        self.assertEqual(len(config["hooks"]["AfterTool"]), 2)
        removed = uninstall_nested_hook(self.settings)
        self.assertEqual(removed["status"], "removed")
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        self.assertEqual(len(config["hooks"]["AfterTool"]), 1)

    def test_kimi_toml_hook_preserves_text_and_is_idempotent(self):
        settings = self.settings.with_suffix(".toml")
        original = "# keep this comment\nmodel = \"local\"\n\n[[hooks]]\nevent = \"Stop\"\ncommand = \"other\"\n"
        settings.write_text(original, encoding="utf-8")
        first = install_toml_hook(settings, event="PostToolUse", command="ai-memory-hook")
        second = install_toml_hook(settings, event="PostToolUse", command="ai-memory-hook")
        content = settings.read_text(encoding="utf-8")
        self.assertEqual(first["status"], "installed")
        self.assertEqual(second["status"], "already_installed")
        self.assertIn(original, content)
        self.assertEqual(content.count("# ai-memory-hub managed hook"), 1)
        with settings.open("rb") as stream:
            parsed = tomllib.load(stream)
        managed = [hook for hook in parsed["hooks"] if hook["command"] == "ai-memory-hook"]
        self.assertEqual(managed[0]["event"], "PostToolUse")
        self.assertTrue(Path(first["backup"]).exists())

    def test_kimi_toml_uninstall_removes_only_managed_block(self):
        settings = self.settings.with_suffix(".toml")
        settings.write_text("model = \"local\"\n", encoding="utf-8")
        install_toml_hook(settings, event="PostToolUse", command="ai-memory-hook")
        settings.write_text(settings.read_text(encoding="utf-8") + "\n[[hooks]]\nevent = \"Stop\"\ncommand = \"other\"\n", encoding="utf-8")
        result = uninstall_toml_hook(settings)
        content = settings.read_text(encoding="utf-8")
        self.assertEqual(result["status"], "removed")
        self.assertIn('event = "Stop"', content)
        self.assertNotIn("ai-memory-hub managed", content)

    def test_kimi_toml_malformed_marker_is_not_rewritten(self):
        settings = self.settings.with_suffix(".toml")
        original = "# ai-memory-hub managed hook\n[[hooks]]\nevent = \"PostToolUse\"\n"
        settings.write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(HookConfigError, "incomplete"):
            install_toml_hook(settings, event="PostToolUse", command="ai-memory-hook")
        self.assertEqual(settings.read_text(encoding="utf-8"), original)

    def test_codex_hook_preserves_unrelated_handlers_and_is_idempotent(self):
        settings = self.settings.with_name("hooks.json")
        settings.write_text(json.dumps({"description": "keep", "hooks": {
            "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other"}]}]
        }}), encoding="utf-8")
        first = install_codex_hook(settings, event="PostToolUse", command="ai-memory-hook")
        second = install_codex_hook(settings, event="PostToolUse", command="ai-memory-hook")
        config = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(first["status"], "installed")
        self.assertEqual(second["status"], "already_installed")
        self.assertEqual(config["description"], "keep")
        self.assertEqual(len(config["hooks"]["PostToolUse"]), 2)
        self.assertTrue(Path(first["backup"]).exists())

    def test_codex_uninstall_removes_only_marked_handler(self):
        settings = self.settings.with_name("hooks.json")
        install_codex_hook(settings, event="PostToolUse", command="ai-memory-hook")
        config = json.loads(settings.read_text(encoding="utf-8"))
        config["hooks"]["PostToolUse"][0]["hooks"].append({"type": "command", "command": "other"})
        settings.write_text(json.dumps(config), encoding="utf-8")
        result = uninstall_codex_hook(settings, command="ai-memory-hook")
        config = json.loads(settings.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "removed")
        self.assertEqual(config["hooks"]["PostToolUse"][0]["hooks"], [{"type": "command", "command": "other"}])


if __name__ == "__main__":
    unittest.main()
