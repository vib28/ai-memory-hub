from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from memory_hub.capture import ObservationBuffer
from memory_hub.session_capture import consolidate_buffered_session


class FakeManager:
    def __init__(self, status="queued"):
        self.status = status
        self.calls = []

    def propose_session(self, payload, *, write_mode):
        self.calls.append((payload, write_mode))
        return {"status": self.status}


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


if __name__ == "__main__":
    unittest.main()
