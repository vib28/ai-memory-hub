"""Supervised local checkpoint worker for the durable observation queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ._env import int_env as _int_env
from .capture import ObservationBuffer
from .manager import MemoryManager
from .session_capture import consolidate_buffered_session
from .transcript import TranscriptStore, transcript_enabled
from .utils import atomic_write


FINAL_EVENTS = {"session-end"}
TURN_EVENTS = {"stop", "post-tool-use-failure", "pre-compact", "post-compaction"}


def _parse_time(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return fallback


def estimated_tokens(row: dict[str, Any]) -> int:
    """Conservatively estimate captured evidence tokens without a model call."""
    value = " ".join([
        str(row.get("input_summary", "")), str(row.get("output_summary", "")),
        " ".join(str(path) for path in row.get("files", []) or []),
    ])
    return max(1, (len(value) + 3) // 4)


def worker_health_path(vault: Path | str) -> Path:
    configured = os.environ.get("MEMORY_WORKER_HEALTH", "").strip()
    if configured:
        return Path(configured).expanduser()
    identity = hashlib.sha256(str(Path(vault).expanduser().resolve()).encode()).hexdigest()[:16]
    return Path.home() / ".ai-memory-hub" / f"worker-health-{identity}.json"


def read_health(vault: Path | str) -> dict[str, Any]:
    path = worker_health_path(vault)
    if not path.exists():
        return {"status": "not_configured", "health_path": str(path)}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"status": "unreadable", "health_path": str(path)}
    if not isinstance(value, dict):
        return {"status": "invalid", "health_path": str(path)}
    value["health_path"] = str(path)
    return value


@dataclass(frozen=True)
class WorkerConfig:
    vault: Path
    buffer_path: Path
    writer: str = "other"
    write_mode: str = "review"
    token_budget: int = 4000
    flush_seconds: int = 60
    idle_seconds: int = 300
    interval_seconds: int = 15
    batch_limit: int = 500

    @classmethod
    def from_env(cls, vault: Path | str, buffer_path: Path | str | None = None) -> "WorkerConfig":
        root = Path(vault).expanduser()
        configured_buffer = buffer_path or os.environ.get("MEMORY_CAPTURE_DB")
        return cls(
            vault=root,
            buffer_path=Path(configured_buffer).expanduser()
            if configured_buffer else Path.home() / ".ai-memory-hub" / "observations.sqlite3",
            writer=os.environ.get("MEMORY_WRITER", "other").strip().lower() or "other",
            write_mode=os.environ.get("MEMORY_WRITE_MODE", "review").strip().lower() or "review",
            token_budget=_int_env("MEMORY_WORKER_TOKEN_BUDGET", 4000),
            flush_seconds=_int_env("MEMORY_WORKER_FLUSH_SECONDS", 60),
            idle_seconds=_int_env("MEMORY_WORKER_IDLE_SECONDS", 300),
            interval_seconds=_int_env("MEMORY_WORKER_INTERVAL_SECONDS", 15),
            batch_limit=_int_env("MEMORY_WORKER_BATCH_LIMIT", 500),
        )


class SessionWorker:
    """Run due local consolidations without making capture depend on a model."""

    def __init__(self, config: WorkerConfig, *, manager: MemoryManager | None = None,
                 buffer: ObservationBuffer | None = None):
        self.config = config
        self.manager = manager or MemoryManager(config.vault)
        self.buffer = buffer or ObservationBuffer(config.buffer_path)
        self._owns_manager = manager is None
        self._owns_buffer = buffer is None
        self.transcript_store = (TranscriptStore(vault=config.vault)
                                 if transcript_enabled() else None)
        self._stop = threading.Event()

    def close(self) -> None:
        if self._owns_buffer:
            self.buffer.close()
        if self._owns_manager:
            self.manager.close()
        if self.transcript_store is not None:
            self.transcript_store.close()

    def stop(self) -> None:
        self._stop.set()

    def _write_health(self, **updates: Any) -> dict[str, Any]:
        current = read_health(self.config.vault)
        current.update(updates)
        current["config"] = {
            "token_budget": self.config.token_budget,
            "flush_seconds": self.config.flush_seconds,
            "idle_seconds": self.config.idle_seconds,
            "interval_seconds": self.config.interval_seconds,
            "write_mode": self.config.write_mode,
            "transcript_enabled": self.transcript_store is not None,
        }
        path = worker_health_path(self.config.vault)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(current, ensure_ascii=False, indent=2) + "\n")
        return current

    def _due_rows(self, session_id: str, now: datetime) -> list[dict[str, Any]]:
        rows = self.buffer.for_session(
            session_id, limit=self.config.batch_limit,
            statuses={"pending", "failed"},
        )
        return [
            row for row in rows
            if not row.get("next_attempt_at")
            or _parse_time(row["next_attempt_at"], now) <= now
        ]

    def _trigger(self, rows: list[dict[str, Any]], now: datetime) -> tuple[str, str, str, bool] | None:
        if not rows:
            return None
        events = {str(row.get("event", "")) for row in rows}
        if events & FINAL_EVENTS:
            return "finalization", "accepted", "final", True
        tokens = sum(estimated_tokens(row) for row in rows)
        if tokens >= self.config.token_budget:
            return "token-budget", "accepted", "checkpoint", False
        if events & TURN_EVENTS:
            state = "provisional" if events & {"stop", "pre-compact", "post-compaction"} else "accepted"
            return "turn", state, "checkpoint", False
        # Idle measures time since the most RECENT activity and is checked first: with
        # the shipped defaults (flush_seconds=60 < idle_seconds=300), the oldest pending
        # row always crosses flush_seconds first on routine polling, so checking flush
        # first made idle permanently unreachable (#71). Checking idle first only
        # changes behavior when the gap since the newest row is itself severe — e.g. the
        # worker was down or otherwise missed a long stretch of polls — which is exactly
        # when a provisional/incomplete close is the more honest result than a routine
        # "accepted" checkpoint.
        newest = _parse_time(rows[-1].get("created_at"), now)
        if now - newest >= timedelta(seconds=self.config.idle_seconds):
            return "idle", "provisional", "checkpoint", False
        oldest = _parse_time(rows[0].get("created_at"), now)
        if now - oldest >= timedelta(seconds=self.config.flush_seconds):
            return "time", "accepted", "checkpoint", False
        return None

    def _batch_size(self, rows: list[dict[str, Any]], reason: str) -> int:
        if reason != "token-budget":
            return min(len(rows), self.config.batch_limit)
        total = 0
        for index, row in enumerate(rows, 1):
            total += estimated_tokens(row)
            if total >= self.config.token_budget:
                return index
        return min(len(rows), self.config.batch_limit)

    def run_once(self, *, now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        stamp = now.isoformat()
        self._write_health(status="running", last_run_at=stamp, last_error=None)
        retention_deleted = self.buffer.prune_expired(now=now)
        processed: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        transcript_deleted = 0
        transcript_rendered = 0
        if self.transcript_store is not None:
            try:
                transcript_deleted = self.transcript_store.prune(now=now)
                for group_id in self.transcript_store.groups():
                    # A routine poll re-render must reproduce the same file with the same
                    # summary back-links the authoritative writer set, not a degraded copy
                    # that drops them and can land at a second, orphaned path (#68). Fall
                    # back to the plain default when the group has no summary yet.
                    target = self.manager.session_transcript_target(group_id)
                    if target:
                        self.transcript_store.render(
                            group_id, self.config.vault,
                            project=target.get("project"), path=target.get("path"),
                            summary_links=target.get("summary_links") or [],
                        )
                    else:
                        self.transcript_store.render(group_id, self.config.vault)
                    transcript_rendered += 1
            except Exception as exc:
                errors.append({"session_id": "transcript", "reason": str(exc)})
        for session_id in self.buffer.pending_sessions():
            rows = self._due_rows(session_id, now)
            trigger = self._trigger(rows, now)
            if not trigger:
                continue
            reason, state, entry_type, host_finalized = trigger
            try:
                result = consolidate_buffered_session(
                    self.buffer, self.manager, session_id,
                    writer=self.config.writer, write_mode=self.config.write_mode,
                    batch_limit=self._batch_size(rows, reason), entry_type=entry_type,
                    state=state, host_session_finalized=host_finalized,
                )
                result["trigger"] = reason
                processed.append(result)
            except Exception as exc:  # one broken session must not stop the worker
                errors.append({"session_id": session_id, "reason": str(exc)})
        backlog = sum(
            len(self.buffer.for_session(session_id, limit=self.config.batch_limit,
                                        statuses={"pending", "failed"}))
            for session_id in self.buffer.pending_sessions()
        )
        status = "degraded" if errors else "ok"
        health_updates: dict[str, Any] = {
            "status": status, "last_run_at": stamp,
            "last_error": errors[0]["reason"] if errors else None,
            "backlog": backlog, "processed": len(processed), "errors": errors,
            "retention_deleted": retention_deleted,
            "transcript_deleted": transcript_deleted,
            "transcript_rendered": transcript_rendered,
        }
        # A degraded run must not overwrite the last known-good timestamp with null —
        # omit the key entirely so _write_health's dict.update() leaves it untouched (#72).
        if not errors:
            health_updates["last_success_at"] = stamp
        self._write_health(**health_updates)
        return {"status": status, "processed": processed, "errors": errors, "backlog": backlog,
                "retention_deleted": retention_deleted,
                "transcript_deleted": transcript_deleted,
                "transcript_rendered": transcript_rendered}

    def run_forever(self) -> None:
        self._write_health(status="starting", started_at=datetime.now(timezone.utc).isoformat())
        try:
            while not self._stop.is_set():
                self.run_once()
                self._stop.wait(self.config.interval_seconds)
        finally:
            self._write_health(status="stopped", stopped_at=datetime.now(timezone.utc).isoformat())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the local AI Memory Hub checkpoint worker.")
    parser.add_argument("--vault", default=os.environ.get("AI_MEMORY_VAULT"))
    parser.add_argument("--buffer", dest="buffer_path")
    parser.add_argument("--writer", default=os.environ.get("MEMORY_WRITER", "other"))
    parser.add_argument("--write-mode", choices=("review", "auto"),
                        default=os.environ.get("MEMORY_WRITE_MODE", "review"))
    parser.add_argument("--token-budget", type=int)
    parser.add_argument("--flush-seconds", type=int)
    parser.add_argument("--idle-seconds", type=int)
    parser.add_argument("--interval-seconds", type=int)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if not args.vault:
        parser.error("Set --vault or AI_MEMORY_VAULT")
    config = WorkerConfig.from_env(args.vault, args.buffer_path)
    overrides = {
        key: value for key, value in {
            "writer": args.writer, "write_mode": args.write_mode,
            "token_budget": args.token_budget, "flush_seconds": args.flush_seconds,
            "idle_seconds": args.idle_seconds, "interval_seconds": args.interval_seconds,
        }.items() if value is not None
    }
    config = WorkerConfig(**{**config.__dict__, **overrides})
    worker = SessionWorker(config)
    if not args.once:
        signal.signal(signal.SIGINT, lambda *_: worker.stop())
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    try:
        result = worker.run_once() if args.once else worker.run_forever()
        if args.once and result:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    finally:
        worker.close()


if __name__ == "__main__":
    raise SystemExit(main())
