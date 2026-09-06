"""Bridge buffered observations to the existing session-write policy."""

from __future__ import annotations

from typing import Any

from .capture import ObservationBuffer
from .consolidator import consolidate_session


def consolidate_buffered_session(
    buffer: ObservationBuffer,
    manager: Any,
    session_id: str,
    *,
    writer: str,
    write_mode: str,
) -> dict[str, Any]:
    recovered = buffer.recover_processing(session_id)
    rows = [row for row in buffer.for_session(session_id) if row["status"] in {"pending", "failed"}]
    if not rows:
        return {"status": "empty", "session_id": session_id, "observations": 0}
    observation_ids = [row["observation_id"] for row in rows]
    buffer.mark_status(observation_ids, "processing")
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
        }, write_mode=write_mode)
    except Exception as exc:
        buffer.mark_status(observation_ids, "failed", str(exc))
        raise
    if result.get("status") in {"stored", "stored_without_project_link", "queued", "queued_as_update", "duplicate"}:
        buffer.mark_status(observation_ids, "completed")
    elif result.get("status") == "rejected":
        buffer.mark_status(observation_ids, "failed", result.get("reason"))
    return {
        "status": result.get("status", "unknown"),
        "session_id": session_id,
        "observations": len(rows),
        "recovered": recovered,
        "summary": summary,
        "write": result,
    }
