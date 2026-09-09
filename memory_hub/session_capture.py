"""Bridge buffered observations to the existing session-write policy."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from .capture import ObservationBuffer
from .consolidator import consolidate_session
from .transcript import transcript_enabled, transcript_path_for


def _batch_metadata(session_id: str, rows: list[dict[str, Any]], buffer: ObservationBuffer,
                    writer: str, *, batch_limit: int = 500,
                    entry_type: str = "checkpoint", state: str = "accepted",
                    host_session_finalized: bool = False) -> dict[str, Any]:
    """Derive a stable identity from the ordered evidence owned by one batch."""
    observation_ids = [str(row["observation_id"]) for row in rows]
    digest = hashlib.sha256("\0".join(observation_ids).encode("utf-8")).hexdigest()[:24]
    group = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    changed_files: list[str] = []
    for row in rows:
        for path in row.get("files", []) or []:
            value = str(path).strip()
            if value and value not in changed_files:
                changed_files.append(value)
    metadata = {
        "session_group_id": f"capture-{group}",
        "host_session_id": session_id,
        "checkpoint_id": f"batch-{digest}",
        "sequence": buffer.batch_sequence(rows, limit=batch_limit),
        "entry_type": entry_type,
        "state": state,
        "host_session_finalized": host_session_finalized,
        "source_client": writer,
        "worktree": rows[0].get("cwd") or None,
        "changed_files": changed_files[:100],
        "evidence_start": rows[0].get("created_at"),
        "evidence_end": rows[-1].get("created_at"),
        "session_tags": ["capture", "automatic"],
    }
    # transcript_path is deliberately NOT derived here: at this point the consolidated
    # summary's project has not been resolved yet, and rows[0]'s project is frequently
    # empty even when a later row (or the summary/fallback project rule) carries one.
    # Two checkpoints in the same group could otherwise disagree on where the group's
    # transcript lives (#70). The caller sets it once the summary's project is known.
    return metadata


def consolidate_buffered_session(
    buffer: ObservationBuffer,
    manager: Any,
    session_id: str,
    *,
    writer: str,
    write_mode: str,
    batch_limit: int = 500,
    entry_type: str = "checkpoint",
    state: str = "accepted",
    host_session_finalized: bool = False,
) -> dict[str, Any]:
    recovered = buffer.recover_processing(session_id)
    owner = uuid.uuid4().hex
    rows = buffer.claim_for_session(session_id, owner=owner, limit=batch_limit)
    if not rows:
        return {"status": "empty", "session_id": session_id, "observations": 0}
    observation_ids = [row["observation_id"] for row in rows]
    metadata = _batch_metadata(
        session_id, rows, buffer, writer, batch_limit=batch_limit,
        entry_type=entry_type, state=state,
        host_session_finalized=host_session_finalized,
    )
    try:
        summary = consolidate_session(rows)
        if transcript_enabled():
            # Derived from the same resolved project the summary itself carries, so
            # every checkpoint in this group agrees on one transcript_path (#70) —
            # never from rows[0] independently, which the summary's own project
            # resolution rule does not always match.
            metadata["transcript_path"] = transcript_path_for(
                metadata["session_group_id"], summary.get("project") or None
            )
        result = manager.propose_session({
            "model": writer,
            "title": summary["title"],
            "project": summary["project"],
            "investigated": summary["investigated"],
            "learned": summary["learned"],
            "completed": summary["completed"],
            "next_steps": summary["next_steps"],
            **metadata,
        }, write_mode=write_mode)
    except Exception as exc:
        buffer.mark_status(observation_ids, "failed", str(exc), owner=owner)
        raise
    if result.get("status") in {"stored", "stored_without_project_link", "queued", "queued_as_update",
                                 "already_pending", "duplicate"}:
        buffer.mark_status(observation_ids, "completed", owner=owner)
    elif result.get("status") == "rejected":
        buffer.mark_status(observation_ids, "failed", result.get("reason"), owner=owner)
    return {
        "status": result.get("status", "unknown"),
        "session_id": session_id,
        "observations": len(rows),
        "recovered": recovered,
        "summary": summary,
        "batch_id": metadata["checkpoint_id"],
        "write": result,
    }
