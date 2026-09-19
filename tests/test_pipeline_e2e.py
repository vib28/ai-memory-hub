"""#83 / #87: the pipeline runs without a resident worker, and cut-offs are honest.

Process-level fixtures: a real ``ai-memory-hook`` subprocess receives host events,
spawns a real detached ``memory_hub.worker --session`` child, which writes a real
checkpoint to the manifest that a real ``memory_hub.handoff`` subprocess then
injects.  No mocks between stages.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from memory_hub.capture import ObservationBuffer
from memory_hub.handoff import build_handoff, catch_up_pending
from memory_hub.manager import MemoryManager
from memory_hub.worker import SessionWorker, WorkerConfig, spawn_detached_consolidation


def _wait_for(predicate, timeout: float = 20.0, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class PipelineFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.vault = root / "vault"
        self.buffer_path = root / "capture.sqlite3"
        self.repo = root / "widget-app"
        (self.repo / ".git").mkdir(parents=True)
        (self.repo / "src").mkdir()
        manager = MemoryManager(self.vault)
        manager.initialize(Path(__file__).resolve().parent.parent / "vault_template")
        manager.close()
        self.env = {
            **os.environ,
            "AI_MEMORY_VAULT": str(self.vault),
            "MEMORY_CAPTURE_DB": str(self.buffer_path),
            "MEMORY_WRITE_MODE": "auto",
            "MEMORY_WRITER": "other",
        }

    def tearDown(self):
        # Detached children may still hold the sqlite file for a moment on Windows.
        _wait_for(lambda: self._try_cleanup(), timeout=10)

    def _try_cleanup(self) -> bool:
        try:
            self.tmp.cleanup()
            return True
        except (PermissionError, OSError):
            return False

    def _hook(self, payload: dict, *args: str) -> dict:
        result = subprocess.run(
            [sys.executable, "-c", "from memory_hub.capture import hook_main; raise SystemExit(hook_main())",
             *args],
            input=json.dumps(payload), text=True, capture_output=True, env=self.env, check=True,
        )
        return json.loads(result.stdout)

    def _manifest(self) -> dict | None:
        path = self.vault / "sessions" / "session-manifest.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


class DetachedConsolidationTests(PipelineFixture):
    def test_session_end_hook_spawns_worker_that_writes_checkpoint_then_handoff_injects_it(self):
        cwd = str(self.repo / "src")
        base = {"session_id": "claude-run-1", "cwd": cwd}
        self._hook({**base, "hook_event_name": "SessionStart", "source": "startup"}, "--client", "claude")
        self._hook({**base, "hook_event_name": "UserPromptSubmit",
                    "prompt": "Add a date filter to the dashboard library view"}, "--client", "claude")
        self._hook({**base, "hook_event_name": "PostToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "git commit -m 'Add dashboard date filter'"},
                    "tool_response": {"stdout": "[master abc123] Add dashboard date filter"}},
                   "--client", "claude")
        self._hook({**base, "hook_event_name": "PostToolUse", "tool_name": "Bash",
                    "tool_input": {"command": "pytest -q"},
                    "tool_response": {"stdout": "12 passed in 0.4s"}}, "--client", "claude")
        self._hook({**base, "hook_event_name": "Stop", "stop_hook_active": False,
                    "last_assistant_message": "Added the filter and its tests; all green."},
                   "--client", "claude")
        started = time.monotonic()
        response = self._hook({**base, "hook_event_name": "SessionEnd", "reason": "prompt_input_exit"},
                              "--client", "claude")
        hook_seconds = time.monotonic() - started
        assert response["status"] == "accepted"
        assert response["consolidation"][0]["status"] == "spawned"
        assert hook_seconds < 5.0, "the hook itself must return quickly"

        assert _wait_for(lambda: self._manifest() is not None), "detached worker never produced a manifest"
        manifest = self._manifest()
        groups = list(manifest["groups"].values())
        assert len(groups) == 1
        entry = groups[0]["entries"][-1]
        assert entry["entry_type"] == "final"
        assert entry["project"] == "widget-app"
        assert entry["source_client"] == "claude"
        assert entry["path"].startswith("/sessions/widget-app/claude")

        # The next client, in the same repository, gets the checkpoint at SessionStart.
        result = subprocess.run(
            [sys.executable, "-m", "memory_hub.handoff", "--vault", str(self.vault), "--client", "codex"],
            input=json.dumps({"session_id": "codex-run-1", "cwd": str(self.repo), "source": "startup"}),
            text=True, capture_output=True, check=True, env=self.env,
        )
        output = json.loads(result.stdout)
        context = output["hookSpecificOutput"]["additionalContext"]
        assert output["status"] == "ok"
        assert "Add a date filter" in context
        assert "Added the filter and its tests" in context
        assert "git commit" in context
        assert "12 passed" in context

    def test_continued_stop_does_not_spawn(self):
        response = self._hook({"session_id": "s", "cwd": str(self.repo), "hook_event_name": "Stop",
                               "stop_hook_active": True, "last_assistant_message": "..."}, "--client", "claude")
        assert "consolidation" not in response

    def test_duplicate_delivery_spawns_once(self):
        payload = {"session_id": "s", "cwd": str(self.repo), "hook_event_name": "SessionEnd",
                   "event_id": "same-event", "reason": "other"}
        first = self._hook(payload, "--client", "claude")
        second = self._hook(payload, "--client", "claude")
        assert first["consolidation"][0]["status"] == "spawned"
        assert "consolidation" not in second

    def test_spawn_is_skipped_without_a_vault_and_never_raises(self):
        saved = os.environ.pop("AI_MEMORY_VAULT", None)
        try:
            result = spawn_detached_consolidation("x", buffer_path=self.buffer_path)
        finally:
            if saved is not None:
                os.environ["AI_MEMORY_VAULT"] = saved
        assert result["status"] == "skipped"

    def test_inline_consolidation_can_be_disabled(self):
        os.environ["MEMORY_INLINE_CONSOLIDATION"] = "false"
        try:
            result = spawn_detached_consolidation("x", vault=self.vault, buffer_path=self.buffer_path)
        finally:
            os.environ.pop("MEMORY_INLINE_CONSOLIDATION", None)
        assert result["status"] == "skipped"


class CatchUpTests(PipelineFixture):
    def _buffer_rows(self, session_id: str, *, cwd: str, n: int = 3) -> None:
        buffer = ObservationBuffer(self.buffer_path)
        try:
            for index in range(n):
                buffer.append({"observation_id": f"{session_id}-{index}", "session_id": session_id,
                               "cwd": cwd, "client": "claude", "hook_event_name": "PostToolUse",
                               "tool_name": "Bash", "tool_input": {"command": f"echo step {index}"},
                               "tool_response": {"stdout": f"step {index}"}})
            buffer.append({"observation_id": f"{session_id}-prompt", "session_id": session_id,
                           "cwd": cwd, "client": "claude", "hook_event_name": "UserPromptSubmit",
                           "prompt": f"work on {session_id}"})
        finally:
            buffer.close()

    def test_killed_session_is_checkpointed_by_next_session_start_in_same_project(self):
        os.environ.update({k: v for k, v in self.env.items() if k.startswith(("AI_MEMORY", "MEMORY_"))})
        self._buffer_rows("killed-claude", cwd=str(self.repo / "src"))
        other = Path(self.tmp.name) / "other-repo"
        (other / ".git").mkdir(parents=True)
        self._buffer_rows("unrelated", cwd=str(other))
        result = build_handoff(self.vault, payload={"session_id": "codex-new", "cwd": str(self.repo)},
                               client="codex")
        assert result["catch_up"]["status"] == "ok"
        assert result["catch_up"]["processed"] == 1
        assert result["status"] == "ok"
        assert "work on killed-claude" in result["packet"]
        assert "unrelated" not in result["packet"]
        # The unrelated project's evidence is untouched, not consumed.
        buffer = ObservationBuffer(self.buffer_path)
        try:
            assert buffer.pending_sessions() == ["unrelated"]
        finally:
            buffer.close()

    def test_catch_up_never_consolidates_the_session_that_is_starting(self):
        os.environ.update({k: v for k, v in self.env.items() if k.startswith(("AI_MEMORY", "MEMORY_"))})
        self._buffer_rows("resumed", cwd=str(self.repo))
        result = catch_up_pending(self.vault, cwd=str(self.repo), exclude_session="resumed")
        assert result["status"] == "clean"

    def test_catch_up_deadline_leaves_the_rest_pending_and_reports_it(self):
        os.environ.update({k: v for k, v in self.env.items() if k.startswith(("AI_MEMORY", "MEMORY_"))})
        for index in range(4):
            self._buffer_rows(f"old-{index}", cwd=str(self.repo))
        result = catch_up_pending(self.vault, cwd=str(self.repo), deadline_seconds=0.1)
        assert result["processed"] + result["pending"] >= 4
        assert result["elapsed_seconds"] < 5

    def test_unscoped_cwd_only_touches_unscoped_evidence(self):
        os.environ.update({k: v for k, v in self.env.items() if k.startswith(("AI_MEMORY", "MEMORY_"))})
        self._buffer_rows("project-work", cwd=str(self.repo))
        result = catch_up_pending(self.vault, cwd=str(Path.home()))
        assert result["processed"] == 0


class CutoffTriggerTests(unittest.TestCase):
    """#87: StopFailure / Interrupt finalize provisionally; heartbeats only refresh idle."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.buffer = ObservationBuffer(root / "capture.sqlite3")
        self.config = WorkerConfig(vault=root / "vault", buffer_path=root / "capture.sqlite3",
                                   writer="claude", write_mode="auto", token_budget=10000,
                                   flush_seconds=60, idle_seconds=300, interval_seconds=1)
        self.calls: list[tuple[dict, str]] = []

    def tearDown(self):
        self.buffer.close()
        self.tmp.cleanup()

    class _Manager:
        def __init__(self, calls):
            self.calls = calls

        def propose_session(self, payload, *, write_mode):
            self.calls.append((payload, write_mode))
            return {"status": "stored", "memory": {"memory_id": "m", "path": "/sessions/x.md"}}

        def session_transcript_target(self, group_id):
            return None

        def close(self):
            pass

    def _append(self, event: str, **fields):
        now = datetime.now(timezone.utc).isoformat()
        self.buffer.append({"session_id": "s", "cwd": "C:/work/repo", "hook_event_name": event,
                            "created_at": now, **fields})

    def test_rate_limit_stop_failure_is_a_provisional_final(self):
        self._append("UserPromptSubmit", prompt="finish the migration")
        self._append("StopFailure", error_type="rate_limit", error_message="Usage limit reached")
        worker = SessionWorker(self.config, manager=self._Manager(self.calls), buffer=self.buffer)
        try:
            result = worker.run_once()
        finally:
            worker.close()
        assert result["processed"][0]["trigger"] == "cutoff"
        payload = self.calls[0][0]
        assert payload["entry_type"] == "final"
        assert payload["state"] == "provisional"
        assert not payload["host_session_finalized"]
        assert any("rate_limit" in item for item in payload["next_steps"])

    def test_interrupt_is_a_provisional_final(self):
        self._append("PostToolUse", tool_name="Bash", tool_input={"command": "pytest"}, tool_response="1 passed")
        self._append("Interrupt", reason="user")
        worker = SessionWorker(self.config, manager=self._Manager(self.calls), buffer=self.buffer)
        try:
            result = worker.run_once()
        finally:
            worker.close()
        assert result["processed"][0]["trigger"] == "cutoff"
        assert self.calls[0][0]["state"] == "provisional"

    def test_heartbeats_alone_never_checkpoint_but_do_close_idle(self):
        old = (datetime.now(timezone.utc) - timedelta(seconds=400)).isoformat()
        self.buffer.append({"session_id": "s", "cwd": "C:/x", "hook_event_name": "SessionHeartbeat",
                            "uptime_ms": 60000, "created_at": old})
        worker = SessionWorker(self.config, manager=self._Manager(self.calls), buffer=self.buffer)
        try:
            first = worker.run_once(now=datetime.now(timezone.utc) - timedelta(seconds=390))
            second = worker.run_once()
        finally:
            worker.close()
        assert first["processed"] == []
        assert second["processed"][0]["trigger"] == "idle"

    def test_compaction_checkpoint_is_accepted_not_provisional(self):
        self._append("UserPromptSubmit", prompt="refactor")
        self._append("PreCompact", trigger="auto")
        worker = SessionWorker(self.config, manager=self._Manager(self.calls), buffer=self.buffer)
        try:
            worker.run_once()
        finally:
            worker.close()
        assert self.calls[0][0]["state"] == "accepted"
        assert self.calls[0][0]["entry_type"] == "checkpoint"

    def test_force_checkpoints_undue_sessions_and_deadline_skips(self):
        self._append("UserPromptSubmit", prompt="just started")
        worker = SessionWorker(self.config, manager=self._Manager(self.calls), buffer=self.buffer)
        try:
            untouched = worker.run_once()
            forced = worker.run_once(force=True)
            skipped = worker.run_once(session_ids=["s"], force=True, deadline_seconds=0.0)
        finally:
            worker.close()
        assert untouched["processed"] == []
        assert forced["processed"][0]["trigger"] == "forced"
        assert skipped["skipped_for_deadline"] == ["s"]


if __name__ == "__main__":
    unittest.main()
