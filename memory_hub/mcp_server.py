from __future__ import annotations

import os
from pathlib import Path

from mcp.server import MCPServer

from .manager import AUTO_POLICY, MemoryManager
from .models import MemoryCandidate
from .capture import ObservationBuffer, default_buffer_path
from .session_capture import consolidate_buffered_session
from .history import commit_vault_change

VAULT = os.environ.get("AI_MEMORY_VAULT") or str(Path.cwd() / "memory-vault")
WRITER = os.environ.get("MEMORY_WRITER", "other").strip().lower()
WRITE_MODE = os.environ.get("MEMORY_WRITE_MODE", "auto").strip().lower()
HISTORY_ENABLED = os.environ.get("MEMORY_VAULT_HISTORY", "false").strip().lower() in {"1", "true", "yes", "on"}
if WRITE_MODE not in {"auto", "review"}:
    WRITE_MODE = "auto"

manager = MemoryManager(VAULT)

mcp = MCPServer(
    "AI Memory Hub",
    instructions=(
        "This server is the canonical persistent-memory interface. "
        "Search memory only when personal context is materially relevant. "
        "Automatically propose high-confidence durable memories according to memory_policy. "
        "Do not store transient facts, generated content, secrets, or sensitive inferred attributes."
    ),
)

@mcp.tool()
def memory_policy() -> str:
    """Return the automatic persistent-memory retention policy and active write mode."""
    return AUTO_POLICY + f"\n\nCurrent write mode: {WRITE_MODE}"

@mcp.tool()
def memory_search(query: str, limit: int = 10) -> list[dict]:
    """Search persistent memory. Prefer this before opening files."""
    return manager.search(query, limit)

@mcp.tool()
def memory_read(path: str) -> str:
    """Read exactly one memory Markdown file. Path must be inside the vault."""
    return manager.read(path)

@mcp.tool()
def memory_propose(
    text: str,
    kind: str,
    tag: str,
    subject: str = "general",
    target_path: str | None = None,
    entity_id: str | None = None,
) -> dict:
    """Validate a durable memory candidate. Auto mode stores it; review mode queues it."""
    candidate = MemoryCandidate(
        text=text, kind=kind, tag=tag, subject=subject,
        writer=WRITER, target_path=target_path, entity_id=entity_id,
    )
    if WRITE_MODE == "review":
        return manager.queue(candidate)
    return manager.propose(candidate)

@mcp.tool()
def memory_supersede(
    old_memory_id: str,
    text: str,
    kind: str,
    tag: str,
    subject: str = "general",
    target_path: str | None = None,
    entity_id: str | None = None,
) -> dict:
    """Supersede an old memory. In review mode the replacement is queued for approval."""
    candidate = MemoryCandidate(
        text=text, kind=kind, tag=tag, subject=subject,
        writer=WRITER, target_path=target_path, supersedes_id=old_memory_id,
        entity_id=entity_id,
    )
    if WRITE_MODE == "review":
        return manager.queue(candidate)
    return manager.propose(candidate)

@mcp.tool()
def memory_forget(memory_id: str) -> dict:
    """Delete one persistent memory by its stable memory ID."""
    return manager.forget(memory_id)

@mcp.tool()
def memory_audit() -> dict:
    """Check file/index integrity without modifying memory."""
    return manager.audit()

@mcp.tool()
def project_audit() -> dict:
    """Report project identity collisions and duplicate candidates without changing memory."""
    return manager.project_audit()

@mcp.tool()
def memory_reindex() -> dict:
    """Rebuild the disposable SQLite search index from the Markdown vault."""
    return {"indexed": manager.reindex()}

@mcp.tool()
def session_write(
    title: str, investigated: list[str], learned: list[str], completed: list[str],
    next_steps: list[str], project: str | None = None, session_date: str | None = None,
) -> dict:
    """Write a four-section session summary for the current client/model."""
    result = manager.propose_session({
        "model": WRITER, "title": title, "date": session_date,
        "project": project, "investigated": investigated, "learned": learned,
        "completed": completed, "next_steps": next_steps,
    }, write_mode=WRITE_MODE)
    # MCP transports can return a successful tool call even when the
    # application-level operation was rejected. Surface that distinction to
    # callers so they cannot mistake a rejected write for persisted memory.
    if result.get("status") == "rejected":
        raise ValueError(f"session write rejected: {result.get('reason', 'unknown reason')}")
    return result

@mcp.tool()
def session_consolidate(session_id: str) -> dict:
    """Consolidate local hook observations and submit them through session_write policy."""
    buffer = ObservationBuffer(os.environ.get("MEMORY_CAPTURE_DB") or default_buffer_path())
    try:
        result = consolidate_buffered_session(
            buffer, manager, session_id, writer=WRITER, write_mode=WRITE_MODE,
        )
        if HISTORY_ENABLED and result.get("status") in {"stored", "stored_without_project_link"}:
            written = result.get("write", {})
            paths = []
            if written.get("memory", {}).get("path"):
                paths.append(written["memory"]["path"])
            if written.get("project", {}).get("memory", {}).get("path"):
                paths.append(written["project"]["memory"]["path"])
            result["history"] = commit_vault_change(VAULT, session_id, paths)
        else:
            result["history"] = {"status": "disabled"}
        return result
    finally:
        buffer.close()

@mcp.tool()
def propose_pattern_match(
    pattern_id: str, project_fact_text: str, preference_rule_text: str, subject: str,
) -> dict:
    """Propose the linked project fact and global preference rule for a recognized pattern."""
    result = manager.propose_pattern_match(pattern_id, project_fact_text, preference_rule_text,
                                           subject, write_mode=WRITE_MODE, writer=WRITER)
    # Same contract as session_write: a rejected pattern must not reach the caller
    # looking like a successful tool call.
    if result.get("status") == "rejected":
        half = f" ({result['half']} half)" if result.get("half") else ""
        raise ValueError(
            f"pattern match rejected{half}: {result.get('reason', 'unknown reason')}")
    return result

def main():
    mcp.run()

if __name__ == "__main__":
    main()
