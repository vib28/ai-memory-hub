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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_MAX_TEXT = 4000
DEFAULT_MAX_FILES = 100


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
        return cls(
            observation_id=_bounded_text(payload.get("observation_id"), 100).strip() or uuid.uuid4().hex,
            session_id=session_id,
            project=_bounded_text(payload.get("project"), 200).strip(),
            cwd=_bounded_text(payload.get("cwd"), 1000).strip(),
            tool=_bounded_text(payload.get("tool"), 100).strip() or "unknown",
            files=_bounded_files(payload.get("files")),
            input_summary=_bounded_text(payload.get("input_summary")),
            output_summary=_bounded_text(payload.get("output_summary")),
            git_commit=_bounded_text(payload.get("git_commit"), 200).strip(),
            created_at=created_at,
            source=_bounded_text(payload.get("source"), 100).strip() or "generic-hook",
            event=normalize_event(
                payload.get("event", payload.get("event_name", payload.get("hook_event")))
            ),
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

    def for_session(self, session_id: str, limit: int = 500) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM observations WHERE session_id=? ORDER BY created_at, observation_id LIMIT ?",
            (session_id, max(1, min(int(limit), 5000))),
        ).fetchall()
        return [self._row(row) for row in rows]

    def pending_sessions(self, limit: int = 100) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT session_id FROM observations WHERE status='pending' ORDER BY session_id LIMIT ?",
            (max(1, min(int(limit), 1000)),),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def mark_status(self, observation_ids: Iterable[str], status: str, error: str | None = None) -> int:
        if status not in {"pending", "processing", "completed", "failed"}:
            raise ValueError("invalid observation status")
        ids = list(observation_ids)
        if not ids:
            return 0
        with self.conn:
            updated = 0
            for observation_id in ids:
                cursor = self.conn.execute(
                    """UPDATE observations SET status=?, attempts=attempts+1,
                       last_error=? WHERE observation_id=?""",
                    (status, _bounded_text(error, 1000) if error else None, observation_id),
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
