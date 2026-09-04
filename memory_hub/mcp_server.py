from __future__ import annotations

import os
from pathlib import Path

from mcp.server import MCPServer

from .manager import AUTO_POLICY, MemoryManager
from .models import MemoryCandidate

VAULT = os.environ.get("AI_MEMORY_VAULT") or str(Path.cwd() / "memory-vault")
WRITER = os.environ.get("MEMORY_WRITER", "other").strip().lower()
WRITE_MODE = os.environ.get("MEMORY_WRITE_MODE", "auto").strip().lower()
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
) -> dict:
    """Validate a durable memory candidate. Auto mode stores it; review mode queues it."""
    candidate = MemoryCandidate(
        text=text, kind=kind, tag=tag, subject=subject,
        writer=WRITER, target_path=target_path,
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
) -> dict:
    """Supersede an old memory. In review mode the replacement is queued for approval."""
    candidate = MemoryCandidate(
        text=text, kind=kind, tag=tag, subject=subject,
        writer=WRITER, target_path=target_path, supersedes_id=old_memory_id,
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
def memory_reindex() -> dict:
    """Rebuild the disposable SQLite search index from the Markdown vault."""
    return {"indexed": manager.reindex()}

def main():
    mcp.run()

if __name__ == "__main__":
    main()
