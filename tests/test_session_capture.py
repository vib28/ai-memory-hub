from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory_hub.capture import ObservationBuffer
from memory_hub.session_capture import consolidate_buffered_session


class FakeManager:
    def __init__(self, status="queued"):
        self.statuses = list(status) if isinstance(status, (list, tuple)) else [status]
        self.calls = []

    def propose_session(self, payload, *, write_mode):
        self.calls.append((payload, write_mode))
        return {"status": self.statuses.pop(0) if self.statuses else "stored"}


class SessionCaptureTests(unittest.TestCase):
    def test_consolidation_uses_existing_write_policy_and_marks_rows_done(self):
        with tempfile.TemporaryDirectory() as temp:
            buffer = ObservationBuffer(Path(temp) / "capture.sqlite3")
            try:
                buffer.append({"observation_id": "one", "session_id": "s1", "project": "demo",
                               "tool": "Edit", "files": ["a.py"], "output_summary": "changed a.py"})
                manager = FakeManager()
                result = consolidate_buffered_session(buffer, manager, "s1", writer="codex", write_mode="review")
                self.assertEqual(result["status"], "queued")
                self.assertEqual(manager.calls[0][1], "review")
                self.assertEqual(buffer.for_session("s1")[0]["status"], "completed")
            finally:
                buffer.close()

    def test_duplicate_write_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            buffer = ObservationBuffer(Path(temp) / "capture.sqlite3")
            try:
                buffer.append({"observation_id": "one", "session_id": "s1", "output_summary": "work"})
                manager = FakeManager("duplicate")
                result = consolidate_buffered_session(buffer, manager, "s1", writer="codex", write_mode="auto")
                self.assertEqual(result["status"], "duplicate")
                self.assertEqual(buffer.pending_sessions(), [])
            finally:
                buffer.close()

    def test_crash_after_write_before_ack_reuses_the_same_batch_id(self):
        with tempfile.TemporaryDirectory() as temp:
            buffer = ObservationBuffer(Path(temp) / "capture.sqlite3")
            try:
                buffer.append({"observation_id": "one", "session_id": "s1", "output_summary": "work"})
                manager = FakeManager(["stored", "duplicate"])
                original_mark_status = buffer.mark_status
                calls = {"count": 0}

                def fail_ack(*args, **kwargs):
                    if calls["count"] == 0:
                        calls["count"] += 1
                        raise RuntimeError("simulated acknowledgement crash")
                    return original_mark_status(*args, **kwargs)

                buffer.mark_status = fail_ack
                with self.assertRaises(RuntimeError):
                    consolidate_buffered_session(buffer, manager, "s1", writer="codex", write_mode="auto")
                buffer.mark_status = original_mark_status
                buffer.conn.execute(
                    "UPDATE observations SET lease_expires_at='2000-01-01T00:00:00+00:00' "
                    "WHERE observation_id='one'"
                )
                buffer.conn.commit()
                result = consolidate_buffered_session(
                    buffer, manager, "s1", writer="codex", write_mode="auto"
                )
                self.assertEqual(result["status"], "duplicate")
                self.assertEqual(manager.calls[0][0]["checkpoint_id"], manager.calls[1][0]["checkpoint_id"])
                self.assertEqual(result["batch_id"], manager.calls[0][0]["checkpoint_id"])
                self.assertEqual(buffer.pending_sessions(), [])
            finally:
                buffer.close()

    def test_interrupted_processing_is_recovered_and_retried(self):
        with tempfile.TemporaryDirectory() as temp:
            buffer = ObservationBuffer(Path(temp) / "capture.sqlite3")
            try:
                buffer.append({"observation_id": "one", "session_id": "s1", "output_summary": "work"})
                buffer.mark_status(["one"], "processing")
                manager = FakeManager("stored")
                result = consolidate_buffered_session(
                    buffer, manager, "s1", writer="codex", write_mode="auto"
                )
                self.assertEqual(result["status"], "stored")
                self.assertEqual(result["recovered"], 1)
                self.assertEqual(buffer.for_session("s1")[0]["status"], "completed")
                self.assertGreaterEqual(buffer.for_session("s1")[0]["attempts"], 4)
            finally:
                buffer.close()

    def test_pending_rows_after_first_page_are_consolidated(self):
        with tempfile.TemporaryDirectory() as temp:
            buffer = ObservationBuffer(Path(temp) / "capture.sqlite3")
            try:
                for index in range(501):
                    buffer.append({"observation_id": f"row-{index:03}", "session_id": "s1",
                                   "created_at": f"2026-01-01T00:00:{index:02}Z"})
                first_page = [row["observation_id"] for row in buffer.for_session("s1", limit=500)]
                buffer.mark_status(first_page, "completed")
                result = consolidate_buffered_session(buffer, FakeManager("stored"), "s1",
                                                       writer="codex", write_mode="auto")
                self.assertEqual(result["observations"], 1)
                self.assertEqual(buffer.pending_sessions(), [])
            finally:
                buffer.close()


if __name__ == "__main__":
    unittest.main()
