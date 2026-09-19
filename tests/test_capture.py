from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
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
        assert not first["duplicate"]
        assert duplicate["duplicate"]
        rows = self.buffer.for_session("s1")
        assert [row["observation_id"] for row in rows] == ["one", "two"]
        assert rows[0]["output_summary"] == "opened file"

    def test_text_and_file_limits_are_applied(self):
        row = self.buffer.append({
            "session_id": "s1",
            "input_summary": "x" * 10000,
            "files": [str(i) for i in range(200)],
        })
        assert len(row["input_summary"]) == 4000
        assert len(row["files"]) == 100

    def test_sensitive_capture_evidence_is_redacted_and_paths_excluded(self):
        row = self.buffer.append({
            "observation_id": "private",
            "session_id": "s1",
            "files": [".env", "src/a.py"],
            "input_summary": "password=super-secret-value",
            "output_summary": "Read .env and password=super-secret-value",
        })
        assert row["files"] == ["src/a.py"]
        assert "super-secret-value" not in row["input_summary"]
        assert "super-secret-value" not in row["output_summary"]
        assert "redacted" in row["output_summary"]

    def test_retention_prunes_terminal_rows_but_keeps_unsummarized_rows(self):
        self.buffer.append({"observation_id": "old-done", "session_id": "done",
                            "created_at": "2020-01-01T00:00:00Z"})
        self.buffer.mark_status(["old-done"], "completed")
        self.buffer.append({"observation_id": "old-pending", "session_id": "pending",
                            "created_at": "2020-01-01T00:00:00Z"})
        deleted = self.buffer.prune_expired(now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        assert deleted == 1
        assert self.buffer.for_session("done") == []
        assert self.buffer.for_session("pending")[0]["status"] == "pending"

    def test_status_and_pending_session_tracking(self):
        self.buffer.append({"observation_id": "one", "session_id": "s1"})
        assert self.buffer.pending_sessions() == ["s1"]
        assert self.buffer.mark_status(["one"], "completed") == 1
        assert self.buffer.pending_sessions() == []

    def test_failed_rows_back_off_after_the_first_retry(self):
        self.buffer.append({"observation_id": "retry", "session_id": "s1"})
        assert self.buffer.mark_status(["retry"], "failed", "first") == 1
        first = self.buffer.for_session("s1")[0]
        assert first["next_attempt_at"] is not None
        assert self.buffer.mark_status(["retry"], "failed", "second") == 1
        second = self.buffer.for_session("s1")[0]
        assert second["next_attempt_at"] > first["next_attempt_at"]
        assert self.buffer.pending_sessions() == ["s1"]
        assert self.buffer.claim_for_session("s1", owner="worker") == []

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
        assert row["event"] == "post-tool-use"
        assert old_row["event"] == "observation"

    def test_native_hook_payload_preserves_event_tool_file_and_host_id(self):
        row = self.buffer.append({
            "session_id": "s1", "event_id": "host-1", "hook_event_name": "PostToolUse",
            "tool_name": "Edit", "tool_input": {"file_path": "a.py"},
            "tool_response": {"success": True}, "client": "claude",
        })
        assert row["observation_id"] == "host-1"
        assert row["event"] == "post-tool-use"
        assert row["tool"] == "Edit"
        assert row["files"] == ["a.py"]
        assert row["source"] == "claude"
        assert "success" in row["output_summary"]

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
        assert sorted(first + second) == [f"claim-{index}" for index in range(8)]
        assert set(first).intersection(second) == set()

    def test_eight_real_connections_drain_repeated_batches_without_overlap(self):
        total = 512
        for index in range(total):
            self.buffer.append({
                "observation_id": f"stress-{index:04}",
                "session_id": "stress-session",
                "created_at": f"2026-01-01T00:00:{index:04}Z",
            })
        database = self.db
        barrier = Barrier(8)

        def drain(owner):
            worker = ObservationBuffer(database)
            claimed = []
            try:
                barrier.wait()
                while True:
                    rows = worker.claim_for_session("stress-session", owner=owner, limit=7)
                    if not rows:
                        break
                    ids = [row["observation_id"] for row in rows]
                    claimed.extend(ids)
                    assert worker.mark_status(ids, "completed", owner=owner) == len(ids)
                return claimed
            finally:
                worker.close()

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(drain, [f"stress-worker-{i}" for i in range(8)]))
        flattened = [item for result in results for item in result]
        assert len(flattened) == total
        assert len(set(flattened)) == total
        assert self.buffer.pending_sessions() == []

    def test_live_lease_is_not_recovered_before_expiry(self):
        self.buffer.append({"observation_id": "leased", "session_id": "shared"})
        claimed = self.buffer.claim_for_session("shared", owner="worker-a", lease_seconds=300)
        assert len(claimed) == 1
        assert self.buffer.recover_processing("shared") == 0
        assert self.buffer.for_session("shared")[0]["status"] == "processing"

    def test_more_than_five_thousand_rows_drain_in_ordered_batches(self):
        for index in range(5001):
            self.buffer.append({
                "observation_id": f"large-{index:04}",
                "session_id": "large-session",
                "created_at": f"2026-01-01T00:00:{index:04}Z",
            })
        first = self.buffer.claim_for_session("large-session", owner="worker-a", limit=5000)
        assert len(first) == 5000
        assert self.buffer.batch_sequence(first, limit=5000) == 1
        assert self.buffer.mark_status([row["observation_id"] for row in first], "completed", owner="worker-a") == 5000
        second = self.buffer.claim_for_session("large-session", owner="worker-b", limit=5000)
        assert len(second) == 1
        assert second[0]["observation_id"] == "large-5000"
        assert self.buffer.batch_sequence(second, limit=5000) == 2

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
        assert row["event"] == "session-start"


class HookMainTests(unittest.TestCase):
    def test_malformed_input_does_not_fail_the_host(self):
        with patch("sys.stdin", io.StringIO("not json")), redirect_stdout(io.StringIO()) as output:
            result = hook_main()
        assert result == 0
        assert json.loads(output.getvalue())["status"] == "rejected"

    def test_batch_payload_is_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {"observations": [{"session_id": "s1"}, {"session_id": "s1", "tool": "Edit"}]}
            with patch.dict("os.environ", {"MEMORY_CAPTURE_DB": str(Path(temp) / "hook.sqlite3")}):
                with patch("sys.stdin", io.StringIO(json.dumps(payload))), redirect_stdout(io.StringIO()) as output:
                    result = hook_main()
            assert result == 0
            assert json.loads(output.getvalue())["count"] == 2

    def test_event_alias_is_stored(self):
        with tempfile.TemporaryDirectory() as temp:
            payload = {"session_id": "s1", "event_name": "post_tool_use_failure"}
            with patch.dict("os.environ", {"MEMORY_CAPTURE_DB": str(Path(temp) / "hook.sqlite3")}):
                with patch("sys.stdin", io.StringIO(json.dumps(payload))), redirect_stdout(io.StringIO()) as output:
                    assert hook_main() == 0
            result = json.loads(output.getvalue())
            assert result["observations"][0]["event"] == "post-tool-use-failure"

    def test_secret_is_redacted_before_persisting_to_buffer_db(self):
        """#94: secrets must be redacted before append() writes to SQLite."""
        import tempfile as _tf
        tmp = _tf.mkdtemp()
        try:
            db_path = Path(tmp) / "capture.sqlite3"
            buffer = ObservationBuffer(db_path)
            try:
                row = buffer.append({
                    "observation_id": "secret-test",
                    "session_id": "s1",
                    "tool": "Read",
                    "files": [".env", "src/a.py"],
                    "input_summary": "api_key: sk-1234567890abcdef1234567890abcdef12345678",
                    "output_summary": "Read .env and found api_key: sk-1234567890abcdef1234567890abcdef12345678",
                })
                # The stored row must not contain the raw secret
                assert "sk-1234567890abcdef1234567890abcdef12345678" not in row["input_summary"]
                assert "sk-1234567890abcdef1234567890abcdef12345678" not in row["output_summary"]
                assert "redacted" in row["input_summary"]
                assert "redacted" in row["output_summary"]
            finally:
                buffer.close()
            # Verify the DB itself doesn't contain the raw secret
            with sqlite3.connect(str(db_path)) as conn:
                row_in_db = conn.execute(
                    "SELECT input_summary, output_summary FROM observations WHERE observation_id=?",
                    ("secret-test",),
                ).fetchone()
                assert row_in_db is not None
                assert "sk-1234567890abcdef1234567890abcdef12345678" not in row_in_db[0]
                assert "sk-1234567890abcdef1234567890abcdef12345678" not in row_in_db[1]
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)

    def test_hook_main_sanitizes_before_buffer_and_transcript(self):
        """#94: hook_main must sanitize payloads before any persistence."""
        import tempfile as _tf
        tmp = _tf.mkdtemp()
        try:
            payload = {
                "session_id": "s1",
                "tool": "Read",
                "prompt": "api_key: sk-1234567890abcdef1234567890abcdef12345678",
                "output_summary": "Read .env and found api_key: sk-1234567890abcdef1234567890abcdef12345678",
            }
            env = {
                "MEMORY_CAPTURE_DB": str(Path(tmp) / "hook.sqlite3"),
                "MEMORY_TRANSCRIPT_ENABLED": "1",
            }
            with patch.dict("os.environ", env, clear=False):
                with patch("sys.stdin", io.StringIO(json.dumps(payload))), redirect_stdout(io.StringIO()):
                    assert hook_main() == 0
            # Check buffer DB
            buffer_db = Path(tmp) / "hook.sqlite3"
            with sqlite3.connect(str(buffer_db)) as conn:
                row = conn.execute(
                    "SELECT input_summary, output_summary FROM observations",
                ).fetchone()
                assert row is not None
                assert "sk-1234567890abcdef1234567890abcdef12345678" not in row[0]
                assert "sk-1234567890abcdef1234567890abcdef12345678" not in row[1]
                assert "redacted" in row[0]
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class EventNormalizationTests(unittest.TestCase):
    def test_common_aliases(self):
        assert normalize_event("SessionStart") == "session-start"
        assert normalize_event("pre_tool_use") == "pre-tool-use"
        assert normalize_event("PostToolUseFailure") == "post-tool-use-failure"

    def test_unknown_events_are_stable_and_bounded(self):
        assert normalize_event("  My_Custom Event  ") == "my-custom-event"
        assert len(normalize_event("x" * 200)) == 80


if __name__ == "__main__":
    unittest.main()
