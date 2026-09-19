from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from memory_hub.capture import hook_main
from memory_hub.github_export import build_export_payloads
from memory_hub.manager import MemoryManager
from memory_hub.transcript import TranscriptStore, transcript_path_for
from memory_hub.worker import SessionWorker, WorkerConfig, read_health


class TranscriptStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = TranscriptStore(self.root / "transcripts.sqlite3", vault=self.root / "vault")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_exact_payloads_are_idempotent_and_ordered(self):
        first = self.store.append({
            "event_id": "user-1", "session_id": "host-1", "session_group_id": "group-1",
            "author": "user", "object_type": "user-message", "client": "codex",
            "generated_at": "2026-09-09T10:00:00+05:30", "payload": "keep *this* verbatim\n```x```",
        })
        structured = {"tool": "Read", "arguments": {"path": "src/a.py", "line": 4}}
        second = self.store.append({
            "event_id": "tool-1", "session_id": "host-1", "session_group_id": "group-1",
            "author": "tool", "object_type": "tool-call", "generated_at": "2026-09-09T10:00:01+05:30",
            "payload": structured,
        })
        duplicate = self.store.append({
            "event_id": "user-1", "session_id": "host-1", "session_group_id": "group-1",
            "author": "user", "object_type": "user-message", "payload": "changed retry",
        })
        rows = self.store.events("group-1")
        assert not first["duplicate"]
        assert not second["duplicate"]
        assert duplicate["duplicate"]
        assert [row["sequence"] for row in rows] == [1, 2]
        assert rows[0]["payload"] == "keep *this* verbatim\n```x```"
        assert rows[1]["payload"] == structured
        assert rows[0]["generated_at"] == "2026-09-09T10:00:00+05:30"

    def test_concurrent_connections_allocate_unique_monotonic_sequences(self):
        database = self.store.path

        def append(index):
            connection = TranscriptStore(database, vault=self.root / "vault")
            try:
                return connection.append({
                    "event_id": f"event-{index}", "session_id": "host-2",
                    "session_group_id": "group-2", "author": "agent",
                    "object_type": "agent-message", "payload": {"index": index},
                })
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(append, range(64)))
        rows = self.store.events("group-2")
        assert len(rows) == 64
        assert [row["sequence"] for row in rows] == list(range(1, 65))
        assert len({row["event_id"] for row in rows}) == 64

    def test_render_is_human_readable_and_uses_obsidian_metadata(self):
        self.store.append({
            "event_id": "render-1", "session_id": "host-3", "session_group_id": "group-3",
            "author": "user", "object_type": "user-message", "project": "demo-app",
            "topic": "transcript QA", "generated_at": "2026-09-09T10:00:00+00:00",
            "payload": "hello transcript",
        })
        self.store.append({
            "event_id": "render-2", "session_id": "host-3", "session_group_id": "group-3",
            "author": "agent", "object_type": "agent-message", "project": "demo-app",
            "generated_at": "2026-09-09T10:00:01+00:00", "payload": {"answer": "world"},
        })
        result = self.store.render(
            "group-3", self.root / "vault", project="demo-app",
            summary_links=["[[sessions/demo-app/codex.md#codex-summary]]"],
        )
        path = self.root / "vault" / result["path"].lstrip("/")
        content = path.read_text(encoding="utf-8")
        assert result["path"] == transcript_path_for("group-3", "demo-app")
        assert "type: transcript" in content
        assert "- user" in content
        assert "- agent" in content
        assert "- project/demo-app" in content
        assert "**Topic:** transcript QA" in content
        assert "[[sessions/demo-app/codex.md#codex-summary]]" in content
        assert '"answer": "world"' in content
        assert "hello transcript" in content

    def test_provider_native_tool_and_lifecycle_fields_normalize_without_summarying(self):
        tool = self.store.append({
            "event_id": "native-tool", "session_id": "host-native",
            "session_group_id": "native-group", "hook_event_name": "PostToolUse",
            "client": "claude", "tool_name": "Read",
            "tool_input": {"file_path": "src/a.py"},
            "tool_response": {"content": "exact result"},
        })
        start = self.store.append({
            "event_id": "native-start", "session_id": "host-native",
            "session_group_id": "native-group", "event": "SessionStart",
            "client": "codex", "payload": {"source": "startup"},
        })
        rows = self.store.events("native-group")
        assert tool["event_id"] == "native-tool"
        assert start["event_id"] == "native-start"
        assert rows[0]["author"] == "tool"
        assert rows[0]["object_type"] == "post-tool-use"
        assert rows[1]["author"] == "system"
        assert rows[1]["object_type"] == "session-start"
        assert "exact result" in rows[0]["payload_raw"]

    def test_generated_at_marks_substituted_timestamps_explicitly(self):
        """#77: a provider-omitted generated_at must be recorded and rendered as
        substituted, never presented identically to a real provider timestamp.
        """
        self.store.append({
            "event_id": "supplied", "session_id": "host-prov", "session_group_id": "prov-group",
            "author": "user", "object_type": "user-message",
            "generated_at": "2026-09-09T10:00:00+00:00", "payload": "has a timestamp",
        })
        self.store.append({
            "event_id": "omitted", "session_id": "host-prov", "session_group_id": "prov-group",
            "author": "agent", "object_type": "agent-message", "payload": "no timestamp given",
        })
        rows = self.store.events("prov-group")
        supplied = next(r for r in rows if r["event_id"] == "supplied")
        omitted = next(r for r in rows if r["event_id"] == "omitted")
        assert supplied["generated_at_source"] == "provider"
        assert omitted["generated_at_source"] == "capture"
        self.store.render("prov-group", self.root / "vault")
        content = (self.root / "vault" / "transcripts" / "prov-group.md").read_text(encoding="utf-8")
        assert "not supplied by provider" in content
        # The supplied event's block must not carry the substitution marker.
        supplied_block = content.split("### ")[1]
        assert "not supplied by provider" not in supplied_block

    def test_delete_group_removes_project_scoped_transcript_with_no_explicit_path(self):
        """#76: a caller that omits `path` must still reach a project-scoped file, or
        the SQLite rows are gone while the rendered Markdown stays on disk.
        """
        self.store.append({
            "event_id": "scoped-1", "session_id": "host-del", "session_group_id": "del-group",
            "project": "widget-app", "payload": "raw prompt",
        })
        self.store.render("del-group", self.root / "vault", project="widget-app")
        destination = self.root / "vault" / "transcripts" / "widget-app" / "del-group.md"
        assert destination.exists()
        removed = self.store.delete_group("del-group", vault=self.root / "vault")
        assert removed == 1
        assert not destination.exists()
        assert self.store.events("del-group") == []

    def test_prune_is_opt_in_and_deletes_only_old_events(self):
        self.store.append({
            "event_id": "old", "session_id": "host-4", "session_group_id": "group-4",
            "generated_at": "2020-01-01T00:00:00+00:00", "captured_at": "2020-01-01T00:00:00+00:00",
            "payload": "old",
        })
        self.store.render("group-4", self.root / "vault")
        with patch.dict("os.environ", {"MEMORY_TRANSCRIPT_RETENTION_DAYS": "30"}):
            assert self.store.prune(now=datetime(2026, 1, 1, tzinfo=timezone.utc)) == 1
        assert self.store.events("group-4") == []
        assert not (self.root / "vault" / "transcripts" / "group-4.md").exists()


class TranscriptIntegrationTests(unittest.TestCase):
    def test_hook_writes_raw_transcript_only_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            payload = {
                "event_id": "hook-transcript-1", "session_id": "hook-session",
                "session_group_id": "hook-group", "author": "user",
                "object_type": "user-message", "payload": "verbatim user text",
            }
            env = {
                "MEMORY_CAPTURE_DB": str(root / "capture.sqlite3"),
                "MEMORY_TRANSCRIPT_DB": str(root / "transcripts.sqlite3"),
                "MEMORY_TRANSCRIPT_ENABLED": "true",
            }
            from contextlib import redirect_stdout
            from io import StringIO
            with patch.dict("os.environ", env, clear=False), patch("sys.stdin", StringIO(json.dumps(payload))), redirect_stdout(StringIO()) as output:
                assert hook_main() == 0
            response = json.loads(output.getvalue())
            assert response["status"] == "accepted"
            assert response["observations"][0]["transcript"]["event_id"] == "hook-transcript-1"
            store = TranscriptStore(root / "transcripts.sqlite3")
            try:
                assert store.events("hook-group")[0]["payload"] == "verbatim user text"
            finally:
                store.close()

    def test_summary_links_to_transcript_and_forget_removes_companion(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            manager = MemoryManager(vault)
            manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")
            env = {
                "MEMORY_TRANSCRIPT_ENABLED": "true",
                "MEMORY_TRANSCRIPT_DB": str(root / "transcripts.sqlite3"),
            }
            try:
                with patch.dict("os.environ", env, clear=False):
                    store = TranscriptStore(vault=vault)
                    store.append({
                        "event_id": "summary-event", "session_id": "host-5",
                        "session_group_id": "group-5", "author": "user",
                        "object_type": "user-message", "project": "demo",
                        "payload": "raw prompt",
                    })
                    store.close()
                    result = manager.propose_session({
                        "model": "codex", "title": "Transcript summary", "date": "2026-09-09T10:00:00",
                        "project": "demo", "investigated": ["Reviewed the raw event"],
                        "learned": [], "completed": ["Linked the transcript"], "next_steps": [],
                        "session_group_id": "group-5", "checkpoint_id": "checkpoint-5",
                        "sequence": 1, "entry_type": "final",
                    })
                    assert result["status"] == "stored"
                    transcript = vault / "transcripts" / "demo" / "group-5.md"
                    content = transcript.read_text(encoding="utf-8")
                    manifest = json.loads(manager.read("/sessions/session-manifest.json"))
                    entry = manifest["groups"]["group-5"]["entries"][0]
                    assert entry["transcript_path"] == "/transcripts/demo/group-5.md"
                    assert entry["transcript_url"] == "[[transcripts/demo/group-5.md]]"
                    assert entry["transcript_event_count"] == 1
                    assert "**Transcript:** [[transcripts/demo/group-5.md]]" in manager.read(result["memory"]["path"])
                    assert "Summaries:" in content
                    assert "raw prompt" in content
                    exported = json.dumps(build_export_payloads(vault))
                    assert "raw prompt" not in exported
                    assert "transcripts/demo/group-5.md" not in exported
                    forgotten = manager.forget(result["memory"]["memory_id"])
                    assert forgotten["status"] == "forgotten"
                    assert not transcript.exists()
            finally:
                manager.close()

    def test_worker_renders_unattached_events_and_reports_transcript_health(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            database = root / "transcripts.sqlite3"
            env = {
                "MEMORY_TRANSCRIPT_ENABLED": "true",
                "MEMORY_TRANSCRIPT_DB": str(database),
                "MEMORY_WORKER_HEALTH": str(root / "worker-health.json"),
            }
            with patch.dict("os.environ", env, clear=False):
                store = TranscriptStore(database, vault=vault)
                store.append({
                    "event_id": "worker-event", "session_id": "host-6",
                    "session_group_id": "group-6", "author": "system",
                    "object_type": "session-start", "payload": {"ready": True},
                })
                store.close()
                config = WorkerConfig(vault=vault, buffer_path=root / "capture.sqlite3")
                # A group with no session_write yet has no manifest entry, so the real
                # MemoryManager.session_transcript_target would return None here too —
                # this stub models exactly that, not a manager capable of full session
                # writes (#68's resolver call needs a manager, unlike plain rendering).
                stub_manager = type("StubManager", (), {
                    "session_transcript_target": lambda self, group_id: None,
                })()
                worker = SessionWorker(config, manager=stub_manager)
                try:
                    result = worker.run_once()
                    health = read_health(vault)
                finally:
                    worker.close()
                assert result["status"] == "ok"
                assert result["transcript_rendered"] == 1
                assert health["config"]["transcript_enabled"]
                assert (vault / "transcripts" / "group-6.md").exists()

    def test_worker_reroll_preserves_summary_back_links_and_single_path(self):
        """#68: the worker's routine poll-driven re-render must not silently strip the
        summary back-link the authoritative writer just set, or land the group's file
        at a second, orphaned path.
        """
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            manager = MemoryManager(vault)
            manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")
            env = {
                "MEMORY_TRANSCRIPT_ENABLED": "true",
                "MEMORY_TRANSCRIPT_DB": str(root / "transcripts.sqlite3"),
                "MEMORY_WORKER_HEALTH": str(root / "worker-health.json"),
            }
            try:
                with patch.dict("os.environ", env, clear=False):
                    store = TranscriptStore(vault=vault)
                    store.append({
                        "event_id": "reroll-event", "session_id": "host-8",
                        "session_group_id": "group-8", "author": "user",
                        "object_type": "user-message", "project": "demo",
                        "payload": "raw prompt",
                    })
                    store.close()
                    result = manager.propose_session({
                        "model": "codex", "title": "Re-render regression", "date": "2026-09-09T10:00:00",
                        "project": "demo", "investigated": ["Reviewed the raw event"],
                        "learned": [], "completed": ["Linked the transcript"], "next_steps": [],
                        "session_group_id": "group-8", "checkpoint_id": "checkpoint-8",
                        "sequence": 1, "entry_type": "checkpoint",
                    })
                    assert result["status"] == "stored"
                    transcript = vault / "transcripts" / "demo" / "group-8.md"
                    before = transcript.read_text(encoding="utf-8")
                    assert "Summaries:" in before
                    config = WorkerConfig(vault=vault, buffer_path=root / "capture.sqlite3")
                    worker = SessionWorker(config, manager=manager)
                    try:
                        worker.run_once()
                        worker.run_once()
                    finally:
                        worker.close()
                    after = transcript.read_text(encoding="utf-8")
                    assert "Summaries:" in after
                    assert "sessions/demo/codex.md#codex-re-render-regression" in after
                    assert not (vault / "transcripts" / "group-8.md").exists()
            finally:
                manager.close()

    def test_crash_between_transcript_and_summary_is_retryable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            vault = root / "vault"
            manager = MemoryManager(vault)
            manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")
            env = {
                "MEMORY_TRANSCRIPT_ENABLED": "true",
                "MEMORY_TRANSCRIPT_DB": str(root / "transcripts.sqlite3"),
            }
            payload = {
                "model": "codex", "title": "Crash retry transcript", "date": "2026-09-09T10:00:00",
                "project": "demo", "investigated": ["Tested the write boundary"],
                "learned": [], "completed": [], "next_steps": [],
                "session_group_id": "group-7", "checkpoint_id": "checkpoint-7",
                "sequence": 1, "entry_type": "checkpoint",
            }
            try:
                with patch.dict("os.environ", env, clear=False):
                    store = TranscriptStore(vault=vault)
                    store.append({
                        "event_id": "crash-event", "session_id": "host-7",
                        "session_group_id": "group-7", "author": "agent",
                        "object_type": "agent-message", "payload": "exact event",
                    })
                    store.close()
                    original_append = manager.vault.append_session_block
                    with patch.object(manager.vault, "append_session_block", side_effect=RuntimeError("crash")):
                        with pytest.raises(RuntimeError):
                            manager.propose_session(payload)
                    # #249: transcript render now happens after append_session_block,
                    # so a crash before append means the transcript is not yet written.
                    # The retry writes it on the successful second attempt.
                    transcript = vault / "transcripts" / "demo" / "group-7.md"
                    assert not transcript.exists()
                    retry = manager.propose_session(payload)
                    assert retry["status"] == "stored"
                    assert transcript.exists()
                    assert transcript.read_text(encoding="utf-8").count("exact event") == 1
                    assert "Summaries:" in transcript.read_text(encoding="utf-8")
                    manager.vault.append_session_block = original_append
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
