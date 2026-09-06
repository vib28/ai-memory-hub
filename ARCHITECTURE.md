# Architecture and boundaries

Decisions that constrain how AI Memory Hub may be extended. Each names the issue that
settled it.

## Public MCP tools vs. internal manager methods (#21)

Clients — connected models, hook scripts, migration utilities — reach the vault through
**public MCP tools only**:

```
client -> session_write            -> MemoryManager.propose_session()
client -> propose_pattern_match    -> MemoryManager.propose_pattern_match()
client -> memory_propose / _supersede / _forget / _search / _read / _audit / _reindex
```

| Public MCP tool | Internal method it wraps |
|---|---|
| `memory_propose`, `memory_supersede` | `MemoryManager.propose()` / `.queue()` |
| `session_write` | `MemoryManager.propose_session()` |
| `propose_pattern_match` | `MemoryManager.propose_pattern_match()` |
| `memory_forget`, `memory_search`, `memory_read`, `memory_audit`, `memory_reindex` | corresponding manager methods |

`MemoryManager` methods remain importable **inside the Python package** — the MCP server
calls them, and the test suite exercises them directly. What must not happen is a
client-facing script proposing memory in-process: that is how #19 bypassed the configured
write mode, writing to the vault under `MEMORY_WRITE_MODE=review`.

The line is *proposing new memory*, not *touching the vault*. `scripts/migrate_session_routing.py`
relocates blocks that are already stored and proposes nothing, so it may use `Vault`
directly. `scripts/backfill_patterns.py` proposes new preference rules and therefore may
not — it currently does, tracked in #28, and `tests/test_mcp_server.py::McpBoundaryTests`
asserts the rule with that one known violation marked expected-failure.

## Write mode is never bypassed (#19)

`MEMORY_WRITE_MODE` is `auto` or `review`, read once at server start.

Under `review`, every write path returns `status: queued` and touches nothing in the
vault until approved. There is no source-based exemption: a fact arriving from a hook is
subject to the same policy as one a model proposes. If unattended operation is wanted, it
is a separate configured mode with its own variable.

## Application-level rejections are surfaced (#12, #23)

An MCP transport can return a successful tool call while the operation underneath was
rejected. Both writing tools therefore raise instead of returning a rejection quietly:
`session_write` since #12, `propose_pattern_match` since #23.

There are six outcomes. Callers must distinguish them:

| Status | Written? | Caller action |
|---|---|---|
| `stored` | yes | done |
| `stored_without_project_link` | session yes, cross-link no | resolve via `project_link_supersedes` (#22) |
| `queued` | no, awaiting review | report queued |
| `queued_as_update` | no, `supersedes_id` pre-filled | report as update |
| `possible_update` | **no** | resolve via `supersede()` |
| `duplicate` | no, already present | no-op |
| `rejected` | no | raised as `ValueError`; keep the source data |

`possible_update` is the trap: neither an error nor a write.

## Pattern writes are atomic (#23)

A pattern is its two linked halves — a project fact and a global preference rule. Both are
validated before either is written, so a failure cannot leave an orphaned fact whose rule
never existed. The preference half always targets global `preferences.md`.

## Session routing is project-major (#26)

```
/sessions/<project>/<model>.md     session naming a project
/sessions/<model>.md               session naming no project
```

Hook capture is per-working-directory. A writer-major layout would grow one unbounded file
per agent spanning every project the agent ever touched, and #16's pattern work is already
project-keyed. Project slugs reuse `Vault._merge_into_existing_project`, so sessions and
`/projects/` agree on naming.

Existing vaults migrate with `scripts/migrate_session_routing.py --vault <path> --dry-run`
first; blocks naming no project stay where they are.

## Capture transport (#30)

Hook capture reaches the vault through `session_write`. Superseded alternatives, recorded
so they are not rediscovered:

| Rejected | Why |
|---|---|
| HTTP `POST /ingest` endpoint | Bypasses the MCP boundary (#21) and the write policy (#19) |
| Fire-and-forget POST with no status handling | Cannot honor review mode or report the six outcomes |
| Raw `{type, context, metadata}` observations | Observations are not memories and have no vault kind |

Observations are buffered **outside** the vault and consolidated into the four-section
session contract before any write. Compression runs locally with no credentials; the
engine choice is settled inside #14.

## Generic observation capture

The first capture boundary is provider-neutral. A client lifecycle hook may send a JSON
observation to `ai-memory-hook` over stdin. The receiver validates and bounds the payload,
then stores it in a local SQLite buffer outside the Obsidian vault.

The receiver is deliberately not a memory writer:

```text
client hook -> ai-memory-hook -> local observation SQLite
                         (later)
local SLM -> session_write MCP tool -> validation/review -> vault
```

The buffer is crash-safe and idempotent by `observation_id`. Duplicate retries do not
replace the original observation. Hook failures return a structured rejection and exit
successfully so a host AI tool is never blocked by memory capture. Raw observations are
bounded and are not durable vault content until a later consolidation step creates the
existing four-section session contract.
