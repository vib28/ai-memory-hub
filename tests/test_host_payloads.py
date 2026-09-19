"""#82: the receiver must keep the evidence each host actually delivers.

Fixtures are copied from the hosts' current hook documentation: Claude Code
2.1.276, Codex CLI 0.155.0, Gemini CLI 0.58.0, Qwen Code 0.22.0, Kimi Code 2.0.1
and Hermes Agent shell hooks.  Before #82 every one of these non-tool events was
stored as ``tool='unknown' input='' output=''``.
"""

from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from memory_hub.capture import ObservationBuffer, hook_main, normalize_client, normalize_event
from memory_hub.project_resolver import clear_cache


class HostPayloadFixtureTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.buffer = ObservationBuffer(Path(self.tmp.name) / "obs.sqlite3")
        self.repo = Path(self.tmp.name) / "widget-app"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "src").mkdir()
        clear_cache()

    def tearDown(self):
        self.buffer.close()
        self.tmp.cleanup()

    def test_claude_user_prompt_submit_keeps_the_prompt(self):
        row = self.buffer.append({
            "session_id": "abc123", "transcript_path": "/Users/x/.claude/projects/p/abc123.jsonl",
            "cwd": str(self.repo / "src"), "permission_mode": "default",
            "hook_event_name": "UserPromptSubmit",
            "prompt": "Write a function to calculate the factorial of a number",
        })
        assert row["event"] == "user-prompt-submit"
        assert row["tool"] == "prompt"
        assert "factorial" in row["input_summary"]
        assert row["project"] == "widget-app"
        assert row["worktree"] == str(self.repo)
        assert row["project_source"] == "git"
        assert row["host_meta"]["transcript_path"] == "/Users/x/.claude/projects/p/abc123.jsonl"
        assert row["host_meta"]["permission_mode"] == "default"

    def test_claude_stop_keeps_the_final_assistant_message(self):
        row = self.buffer.append({
            "session_id": "abc123", "cwd": str(self.repo), "hook_event_name": "Stop",
            "stop_hook_active": False,
            "last_assistant_message": "Analysis complete. Found 3 potential issues.",
            "background_tasks": [], "session_crons": [],
        })
        assert row["event"] == "stop"
        assert row["tool"] == "assistant"
        assert "Found 3 potential issues" in row["output_summary"]
        assert row["host_meta"]["stop_hook_active"] is False

    def test_claude_session_start_and_end_keep_source_and_reason(self):
        start = self.buffer.append({"session_id": "s", "cwd": str(self.repo),
                                    "hook_event_name": "SessionStart", "source": "resume",
                                    "model": "claude-sonnet-4-5"})
        end = self.buffer.append({"session_id": "s", "cwd": str(self.repo),
                                  "hook_event_name": "SessionEnd", "reason": "prompt_input_exit"})
        assert start["input_summary"] == "session-start: resume"
        assert start["host_meta"]["model"] == "claude-sonnet-4-5"
        assert end["input_summary"] == "session-end: prompt_input_exit"
        assert end["tool"] == "session"

    def test_claude_stop_failure_keeps_error_type(self):
        row = self.buffer.append({"session_id": "s", "cwd": str(self.repo),
                                  "hook_event_name": "StopFailure",
                                  "error_type": "rate_limit", "error_message": "Usage limit reached"})
        assert row["event"] == "stop-failure"
        assert row["input_summary"] == "stop-failure: rate_limit - Usage limit reached"

    def test_codex_payload_shape(self):
        row = self.buffer.append({
            "session_id": "thread-1", "transcript_path": None, "cwd": str(self.repo),
            "hook_event_name": "UserPromptSubmit", "model": "gpt-5-codex",
            "turn_id": "turn-9", "prompt": "please untrack the personal trade journal",
        })
        assert row["event"] == "user-prompt-submit"
        assert "trade journal" in row["input_summary"]
        assert row["host_meta"]["turn_id"] == "turn-9"
        assert "transcript_path" not in row["host_meta"]  # null is not a value

    def test_gemini_before_and_after_agent_map_onto_canonical_events(self):
        before = self.buffer.append({"session_id": "g", "cwd": str(self.repo),
                                     "timestamp": "2026-09-18T10:00:00Z",
                                     "hook_event_name": "BeforeAgent", "prompt": "add a date filter"})
        after = self.buffer.append({"session_id": "g", "cwd": str(self.repo),
                                    "hook_event_name": "AfterAgent", "prompt": "add a date filter",
                                    "prompt_response": "Added the filter and tests.",
                                    "stop_hook_active": False})
        tool = self.buffer.append({"session_id": "g", "cwd": str(self.repo), "hook_event_name": "AfterTool",
                                   "tool_name": "write_file", "tool_input": {"file_path": "a.py"},
                                   "tool_response": {"llmContent": "ok", "returnDisplay": "ok"}})
        compress = self.buffer.append({"session_id": "g", "cwd": str(self.repo),
                                       "hook_event_name": "PreCompress", "trigger": "auto"})
        assert before["event"] == "user-prompt-submit"
        assert before["input_summary"] == "add a date filter"
        assert after["event"] == "stop"
        assert after["output_summary"] == "Added the filter and tests."
        # AfterAgent also carries the prompt; the *assistant* text is what matters here.
        assert tool["event"] == "post-tool-use"
        assert tool["files"] == ["a.py"]
        assert compress["event"] == "pre-compact"
        assert compress["input_summary"] == "pre-compact: auto"

    def test_qwen_submitted_prompt_field(self):
        row = self.buffer.append({"session_id": "q", "cwd": str(self.repo),
                                  "hook_event_name": "UserPromptSubmit",
                                  "submitted_prompt": "never push directly to master"})
        assert row["input_summary"] == "never push directly to master"

    def test_kimi_client_type_identifies_the_writer(self):
        row = self.buffer.append({"hook_event_name": "PreToolUse", "session_id": "session_abc",
                                  "session_title": "Fix the login page", "client_type": "kimi_code_cli",
                                  "cwd": str(self.repo), "tool_name": "Shell",
                                  "tool_input": {"command": "pytest -q"}})
        assert row["source"] == "kimi"
        assert row["host_meta"]["session_title"] == "Fix the login page"
        assert row["tool"] == "Shell"

    def test_hermes_shell_hook_payload_with_extra(self):
        row = self.buffer.append({
            "hook_event_name": "pre_llm_call", "tool_name": None, "tool_input": None,
            "session_id": "sess_abc123", "cwd": str(self.repo), "profile": "aimemoryhub",
            "extra": {"user_message": "status of the trading agent?", "is_first_turn": True},
            "client": "hermes",
        })
        assert row["event"] == "user-prompt-submit"
        assert row["input_summary"] == "status of the trading agent?"
        assert row["source"] == "hermes"
        assert row["host_meta"]["profile"] == "aimemoryhub"

    def test_installer_client_flag_labels_rows_without_self_identification(self):
        payload = {"session_id": "s1", "cwd": str(self.repo), "hook_event_name": "PostToolUse",
                   "tool_name": "Bash", "tool_input": {"command": "git status"},
                   "tool_response": "clean"}
        with patch.dict("os.environ", {"MEMORY_CAPTURE_DB": str(Path(self.tmp.name) / "hook.sqlite3")}):
            with patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                    redirect_stdout(io.StringIO()) as output:
                assert hook_main(["--client", "Claude Code"]) == 0
        row = json.loads(output.getvalue())["observations"][0]
        assert row["source"] == "claude"
        assert row["project"] == "widget-app"

    def test_unknown_argv_never_breaks_the_host(self):
        payload = {"session_id": "s1", "cwd": str(self.repo), "hook_event_name": "Stop"}
        with patch.dict("os.environ", {"MEMORY_CAPTURE_DB": str(Path(self.tmp.name) / "hook.sqlite3")}):
            with patch("sys.stdin", io.StringIO(json.dumps(payload))), \
                    redirect_stdout(io.StringIO()) as output:
                assert hook_main(["--bogus", "--client=codex"]) == 0
        assert json.loads(output.getvalue())["status"] == "accepted"

    def test_prompt_text_is_still_secret_filtered(self):
        row = self.buffer.append({"session_id": "s", "cwd": str(self.repo),
                                  "hook_event_name": "UserPromptSubmit",
                                  "prompt": "use api_key = sk-abcdefghijklmnopqrstuvwxyz1234 for it"})
        assert "sk-abcdefghijklmnopqrstuvwxyz1234" not in row["input_summary"]

    def test_home_directory_session_is_unscoped_not_a_project(self):
        row = self.buffer.append({"session_id": "s", "cwd": str(Path.home()),
                                  "hook_event_name": "UserPromptSubmit", "prompt": "hi"})
        assert row["project"] == ""
        assert row["project_source"] == "unscoped"

    def test_explicit_project_from_payload_wins_over_cwd(self):
        row = self.buffer.append({"session_id": "s", "cwd": str(self.repo), "project": "Trading Agent",
                                  "hook_event_name": "PostToolUse", "tool_name": "Bash"})
        assert row["project"] == "trading-agent"
        assert row["project_source"] == "explicit"

    def test_old_database_gains_new_columns_and_old_rows_read_back(self):
        path = Path(self.tmp.name) / "legacy.sqlite3"
        conn = sqlite3.connect(path)
        conn.executescript(
            "CREATE TABLE observations ("
            " observation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, project TEXT NOT NULL,"
            " cwd TEXT NOT NULL, tool TEXT NOT NULL, files_json TEXT NOT NULL,"
            " input_summary TEXT NOT NULL, output_summary TEXT NOT NULL, git_commit TEXT NOT NULL,"
            " created_at TEXT NOT NULL, source TEXT NOT NULL,"
            " event TEXT NOT NULL DEFAULT 'observation', status TEXT NOT NULL DEFAULT 'pending',"
            " attempts INTEGER NOT NULL DEFAULT 0, last_error TEXT, claim_token TEXT,"
            " lease_expires_at TEXT, next_attempt_at TEXT);"
            "INSERT INTO observations (observation_id, session_id, project, cwd, tool, files_json,"
            " input_summary, output_summary, git_commit, created_at, source)"
            " VALUES ('old', 's', '', 'C:/x', 'Bash', '[]', 'ls', 'ok', '',"
            " '2026-01-01T00:00:00+00:00', 'generic-hook');"
        )
        conn.commit()
        conn.close()
        buffer = ObservationBuffer(path)
        try:
            rows = buffer.for_session("s")
            assert rows[0]["host_meta"] == {}
            assert rows[0]["worktree"] == ""
            assert buffer.sessions_for_project("") == ["s"]
        finally:
            buffer.close()


class ClientAndEventAliasTests(unittest.TestCase):
    def test_client_aliases(self):
        for raw, expected in [("Claude Code", "claude"), ("kimi_code_cli", "kimi"), ("codex-cli", "codex"),
                              ("Gemini CLI", "gemini"), ("qwen-code", "qwen"), ("hermes-agent", "hermes"),
                              ("", ""), (None, ""), ("something-else", "something-else")]:
            with self.subTest(raw=raw):
                assert normalize_client(raw) == expected

    def test_host_event_aliases(self):
        for raw, expected in [("BeforeAgent", "user-prompt-submit"), ("AfterAgent", "stop"),
                              ("BeforeTool", "pre-tool-use"), ("AfterTool", "post-tool-use"),
                              ("PreCompress", "pre-compact"), ("PostCompact", "post-compaction"),
                              ("StopFailure", "stop-failure"), ("Interrupt", "interrupt"),
                              ("SessionHeartbeat", "session-heartbeat"), ("pre_llm_call", "user-prompt-submit"),
                              ("post_tool_call", "post-tool-use"), ("on_session_end", "session-end")]:
            with self.subTest(raw=raw):
                assert normalize_event(raw) == expected


if __name__ == "__main__":
    unittest.main()
