"""Crash-safe local buffering for generic AI-tool lifecycle observations.

The buffer deliberately lives outside the Obsidian vault.  A later consolidation
step turns observations into the existing four-section ``session_write`` contract.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .app_config import bootstrap_environment
from .browser_normalize import (
    is_browser_tool_payload,
    normalize_browser_tool_payload,
)
from .events import (
    ASSISTANT_FIELDS,
    CONSOLIDATION_EVENTS,
    HOST_META_FIELDS,
    PROMPT_FIELDS,
)
from .project_resolver import UNSCOPED, resolve_project_cached
from .security import SECRET_PATTERNS, check_text
from .utils import (
    is_truthy,
    to_kebab,
    truncated_text,
    utc_timestamp,
)

DEFAULT_MAX_TEXT = 4000
DEFAULT_MAX_FILES = 100
DEFAULT_LEASE_SECONDS = 300
MAX_RETRY_DELAY_SECONDS = 300
DEFAULT_RETENTION_DAYS = 30
DEFAULT_SENSITIVE_PATHS = (".env", ".env.*", "*/.ssh/*", "*/.aws/*", "*.pem", "*.key",
                           "*id_rsa*", "*id_ed25519*", "*.p12", "*.pfx")


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
    "postcompact": "post-compaction",
    "post-compact": "post-compaction",
    "stop": "stop",
    "stopfailure": "stop-failure",
    "stop-failure": "stop-failure",
    "interrupt": "interrupt",
    "sessionheartbeat": "session-heartbeat",
    "session-heartbeat": "session-heartbeat",
    "subagentstop": "subagent-stop",
    "subagent-stop": "subagent-stop",
    # Gemini CLI spellings (#82).
    "beforeagent": "user-prompt-submit",
    "before-agent": "user-prompt-submit",
    "afteragent": "stop",
    "after-agent": "stop",
    "beforetool": "pre-tool-use",
    "before-tool": "pre-tool-use",
    "aftertool": "post-tool-use",
    "after-tool": "post-tool-use",
    "precompress": "pre-compact",
    "pre-compress": "pre-compact",
    # Hermes Agent shell-hook spellings (#82).
    "pre-tool-call": "pre-tool-use",
    "post-tool-call": "post-tool-use",
    "on-session-start": "session-start",
    "on-session-end": "session-end",
    "pre-llm-call": "user-prompt-submit",
}

# Event -> which host field carries the human-readable evidence for it (#82).
# The receiver used to know only tool_input/tool_response, so every non-tool event
# arrived as an empty row and the pipeline had nothing but shell echoes to work with.
DEFAULT_MAX_META = 2000


def normalize_event(value: Any) -> str:
    """Map common client lifecycle spellings to one stable local name."""
    raw = "" if value is None else str(value).strip()
    if not raw:
        return "observation"
    kebab = to_kebab(raw, limit=80)
    return _EVENT_ALIASES.get(kebab, _EVENT_ALIASES.get(kebab.replace("-", ""), kebab))


def default_buffer_path() -> Path:
    configured = os.environ.get("MEMORY_CAPTURE_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".ai-memory-hub" / "observations.sqlite3"





def _capture_exclude_patterns() -> tuple[str, ...]:
    configured = os.environ.get("MEMORY_CAPTURE_EXCLUDE_PATHS", "")
    custom = tuple(item.strip().replace("\\", "/").casefold()
                   for item in configured.split(",") if item.strip())
    return DEFAULT_SENSITIVE_PATHS + custom


def _sensitive_path(value: str) -> bool:
    normalized = value.replace("\\", "/").casefold()
    name = normalized.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(name, pattern)
               for pattern in _capture_exclude_patterns())


def _sanitize_text(value: Any, excluded_paths: Iterable[str] = ()) -> str:
    # Normalize browser-tool payloads before any other processing
    if is_browser_tool_payload(value):
        return normalize_browser_tool_payload(value)
    text = truncated_text(value, DEFAULT_MAX_TEXT)
    for pattern, _label in SECRET_PATTERNS:
        text = pattern.sub("[redacted sensitive evidence]", text)
    for path in excluded_paths:
        if path:
            text = text.replace(path, "[redacted sensitive path]")
    result = check_text(text)
    if not result.safe and "sensitive" in result.reason:
        return "[redacted sensitive evidence]"
    return text


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Sanitize a raw payload dict before any persistence.

    Applies the same secret-redaction logic that ``Observation.from_payload``
    uses, but runs it on the raw dict first so that no unsanitized secret
    ever reaches a buffer or transcript store (#94).
    """
    if not isinstance(payload, dict):
        return payload
    sensitive_keys = (
        "input_summary", "output_summary", "prompt", "submitted_prompt",
        "user_message", "last_assistant_message", "prompt_response", "response",
        "final_response", "error_message", "reason", "trigger", "source",
    )
    sanitized = {}
    for key, value in payload.items():
        if key in sensitive_keys and isinstance(value, str):
            sanitized[key] = _sanitize_text(value)
        elif key == "extra" and isinstance(value, dict):
            sanitized[key] = _sanitize_payload(value)
        else:
            sanitized[key] = value
    return sanitized


def _bounded_files(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [path for path in (truncated_text(item, 500) for item in value[:DEFAULT_MAX_FILES]
                              if item is not None)
            if path and not _sensitive_path(path)]


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
    host_meta: dict[str, Any] = field(default_factory=dict)
    worktree: str = ""
    project_source: str = ""

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "Observation":
        if not isinstance(payload, dict):
            raise ValueError("observation must be a JSON object")
        session_id = truncated_text(payload.get("session_id"), 200).strip()
        if not session_id:
            raise ValueError("missing session_id")
        created_at = truncated_text(payload.get("created_at"), 80).strip()
        if not created_at:
            created_at = utc_timestamp()
        event = payload.get("event", payload.get("event_name", payload.get("hook_event")))
        event = event or payload.get("hook_event_name")
        event_name = normalize_event(event)

        # Hermes shell hooks wrap event-specific kwargs in "extra" (#82).
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}
        merged = {**extra, **{k: v for k, v in payload.items() if k != "extra"}}

        tool_input = merged.get("tool_input") if isinstance(merged.get("tool_input"), dict) else {}
        tool_response = merged.get("tool_response")
        tool = merged.get("tool") or merged.get("tool_name") or merged.get("name")
        files = merged.get("files")
        if not files:
            file_path = tool_input.get("file_path") or tool_input.get("path")
            files = [file_path] if file_path else []
        input_summary = merged.get("input_summary")
        output_summary = merged.get("output_summary")

        # Non-tool lifecycle events carry their evidence in event-specific fields.
        # Preserve the user's own words and the assistant's completed answer; they
        # are the only categorizable evidence most sessions produce (#82).
        prompt_text = next((merged[key] for key in PROMPT_FIELDS
                            if isinstance(merged.get(key), str) and merged[key].strip()), None)
        assistant_text = next((merged[key] for key in ASSISTANT_FIELDS
                               if isinstance(merged.get(key), str) and merged[key].strip()), None)
        if input_summary is None and prompt_text is not None:
            input_summary = prompt_text
            tool = tool or "prompt"
        if output_summary is None and assistant_text is not None:
            output_summary = assistant_text
            tool = tool or "assistant"
        if input_summary is None and tool_input:
            input_summary = json.dumps(tool_input, ensure_ascii=False, sort_keys=True)
        if output_summary is None and tool_response is not None:
            output_summary = (json.dumps(tool_response, ensure_ascii=False, sort_keys=True)
                              if isinstance(tool_response, (dict, list)) else str(tool_response))
        if input_summary is None:
            # session-start/source, session-end/reason, compaction/trigger, failure type.
            marker = next((merged[key] for key in ("source", "reason", "trigger", "error_type")
                           if isinstance(merged.get(key), str) and merged[key].strip()), None)
            if marker is not None and event_name not in {"pre-tool-use", "post-tool-use"}:
                input_summary = f"{event_name}: {marker}"
                if isinstance(merged.get("error_message"), str) and merged["error_message"].strip():
                    input_summary += f" - {merged['error_message']}"
        if not tool:
            tool = {"session-start": "session", "session-end": "session", "stop": "assistant",
                    "stop-failure": "session", "interrupt": "session", "pre-compact": "session",
                    "post-compaction": "session", "session-heartbeat": "session",
                    "user-prompt-submit": "prompt"}.get(event_name)

        raw_files = [truncated_text(item, 500) for item in (files or [])[:DEFAULT_MAX_FILES]
                     if item is not None]
        files = _bounded_files(raw_files)
        excluded_paths = [path for path in raw_files if _sensitive_path(path)]

        host_meta: dict[str, Any] = {}
        for key in HOST_META_FIELDS:
            value = merged.get(key)
            if value is None or isinstance(value, (dict, list)):
                continue
            if isinstance(value, str):
                if not value.strip():
                    continue
                value = _sanitize_text(value, excluded_paths)[:500]
            host_meta[key] = value
        if len(json.dumps(host_meta, ensure_ascii=False)) > DEFAULT_MAX_META:
            host_meta = {k: host_meta[k] for k in ("transcript_path", "model", "source", "reason",
                                                    "trigger", "error_type") if k in host_meta}

        cwd = truncated_text(merged.get("cwd"), 1000).strip()
        explicit_project = truncated_text(merged.get("project"), 200).strip()
        identity = resolve_project_cached(
            cwd or None, vault=os.environ.get("AI_MEMORY_VAULT") or None,
            explicit=explicit_project or None,
        )
        return cls(
            observation_id=truncated_text(
                merged.get("observation_id") or merged.get("event_id") or merged.get("hook_event_id"),
                100,
            ).strip() or uuid.uuid4().hex,
            session_id=session_id,
            project=identity.project if identity.project != UNSCOPED else "",
            cwd=cwd,
            tool=truncated_text(tool, 100).strip() or "unknown",
            files=files,
            input_summary=_sanitize_text(input_summary, excluded_paths),
            output_summary=_sanitize_text(output_summary, excluded_paths),
            git_commit=truncated_text(merged.get("git_commit"), 200).strip(),
            created_at=created_at,
            source=normalize_client(merged.get("source_client") or merged.get("client")
                                    or merged.get("client_type") or merged.get("writer"))
                   or "generic-hook",
            event=event_name,
            host_meta=host_meta,
            worktree=truncated_text(identity.worktree, 1000),
            project_source=identity.source,
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
            "host_meta": dict(self.host_meta),
            "worktree": self.worktree,
            "project_source": self.project_source,
        }


class ObservationBuffer:
    """Persistent, idempotent SQLite queue for raw observations."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path or default_buffer_path()).expanduser()
        try:
            self.retention_days = max(0, int(os.environ.get(
                "MEMORY_CAPTURE_RETENTION_DAYS", DEFAULT_RETENTION_DAYS)))
        except (TypeError, ValueError):
            self.retention_days = DEFAULT_RETENTION_DAYS
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
        # #82/#84: host-supplied metadata and resolved project identity. Additive
        # only; rows written by older receivers read back with empty defaults.
        if "host_meta_json" not in columns:
            self.conn.execute("ALTER TABLE observations ADD COLUMN host_meta_json TEXT NOT NULL DEFAULT '{}'")
        if "worktree" not in columns:
            self.conn.execute("ALTER TABLE observations ADD COLUMN worktree TEXT NOT NULL DEFAULT ''")
        if "project_source" not in columns:
            self.conn.execute("ALTER TABLE observations ADD COLUMN project_source TEXT NOT NULL DEFAULT ''")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_event ON observations(event, created_at)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_observations_project ON observations(project, created_at)")
        self.conn.commit()

    def prune_expired(self, *, now: datetime | None = None, include_pending: bool = False) -> int:
        """Remove terminal evidence older than retention without losing live work."""
        if self.retention_days <= 0:
            return 0
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=self.retention_days)).isoformat()
        statuses = ("completed", "failed") if not include_pending else (
            "pending", "failed", "processing", "completed")
        placeholders = ",".join("?" for _ in statuses)
        with self.conn:
            cursor = self.conn.execute(
                f"DELETE FROM observations WHERE created_at < ? AND status IN ({placeholders})",
                (cutoff, *statuses),
            )
        return cursor.rowcount

    def close(self) -> None:
        self.conn.close()

    def append(self, payload: Observation | dict[str, Any]) -> dict[str, Any]:
        observation = payload if isinstance(payload, Observation) else Observation.from_payload(payload)
        with self.conn:
            cursor = self.conn.execute(
                """INSERT OR IGNORE INTO observations
                (observation_id, session_id, project, cwd, tool, files_json,
                 input_summary, output_summary, git_commit, created_at, source, event,
                 host_meta_json, worktree, project_source)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    json.dumps(observation.host_meta, ensure_ascii=False, sort_keys=True),
                    observation.worktree,
                    observation.project_source,
                ),
            )
        row = self.conn.execute(
            "SELECT * FROM observations WHERE observation_id=?", (observation.observation_id,)
        ).fetchone()
        if row is None:
            raise RuntimeError("observation vanished between insert and select")
        result = self._row(row)
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
            if not ids:
                return []
            # Single bulk UPDATE ... RETURNING in one round-trip replaces the N
            # individual UPDATEs that each read-then-write one row (#252).
            placeholders = ",".join("?" for _ in ids)
            claimed_rows = self.conn.execute(
                f"""UPDATE observations SET status='processing', attempts=attempts+1,
                       claim_token=?, lease_expires_at=?, last_error=NULL,
                       next_attempt_at=NULL
                       WHERE observation_id IN ({placeholders})
                       AND status IN ('pending','failed')
                       RETURNING *""",
                (owner, expires, *ids),
            ).fetchall()
            return [self._row(row) for row in claimed_rows]

    def mark_status(self, observation_ids: Iterable[str], status: str, error: str | None = None,
                    owner: str | None = None) -> int:
        if status not in {"pending", "processing", "completed", "failed"}:
            raise ValueError("invalid observation status")
        ids = list(observation_ids)
        if not ids:
            return 0
        owner_clause = " AND claim_token=?" if owner else ""
        select_params: list[Any] = list(ids)
        if owner:
            select_params.append(owner)
        bounded_error = truncated_text(error, 1000) if error else None
        with self.conn:
            # Pre-fetch attempts/status in a single SELECT; batch UPDATE via executemany.
            rows = self.conn.execute(
                f"""SELECT observation_id, attempts, status FROM observations
                    WHERE observation_id IN ({",".join("?" for _ in ids)}){owner_clause}""",
                select_params,
            ).fetchall()
            if not rows:
                return 0
            now = datetime.now(timezone.utc)
            update_params: list[tuple] = []
            for row in rows:
                attempts = int(row[1]) + 1
                retry_at = None
                if status == "failed":
                    # The first retry is immediate; later failures back off up to
                    # five minutes without hiding the row from inspection.
                    delay = 0 if row[2] != "failed" else min(
                        MAX_RETRY_DELAY_SECONDS, 2 ** min(attempts, 8)
                    )
                    retry_at = (now + timedelta(seconds=delay)).isoformat()
                if owner:
                    update_params.append((status, attempts, bounded_error, None, retry_at,
                                          row[0], owner))
                else:
                    update_params.append((status, attempts, bounded_error, None, retry_at, row[0]))
            cursor = self.conn.executemany(
                f"""UPDATE observations SET status=?, attempts=?,
                    last_error=?, claim_token=NULL, lease_expires_at=?, next_attempt_at=?
                    WHERE observation_id=?{owner_clause}""",
                update_params,
            )
            return cursor.rowcount

    def _row(self, row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["files"] = json.loads(result.pop("files_json"))
        raw_meta = result.pop("host_meta_json", None)
        try:
            meta = json.loads(raw_meta) if raw_meta else {}
        except (TypeError, json.JSONDecodeError):
            meta = {}
        result["host_meta"] = meta if isinstance(meta, dict) else {}
        result.setdefault("worktree", "")
        result.setdefault("project_source", "")
        return result

    def pending_count(self, *, statuses: Iterable[str] | None = ("pending", "failed")) -> int:
        """Total observations awaiting consolidation across all sessions (#98).

        Single aggregate query replacing the prior N+1 pattern (one query per
        pending session via ``for_session``) that scaled poorly with many sessions.
        """
        values = list(statuses) if statuses else ("pending", "failed")
        placeholders = ",".join("?" for _ in values)
        row = self.conn.execute(
            f"SELECT COUNT(*) FROM observations WHERE status IN ({placeholders})",
            values,
        ).fetchone()
        return int(row[0]) if row else 0

    def sessions_for_project(self, project: str, *, statuses: Iterable[str] | None = None,
                             limit: int = 100) -> list[str]:
        """Session IDs whose evidence belongs to ``project`` (#84)."""
        params: list[Any] = [project]
        where = "project=?"
        if statuses:
            values = list(statuses)
            where += " AND status IN (" + ",".join("?" for _ in values) + ")"
            params.extend(values)
        params.append(max(1, min(int(limit), 1000)))
        rows = self.conn.execute(
            f"SELECT session_id, MAX(created_at) AS latest FROM observations WHERE {where} "
            "GROUP BY session_id ORDER BY latest DESC LIMIT ?",
            params,
        ).fetchall()
        return [str(row[0]) for row in rows]


_CLIENT_ALIASES = {
    "claude": "claude", "claude-code": "claude", "claude_code": "claude", "anthropic": "claude",
    "codex": "codex", "codex-cli": "codex", "openai": "codex",
    "gemini": "gemini", "gemini-cli": "gemini", "google": "gemini",
    "qwen": "qwen", "qwen-code": "qwen", "qwen_code": "qwen",
    "kimi": "kimi", "kimi-code": "kimi", "kimi_code_cli": "kimi", "kimi-cli": "kimi",
    "hermes": "hermes", "hermes-agent": "hermes",
    "cursor": "cursor", "chatgpt": "chatgpt", "user": "user", "other": "other",
}


def _build_prefix_index() -> dict[str, str]:
    """Pre-build a first-char index into _CLIENT_ALIASES for prefix matching (#224).

    Many callers pass strings that don't exactly match a key but share a prefix
    (e.g. "hermes-agent" matches "hermes"). A first-character index avoids
    scanning every alias on every call.
    """
    index: dict[str, str] = {}
    for key in _CLIENT_ALIASES:
        if key:
            index.setdefault(key[0], key)
    return index


_CLIENT_PREFIX_INDEX = _build_prefix_index()


def normalize_client(value: Any) -> str:
    """Map a host's self-description or the installer's --client to a writer name."""
    raw = "" if value is None else str(value).strip().lower().replace(" ", "-")
    if not raw:
        return ""
    if raw in _CLIENT_ALIASES:
        return _CLIENT_ALIASES[raw]
    # Pre-build prefix index: only check keys sharing the first character (#224)
    first_char = raw[0] if raw else ""
    if first_char in _CLIENT_PREFIX_INDEX:
        # Still need to check all keys with same first char (rare), but bounded
        for key, writer in _CLIENT_ALIASES.items():
            if key and key[0] == first_char and raw.startswith(key):
                return writer
    return raw[:100]


def _payloads_from_stdin(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict) and isinstance(value.get("observations"), list):
        return [item for item in value["observations"] if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    raise ValueError("stdin must contain an observation object, list, or observations array")


def hook_main(argv: list[str] | None = None) -> int:
    """Receive one generic hook payload and never block the host tool.

    ``--client <name>`` is set by the installer so every row carries the producing
    client even when the host payload has no self-identification (Claude Code and
    Codex send none; Kimi sends ``client_type``; Hermes sends ``profile``) (#82).
    """
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--client", default=os.environ.get("AI_MEMORY_HOOK_CLIENT", ""))
    parser.add_argument("--vault", default=None)
    try:
        args, _unknown = parser.parse_known_args(argv if argv is not None else sys.argv[1:])
    except SystemExit:  # argparse must never take the host down with it
        args = argparse.Namespace(client="", vault=None)
    client = normalize_client(args.client)
    transcript = None
    transcript_error = None
    try:
        if args.vault:
            os.environ.setdefault("AI_MEMORY_VAULT", str(args.vault))
        bootstrap_environment(os.environ.get("AI_MEMORY_VAULT"))  # never blocks; best-effort only.
        raw = sys.stdin.read()
        payloads = _payloads_from_stdin(json.loads(raw))
        if client:
            for payload in payloads:
                payload.setdefault("client", client)
        # #94: sanitize raw payloads before any persistence so secrets never
        # reach the buffer DB or transcript store.
        payloads = [_sanitize_payload(p) for p in payloads]
        buffer = ObservationBuffer()
        try:
            if is_truthy(os.environ.get("MEMORY_TRANSCRIPT_ENABLED", "")):
                from .transcript import TranscriptStore
                try:
                    transcript = TranscriptStore()
                except Exception as exc:  # Raw capture remains non-blocking.
                    transcript_error = str(exc)
            results = []
            for payload in payloads:
                result = buffer.append(payload)
                if transcript is not None:
                    try:
                        result["transcript"] = transcript.append(payload)
                    except Exception as exc:  # A hook must never block its host.
                        result["transcript_error"] = str(exc)
                results.append(result)
            buffer_path = buffer.path
        finally:
            buffer.close()
            if transcript is not None:
                transcript.close()
        response = {"status": "accepted", "count": len(results), "observations": results}
        if transcript_error:
            response["transcript_error"] = transcript_error
        # #83: a terminal event means the host will not send more evidence for this
        # session soon (or ever). Kick off a detached one-shot consolidation so a
        # checkpoint exists without a resident worker. Returns in milliseconds; the
        # child outlives this hook and the host's timeout budget.
        terminal_sessions = []
        for row in results:
            if row.get("event") in CONSOLIDATION_EVENTS and not row.get("duplicate"):
                if row.get("event") == "stop" and is_truthy(row.get("host_meta", {}).get("stop_hook_active")):
                    continue  # a continued turn is not a boundary
                if row["session_id"] not in terminal_sessions:
                    terminal_sessions.append(row["session_id"])
        if terminal_sessions:
            from .worker import spawn_detached_consolidation
            response["consolidation"] = [
                spawn_detached_consolidation(session_id, buffer_path=buffer_path)
                for session_id in terminal_sessions
            ]
        print(json.dumps(response))
    except Exception as exc:  # Hook failures must not block the calling AI tool.
        # Sanitize the exception message to avoid leaking internal paths or
        # implementation details back to the AI tool via stdout.
        reason = f"{type(exc).__name__}: {exc}"
        if len(reason) > 200:
            reason = reason[:200] + "…"
        print(json.dumps({"status": "rejected", "count": 0, "reason": reason}))
    return 0



