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
client -> project_audit / subject_audit / project_link / entity_alias_link
```

| Public MCP tool | Internal method it wraps |
|---|---|
| `memory_propose`, `memory_supersede` | `MemoryManager.propose()` / `.queue()` |
| `session_write` | `MemoryManager.propose_session()` |
| `propose_pattern_match` | `MemoryManager.propose_pattern_match()` |
| `memory_forget`, `memory_search`, `memory_read`, `memory_audit`, `memory_reindex` | corresponding manager methods |
| `project_audit`, `subject_audit` | read-only; never call `queue()`/`propose()` |
| `project_link`, `entity_alias_link` | explicit, reviewed merges — never invoked from write-time validation |

`MemoryManager` methods remain importable **inside the Python package** — the MCP server
calls them, and the test suite exercises them directly. What must not happen is a
client-facing script proposing memory in-process: that is how #19 bypassed the configured
write mode, writing to the vault under `MEMORY_WRITE_MODE=review`.

The line is *proposing new memory*, not *touching the vault*. `scripts/migrate_session_routing.py`
relocates blocks that are already stored and proposes nothing, so it may use `Vault`
directly. `scripts/backfill_patterns.py` proposes new preference rules and therefore may
not; #28 fixed the one place it did, and `tests/test_mcp_server.py::McpBoundaryTests`
now asserts the rule with no exemption — `backfill_patterns.py` submits through the
public MCP workflow (`--dry-run` included) rather than driving `MemoryManager` in-process.

## Write mode is never bypassed (#19)

`MEMORY_WRITE_MODE` is `auto` or `review`, read once at server start.

Under `review`, every write path returns `status: queued` and touches nothing in the
vault until approved. There is no source-based exemption: a fact arriving from a hook is
subject to the same policy as one a model proposes. If unattended operation is wanted, it
is a separate configured mode with its own variable.

## Application-level rejections are surfaced (#12, #23, #36)

An MCP transport can return a successful tool call while the operation underneath was
rejected. Both writing tools therefore raise instead of returning a rejection quietly:
`session_write` since #12, `propose_pattern_match` since #23.

**Raise `mcp.server.mcpserver.exceptions.ToolError`, never a plain `ValueError` (#36).**
This is not a style preference. The SDK (`mcp` 2.x) treats any exception that is not
`ToolError`/`ResourceError`/`MCPError` as a crash: `Tool.run()` wraps it in
`UnexpectedToolError` and discards the original message, so the caller sees only
`Error executing tool <name>` with no reason. `ToolError` is the SDK's own "anticipated
failure" channel — its message survives the same wrapping intact. Confirmed against the
SDK source (`mcp/server/mcpserver/tools/base.py`) and reproduced live before the fix: a
rejected `session_write` call returned exactly that bare message, with the actual reason
(e.g. "memory is too long") visible only in server-side logs. Any new write tool that
raises on rejection must use `ToolError`, verified through `mcp.call_tool(...)`, not just
the bare function — a test that only calls the tool function directly cannot see this
class of regression, since the SDK's wrapping only happens on the real registered path.

There are six outcomes. Callers must distinguish them:

| Status | Written? | Caller action |
|---|---|---|
| `stored` | yes | done |
| `stored_without_project_link` | session yes, cross-link no | resolve via `project_link_supersedes` (#22) |
| `queued` | no, awaiting review | report queued |
| `queued_as_update` | no, `supersedes_id` pre-filled | report as update |
| `possible_update` | **no** | resolve via `supersede()` |
| `duplicate` | no, already present | no-op |
| `rejected` | no | raised as `ToolError`; keep the source data |

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
project-keyed. Project slugs reuse `Vault._entity_slug('projects', ...)` (renamed from
`_merge_into_existing_project` when #35 generalized it to every `FILE_PER_ENTITY_KINDS`
kind — see below), so sessions and `/projects/` agree on naming.

Existing vaults migrate with `scripts/migrate_session_routing.py --vault <path> --dry-run`
first; blocks naming no project stay where they are.

## Entity identity: explicit and never silently merged (#33, #35, #37)

Two mechanisms, chosen by whether the kind routes one file per subject or shares one file
across all of them (`vault.canonical_path`):

**`FILE_PER_ENTITY_KINDS = {"project", "topic", "decision", "person"}`** each get their own
file per subject, so identity lives in that file's own frontmatter (`id`, `aliases`).
`Vault._entity_slug(directory, subject_slug, entity_id)` resolves a write to an existing
file only by an explicit `entity_id` match or an already-recorded alias — **never** by
fuzzy or prefix similarity (#37: a caller that has not identified the entity must get a
separate subject-based file, not have its fact silently folded into whatever existing file
happens to share a prefix). `project_link()` merges two such files explicitly and
reversibly (a `.merged-<timestamp>` backup, never a delete); it is a preview-then-apply
operation, and applying it is the *only* thing that merges these files. Originally
project-only (#33), generalized to all four kinds by widening one type-check (#35) — the
merge logic itself needed no change, since it was never kind-specific beyond that check.

**`SHARED_FILE_KINDS = {"preference", "profile"}`** route every subject into one file
(`/preferences.md`, `/profile.md`), so there is no per-subject file to carry `id`/`aliases`.
Widening the same frontmatter mechanism to these kinds was considered and rejected: it
would give the entire file one entity id shared across every distinct concern living in
it. Identity for these two kinds instead lives in a separate, small registry file,
`entity-aliases.md` (`memory_hub/entities.py`, parsed the same deliberately
Markdown-fencing-naive way as `patterns.py`), consulted by `conflicts()`,
`resolve_conflict()`, and the dashboard's grouping to resolve one subject to another.
`entity_alias_link()` is the only way to add an entry, and it never merges, moves, or
deletes a memory entry — both subjects keep their own entries exactly where they are; only
grouping changes. A registry entry is reversible by hand-editing the file or, with vault
history enabled, by `git revert`.

**Both mechanisms share the same principle:** identity is resolved by an explicit,
human-reviewed action, never inferred from text similarity. `subject_audit()` is the
read-only detector for both — exact-duplicate and subject-variant candidates across every
kind — and never itself writes anything; `project_link()`/`entity_alias_link()` are the
only write paths, and both require an explicit call naming the two subjects, not a
threshold crossed automatically.

Do not add a fuzzy-matching fallback to either mechanism when a caller omits an identifier.
That fallback existed once for `project` (the pre-#37 behavior) and silently merged
`widget-app` and `widget-app-ui` writes that were never confirmed to be the same entity —
exactly the failure mode this whole section exists to prevent.

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

## Current implementation gates

Buffering, local consolidation, optional hybrid retrieval, history, hook configuration
helpers and historical import exist. They do not yet form a supervised automatic
checkpoint/handoff service. Current connection code installs only PostToolUse (AfterTool
for Gemini), and native payload/schema gaps remain (#52). Hook reinstall can remove
unrelated sibling handlers (#53). Queue pagination/claim safety (#54), cross-project
session deduplication (#55) and context scope/budget (#56) also need correction.

The first-priority next phase is [automatic session continuity](docs/automatic-session-continuity.md),
tracked by [#61](https://github.com/vib28/ai-memory-hub/issues/61): linked checkpoints and
final rollups (#57), a local worker (#58), automatic lifecycle/startup handoff (#59),
then optional sanitized GitHub publication (#60). No routine manual trigger is allowed.
One-time setup and separate persistence/export permissions remain explicit.

Capture evidence and pending proposals are durable operational data, not rebuildable
search indexes. A worker must preserve them across restarts, and claim work with leases
rather than treating every processing row as a crashed job. The local handoff packet
must remain usable without GitHub, embeddings, or MCP being ready at client startup.

Accepted memories still cross the public MCP write-policy boundary; the local packet
may expose pending operational evidence only with an explicit unreviewed label. Automatic
session saving does not authorize automatic merging or deleting durable preferences.

Required evaluation: [paired two-tool ON/OFF benchmark](docs/session-handoff-benchmark.md)
(#62), counting total workflow overhead and task quality, not just packet length.

Confidence and importance scores are planned ranking metadata. They may prioritize review
and retrieval, but they must never bypass validation, secret rejection, deduplication, or
the configured write mode.

## Opt-in vault history

Automated consolidation may commit only the Markdown files it changed, and only when
`MEMORY_VAULT_HISTORY=true` is set for the MCP server. The user must first run
`history-init` for the vault. Initialization is idempotent, sets a local Git identity,
and adds disposable SQLite, lock, and temporary artifacts to `.gitignore`.

History commits happen after the vault write and outside the vault file lock. A commit
failure is surfaced in the consolidation result rather than silently reported as a clean
history update. If the vault already has staged changes, the automated commit refuses to
mix them with the session commit. Review-mode queueing does not create a history commit
because no vault content has changed.
