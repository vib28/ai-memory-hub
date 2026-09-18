from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .app_config import bootstrap_environment
from .manager import AUTO_POLICY, MemoryManager
from .models import MemoryCandidate
from .capture import ObservationBuffer, default_buffer_path
from .session_capture import consolidate_buffered_session
from .history import commit_vault_change
from .utils import is_truthy

# ---------------------------------------------------------------------------
# Module-level constants (no side effects to compute).
# ---------------------------------------------------------------------------
VAULT = os.environ.get("AI_MEMORY_VAULT") or str(Path.cwd() / "memory-vault")

# ---------------------------------------------------------------------------
# Lazy runtime state.
#
# bootstrap_environment() mutates os.environ and MemoryManager() creates
# directories plus a SQLite index -- both are side effects that must not run
# at import time.  They are deferred to _ensure_init(), which is triggered on
# first use (tool call or attribute access).
#
# WRITER / WRITE_MODE / HISTORY_ENABLED start as None and are populated by
# _ensure_init().  Tests may patch them before first use; the init routine
# respects any pre-set value so patching works.
# ---------------------------------------------------------------------------
WRITER = None
WRITE_MODE = None
HISTORY_ENABLED = None

_state = SimpleNamespace(initialized=False, manager=None)


def _ensure_init() -> None:
    """Seed env from the vault config and build the MemoryManager.

    Best-effort and idempotent: the expensive work runs exactly once.  Every
    tool function calls this before touching the manager; ``__getattr__``
    triggers it for attribute access.
    """
    if _state.initialized:
        return
    _state.initialized = True

    bootstrap_environment(VAULT)

    # After bootstrap_environment seeds os.environ from config.json, read the
    # effective values.  bootstrap_environment uses setdefault semantics, so a
    # real env var still wins over the file.  Skip any value a test has already
    # patched in so the patch survives.
    if globals()["WRITER"] is None:
        globals()["WRITER"] = os.environ.get("MEMORY_WRITER", "other").strip().lower()
    if globals()["WRITE_MODE"] is None:
        mode = os.environ.get("MEMORY_WRITE_MODE", "auto").strip().lower()
        if mode not in {"auto", "review"}:
            mode = "auto"
        globals()["WRITE_MODE"] = mode
    if globals()["HISTORY_ENABLED"] is None:
        globals()["HISTORY_ENABLED"] = is_truthy(os.environ.get("MEMORY_VAULT_HISTORY", "false"))

    _state.manager = MemoryManager(VAULT)


def __getattr__(name: str):
    """Trigger lazy initialization when module attributes are accessed."""
    if name == "manager":
        _ensure_init()
        return _state.manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ---------------------------------------------------------------------------
# MCP server instance (lightweight -- no side effects).
# ---------------------------------------------------------------------------
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
    _ensure_init()
    return _state.manager.search(query, limit)


@mcp.tool()
def memory_context(project: str | None = None, query: str | None = None,
                   limit: int = 5, max_chars: int = 4000, cwd: str | None = None,
                   session_id: str | None = None) -> dict:
    """Return a small, bounded context packet for a new session or turn."""
    _ensure_init()
    return _state.manager.context_prime(project=project, query=query, limit=limit, max_chars=max_chars,
                                        cwd=cwd, session_id=session_id)


@mcp.tool()
def memory_read(path: str) -> str:
    """Read exactly one memory Markdown file. Path must be inside the vault."""
    _ensure_init()
    return _state.manager.read(path)


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
    _ensure_init()
    candidate = MemoryCandidate(
        text=text, kind=kind, tag=tag, subject=subject,
        writer=WRITER, target_path=target_path, entity_id=entity_id,
    )
    if WRITE_MODE == "review":
        return _state.manager.queue(candidate)
    return _state.manager.propose(candidate)


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
    _ensure_init()
    candidate = MemoryCandidate(
        text=text, kind=kind, tag=tag, subject=subject,
        writer=WRITER, target_path=target_path, supersedes_id=old_memory_id,
        entity_id=entity_id,
    )
    if WRITE_MODE == "review":
        return _state.manager.queue(candidate)
    return _state.manager.propose(candidate)


@mcp.tool()
def memory_forget(memory_id: str) -> dict:
    """Delete one persistent memory by its stable memory ID."""
    _ensure_init()
    return _state.manager.forget(memory_id)


@mcp.tool()
def memory_audit() -> dict:
    """Check file/index integrity without modifying memory."""
    _ensure_init()
    return _state.manager.audit()


@mcp.tool()
def project_audit() -> dict:
    """Report project identity collisions and duplicate candidates without changing memory."""
    _ensure_init()
    return _state.manager.project_audit()


@mcp.tool()
def project_link(source_path: str, target_path: str, apply: bool = False) -> dict:
    """Preview or explicitly apply a reversible project-file link."""
    _ensure_init()
    return _state.manager.project_link(source_path, target_path, apply=apply)


@mcp.tool()
def subject_audit(kinds: list[str] | None = None) -> dict:
    """Report exact duplicates and subject-variant candidates across memory kinds
    (project, preference, topic, decision, person, profile, session) without
    changing memory. Pass kinds to limit the scope; omit it to check everything."""
    _ensure_init()
    return _state.manager.subject_audit(kinds)


@mcp.tool()
def entity_alias_link(kind: str, source_subject: str, target_subject: str, apply: bool = False) -> dict:
    """Preview or apply linking two subjects of a shared-file kind (preference,
    profile) as one entity. Nothing is merged or deleted; both subjects keep
    their own memory entries. Use project_link instead for project/topic/
    decision/person, which each have their own file to merge."""
    _ensure_init()
    return _state.manager.entity_alias_link(kind, source_subject, target_subject, apply=apply)


@mcp.tool()
def memory_reindex() -> dict:
    """Rebuild the disposable SQLite search index from the Markdown vault."""
    _ensure_init()
    return {"indexed": _state.manager.reindex()}


@mcp.tool()
def session_write(
    title: str, investigated: list[str], learned: list[str], completed: list[str],
    next_steps: list[str], project: str | None = None, session_date: str | None = None,
    session_group_id: str | None = None, host_session_id: str | None = None,
    host_session_finalized: bool = False,
    checkpoint_id: str | None = None, sequence: int | None = None,
    entry_type: str | None = None, previous_id: str | None = None,
    final_id: str | None = None, source_client: str | None = None,
    worktree: str | None = None, evidence_start: str | None = None,
    evidence_end: str | None = None, token_count: int | None = None,
    token_basis: str | None = None, session_tags: list[str] | None = None,
) -> dict:
    """Write a four-section session summary for the current client/model."""
    _ensure_init()
    payload = {
        "model": WRITER, "title": title, "date": session_date,
        "project": project, "investigated": investigated, "learned": learned,
        "completed": completed, "next_steps": next_steps,
    }
    metadata = {
        "session_group_id": session_group_id, "host_session_id": host_session_id,
        "host_session_finalized": host_session_finalized,
        "checkpoint_id": checkpoint_id, "sequence": sequence, "entry_type": entry_type,
        "previous_id": previous_id, "final_id": final_id, "source_client": source_client,
        "worktree": worktree, "evidence_start": evidence_start, "evidence_end": evidence_end,
        "token_count": token_count, "token_basis": token_basis, "session_tags": session_tags,
    }
    payload.update({key: value for key, value in metadata.items() if value is not None})
    result = _state.manager.propose_session(payload, write_mode=WRITE_MODE)
    # MCP transports can return a successful tool call even when the
    # application-level operation was rejected. Surface that distinction to
    # callers so they cannot mistake a rejected write for persisted memory.
    # ToolError (not ValueError/RuntimeError) is required here: the SDK treats a
    # plain exception raised from a tool body as a crash and discards its message,
    # replacing it with a bare "Error executing tool <name>". ToolError is the
    # "anticipated failure" channel whose message reaches the caller intact (#36).
    if result.get("status") == "rejected":
        raise ToolError(f"session write rejected: {result.get('reason', 'unknown reason')}")
    return result


@mcp.tool()
def session_consolidate(session_id: str) -> dict:
    """Consolidate local hook observations and submit them through session_write policy."""
    _ensure_init()
    buffer = ObservationBuffer(os.environ.get("MEMORY_CAPTURE_DB") or default_buffer_path())
    try:
        result = consolidate_buffered_session(
            buffer, _state.manager, session_id, writer=WRITER, write_mode=WRITE_MODE,
        )
        if HISTORY_ENABLED and result.get("status") in {"stored", "stored_without_project_link"}:
            written = result.get("write") or {}
            paths = []
            if (written.get("memory") or {}).get("path"):
                paths.append(written["memory"]["path"])
            project = written.get("project") or {}
            if (project.get("memory") or {}).get("path"):
                paths.append(project["memory"]["path"])
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
    _ensure_init()
    result = _state.manager.propose_pattern_match(pattern_id, project_fact_text, preference_rule_text,
                                                  subject, write_mode=WRITE_MODE, writer=WRITER)
    # Same contract as session_write: a rejected pattern must not reach the caller
    # looking like a successful tool call. Must be ToolError, not ValueError — see
    # the comment on session_write's raise (#36).
    if result.get("status") == "rejected":
        half = f" ({result['half']} half)" if result.get("half") else ""
        raise ToolError(
            f"pattern match rejected{half}: {result.get('reason', 'unknown reason')}")
    return result


def main() -> None:
    """Entry point for the ``ai-memory-mcp`` console script."""
    _ensure_init()
    mcp.run()


if __name__ == "__main__":
    main()
