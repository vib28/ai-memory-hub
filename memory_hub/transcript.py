"""Opt-in, local-first verbatim session transcript storage.

The ordinary capture queue is intentionally bounded and sanitized.  This module
is a separate companion path for users who explicitly opt in to retaining raw
provider envelopes.  It is not indexed as a memory and is never read by the
GitHub exporter.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from .utils import atomic_write, file_lock, slugify


DEFAULT_TRANSCRIPT_RETENTION_DAYS = 0
_SAFE_TAG = re.compile(r"[^a-z0-9/_-]+")


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def transcript_enabled() -> bool:
    """Return whether raw transcript persistence was explicitly enabled."""
    return _env_flag("MEMORY_TRANSCRIPT_ENABLED")


def _retention_days() -> int:
    try:
        return max(0, int(os.environ.get(
            "MEMORY_TRANSCRIPT_RETENTION_DAYS", DEFAULT_TRANSCRIPT_RETENTION_DAYS)))
    except (TypeError, ValueError):
        return DEFAULT_TRANSCRIPT_RETENTION_DAYS


def _vault_root(vault: Path | str | Any | None = None) -> Path:
    if vault is not None and not isinstance(vault, (Path, str)) and hasattr(vault, "root"):
        return Path(vault.root).expanduser().resolve()
    if vault is not None:
        return Path(vault).expanduser().resolve()
    configured = os.environ.get("AI_MEMORY_VAULT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.home() / ".ai-memory-hub"


def default_transcript_db(vault: Path | str | Any | None = None) -> Path:
    configured = os.environ.get("MEMORY_TRANSCRIPT_DB", "").strip()
    if configured:
        return Path(configured).expanduser()
    return _vault_root(vault) / ".ai-memory-hub" / "transcripts.sqlite3"


def transcript_group_id(session_id: str) -> str:
    """Use the continuity group identity used by the existing capture bridge."""
    digest = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:16]
    return f"capture-{digest}"


def transcript_path_for(session_group_id: str, project: str | None = None) -> str:
    group = slugify(str(session_group_id)) or "session"
    if project:
        return f"/transcripts/{slugify(str(project))}/{group}.md"
    return f"/transcripts/{group}.md"


def _text(value: Any, maximum: int = 500) -> str:
    return str(value).strip()[:maximum] if value is not None else ""


def _timestamp(value: Any, *, fallback: datetime | None = None) -> str:
    if value:
        raw = str(value).strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.isoformat()
        except ValueError:
            return raw
    return (fallback or datetime.now(timezone.utc)).isoformat()


def _normalize_author(value: Any, object_type: str) -> str:
    raw = _text(value, 40).lower().replace("_", "-")
    if raw in {"assistant", "ai", "model", "agent", "codex", "claude"}:
        return "agent"
    if raw in {"human", "user", "operator", "person"}:
        return "user"
    if raw in {"tool", "function", "command"}:
        return "tool"
    if raw in {"system", "host", "lifecycle"}:
        return "system"
    if raw:
        return slugify(raw) or "unknown"
    if object_type in {"user", "user-message", "user-prompt-submit"}:
        return "user"
    if object_type in {"agent", "agent-message", "assistant-message", "assistant"}:
        return "agent"
    if object_type in {"pre-tool-use", "post-tool-use", "post-tool-use-failure", "tool-call", "tool-result"}:
        return "tool"
    if object_type in {"session-start", "session-end", "stop", "lifecycle"}:
        return "system"
    return "unknown"


def _normalize_object_type(payload: dict[str, Any]) -> str:
    value = (payload.get("object_type") or payload.get("object") or
             payload.get("type") or payload.get("event") or
             payload.get("event_name") or payload.get("hook_event") or "message")
    if value == "message" and payload.get("hook_event_name"):
        value = payload["hook_event_name"]
    normalized = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", str(value))
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", normalized.replace("_", "-"))
    return normalized.strip("-").lower()[:80] or "message"


def _raw_payload(payload: dict[str, Any]) -> tuple[str, str]:
    if "payload" in payload:
        value = payload["payload"]
    elif "content" in payload:
        value = payload["content"]
    elif "message" in payload:
        value = payload["message"]
    else:
        value = payload
    if isinstance(value, str):
        return "text", value
    return "json", json.dumps(value, ensure_ascii=False, sort_keys=False, indent=2)


def _safe_tag(value: str) -> str:
    value = _SAFE_TAG.sub("-", value.casefold()).strip("-/")
    return value[:80] or "unknown"


def _fence(value: str) -> str:
    longest = max((len(item) for item in re.findall(r"`+", value)), default=0)
    return "`" * max(3, longest + 1)


class TranscriptStore:
    """SQLite-backed idempotent event store with deterministic Markdown rendering."""

    def __init__(self, path: Path | str | None = None, *, vault: Path | str | Any | None = None):
        self.path = Path(path or default_transcript_db(vault)).expanduser()
        self.vault = _vault_root(vault)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS transcript_events (
                event_id TEXT PRIMARY KEY,
                session_group_id TEXT NOT NULL,
                host_session_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                source_sequence INTEGER,
                author TEXT NOT NULL,
                object_type TEXT NOT NULL,
                client TEXT,
                model TEXT,
                project TEXT,
                topic TEXT,
                generated_at TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                payload_kind TEXT NOT NULL,
                payload_text TEXT NOT NULL,
                envelope_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_transcript_group_sequence
                ON transcript_events(session_group_id, sequence, event_id);
            CREATE INDEX IF NOT EXISTS idx_transcript_generated_at
                ON transcript_events(generated_at);
            """
        )
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(transcript_events)")}
        if "generated_at_source" not in columns:
            # Rows written before this column existed have no recoverable provenance —
            # "unknown" rather than defaulting to "capture", which would falsely claim
            # the substitution happened when it may not have (#77).
            self.conn.execute(
                "ALTER TABLE transcript_events ADD COLUMN generated_at_source "
                "TEXT NOT NULL DEFAULT 'unknown'")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _normalize(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("transcript event must be a JSON object")
        host_session_id = _text(payload.get("session_id") or payload.get("host_session_id"), 200)
        if not host_session_id:
            raise ValueError("missing session_id")
        group = _text(payload.get("session_group_id"), 200) or transcript_group_id(host_session_id)
        object_type = _normalize_object_type(payload)
        source_sequence = payload.get("sequence")
        try:
            source_sequence = max(0, int(source_sequence)) if source_sequence is not None else None
        except (TypeError, ValueError):
            source_sequence = None
        generated_supplied = payload.get("generated_at") or payload.get("created_at")
        generated_at = _timestamp(generated_supplied)
        # #77: a substituted timestamp must be recorded as substituted, not presented
        # identically to one the provider actually supplied.
        generated_at_source = "provider" if generated_supplied else "capture"
        captured_at = _timestamp(payload.get("captured_at"))
        kind, raw = _raw_payload(payload)
        explicit_id = _text(payload.get("event_id") or payload.get("id") or
                             payload.get("observation_id") or payload.get("hook_event_id"), 200)
        author_value = payload.get("author") or payload.get("speaker") or payload.get("role")
        if not author_value and (payload.get("tool_name") or payload.get("tool_input")
                                 or payload.get("tool_response")):
            author_value = "tool"
        seed = {
            "session_group_id": group,
            "host_session_id": host_session_id,
            "source_sequence": source_sequence,
            "author": _normalize_author(author_value, object_type),
            "object_type": object_type,
            "client": _text(payload.get("client") or payload.get("source"), 100) or None,
            "model": _text(payload.get("model"), 200) or None,
            "project": _text(payload.get("project"), 200) or None,
            "topic": _text(payload.get("topic"), 200) or None,
            "payload_kind": kind,
            "payload_text": raw,
            # Do not include an auto-generated timestamp in the fallback seed.
            # This keeps retries stable when a provider omitted its timestamp.
            "generated_at": _timestamp(generated_supplied, fallback=datetime(1970, 1, 1, tzinfo=timezone.utc))
            if generated_supplied else None,
        }
        event_id = explicit_id or "tr-" + hashlib.sha256(
            json.dumps(seed, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()[:32]
        return {
            "event_id": event_id,
            "session_group_id": group,
            "host_session_id": host_session_id,
            "source_sequence": source_sequence,
            "author": seed["author"],
            "object_type": object_type,
            "client": seed["client"],
            "model": seed["model"],
            "project": seed["project"],
            "topic": seed["topic"],
            "generated_at": generated_at,
            "generated_at_source": generated_at_source,
            "captured_at": captured_at,
            "payload_kind": kind,
            "payload_text": raw,
        }

    def append(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = self._normalize(payload)
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self.conn.execute(
                "SELECT * FROM transcript_events WHERE event_id=?", (event["event_id"],)
            ).fetchone()
            if existing is not None:
                self.conn.commit()
                result = self._row(existing)
                result["duplicate"] = True
                return result
            current = self.conn.execute(
                "SELECT COALESCE(MAX(sequence), 0) FROM transcript_events WHERE session_group_id=?",
                (event["session_group_id"],),
            ).fetchone()[0]
            event["sequence"] = max(int(current) + 1, int(event["source_sequence"] or 0))
            envelope = dict(event)
            envelope.pop("payload_text", None)
            envelope["payload"] = (event["payload_text"] if event["payload_kind"] == "text"
                                    else json.loads(event["payload_text"]))
            self.conn.execute(
                """INSERT INTO transcript_events
                (event_id, session_group_id, host_session_id, sequence, source_sequence,
                 author, object_type, client, model, project, topic, generated_at,
                 generated_at_source, captured_at, payload_kind, payload_text, envelope_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event["event_id"], event["session_group_id"], event["host_session_id"],
                 event["sequence"], event["source_sequence"], event["author"], event["object_type"],
                 event["client"], event["model"], event["project"], event["topic"],
                 event["generated_at"], event["generated_at_source"], event["captured_at"],
                 event["payload_kind"], event["payload_text"],
                 json.dumps(envelope, ensure_ascii=False, sort_keys=True)),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        result = dict(event)
        result["duplicate"] = False
        return result

    def _row(self, row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
        result = dict(row)
        raw = result.pop("payload_text")
        result["payload_raw"] = raw
        result["payload"] = raw if result["payload_kind"] == "text" else json.loads(raw)
        result.pop("envelope_json", None)
        return result

    def events(self, session_group_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM transcript_events WHERE session_group_id=? "
            "ORDER BY sequence, generated_at, event_id", (session_group_id,)
        ).fetchall()
        return [self._row(row) for row in rows]

    def groups(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT session_group_id FROM transcript_events ORDER BY session_group_id"
        ).fetchall()
        return [str(row[0]) for row in rows]

    def coverage(self, session_group_id: str) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT COUNT(*), MIN(sequence), MAX(sequence), MIN(generated_at), MAX(generated_at) "
            "FROM transcript_events WHERE session_group_id=?", (session_group_id,)
        ).fetchone()
        return {
            "transcript_event_count": int(rows[0] or 0),
            "transcript_sequence_start": int(rows[1]) if rows[1] is not None else None,
            "transcript_sequence_end": int(rows[2]) if rows[2] is not None else None,
            "transcript_evidence_start": rows[3],
            "transcript_evidence_end": rows[4],
        }

    def render(self, session_group_id: str, vault: Path | str | Any | None = None, *,
               project: str | None = None, path: str | None = None,
               summary_links: Iterable[str] = ()) -> dict[str, Any]:
        rows = self.events(session_group_id)
        project = project or next((row.get("project") for row in rows if row.get("project")), None)
        relative = path or transcript_path_for(session_group_id, project)
        relative = "/" + str(relative).replace("\\", "/").lstrip("/")
        root = _vault_root(vault or self.vault)
        destination = root / relative.lstrip("/")
        destination.parent.mkdir(parents=True, exist_ok=True)
        authors = sorted({_safe_tag(str(row.get("author") or "unknown")) for row in rows})
        object_types = sorted({_safe_tag(str(row.get("object_type") or "message")) for row in rows})
        tags = ["transcript", "session", *authors, *object_types]
        if project:
            tags.append(f"project/{_safe_tag(str(project))}")
        topics = sorted({str(row["topic"]) for row in rows if row.get("topic")})
        first = rows[0] if rows else {}
        last = rows[-1] if rows else {}
        lines = ["---", "type: transcript", "version: 1",
                 f"session_group_id: {json.dumps(session_group_id, ensure_ascii=False)}",
                 f"project: {json.dumps(project, ensure_ascii=False) if project else 'null'}",
                 f"topic: {json.dumps(topics[0], ensure_ascii=False) if topics else 'null'}",
                 f"started_at: {json.dumps(first.get('generated_at'))}",
                 f"ended_at: {json.dumps(last.get('generated_at'))}",
                 f"event_count: {len(rows)}", "tags:"]
        lines.extend(f"  - {_safe_tag(tag)}" for tag in dict.fromkeys(tags))
        lines.extend(["---", "", f"# Session transcript — {session_group_id}", "",
                      f"**Session group:** `{session_group_id}`"])
        links = [str(link) for link in summary_links if str(link).strip()]
        if links:
            lines.append("**Summaries:** " + " · ".join(links))
        lines.extend([f"**Events:** {len(rows)}", "", "## Chronological events", ""])
        for row in rows:
            stamp = str(row["generated_at"])
            author = row["author"]
            kind = row["object_type"]
            lines.extend([f"### {stamp} — {author} — {kind}",
                          f"**Sequence:** {row['sequence']}",
                          f"**Event ID:** `{row['event_id']}`",
                          f"**Client:** {row.get('client') or 'unknown'}",
                          f"**Model:** {row.get('model') or 'unknown'}",
                          f"**Captured:** {row['captured_at']}"])
            # #77: a substituted generated_at must be recorded as substituted, not
            # presented as though the provider supplied it. Only annotate the cases
            # that are not plain provider-supplied, so an ordinary reader is not
            # burdened with a marker on every line.
            source = row.get("generated_at_source")
            if source == "capture":
                lines.append("**Generated-at source:** not supplied by provider — capture time recorded")
            elif source == "unknown":
                lines.append("**Generated-at source:** unknown (recorded before provenance tracking)")
            if row.get("topic"):
                lines.append(f"**Topic:** {row['topic']}")
            if row.get("project"):
                lines.append(f"**Project:** [[{slugify(str(row['project']))}]]")
            lines.extend(["", "**Verbatim payload:**", ""])
            fence = _fence(str(row["payload_raw"]))
            language = "text" if row["payload_kind"] == "text" else "json"
            lines.extend([f"{fence}{language}", str(row["payload_raw"]), fence, ""])
        content = "\n".join(lines).rstrip() + "\n"
        with file_lock(destination):
            atomic_write(destination, content)
        return {"path": relative, **self.coverage(session_group_id)}

    def prune(self, *, now: datetime | None = None) -> int:
        days = _retention_days()
        if days <= 0:
            return 0
        cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=days)).isoformat()
        affected_rows = self.conn.execute(
            "SELECT DISTINCT session_group_id, project FROM transcript_events "
            "WHERE captured_at < ?", (cutoff,)
        ).fetchall()
        with self.conn:
            result = self.conn.execute("DELETE FROM transcript_events WHERE captured_at < ?", (cutoff,))
        for row in affected_rows:
            group_id = str(row[0])
            project = row[1] or None
            if self.events(group_id):
                self.render(group_id, self.vault, project=project)
                continue
            for relative in {
                transcript_path_for(group_id),
                transcript_path_for(group_id, project),
            }:
                destination = self.vault / relative.lstrip("/")
                if destination.exists() and destination.is_file():
                    destination.unlink()
        return result.rowcount

    def delete_group(self, session_group_id: str, *, vault: Path | str | Any | None = None,
                     path: str | None = None) -> int:
        # Read the group's distinct projects BEFORE deleting rows: a caller that omits
        # `path` (a manifest entry with no session-meta marker) must still reach a
        # project-scoped file, or the SQLite rows are gone while the rendered Markdown
        # — verbatim prompts, tool inputs, tool outputs — stays on disk (#76). Mirrors
        # the same project-enumeration prune() already does below.
        projects = {
            str(row[0]) if row[0] else None
            for row in self.conn.execute(
                "SELECT DISTINCT project FROM transcript_events WHERE session_group_id=?",
                (session_group_id,),
            ).fetchall()
        }
        with self.conn:
            result = self.conn.execute(
                "DELETE FROM transcript_events WHERE session_group_id=?", (session_group_id,)
            )
        root = _vault_root(vault or self.vault)
        candidates = {path} if path else set()
        candidates |= {transcript_path_for(session_group_id, project) for project in (projects or {None})}
        for relative in candidates:
            destination = root / str(relative).lstrip("/")
            if destination.exists() and destination.is_file():
                destination.unlink()
        return result.rowcount
