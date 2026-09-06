from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from memory_hub.capture import ObservationBuffer, hook_main


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


if __name__ == "__main__":
    unittest.main()
