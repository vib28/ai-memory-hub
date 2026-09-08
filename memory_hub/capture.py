"""Crash-safe local buffering for generic AI-tool lifecycle observations.

The buffer deliberately lives outside the Obsidian vault.  A later consolidation
step turns observations into the existing four-section ``session_write`` contract.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_MAX_TEXT = 4000
DEFAULT_MAX_FILES = 100
DEFAULT_LEASE_SECONDS = 300
MAX_RETRY_DELAY_SECONDS = 300


_EVENT_ALIASES = {
    "sessionstart": "session-start",
    "session-start": "session-start",
    "sessionend": "session-end",
    "session-end": "session-end",
    "userpromptsubmit": "user-prompt-submit",
    "user-prompt-submit": "user-prompt-submit",
    "user-prompt": "user-prompt-submit",
    "pretooluse": "pre-tool-use",
    "pre-tool-use": "pre-tool-use",
    "posttooluse": "post-tool-use",
    "post-tool-use": "post-tool-use",
    "posttoolusefailure": "post-tool-use-failure",
    "post-tool-use-failure": "post-tool-use-failure",
    "precompact": "pre-compact",
    "pre-compact": "pre-compact",
    "postcompaction": "post-compaction",
    "post-compaction": "post-compaction",
    "stop": "stop",
}


def normalize_event(value: Any) -> str:
    """Map common client lifecycle spellings to one stable local name."""
    raw = "" if value is None else str(value).strip()
    if not raw:
        return "observation"
    kebab = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", raw).replace("_", "-").replace(" ", "-")
    kebab = re.sub(r"-+", "-", kebab).strip("-").lower()
    return _EVENT_ALIASES.get(kebab, _EVENT_ALIASES.get(kebab.replace("-", ""), kebab[:80]))


def default_buffer_path() -> Path:
    configured = os.environ.get("MEMORY_CAPTURE_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ai-memory-hub" / "observations.sqlite3"


def _bounded_text(value: Any, maximum: int = DEFAULT_MAX_TEXT) -> str:
    text = "" if value is None else str(value)
    return text[:maximum]


def _bounded_files(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [_bounded_text(item, 500) for item in value[:DEFAULT_MAX_FILES] if item is not None]


@dataclass(frozen=True)
class Observation:
    observation_id: str
    session_id: str
    project: str
    cwd: str
    tool: str
    files: list[str]
    input_summary: str
    output_summary: str
    git_commit: str
    created_at: str
    source: str
    event: str

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Observation":
        if not isinstance(payload, dict):
            raise ValueError("observation must be a JSON object")
        session_id = _bounded_text(payload.get("session_id"), 200).strip()
        if not session_id:
            raise ValueError("missing session_id")
        created_at = _bounded_text(payload.get("created_at"), 80).strip()
        if not created_at:
            created_at = datetime.now(timezone.utc).isoformat()
        tool_input = payload.get("tool_input") if isinstance(payload.get("tool_input"), dict) else {}
        tool_response = payload.get("tool_response")
        tool = payload.get("tool") or payload.get("tool_name") or payload.get("name")
        files = payload.get("files")
        if not files:
            file_path = tool_input.get("file_path") or tool_input.get("path")
            files = [file_path] if file_path else []
        input_summary = payload.get("input_summary")
        if input_summary is None and tool_input:
            input_summary = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
        output_summary = payload.get("output_summary")
        if output_summary is None and tool_response is not None:
            output_summary = (json.dumps(tool_response, ensure_ascii=False, sort_keys=True)
                              if isinstance(tool_response, (dict, list)) else str(tool_response))
        event = payload.get("event", payload.get("event_name", payload.get("hook_event")))
        event = event or payload.get("hook_event_name")
        return cls(
            observation_id=_bounded_text(
                payload.get("observation_id") or payload.get("event_id") or payload.get("hook_event_id"),
                100,
            ).strip() or uuid.uuid4().hex,
            session_id=session_id,
            project=_bounded_text(payload.get("project"), 200).strip(),
            cwd=_bounded_text(payload.get("cwd"), 1000).strip(),
            tool=_bounded_text(tool, 100).strip() or "unknown",
            files=_bounded_files(files),
            input_summary=_bounded_text(input_summary),
            output_summary=_bounded_text(output_summary),
            git_commit=_bounded_text(payload.get("git_commit"), 200).strip(),
            created_at=created_at,
            source=_bounded_text(payload.get("source") or payload.get("client"), 100).strip() or "generic-hook",
            event=normalize_event(event),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "observation_id": self.observation_id,
            "session_id": self.session_id,
            "project": self.project,
            "cwd": self.cwd,
            "tool": self.tool,
            "files": self.files,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "git_commit": self.git_commit,
            "created_at": self.created_at,
            "source": self.source,
            "event": self.event,
        }


class ObservationBuffer:
    """Persistent, idempotent SQLite queue for raw observations."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or default_buffer_path()).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS observations (
                observation_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                project TEXT NOT NULL,
                cwd TEXT NOT NULL,
                tool TEXT NOT NULL,
                files_json TEXT NOT NULL,
                input_summary TEXT NOT NULL,
                output_summary TEXT NOT NULL,
                git_commit TEXT NOT NULL,
                created_at TEXT NOT NULL,
                source TEXT NOT NULL,
                event TEXT NOT NULL DEFAULT 'observation',
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT
                ,claim_token TEXT
                ,lease_expires_at TEXT
                ,next_attempt_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_observations_session
                ON observations(session_id, created_at);
            CREATE INDEX IF NOT EXISTS idx_observations_status
                ON observations(status, created_at);
            """
        )
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(observations)")}
        if "event" not in columns:
            self.conn.execute("ALTER TABLE observations ADD COLUMN event TEXT NOT NULL DEFAULT 'observation'")
        if "claim_token" not in columns:
            self.conn.execute("ALTER TABLE observations ADD COLUMN claim_token TEXT")
        if "lease_expires_at" not in columns:
            self.conn.execute("ALTER TABLE observations ADD COLUMN lease_expires_at TEXT")
        if "next_attempt_at" not in columns:
            self.conn.execute("ALTER TABLE observations ADD COLUMN next_attempt_at TEXT")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_event ON observations(event, created_at)")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def append(self, payload: Observation | dict[str, Any]) -> dict[str, Any]:
        observation = payload if isinstance(payload, Observation) else Observation.from_payload(payload)
        with self.conn:
            cursor = self.conn.execute(
                """INSERT OR IGNORE INTO observations
                (observation_id, session_id, project, cwd, tool, files_json,
                 input_summary, output_summary, git_commit, created_at, source, event)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    observation.observation_id,
                    observation.session_id,
                    observation.project,
                    observation.cwd,
                    observation.tool,
                    json.dumps(observation.files, ensure_ascii=False),
                    observation.input_summary,
                    observation.output_summary,
                    observation.git_commit,
                    observation.created_at,
                    observation.source,
                    observation.event,
                ),
            )
        row = self.conn.execute(
            "SELECT * FROM observations WHERE observation_id=?", (observation.observation_id,)
        ).fetchone()
        assert row is not None
        result = dict(row)
        result["files"] = json.loads(result.pop("files_json"))
        result["duplicate"] = cursor.rowcount == 0
        return result

    def for_session(self, session_id: str, limit: int = 500,
                    statuses: Iterable[str] | None = None) -> list[dict[str, Any]]:
        params: list[Any] = [session_id]
        where = "session_id=?"
        if statuses:
            values = list(statuses)
            where += " AND status IN (" + ",".join("?" for _ in values) + ")"
            params.extend(values)
        params.append(max(1, min(int(limit), 5000)))
        rows = self.conn.execute(
            f"SELECT * FROM observations WHERE {where} ORDER BY created_at, observation_id LIMIT ?",
            params,
        ).fetchall()
        return [self._row(row) for row in rows]

    def pending_sessions(self, limit: int = 100) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT session_id FROM observations "
            "WHERE status IN ('pending', 'failed', 'processing') "
            "ORDER BY session_id LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def batch_sequence(self, rows: list[dict[str, Any]], *, limit: int = 500) -> int:
        """Return the stable one-based page number for an ordered claimed batch."""
        if not rows:
            return 0
        first = rows[0]
        before = self.conn.execute(
            """SELECT COUNT(*) FROM observations
               WHERE session_id=? AND
                 (created_at < ? OR (created_at=? AND observation_id <= ?))""",
            (first["session_id"], first["created_at"], first["created_at"], first["observation_id"]),
        ).fetchone()[0]
        return ((int(before) - 1) // max(1, min(int(limit), 5000))) + 1

    def recover_processing(self, session_id: str) -> int:
        """Return rows left processing by a crashed consolidation to retryable state."""
        now = datetime.now(timezone.utc)
        with self.conn:
            cursor = self.conn.execute(
                """UPDATE observations SET status='failed', attempts=attempts+1,
                   last_error=?, claim_token=NULL, lease_expires_at=NULL,
                   next_attempt_at=?
                   WHERE session_id=? AND status='processing'
                   AND (lease_expires_at IS NULL OR lease_expires_at <= ?)""",
                ("recovered after interrupted consolidation", now.isoformat(), session_id,
                 now.isoformat()),
            )
        return cursor.rowcount

    def claim_for_session(self, session_id: str, *, owner: str,
                          limit: int = 500, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> list[dict[str, Any]]:
        """Atomically claim one bounded, ordered batch for a worker."""
        now = datetime.now(timezone.utc)
        lease = (now.timestamp() + max(1, int(lease_seconds)))
        expires = datetime.fromtimestamp(lease, timezone.utc).isoformat()
        with self.conn:
            rows = self.conn.execute(
                """SELECT observation_id FROM observations
                   WHERE session_id=? AND status IN ('pending','failed')
                     AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                   ORDER BY created_at, observation_id LIMIT ?""",
                (session_id, now.isoformat(), max(1, min(int(limit), 5000))),
            ).fetchall()
            ids = [row[0] for row in rows]
            for observation_id in ids:
                self.conn.execute(
                    """UPDATE observations SET status='processing', attempts=attempts+1,
                       claim_token=?, lease_expires_at=?, last_error=NULL,
                       next_attempt_at=NULL
                       WHERE observation_id=? AND status IN ('pending','failed')""",
                    (owner, expires, observation_id),
                )
        if not ids:
            return []
        rows = self.conn.execute(
            "SELECT * FROM observations WHERE session_id=? AND claim_token=? "
            "ORDER BY created_at, observation_id LIMIT ?",
            (session_id, owner, len(ids)),
        ).fetchall()
        return [self._row(row) for row in rows]

    def mark_status(self, observation_ids: Iterable[str], status: str, error: str | None = None,
                    owner: str | None = None) -> int:
        if status not in {"pending", "processing", "completed", "failed"}:
            raise ValueError("invalid observation status")
        ids = list(observation_ids)
        if not ids:
            return 0
        with self.conn:
            updated = 0
            for observation_id in ids:
                row = self.conn.execute(
                    f"SELECT attempts, status FROM observations WHERE observation_id=?"
                    f"{(' AND claim_token=?' if owner else '')}",
                    (observation_id, owner) if owner else (observation_id,),
                ).fetchone()
                if row is None:
                    continue
                attempts = int(row[0]) + 1
                retry_at = None
                if status == "failed":
                    # The first retry is immediate; later failures back off up to
                    # five minutes without hiding the row from inspection.
                    delay = 0 if row[1] != "failed" else min(
                        MAX_RETRY_DELAY_SECONDS, 2 ** min(attempts, 8)
                    )
                    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                cursor = self.conn.execute(
                    f"""UPDATE observations SET status=?, attempts=attempts+1,
                       last_error=?, claim_token=NULL, lease_expires_at=?, next_attempt_at=?
                       WHERE observation_id=?{(' AND claim_token=?' if owner else '')}""",
                    ((status, _bounded_text(error, 1000) if error else None, None, retry_at,
                      observation_id, owner)
                     if owner else (status, _bounded_text(error, 1000) if error else None, None,
                                    retry_at, observation_id)),
                )
                updated += cursor.rowcount
        return updated

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["files"] = json.loads(result.pop("files_json"))
        return result


def _payloads_from_stdin(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and isinstance(value.get("observations"), list):
        return [item for item in value["observations"] if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    raise ValueError("stdin must contain an observation object, list, or observations array")


def hook_main(argv: list[str] | None = None) -> int:
    """Receive one generic hook payload and never block the host tool."""
    del argv
    try:
        raw = sys.stdin.read()
        payloads = _payloads_from_stdin(json.loads(raw))
        buffer = ObservationBuffer()
        try:
            results = [buffer.append(payload) for payload in payloads]
        finally:
            buffer.close()
        print(json.dumps({"status": "accepted", "count": len(results), "observations": results}))
    except Exception as exc:  # Hook failures must not block the calling AI tool.
        print(json.dumps({"status": "rejected", "count": 0, "reason": str(exc)}))
    return 0
