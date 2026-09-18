"""#86: one context packet, six host wire shapes, no double injection."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from memory_hub.context_packet import (
    DEFAULT_START_CHARS, build_packet, load_ledger, prune_ledgers, render,
)
from memory_hub.hooks import (
    install_hermes_hook, install_toml_hook, uninstall_hermes_hook, uninstall_toml_hook,
)
from memory_hub.manager import MemoryManager
from memory_hub.models import MemoryCandidate
from memory_hub.project_resolver import clear_cache


class PacketFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.vault = root / "vault"
        self.repo = root / "widget-app"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "src").mkdir()
        self.other = root / "other-app"
        (self.other / ".git").mkdir(parents=True)
        clear_cache()
        self.manager = MemoryManager(self.vault)
        self.manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")
        self._seed()

    def tearDown(self):
        self.manager.close()
        self.tmp.cleanup()

    def _propose(self, text, kind, tag, subject):
        result = self.manager.propose(MemoryCandidate(text=text, kind=kind, tag=tag, subject=subject,
                                                      writer="claude"))
        self.assertIn(result["status"], {"stored"}, result)
        return result["memory"]["memory_id"]

    def _seed(self):
        self.pref_id = self._propose("Rule: status reports must be tables. Reason: scannable.",
                                     "preference", "preference", "status-report-format")
        self.profile_id = self._propose("Primary development OS is Windows 11 with git-bash.",
                                        "profile", "stated", "primary-development-os")
        self.project_id = self._propose(
            "Fact: widget-app ships a date filter on the dashboard library. Context: shipped 2026-09.",
            "project", "stated", "widget-app")
        self.foreign_id = self._propose(
            "Fact: other-app uses a dashboard date filter too but with a different library.",
            "project", "stated", "other-app")
        self.manager.propose_session({
            "model": "claude", "title": "Add dashboard date filter", "date": "2026-09-18T10:00:00",
            "project": "widget-app",
            "investigated": ["Looked at the library view"], "learned": ["Inclusive ranges are expected"],
            "completed": ["Filter and tests added"], "next_steps": ["Wire the clear button"],
            "session_group_id": "grp-1", "checkpoint_id": "cp-1", "sequence": 1,
            "entry_type": "final", "source_client": "claude", "worktree": str(self.repo),
            "changed_files": ["src/library.js"], "host_session_finalized": True,
        })


class StartPacketTests(PacketFixture):
    def test_start_packet_has_checkpoint_project_facts_and_globals_but_not_foreign_projects(self):
        packet = build_packet(self.vault, mode="start", host="claude",
                              payload={"session_id": "s1", "cwd": str(self.repo / "src")})
        text = packet["text"]
        self.assertEqual(packet["project"], "widget-app")
        self.assertIn("## Last checkpoint", text)
        self.assertIn("Wire the clear button", text)
        self.assertIn("## Project facts: widget-app", text)
        self.assertIn("date filter on the dashboard library", text)
        self.assertIn("## Global preferences and profile", text)
        self.assertIn("status reports must be tables", text)
        self.assertIn("Windows 11", text)
        self.assertNotIn("other-app uses", text)
        self.assertLessEqual(packet["chars"], DEFAULT_START_CHARS)
        self.assertIn(self.pref_id, packet["memory_ids"])
        self.assertIn(self.project_id, packet["memory_ids"])
        self.assertNotIn(self.foreign_id, packet["memory_ids"])

    def test_budget_is_respected_and_wrapper_stays_well_formed(self):
        packet = build_packet(self.vault, mode="start", host="codex",
                              payload={"session_id": "s2", "cwd": str(self.repo)}, max_chars=400)
        self.assertLessEqual(packet["chars"], 400)
        self.assertTrue(packet["text"].startswith("<ai-memory-context"))
        self.assertTrue(packet["text"].rstrip().endswith("</ai-memory-context>"))

    def test_unscoped_cwd_gets_globals_only(self):
        packet = build_packet(self.vault, mode="start", host="claude",
                              payload={"session_id": "s3", "cwd": str(Path.home())})
        self.assertIsNone(packet["project"])
        self.assertIn("status reports must be tables", packet["text"])
        self.assertNotIn("Project facts", packet["text"])


class TurnPacketTests(PacketFixture):
    def test_turn_after_start_is_silent_when_nothing_new(self):
        payload = {"session_id": "s1", "cwd": str(self.repo)}
        build_packet(self.vault, mode="start", host="claude", payload=payload)
        turn = build_packet(self.vault, mode="turn", host="claude",
                            payload={**payload, "prompt": "continue please"})
        self.assertTrue(turn["empty"])
        self.assertEqual(turn["text"], "")

    def test_turn_injects_only_new_project_facts_once(self):
        payload = {"session_id": "s1", "cwd": str(self.repo)}
        build_packet(self.vault, mode="start", host="claude", payload=payload)
        new_id = self._propose("Decision: keep the filter inclusive on both ends. Why: user expectation.",
                               "project", "decided", "widget-app")
        first = build_packet(self.vault, mode="turn", host="claude", payload={**payload, "prompt": "hi"})
        second = build_packet(self.vault, mode="turn", host="claude", payload={**payload, "prompt": "hi"})
        self.assertIn("inclusive on both ends", first["text"])
        self.assertEqual(first["memory_ids"], [new_id])
        self.assertTrue(second["empty"])
        ledger = load_ledger(self.vault, "claude", "s1")
        self.assertEqual(ledger["injected"].count(new_id), 1)

    def test_turn_surfaces_related_memories_by_prompt_words(self):
        payload = {"session_id": "s1", "cwd": str(self.repo)}
        build_packet(self.vault, mode="start", host="claude", payload=payload)
        self._propose("Finding: git-bash mangles backslashes in PowerShell args. Fix: use forward slashes.",
                      "topic", "stated", "windows-git-bash-paths")
        turn = build_packet(self.vault, mode="turn", host="claude",
                            payload={**payload, "prompt": "why does git-bash break my PowerShell backslashes?"})
        self.assertIn("## Related memories", turn["text"])
        self.assertIn("forward slashes", turn["text"])

    def test_turn_without_prior_start_behaves_like_start(self):
        turn = build_packet(self.vault, mode="turn", host="kimi",
                            payload={"session_id": "fresh", "cwd": str(self.repo), "prompt": "hello"})
        self.assertEqual(turn["mode"], "start")
        self.assertIn("## Last checkpoint", turn["text"])

    def test_sessions_are_isolated_in_the_ledger(self):
        payload = {"cwd": str(self.repo)}
        a = build_packet(self.vault, mode="start", host="claude", payload={**payload, "session_id": "a"})
        b = build_packet(self.vault, mode="start", host="claude", payload={**payload, "session_id": "b"})
        self.assertEqual(sorted(a["memory_ids"]), sorted(b["memory_ids"]))

    def test_ledger_pruning(self):
        build_packet(self.vault, mode="start", host="claude", payload={"session_id": "old", "cwd": str(self.repo)})
        self.assertEqual(prune_ledgers(self.vault, max_age_days=0), 1)


class RenderShapeTests(PacketFixture):
    def _packet(self, host):
        return build_packet(self.vault, mode="start", host=host,
                            payload={"session_id": f"r-{host}", "cwd": str(self.repo)})

    def test_claude_codex_qwen_use_hook_specific_output(self):
        for host in ("claude", "codex", "qwen"):
            with self.subTest(host=host):
                out = json.loads(render(self._packet(host), host=host))
                self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
                self.assertIn("<ai-memory-context", out["hookSpecificOutput"]["additionalContext"])

    def test_gemini_is_pure_json_with_before_agent_on_turn(self):
        start = json.loads(render(self._packet("gemini"), host="gemini"))
        self.assertEqual(start["hookSpecificOutput"]["hookEventName"], "SessionStart")
        empty = render({"text": "", "mode": "turn"}, host="gemini")
        self.assertEqual(json.loads(empty), {})
        turn = render({"text": "x", "mode": "turn"}, host="gemini")
        self.assertEqual(json.loads(turn)["hookSpecificOutput"]["hookEventName"], "BeforeAgent")

    def test_kimi_is_plain_text(self):
        out = render(self._packet("kimi"), host="kimi")
        self.assertTrue(out.startswith("<ai-memory-context"))
        self.assertEqual(render({"text": ""}, host="kimi"), "")

    def test_hermes_is_context_object(self):
        out = json.loads(render(self._packet("hermes"), host="hermes"))
        self.assertIn("<ai-memory-context", out["context"])
        self.assertEqual(json.loads(render({"text": ""}, host="hermes")), {})

    def test_cli_auto_mode_and_never_fails_the_host(self):
        payload = {"session_id": "cli", "cwd": str(self.repo), "hook_event_name": "SessionStart",
                   "source": "startup"}
        result = subprocess.run(
            [sys.executable, "-m", "memory_hub.context_packet", "--vault", str(self.vault), "--host", "codex",
             "--no-catch-up"],
            input=json.dumps(payload), text=True, capture_output=True, check=True)
        out = json.loads(result.stdout)
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "SessionStart")
        # Missing vault -> stderr note, empty JSON on stdout, exit 0.
        result = subprocess.run(
            [sys.executable, "-m", "memory_hub.context_packet", "--vault", str(self.vault / "missing"),
             "--host", "gemini", "--no-catch-up"],
            input="not json", text=True, capture_output=True, env={"PATH": ""})
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout or "{}"), {})


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_kimi_toml_one_block_per_event_with_matcher_and_timeout(self):
        settings = self.root / "config.toml"
        settings.write_text('default_model = "k3"\n\n[[hooks]]\nevent = "Stop"\ncommand = "mine"\n',
                            encoding="utf-8")
        install_toml_hook(settings, event="PostToolUse", command="hook --client kimi")
        install_toml_hook(settings, event="SessionStart", command="ctx --host kimi", timeout=5)
        again = install_toml_hook(settings, event="SessionStart", command="ctx --host kimi", timeout=5)
        content = settings.read_text(encoding="utf-8")
        self.assertEqual(again["status"], "already_installed")
        self.assertEqual(content.count("# ai-memory-hub managed hook"), 2)
        self.assertIn('command = "mine"', content)  # user block untouched
        self.assertIn("timeout = 5", content)
        changed = install_toml_hook(settings, event="SessionStart", command="ctx --host kimi", timeout=9)
        self.assertEqual(changed["status"], "installed")
        self.assertEqual(settings.read_text(encoding="utf-8").count("# ai-memory-hub managed hook"), 2)
        removed = uninstall_toml_hook(settings, command="ctx --host kimi")
        self.assertEqual(removed["removed"], 1)
        self.assertIn("hook --client kimi", settings.read_text(encoding="utf-8"))
        self.assertEqual(uninstall_toml_hook(settings)["removed"], 1)
        self.assertIn('command = "mine"', settings.read_text(encoding="utf-8"))

    def test_hermes_yaml_install_preserves_siblings_and_uninstalls_cleanly(self):
        config = self.root / "config.yaml"
        original = ("model:\n  default: anthropic/claude\n\n"
                    "hooks:\n  post_tool_call:\n    - command: \"echo user-hook\"\n\n"
                    "plugins:\n  enabled: []\n")
        config.write_text(original, encoding="utf-8")
        first = install_hermes_hook(config, event="pre_llm_call", command="ctx --host hermes", timeout=10)
        install_hermes_hook(config, event="on_session_end", command="hook --client hermes")
        again = install_hermes_hook(config, event="pre_llm_call", command="ctx --host hermes", timeout=10)
        content = config.read_text(encoding="utf-8")
        self.assertEqual(first["status"], "installed")
        self.assertEqual(again["status"], "already_installed")
        self.assertIn('- command: "echo user-hook"', content)
        self.assertIn("  pre_llm_call:\n", content)
        self.assertIn("  on_session_end:\n", content)
        self.assertIn("plugins:\n  enabled: []", content)
        self.assertTrue(content.index("hooks:") < content.index("pre_llm_call") < content.index("plugins:"))
        try:
            import yaml  # type: ignore
            data = yaml.safe_load(content)
            self.assertEqual(data["hooks"]["pre_llm_call"][0]["command"], "ctx --host hermes")
            self.assertEqual(data["hooks"]["pre_llm_call"][0]["timeout"], 10)
            self.assertEqual(data["hooks"]["post_tool_call"][0]["command"], "echo user-hook")
        except ImportError:
            pass
        removed = uninstall_hermes_hook(config)
        self.assertEqual(removed["removed"], 2)
        after = config.read_text(encoding="utf-8")
        self.assertIn('- command: "echo user-hook"', after)
        self.assertNotIn("pre_llm_call", after)
        self.assertNotIn("on_session_end", after)
        self.assertIn("plugins:", after)

    def test_hermes_yaml_creates_hooks_map_when_absent(self):
        config = self.root / "config.yaml"
        config.write_text("model:\n  default: x\n", encoding="utf-8")
        install_hermes_hook(config, event="on_session_start", command="ctx --host hermes")
        content = config.read_text(encoding="utf-8")
        self.assertIn("\nhooks:\n  on_session_start:\n", content)
        self.assertEqual(uninstall_hermes_hook(config)["removed"], 1)
        self.assertNotIn("hooks:", config.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
