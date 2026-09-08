"""Bridge buffered observations to the existing session-write policy."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from .capture import ObservationBuffer
from .consolidator import consolidate_session


def _batch_metadata(session_id: str, rows: list[dict[str, Any]], buffer: ObservationBuffer,
                    writer: str) -> dict[str, Any]:
    """Derive a stable identity from the ordered evidence owned by one batch."""
    observation_ids = [str(row["observation_id"]) for row in rows]
    digest = hashlib.sha256("\0".join(observation_ids).encode("utf-8")).hexdigest()[:24]
    group = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return {
        "session_group_id": f"capture-{group}",
        "host_session_id": session_id,
        "checkpoint_id": f"batch-{digest}",
        "sequence": buffer.batch_sequence(rows),
        "entry_type": "checkpoint",
        "source_client": writer,
        "worktree": rows[0].get("cwd") or None,
        "evidence_start": rows[0].get("created_at"),
        "evidence_end": rows[-1].get("created_at"),
        "session_tags": ["capture", "automatic"],
    }


def consolidate_buffered_session(
    buffer: ObservationBuffer,
    manager: Any,
    session_id: str,
    *,
    writer: str,
    write_mode: str,
) -> dict[str, Any]:
    recovered = buffer.recover_processing(session_id)
    owner = uuid.uuid4().hex
    rows = buffer.claim_for_session(session_id, owner=owner)
    if not rows:
        return {"status": "empty", "session_id": session_id, "observations": 0}
    observation_ids = [row["observation_id"] for row in rows]
    metadata = _batch_metadata(session_id, rows, buffer, writer)
    try:
        summary = consolidate_session(rows)
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
