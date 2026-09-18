"""Supervised local checkpoint worker for the durable observation queue."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from ._env import int_env as _int_env
from .app_config import bootstrap_environment
from .capture import ObservationBuffer
from .manager import MemoryManager
from .session_capture import consolidate_buffered_session
from .transcript import TranscriptStore, transcript_enabled
from .utils import atomic_write, parse_iso_datetime


FINAL_EVENTS = {"session-end"}
# A quota/rate-limit cut-off or an explicit interrupt is the end of what this host
# will contribute; it is *not* evidence the work finished, so it finalizes as
# provisional (#87). The next client's start packet states the reason verbatim.
CUTOFF_EVENTS = {"stop-failure", "interrupt"}
TURN_EVENTS = {"stop", "post-tool-use-failure", "pre-compact", "post-compaction"}
# Heartbeats carry no evidence of their own; they only prove the session was still
# alive, which refreshes the idle clock (#87).
HEARTBEAT_EVENTS = {"session-heartbeat"}



def estimated_tokens(row: dict[str, Any]) -> int:
    """Conservatively estimate captured evidence tokens without a model call."""
    value = " ".join([
        str(row.get("input_summary", "")), str(row.get("output_summary", "")),
        " ".join(str(path) for path in row.get("files", []) or []),
    ])
    return max(1, (len(value) + 3) // 4)


def worker_health_path(vault: Path | str) -> Path:
    """Return the worker health file for ``vault``.

    The health file lives *inside the vault's* ``.ai-memory-hub`` directory, next
    to ``config.json``, so each vault owns exactly one health record and a scratch
    vault (tests, experiments) never litters the user's home directory (#88).
    ``MEMORY_WORKER_HEALTH`` still overrides the location explicitly.
    """
    configured = os.environ.get("MEMORY_WORKER_HEALTH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path(vault).expanduser() / ".ai-memory-hub" / "worker-health.json"


def legacy_worker_health_path(vault: Path | str) -> Path:
    """Pre-#88 location: one hashed file per vault under the user's home."""
    identity = hashlib.sha256(str(Path(vault).expanduser().resolve()).encode()).hexdigest()[:16]
    return Path.home() / ".ai-memory-hub" / f"worker-health-{identity}.json"


def read_health(vault: Path | str) -> dict[str, Any]:
    path = worker_health_path(vault)
    if not path.exists():
        # A vault upgraded from the home-directory layout keeps reporting its last
        # known state until the next worker pass rewrites it at the new location.
        legacy = legacy_worker_health_path(vault)
        if legacy.exists():
            path = legacy
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
        bootstrap_environment(root)  # config.json fills gaps; an explicit env var still wins.
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
        # Per-group content-hash watermarks so a routine poll skips re-rendering a
        # transcript whose events AND resolved target are both unchanged (#117).
        self._transcript_watermarks: dict[str, str] = {}
        # Manifest cache keyed on mtime (#126): the routine transcript re-render
        # loop calls session_transcript_target(group_id) for every group on every
        # poll; that method re-reads and re-parses session-manifest.json from disk
        # each time. For a vault with G groups, that's G manifest reads per poll
        # interval. Cache the parsed manifest and its mtime; invalidate whenever a
        # checkpoint is appended so the next poll picks up the fresh manifest.
        self._manifest_cache: tuple[float, dict[str, Any]] | None = None
        self._stop = threading.Event()

    def close(self) -> None:
        if self._owns_buffer:
            self.buffer.close()
        if self._owns_manager:
            self.manager.close()
        if self.transcript_store is not None:
            self.transcript_store.close()

    def _cached_manifest(self) -> dict | None:
        """Return the parsed session manifest, caching keyed on mtime (#126).

        The routine transcript re-render loop calls
        ``session_transcript_target(group_id)`` for every group on every poll;
        that method reads and parses ``session-manifest.json`` from disk each
        time. For a vault with G groups, that's G manifest reads per poll
        interval. Cache the parsed manifest and its mtime; invalidate whenever
        a checkpoint is appended so the next poll picks up the fresh manifest.

        Returns ``None`` if the manager does not support manifest operations
        (e.g. a test stub that only provides ``session_transcript_target``),
        in which case the caller must not pass a manifest to
        ``session_transcript_target`` (preserving the old behavior).
        """
        if not hasattr(self.manager, "_session_manifest_path"):
            return None
        path = self.manager._session_manifest_path()
        if not path.exists():
            return {"version": 1, "groups": {}}
        mtime = path.stat().st_mtime
        if self._manifest_cache is not None and self._manifest_cache[0] == mtime:
            return self._manifest_cache[1]
        manifest = self.manager._load_session_manifest()
        self._manifest_cache = (mtime, manifest)
        return manifest

    def _invalidate_manifest_cache(self) -> None:
        """Invalidate the manifest cache after a checkpoint append (#126)."""
        self._manifest_cache = None

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
        payload = json.dumps(current, ensure_ascii=False, indent=2) + "\n"
        # Only write if the payload actually changed — avoid rewriting the same
        # health JSON on every poll when status/backlog are stable (#108). The
        # "running" marker is ephemeral; skip writing it when the terminal state
        # on disk hasn't changed, so idle workers don't churn the file.
        is_terminal = current.get("status") != "running"
        last_terminal = getattr(self, "_last_terminal_health_payload", None)
        if is_terminal:
            if last_terminal == payload:
                return current
            self._last_terminal_health_payload = payload
        elif last_terminal is not None:
            try:
                if path.exists() and path.read_text(encoding="utf-8") == last_terminal:
                    return current
            except OSError:
                pass
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, payload)
        return current

    def _due_rows(self, session_id: str, now: datetime) -> list[dict[str, Any]]:
        rows = self.buffer.for_session(
            session_id, limit=self.config.batch_limit,
            statuses={"pending", "failed"},
        )
        return [
            row for row in rows
            if not row.get("next_attempt_at")
            or parse_iso_datetime(row["next_attempt_at"], now) <= now
        ]

    def _trigger(self, rows: list[dict[str, Any]], now: datetime) -> tuple[str, str, str, bool] | None:
        if not rows:
            return None
        events = {str(row.get("event", "")) for row in rows}
        if events & FINAL_EVENTS:
            return "finalization", "accepted", "final", True
        if events & CUTOFF_EVENTS:
            # The host stopped abruptly (rate limit, API error, user interrupt). Close
            # this host's contribution as a provisional final so the work group stays
            # continuable by another client, and never claim completion (#87).
            return "cutoff", "provisional", "final", False
        evidence_rows = [row for row in rows if str(row.get("event", "")) not in HEARTBEAT_EVENTS]
        if not evidence_rows:
            # Heartbeats alone never produce a checkpoint; they are consumed silently
            # once the session goes idle (the idle path below marks them completed via
            # the caller's normal flow because rows still includes them).
            newest = parse_iso_datetime(rows[-1].get("created_at"), now)
            if now - newest >= timedelta(seconds=self.config.idle_seconds):
                return "idle", "provisional", "checkpoint", False
            return None
        tokens = sum(estimated_tokens(row) for row in evidence_rows)
        if tokens >= self.config.token_budget:
            return "token-budget", "accepted", "checkpoint", False
        if events & TURN_EVENTS:
            # Compaction is a deliberate summarization point chosen by the host; the
            # evidence before it is complete for its span, so it is accepted (#87).
            state = "provisional" if events & {"stop"} else "accepted"
            return "turn", state, "checkpoint", False
        # Idle measures time since the most RECENT activity and is checked first: with
        # the shipped defaults (flush_seconds=60 < idle_seconds=300), the oldest pending
        # row always crosses flush_seconds first on routine polling, so checking flush
        # first made idle permanently unreachable (#71). Checking idle first only
        # changes behavior when the gap since the newest row is itself severe — e.g. the
        # worker was down or otherwise missed a long stretch of polls — which is exactly
        # when a provisional/incomplete close is the more honest result than a routine
        # "accepted" checkpoint.
        newest = parse_iso_datetime(rows[-1].get("created_at"), now)
        if now - newest >= timedelta(seconds=self.config.idle_seconds):
            return "idle", "provisional", "checkpoint", False
        oldest = parse_iso_datetime(evidence_rows[0].get("created_at"), now)
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

    def run_once(self, *, now: datetime | None = None, session_ids: list[str] | None = None,
                 deadline_seconds: float | None = None, force: bool = False,
                 project: str | None = None) -> dict[str, Any]:
        """Run one consolidation pass.

        ``session_ids`` restricts the pass to those sessions (the detached
        post-event child spawned by the hook receiver names exactly one, #83).
        ``project`` restricts it to sessions whose evidence resolved to that
        project (the SessionStart catch-up pass, #83).  ``force`` consolidates
        every due session immediately as an ``accepted`` checkpoint even when no
        time/token/event trigger has fired yet -- used when the host has told us
        the session is over or the next client is about to start.  ``deadline_seconds``
        bounds the pass; sessions not reached are left pending and reported.
        """
        now = now or datetime.now(timezone.utc)
        started = time.monotonic()
        stamp = now.isoformat()
        self._write_health(status="running", last_run_at=stamp, last_error=None)
        retention_deleted = self.buffer.prune_expired(now=now)
        processed: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        skipped_for_deadline: list[str] = []
        transcript_deleted = 0
        transcript_rendered = 0
        if self.transcript_store is not None and not session_ids:
            try:
                transcript_deleted = self.transcript_store.prune(now=now)
            except Exception as exc:
                logger.exception("Transcript prune failed")
                errors.append({"session_id": "transcript", "reason": f"prune: {exc}"})
            cached_manifest = self._cached_manifest()
            for group_id in self.transcript_store.groups():
                try:
                    if cached_manifest is not None:
                        target = self.manager.session_transcript_target(
                            group_id, manifest=cached_manifest)
                    else:
                        target = self.manager.session_transcript_target(group_id)
                    events = self.transcript_store.events(group_id)
                    fingerprint = hashlib.sha256(json.dumps(
                        {"event_ids": [e["event_id"] for e in events], "target": target},
                        ensure_ascii=False, sort_keys=True,
                    ).encode("utf-8")).hexdigest()
                    if self._transcript_watermarks.get(group_id) == fingerprint:
                        continue
                    self.transcript_store.render(
                        group_id, self.config.vault,
                        project=target.get("project") if target else None,
                        path=target.get("path") if target else None,
                        summary_links=target.get("summary_links") or [] if target else [],
                    )
                    self._transcript_watermarks[group_id] = fingerprint
                    transcript_rendered += 1
                except Exception as exc:
                    logger.exception("Transcript processing failed for group %s", group_id)
                    errors.append({"session_id": f"transcript:{group_id}", "reason": str(exc)})
        candidates = list(session_ids) if session_ids else self.buffer.pending_sessions()
        if project is not None:
            scoped = set(self.buffer.sessions_for_project(
                project, statuses={"pending", "failed", "processing"}))
            candidates = [sid for sid in candidates if sid in scoped]
        for session_id in candidates:
            if deadline_seconds is not None and time.monotonic() - started >= deadline_seconds:
                skipped_for_deadline.append(session_id)
                continue
            rows = self._due_rows(session_id, now)
            trigger = self._trigger(rows, now)
            if not trigger and force and rows:
                trigger = ("forced", "accepted", "checkpoint", False)
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
                # A checkpoint append writes session-manifest.json, so the cached
                # manifest is now stale — invalidate it (#126) so the next poll
                # re-reads the fresh manifest for transcript_target resolution.
                if result.get("status") in {"stored", "stored_without_project_link"}:
                    self._invalidate_manifest_cache()
                result["trigger"] = reason
                try:
                    from .categorizer import apply_from_observations
                    batch = rows[: self._batch_size(rows, reason)]
                    result["categorized"] = apply_from_observations(
                        self.manager, batch, write_mode=self.config.write_mode,
                        writer=self.config.writer,
                        project=next((str(row.get("project") or "") for row in batch if row.get("project")), None),
                    )
                except Exception as cat_exc:  # categorization must not fail the checkpoint
                    result["categorized"] = [{"status": "error", "reason": str(cat_exc)}]
                processed.append(result)
            except Exception as exc:  # one broken session must not stop the worker
                errors.append({"session_id": session_id, "reason": str(exc)})
        backlog = self.buffer.pending_count()
        status = "degraded" if errors else "ok"
        health_updates: dict[str, Any] = {
            "status": status, "last_run_at": stamp,
            "last_error": errors[0]["reason"] if errors else None,
            "backlog": backlog, "processed": len(processed), "errors": errors,
            "retention_deleted": retention_deleted,
            "transcript_deleted": transcript_deleted,
            "transcript_rendered": transcript_rendered,
            "last_run_mode": ("session" if session_ids else "project" if project else "poll"),
        }
        # A degraded run must not overwrite the last known-good timestamp with null —
        # omit the key entirely so _write_health's dict.update() leaves it untouched (#72).
        if not errors:
            health_updates["last_success_at"] = stamp
        self._write_health(**health_updates)
        return {"status": status, "processed": processed, "errors": errors, "backlog": backlog,
                "retention_deleted": retention_deleted,
                "transcript_deleted": transcript_deleted,
                "transcript_rendered": transcript_rendered,
                "skipped_for_deadline": skipped_for_deadline,
                "elapsed_seconds": round(time.monotonic() - started, 3)}

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
    parser.add_argument("--session", action="append", default=[],
                        help="Consolidate only this host session (repeatable). Implies --once.")
    parser.add_argument("--project", default=None,
                        help="Consolidate only sessions resolved to this project. Implies --once.")
    parser.add_argument("--force", action="store_true",
                        help="Checkpoint due sessions now even if no trigger fired.")
    parser.add_argument("--deadline-seconds", type=float, default=None,
                        help="Stop the pass after this many seconds; unreached sessions stay pending.")
    parser.add_argument("--quiet", action="store_true", help="Do not print the JSON result.")
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
    once = args.once or bool(args.session) or args.project is not None
    worker = SessionWorker(config)
    if not once:
        signal.signal(signal.SIGINT, lambda *_: worker.stop())
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, lambda *_: worker.stop())
    try:
        if once:
            result = worker.run_once(session_ids=args.session or None, project=args.project,
                                     force=args.force, deadline_seconds=args.deadline_seconds)
            if not args.quiet:
                print(json.dumps(result, ensure_ascii=False))
        else:
            worker.run_forever()
        return 0
    finally:
        worker.close()


def spawn_detached_consolidation(session_id: str, *, vault: str | os.PathLike[str] | None = None,
                                 buffer_path: str | os.PathLike[str] | None = None,
                                 force: bool = True) -> dict[str, Any]:
    """Start a fire-and-forget ``worker --session <id>`` child and return at once (#83).

    Called by the hook receiver on terminal events so a checkpoint is produced
    even when no resident worker is registered.  The child is fully detached
    (its own process group / console) so the host's hook timeout cannot kill it
    and it never inherits the host's stdio.  Failure to spawn is reported, never
    raised: the receiver must stay non-blocking.
    """
    import subprocess
    import sys

    vault = str(vault or os.environ.get("AI_MEMORY_VAULT") or "")
    if not vault:
        return {"status": "skipped", "reason": "AI_MEMORY_VAULT is not set"}
    if os.environ.get("MEMORY_INLINE_CONSOLIDATION", "").strip().lower() in {"0", "false", "off", "no"}:
        return {"status": "skipped", "reason": "MEMORY_INLINE_CONSOLIDATION disabled"}
    command = [sys.executable, "-m", "memory_hub.worker", "--vault", vault, "--session", session_id,
               "--quiet"]
    if force:
        command.append("--force")
    if buffer_path:
        command.extend(["--buffer", str(buffer_path)])
    _allowlisted_vars = ("AI_MEMORY_VAULT", "MEMORY_WRITER", "MEMORY_WRITE_MODE", "PATH", "HOME", "USERPROFILE")
    kwargs: dict[str, Any] = {
        "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL,
        "close_fds": True, "env": {k: v for k, v in os.environ.items() if k in _allowlisted_vars},
    }
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **kwargs)
    except Exception as exc:  # never block the host
        return {"status": "failed", "reason": str(exc)}
    return {"status": "spawned", "pid": process.pid, "session_id": session_id}


if __name__ == "__main__":
    raise SystemExit(main())
