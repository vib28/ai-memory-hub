from __future__ import annotations

import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

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
        self.assertFalse(first["duplicate"])
        self.assertFalse(second["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual([row["sequence"] for row in rows], [1, 2])
        self.assertEqual(rows[0]["payload"], "keep *this* verbatim\n```x```")
        self.assertEqual(rows[1]["payload"], structured)
        self.assertEqual(rows[0]["generated_at"], "2026-09-09T10:00:00+05:30")

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
        self.assertEqual(len(rows), 64)
        self.assertEqual([row["sequence"] for row in rows], list(range(1, 65)))
        self.assertEqual(len({row["event_id"] for row in rows}), 64)

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
        self.assertEqual(result["path"], transcript_path_for("group-3", "demo-app"))
        self.assertIn("type: transcript", content)
        self.assertIn("- user", content)
        self.assertIn("- agent", content)
        self.assertIn("- project/demo-app", content)
        self.assertIn("**Topic:** transcript QA", content)
        self.assertIn("[[sessions/demo-app/codex.md#codex-summary]]", content)
        self.assertIn('"answer": "world"', content)
        self.assertIn("hello transcript", content)

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
        self.assertEqual(tool["event_id"], "native-tool")
        self.assertEqual(start["event_id"], "native-start")
        self.assertEqual(rows[0]["author"], "tool")
        self.assertEqual(rows[0]["object_type"], "post-tool-use")
        self.assertEqual(rows[1]["author"], "system")
        self.assertEqual(rows[1]["object_type"], "session-start")
        self.assertIn("exact result", rows[0]["payload_raw"])

    def test_prune_is_opt_in_and_deletes_only_old_events(self):
        self.store.append({
            "event_id": "old", "session_id": "host-4", "session_group_id": "group-4",
            "generated_at": "2020-01-01T00:00:00+00:00", "captured_at": "2020-01-01T00:00:00+00:00",
            "payload": "old",
        })
        self.store.render("group-4", self.root / "vault")
        with patch.dict("os.environ", {"MEMORY_TRANSCRIPT_RETENTION_DAYS": "30"}):
            self.assertEqual(self.store.prune(now=datetime(2026, 1, 1, tzinfo=timezone.utc)), 1)
        self.assertEqual(self.store.events("group-4"), [])
        self.assertFalse((self.root / "vault" / "transcripts" / "group-4.md").exists())


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
            from io import StringIO
            from contextlib import redirect_stdout
            with patch.dict("os.environ", env, clear=False), patch("sys.stdin", StringIO(json.dumps(payload))), redirect_stdout(StringIO()) as output:
                self.assertEqual(hook_main(), 0)
            response = json.loads(output.getvalue())
            self.assertEqual(response["status"], "accepted")
            self.assertEqual(response["observations"][0]["transcript"]["event_id"], "hook-transcript-1")
            store = TranscriptStore(root / "transcripts.sqlite3")
            try:
                self.assertEqual(store.events("hook-group")[0]["payload"], "verbatim user text")
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
                    self.assertEqual(result["status"], "stored")
                    transcript = vault / "transcripts" / "demo" / "group-5.md"
                    content = transcript.read_text(encoding="utf-8")
                    manifest = json.loads(manager.read("/sessions/session-manifest.json"))
                    entry = manifest["groups"]["group-5"]["entries"][0]
                    self.assertEqual(entry["transcript_path"], "/transcripts/demo/group-5.md")
                    self.assertEqual(entry["transcript_url"], "[[transcripts/demo/group-5.md]]")
                    self.assertEqual(entry["transcript_event_count"], 1)
                    self.assertIn("**Transcript:** [[transcripts/demo/group-5.md]]", manager.read(result["memory"]["path"]))
                    self.assertIn("Summaries:", content)
                    self.assertIn("raw prompt", content)
                    exported = json.dumps(build_export_payloads(vault))
                    self.assertNotIn("raw prompt", exported)
                    self.assertNotIn("transcripts/demo/group-5.md", exported)
                    forgotten = manager.forget(result["memory"]["memory_id"])
                    self.assertEqual(forgotten["status"], "forgotten")
                    self.assertFalse(transcript.exists())
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
                worker = SessionWorker(config, manager=object())
                try:
                    result = worker.run_once()
                    health = read_health(vault)
                finally:
                    worker.close()
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["transcript_rendered"], 1)
                self.assertTrue(health["config"]["transcript_enabled"])
                self.assertTrue((vault / "transcripts" / "group-6.md").exists())

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
                        with self.assertRaises(RuntimeError):
                            manager.propose_session(payload)
                    transcript = vault / "transcripts" / "demo" / "group-7.md"
                    self.assertTrue(transcript.exists())
                    retry = manager.propose_session(payload)
                    self.assertEqual(retry["status"], "stored")
                    self.assertEqual(transcript.read_text(encoding="utf-8").count("exact event"), 1)
                    self.assertIn("Summaries:", transcript.read_text(encoding="utf-8"))
                    manager.vault.append_session_block = original_append
            finally:
                manager.close()


if __name__ == "__main__":
    unittest.main()
