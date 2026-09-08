from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from memory_hub.capture import ObservationBuffer
from memory_hub.worker import SessionWorker, WorkerConfig, read_health


class FakeManager:
    def __init__(self, result=None, error=None):
        self.result = result or {"status": "stored"}
        self.error = error
        self.calls = []

    def propose_session(self, payload, *, write_mode):
        if self.error:
            raise self.error
        self.calls.append((payload, write_mode))
        return dict(self.result)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.buffer = ObservationBuffer(root / "capture.sqlite3")
        self.health = root / "worker-health.json"
        self.config = WorkerConfig(
            vault=root / "vault", buffer_path=root / "capture.sqlite3", writer="codex",
            write_mode="auto", token_budget=20, flush_seconds=60, idle_seconds=300,
            interval_seconds=1, batch_limit=20,
        )

    def tearDown(self):
        self.buffer.close()
        self.tmp.cleanup()

    def worker(self, manager):
        return SessionWorker(self.config, manager=manager, buffer=self.buffer)

    def append(self, event="observation", output="x" * 80, created_at="2026-09-09T12:00:00+00:00"):
        return self.buffer.append({
            "observation_id": f"observation-{self.buffer.conn.total_changes}",
            "session_id": "session-1", "project": "demo", "tool": "Edit",
            "files": ["src/a.py"], "output_summary": output,
            "created_at": created_at, "event": event,
        })

    def test_token_budget_flushes_and_preserves_auto_policy(self):
        self.append()
        manager = FakeManager()
        worker = self.worker(manager)
        try:
            result = worker.run_once(now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc))
        finally:
            worker.close()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["processed"][0]["trigger"], "token-budget")
        self.assertEqual(manager.calls[0][1], "auto")
        self.assertEqual(manager.calls[0][0]["entry_type"], "checkpoint")
        self.assertEqual(self.buffer.pending_sessions(), [])

    def test_stop_flush_is_provisional_and_not_final(self):
        self.config = WorkerConfig(**{**self.config.__dict__, "token_budget": 10000})
        self.append(event="stop", output="turn ended but session may continue")
        manager = FakeManager()
        worker = self.worker(manager)
        try:
            worker.run_once()
        finally:
            worker.close()
        payload = manager.calls[0][0]
        self.assertEqual(payload["state"], "provisional")
        self.assertEqual(payload["entry_type"], "checkpoint")
        self.assertFalse(payload["host_session_finalized"])

    def test_session_end_flush_is_final_and_marks_host_end(self):
        self.config = WorkerConfig(**{**self.config.__dict__, "token_budget": 10000})
        self.append(event="session-end", output="explicit host session end")
        manager = FakeManager()
        worker = self.worker(manager)
        try:
            worker.run_once()
        finally:
            worker.close()
        payload = manager.calls[0][0]
        self.assertEqual(payload["entry_type"], "final")
        self.assertEqual(payload["state"], "accepted")
        self.assertTrue(payload["host_session_finalized"])

    def test_time_trigger_flushes_older_evidence(self):
        self.config = WorkerConfig(**{**self.config.__dict__, "token_budget": 10000})
        self.append(created_at="2026-09-09T11:00:00+00:00")
        manager = FakeManager()
        worker = self.worker(manager)
        try:
            result = worker.run_once(now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc))
        finally:
            worker.close()
        self.assertEqual(result["processed"][0]["trigger"], "time")

    def test_idle_closure_is_provisional_and_new_evidence_reopens_session(self):
        self.config = WorkerConfig(**{
            **self.config.__dict__, "token_budget": 10000, "flush_seconds": 10000,
            "idle_seconds": 60,
        })
        self.append(created_at="2026-09-09T11:00:00+00:00")
        manager = FakeManager()
        worker = self.worker(manager)
        try:
            first = worker.run_once(now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc))
            self.append(event="stop", output="new work after provisional closure",
                        created_at="2026-09-09T12:02:00+00:00")
            second = worker.run_once(now=datetime(2026, 9, 9, 12, 3, tzinfo=timezone.utc))
        finally:
            worker.close()
        self.assertEqual(first["processed"][0]["trigger"], "idle")
        self.assertEqual(manager.calls[0][0]["state"], "provisional")
        self.assertEqual(second["processed"][0]["trigger"], "turn")
        self.assertNotEqual(manager.calls[0][0]["checkpoint_id"], manager.calls[1][0]["checkpoint_id"])

    def test_model_failure_is_visible_and_rows_remain_retryable(self):
        self.append()
        with patch.dict("os.environ", {"MEMORY_WORKER_HEALTH": str(self.health)}):
            worker = self.worker(FakeManager(error=RuntimeError("local model unavailable")))
            try:
                result = worker.run_once(now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc))
            finally:
                worker.close()
            health = read_health(self.config.vault)
        self.assertEqual(result["status"], "degraded")
        self.assertEqual(self.buffer.for_session("session-1")[0]["status"], "failed")
        self.assertEqual(health["status"], "degraded")
        self.assertIn("local model unavailable", health["last_error"])

    def test_health_file_is_written_when_configured(self):
        self.append()
        with patch.dict("os.environ", {"MEMORY_WORKER_HEALTH": str(self.health)}):
            worker = self.worker(FakeManager())
            try:
                worker.run_once(now=datetime(2026, 9, 9, 12, 1, tzinfo=timezone.utc))
            finally:
                worker.close()
            health = read_health(self.config.vault)
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["backlog"], 0)
        self.assertEqual(json.loads(self.health.read_text(encoding="utf-8"))["status"], "ok")


if __name__ == "__main__":
    unittest.main()
