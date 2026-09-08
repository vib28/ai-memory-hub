from __future__ import annotations

import io
import json
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from memory_hub.capture import ObservationBuffer, hook_main, normalize_event


class ObservationBufferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "capture.sqlite3"
        self.buffer = ObservationBuffer(self.db)

    def tearDown(self):
        self.buffer.close()
        self.tmp.cleanup()

    def test_append_is_idempotent_and_preserves_session_order(self):
        first = self.buffer.append({
            "observation_id": "one",
            "session_id": "s1",
            "tool": "Read",
            "files": ["src/a.py"],
            "output_summary": "opened file",
            "created_at": "2026-09-06T10:00:00Z",
        })
        duplicate = self.buffer.append({
            "observation_id": "one",
            "session_id": "s1",
            "tool": "Read",
            "output_summary": "different retry payload",
        })
        self.buffer.append({
            "observation_id": "two",
            "session_id": "s1",
            "tool": "Edit",
            "output_summary": "changed file",
            "created_at": "2026-09-06T10:01:00Z",
        })
        self.assertFalse(first["duplicate"])
        self.assertTrue(duplicate["duplicate"])
        rows = self.buffer.for_session("s1")
        self.assertEqual([row["observation_id"] for row in rows], ["one", "two"])
        self.assertEqual(rows[0]["output_summary"], "opened file")

    def test_text_and_file_limits_are_applied(self):
        row = self.buffer.append({
            "session_id": "s1",
            "input_summary": "x" * 10000,
            "files": [str(i) for i in range(200)],
        })
        self.assertEqual(len(row["input_summary"]), 4000)
        self.assertEqual(len(row["files"]), 100)

    def test_status_and_pending_session_tracking(self):
        self.buffer.append({"observation_id": "one", "session_id": "s1"})
        self.assertEqual(self.buffer.pending_sessions(), ["s1"])
        self.assertEqual(self.buffer.mark_status(["one"], "completed"), 1)
        self.assertEqual(self.buffer.pending_sessions(), [])

    def test_failed_rows_back_off_after_the_first_retry(self):
        self.buffer.append({"observation_id": "retry", "session_id": "s1"})
        self.assertEqual(self.buffer.mark_status(["retry"], "failed", "first"), 1)
        first = self.buffer.for_session("s1")[0]
        self.assertIsNotNone(first["next_attempt_at"])
        self.assertEqual(self.buffer.mark_status(["retry"], "failed", "second"), 1)
        second = self.buffer.for_session("s1")[0]
        self.assertGreater(second["next_attempt_at"], first["next_attempt_at"])
        self.assertEqual(self.buffer.claim_for_session("s1", owner="worker"), [])

    def test_event_names_are_normalized_and_old_payloads_stay_compatible(self):
        row = self.buffer.append({
            "observation_id": "event-one",
            "session_id": "s1",
            "event": "PostToolUse",
        })
        old_row = self.buffer.append({
            "observation_id": "old-one",
            "session_id": "s1",
        })
        self.assertEqual(row["event"], "post-tool-use")
        self.assertEqual(old_row["event"], "observation")

    def test_native_hook_payload_preserves_event_tool_file_and_host_id(self):
        row = self.buffer.append({
            "session_id": "s1", "event_id": "host-1", "hook_event_name": "PostToolUse",
            "tool_name": "Edit", "tool_input": {"file_path": "a.py"},
            "tool_response": {"success": True}, "client": "claude",
        })
        self.assertEqual(row["observation_id"], "host-1")
        self.assertEqual(row["event"], "post-tool-use")
        self.assertEqual(row["tool"], "Edit")
        self.assertEqual(row["files"], ["a.py"])
        self.assertEqual(row["source"], "claude")
        self.assertIn("success", row["output_summary"])

    def test_two_workers_cannot_claim_the_same_live_batch(self):
        for index in range(8):
            self.buffer.append({"observation_id": f"claim-{index}", "session_id": "shared"})
        database = self.db

        def claim(owner):
            worker = ObservationBuffer(database)
            try:
                return [row["observation_id"] for row in worker.claim_for_session(
                    "shared", owner=owner, limit=8
                )]
            finally:
                worker.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first, second = executor.map(claim, ("worker-a", "worker-b"))
        self.assertEqual(sorted(first + second), [f"claim-{index}" for index in range(8)])
        self.assertEqual(set(first).intersection(second), set())

    def test_live_lease_is_not_recovered_before_expiry(self):
        self.buffer.append({"observation_id": "leased", "session_id": "shared"})
        claimed = self.buffer.claim_for_session("shared", owner="worker-a", lease_seconds=300)
        self.assertEqual(len(claimed), 1)
        self.assertEqual(self.buffer.recover_processing("shared"), 0)
        self.assertEqual(self.buffer.for_session("shared")[0]["status"], "processing")

    def test_more_than_five_thousand_rows_drain_in_ordered_batches(self):
        for index in range(5001):
            self.buffer.append({
                "observation_id": f"large-{index:04}",
                "session_id": "large-session",
                "created_at": f"2026-01-01T00:00:{index:04}Z",
            })
        first = self.buffer.claim_for_session("large-session", owner="worker-a", limit=5000)
        self.assertEqual(len(first), 5000)
        self.assertEqual(self.buffer.batch_sequence(first, limit=5000), 1)
        self.assertEqual(self.buffer.mark_status(
            [row["observation_id"] for row in first], "completed", owner="worker-a"), 5000)
        second = self.buffer.claim_for_session("large-session", owner="worker-b", limit=5000)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0]["observation_id"], "large-5000")
        self.assertEqual(self.buffer.batch_sequence(second, limit=5000), 2)

    def test_existing_database_gets_event_column(self):
        legacy_db = Path(self.tmp.name) / "legacy.sqlite3"
        connection = sqlite3.connect(legacy_db)
        connection.execute(
            """CREATE TABLE observations (
                observation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL,
                project TEXT NOT NULL, cwd TEXT NOT NULL, tool TEXT NOT NULL,
                files_json TEXT NOT NULL, input_summary TEXT NOT NULL,
                output_summary TEXT NOT NULL, git_commit TEXT NOT NULL,
                created_at TEXT NOT NULL, source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT)"""
        )
        connection.commit()
        connection.close()
        legacy = ObservationBuffer(legacy_db)
        row = legacy.append({"observation_id": "migrated", "session_id": "s1", "event_name": "SessionStart"})
        legacy.close()
        self.assertEqual(row["event"], "session-start")


class HookMainTests(unittest.TestCase):
    def test_malformed_input_does_not_fail_the_host(self):
        with patch("sys.stdin", io.StringIO("not json")), redirect_stdout(io.StringIO()) as output:
            result = hook_main()
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "rejected")

    def test_batch_payload_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {"observations": [{"session_id": "s1"}, {"session_id": "s1", "tool": "Edit"}]}
            with patch.dict("os.environ", {"MEMORY_CAPTURE_DB": str(Path(temp) / "hook.sqlite3")}):
                with patch("sys.stdin", io.StringIO(json.dumps(payload))), redirect_stdout(io.StringIO()) as output:
                    result = hook_main()
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(output.getvalue())["count"], 2)

    def test_event_alias_is_stored(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {"session_id": "s1", "event_name": "post_tool_use_failure"}
            with patch.dict("os.environ", {"MEMORY_CAPTURE_DB": str(Path(temp) / "hook.sqlite3")}):
                with patch("sys.stdin", io.StringIO(json.dumps(payload))), redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(hook_main(), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result["observations"][0]["event"], "post-tool-use-failure")


class EventNormalizationTests(unittest.TestCase):
    def test_common_aliases(self):
        self.assertEqual(normalize_event("SessionStart"), "session-start")
        self.assertEqual(normalize_event("pre_tool_use"), "pre-tool-use")
        self.assertEqual(normalize_event("PostToolUseFailure"), "post-tool-use-failure")

    def test_unknown_events_are_stable_and_bounded(self):
        self.assertEqual(normalize_event("  My_Custom Event  "), "my-custom-event")
        self.assertEqual(len(normalize_event("x" * 200)), 80)


if __name__ == "__main__":
    unittest.main()
