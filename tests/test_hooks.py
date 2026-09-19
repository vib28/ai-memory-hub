from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pytest
import tomllib

from memory_hub.hooks import (
    HookConfigError,
    install_claude_hook,
    install_codex_hook,
    install_hook,
    install_nested_hook,
    install_toml_hook,
    uninstall_codex_hook,
    uninstall_hook,
    uninstall_nested_hook,
    uninstall_toml_hook,
)


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
        assert result["status"] == "installed"
        assert Path(result["backup"]).exists()
        assert config["theme"] == "dark"
        assert config["hooks"]["PostToolUse"][0]["command"] == "other"
        assert sum(item.get("ai_memory_hub_managed", False) for item in config["hooks"]["PostToolUse"]) == 1

    def test_repeat_install_is_idempotent(self):
        first = install_hook(self.settings, event="PostToolUse", command="ai-memory-hook")
        second = install_hook(self.settings, event="PostToolUse", command="ai-memory-hook")
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        assert first["status"] == "installed"
        assert second["status"] == "already_installed"
        assert len(config["hooks"]["PostToolUse"]) == 1

    def test_uninstall_removes_only_managed_entries(self):
        self.settings.write_text(json.dumps({"hooks": {"PostToolUse": [{"command": "other"}]}}), encoding="utf-8")
        install_hook(self.settings, event="PostToolUse", command="ai-memory-hook")
        result = uninstall_hook(self.settings)
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        assert result["status"] == "removed"
        assert Path(result["backup"]).exists()
        assert config["hooks"]["PostToolUse"] == [{"command": "other"}]

    def test_uninstall_is_safe_noop(self):
        self.settings.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        result = uninstall_hook(self.settings)
        assert result["status"] == "not_found"
        assert list(self.settings.parent.glob("settings.json.bak-*")) == []

    def test_malformed_json_is_backed_up_and_not_overwritten(self):
        original = "{not json"
        self.settings.write_text(original, encoding="utf-8")
        with pytest.raises(HookConfigError, match="backup created"):
            install_hook(self.settings, event="PostToolUse", command="ai-memory-hook")
        assert self.settings.read_text(encoding="utf-8") == original
        assert len(list(self.settings.parent.glob("settings.json.bak-*"))) == 1

    def test_nested_hook_preserves_unrelated_groups(self):
        self.settings.write_text(json.dumps({"theme": "dark", "hooks": {
            "AfterTool": [{"matcher": "Other", "hooks": [{"type": "command", "command": "other"}]}]
        }}), encoding="utf-8")
        result = install_nested_hook(self.settings, event="AfterTool", command="ai-memory-hook")
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        assert result["status"] == "installed"
        assert config["theme"] == "dark"
        assert len(config["hooks"]["AfterTool"]) == 2
        removed = uninstall_nested_hook(self.settings)
        assert removed["status"] == "removed"
        config = json.loads(self.settings.read_text(encoding="utf-8"))
        assert len(config["hooks"]["AfterTool"]) == 1

    def test_nested_reinstall_preserves_sibling_in_same_group(self):
        self.settings.write_text(json.dumps({"hooks": {"AfterTool": [
            {"matcher": "*", "hooks": [
                {"type": "command", "command": "user-hook"},
                {"type": "command", "command": "ai-memory-hub", "name": "ai-memory-hub"},
            ]}
        ]}}), encoding="utf-8")
        install_nested_hook(self.settings, event="AfterTool", command="new-hook")
        handlers = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["AfterTool"][0]["hooks"]
        assert [item.get("command") for item in handlers] == ["user-hook", "ai-memory-hub", "new-hook"]
        uninstall_nested_hook(self.settings)
        groups = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["AfterTool"]
        assert [item.get("command") for item in groups[0]["hooks"]] == ["user-hook"]

    def test_claude_hook_uses_nested_matcher_schema_and_preserves_sibling(self):
        self.settings.write_text(json.dumps({"hooks": {"PostToolUse": [
            {"matcher": "*", "hooks": [{"type": "command", "command": "user-hook"}]}
        ]}}), encoding="utf-8")
        install_claude_hook(self.settings, event="PostToolUse", command="C:/Program Files/hook.exe")
        groups = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"]
        group = next(group for group in groups if any(item.get("ai_memory_hub_managed") for item in group["hooks"]))
        assert group["matcher"] == "*"
        assert [item["command"] for item in group["hooks"]] == ["user-hook", "C:/Program Files/hook.exe"]
        assert any(item["command"] == "user-hook" for group in groups for item in group["hooks"])

    def test_kimi_toml_hook_preserves_text_and_is_idempotent(self):
        settings = self.settings.with_suffix(".toml")
        original = "# keep this comment\nmodel = \"local\"\n\n[[hooks]]\nevent = \"Stop\"\ncommand = \"other\"\n"
        settings.write_text(original, encoding="utf-8")
        first = install_toml_hook(settings, event="PostToolUse", command="ai-memory-hook")
        second = install_toml_hook(settings, event="PostToolUse", command="ai-memory-hook")
        content = settings.read_text(encoding="utf-8")
        assert first["status"] == "installed"
        assert second["status"] == "already_installed"
        assert original in content
        assert content.count("# ai-memory-hub managed hook") == 1
        with settings.open("rb") as stream:
            parsed = tomllib.load(stream)
        managed = [hook for hook in parsed["hooks"] if hook["command"] == "ai-memory-hook"]
        assert managed[0]["event"] == "PostToolUse"
        assert Path(first["backup"]).exists()

    def test_kimi_toml_uninstall_removes_only_managed_block(self):
        settings = self.settings.with_suffix(".toml")
        settings.write_text("model = \"local\"\n", encoding="utf-8")
        install_toml_hook(settings, event="PostToolUse", command="ai-memory-hook")
        settings.write_text(settings.read_text(encoding="utf-8") + "\n[[hooks]]\nevent = \"Stop\"\ncommand = \"other\"\n", encoding="utf-8")
        result = uninstall_toml_hook(settings)
        content = settings.read_text(encoding="utf-8")
        assert result["status"] == "removed"
        assert 'event = "Stop"' in content
        assert "ai-memory-hub managed" not in content

    def test_kimi_toml_malformed_marker_is_not_rewritten(self):
        settings = self.settings.with_suffix(".toml")
        original = "# ai-memory-hub managed hook\n[[hooks]]\nevent = \"PostToolUse\"\n"
        settings.write_text(original, encoding="utf-8")
        with pytest.raises(HookConfigError, match="incomplete"):
            install_toml_hook(settings, event="PostToolUse", command="ai-memory-hook")
        assert settings.read_text(encoding="utf-8") == original

    def test_codex_hook_preserves_unrelated_handlers_and_is_idempotent(self):
        settings = self.settings.with_name("hooks.json")
        settings.write_text(json.dumps({"description": "keep", "hooks": {
            "PostToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "other"}]}]
        }}), encoding="utf-8")
        first = install_codex_hook(settings, event="PostToolUse", command="ai-memory-hook")
        second = install_codex_hook(settings, event="PostToolUse", command="ai-memory-hook")
        config = json.loads(settings.read_text(encoding="utf-8"))
        assert first["status"] == "installed"
        assert second["status"] == "already_installed"
        assert config["description"] == "keep"
        assert len(config["hooks"]["PostToolUse"]) == 2
        assert Path(first["backup"]).exists()

    def test_codex_uninstall_removes_only_marked_handler(self):
        settings = self.settings.with_name("hooks.json")
        install_codex_hook(settings, event="PostToolUse", command="ai-memory-hook")
        config = json.loads(settings.read_text(encoding="utf-8"))
        config["hooks"]["PostToolUse"][0]["hooks"].append({"type": "command", "command": "other"})
        settings.write_text(json.dumps(config), encoding="utf-8")
        result = uninstall_codex_hook(settings, command="ai-memory-hook")
        config = json.loads(settings.read_text(encoding="utf-8"))
        assert result["status"] == "removed"
        assert config["hooks"]["PostToolUse"][0]["hooks"] == [{"type": "command", "command": "other"}]

    def test_codex_uninstall_removes_sole_handler_and_empty_group(self):
        # Regression for #67: install_codex_hook always creates a single-handler group
        # ({"matcher": "*", "hooks": [entry]}), which is the common case — not the
        # sibling-survives case test_codex_uninstall_removes_only_marked_handler covers.
        settings = self.settings.with_name("hooks.json")
        install_codex_hook(settings, event="SessionStart", command="ai-memory-hook")
        result = uninstall_codex_hook(settings, command="ai-memory-hook")
        config = json.loads(settings.read_text(encoding="utf-8"))
        assert result["status"] == "removed"
        assert result["removed"] == 1
        assert "SessionStart" not in config.get("hooks", {})

    def test_codex_reinstall_preserves_sibling_and_updates_path(self):
        settings = self.settings.with_name("hooks.json")
        install_codex_hook(settings, event="PostToolUse", command="old-hook")
        config = json.loads(settings.read_text(encoding="utf-8"))
        config["hooks"]["PostToolUse"][0]["hooks"].append({"type": "command", "command": "user-hook"})
        settings.write_text(json.dumps(config), encoding="utf-8")
        install_codex_hook(settings, event="PostToolUse", command="old-hook")
        handlers = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"][0]["hooks"]
        assert [item["command"] for item in handlers] == ["old-hook", "user-hook"]
        install_codex_hook(settings, event="PostToolUse", command="new-hook")
        handlers = json.loads(settings.read_text(encoding="utf-8"))["hooks"]["PostToolUse"][0]["hooks"]
        assert [item["command"] for item in handlers] == ["old-hook", "user-hook", "new-hook"]

    def test_claude_capture_and_context_coexist_on_the_same_event(self):
        install_claude_hook(self.settings, event="UserPromptSubmit", command="hook.exe",
                            args=["--client", "claude"])
        install_claude_hook(self.settings, event="UserPromptSubmit", command="context.exe",
                            args=["--host", "claude", "--mode", "turn"])
        groups = json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
        commands = [handler["command"] for group in groups for handler in group["hooks"]]
        assert commands.count("hook.exe") == 1
        assert commands.count("context.exe") == 1
        from memory_hub.hooks import uninstall_claude_hook
        removed = uninstall_claude_hook(self.settings, command="context.exe")
        assert removed["removed"] == 1
        leftover = [handler["command"] for group in json.loads(self.settings.read_text(encoding="utf-8"))["hooks"]["UserPromptSubmit"]
                    for handler in group["hooks"]]
        assert "hook.exe" in leftover
        assert "context.exe" not in leftover


if __name__ == "__main__":
    unittest.main()
