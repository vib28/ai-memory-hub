# Local Memory v1 implementation plan

This is the tracked implementation plan for the `enhancements/roadmap` branch. The
private working copy may contain additional notes, but this document is the source of
truth for the public repository roadmap.

## Goal

Add automatic, local-first session capture and token-efficient retrieval without a
persistent cloud-memory subscription, while preserving AI Memory Hub's governed write
path and human-readable Obsidian vault.

## Design principles

- Obsidian Markdown remains the canonical source of truth.
- SQLite indexes and capture buffers are disposable and rebuildable.
- Hooks never write directly to the vault.
- New memory reaches the vault through the existing MCP/session-write policy.
- Review and auto modes are both supported; review is the safe default.
- Raw tool output is evidence, not durable memory.
- Local models are optional. FTS search and deterministic fallback must continue to work.
- Automatic writes remain disabled until undo and hook uninstall support are complete.

## Current state

### Complete on `enhancements/roadmap`

- Generic `ai-memory-hook` stdin receiver.
- Crash-safe local SQLite observation buffer outside the vault.
- Idempotent observation IDs and bounded payload sizes.
- Local SLM consolidation through the existing four-section session contract.
- Deterministic consolidation fallback when no local model is configured.
- `session_consolidate(session_id)` MCP tool.
- Review and auto write-mode propagation.
- Optional local OpenAI-compatible embeddings.
- Hybrid semantic plus SQLite FTS search with FTS fallback.
- Normalized lifecycle events in the local observation buffer with additive SQLite migration.
- Embeddings are treated as optional duplicate-candidate and retrieval support; changing
  the embedding model does not replace stable project identity, canonical routing, or
  human-reviewed merge rules ([#27](https://github.com/vib28/ai-memory-hub/issues/27),
  [#33](https://github.com/vib28/ai-memory-hub/issues/33)).
- Stable project identity routing, read-only duplicate/split auditing, and reversible
  explicit project linking with source backups.
- Identity generalized from project-only to every file-per-subject kind (topic, decision,
  person), and a separate registry mechanism (`entity-aliases.md`) added for the two
  shared-file kinds (preference, profile) that cannot carry per-file identity metadata;
  dashboard grouping and `conflicts()`/`resolve_conflict()` both resolve through it
  ([#34](https://github.com/vib28/ai-memory-hub/issues/34),
  [#35](https://github.com/vib28/ai-memory-hub/issues/35)).
- The identity-less prefix-merge fallback removed entirely: a project (or now
  topic/decision/person) write that omits `entity_id` never uses fuzzy or prefix matching
  to select an existing file ([#37](https://github.com/vib28/ai-memory-hub/issues/37)).
- Rejected `session_write`/`propose_pattern_match` calls now surface their reason to the
  caller; a plain `ValueError` was silently discarded by the MCP SDK's crash-handling path,
  reaching the caller as a bare `Error executing tool <name>` with no reason
  ([#36](https://github.com/vib28/ai-memory-hub/issues/36)).
- Generic hook install/removal wired into the default connection script for Claude Code:
  `connect-ai-tools.ps1 -InstallHooks` / `-RemoveHooks`, idempotent, with a timestamped
  backup before each write ([#29](https://github.com/vib28/ai-memory-hub/issues/29)).
- Documentation and tests for the above paths.

### In progress

- Client-specific lifecycle-hook adapters for clients beyond Claude Code.
- Session-start and per-turn context priming.
- End-to-end host-client adapters.
- The write-path optimization is now optional: when a complete embedding index exists,
  `_best_match()` narrows comparisons to bounded cosine candidates; missing, incomplete,
  or failed embeddings use the conservative lexical fallback ([#27](https://github.com/vib28/ai-memory-hub/issues/27)).

### Safety gate — complete

- Opt-in vault Git initialization and status inspection.
- Disposable index, WAL/SHM, lock, and temporary-file ignores.
- Session-ID commit support for successful automated consolidation.
- Provider-neutral JSON hook installation/removal with timestamped backups and managed-entry
  preservation, **now wired into the default connection script** for Claude Code
  (`-InstallHooks`/`-RemoveHooks`) — this was the missing piece that kept #29 open.

Automated commits refuse to mix with pre-staged user changes.

[#29](https://github.com/vib28/ai-memory-hub/issues/29) is closed: this safety gate is
cleared. What still gates automatic capture shipping *by default* is client-specific
adapter coverage (#14) and the write-path benchmark (#27), not this gate.

### Not yet implemented

- Confidence and importance scoring.
- Graph-aware retrieval and reranking.
- Full token-savings benchmark.
- Automatic hook enablement in the default installer.
- A migration/backfill that scans `subject_audit()` candidates and proposes
  `entity_alias_link()`/`project_link()` calls automatically — linking stays a one-at-a-time,
  human-reviewed action by design.

## Safety gates

Automatic capture must follow this order:

1. Complete vault integrity and deletion guarantees.
2. Complete hook installation, uninstall, and backup behavior.
3. Add opt-in vault Git initialization and consolidation commits.
4. Verify crash-safe buffering and retry behavior.
5. Enable local SLM consolidation through `session_write`.
6. Keep new capture in review mode until benchmark and review results are trusted.
7. Only then offer auto mode as an explicit configuration choice.

The hook receiver may be installed and tested before these gates are complete, but the
default connection script must not silently enable automatic vault writes.

## Architecture

```text
AI lifecycle hook
        |
        v
local observation SQLite buffer
        |
        v
local SLM or deterministic fallback
        |
        v
session_consolidate MCP tool
        |
        v
validation + secret rejection + deduplication + review/auto policy
        |
        v
Obsidian Markdown vault + disposable SQLite index
        |
        +--> FTS5 keyword search
        +--> optional local Nomic-compatible vectors
        +--> future context priming
```

## Workstream 1: generic capture

The generic receiver accepts one observation, a list, or an `observations` array on
stdin. It stores bounded fields such as session ID, project, working directory, tool,
files, summaries, Git commit, timestamp, and source.

Required behavior:

- malformed input never blocks the host tool;
- repeated observation IDs are idempotent;
- local-model and MCP failures leave observations retryable;
- raw observations remain outside the vault;
- no hook imports or calls `MemoryManager` directly.

## Workstream 2: local consolidation

The consolidator creates:

- Investigated
- Learned
- Completed
- Next Steps

The local SLM must return conservative JSON, omit secrets and temporary noise, and avoid
inventing completion claims. If no model is configured, the deterministic fallback uses
files, tools, and bounded output summaries. Every result enters through `session_write`
policy and is marked complete only after a stored, queued, or duplicate result.

## Workstream 3: retrieval

SQLite FTS5 remains the explainable baseline. Optional local embeddings index compact
summaries and durable memories, not every raw tool call. Hybrid ranking combines:

- lexical match;
- vector similarity;
- project/path match;
- recency;
- future confidence and importance scores.

If the embedding endpoint is missing or fails, search automatically returns to FTS/LIKE
behavior.

## Workstream 4: confidence and importance

Add explicit metadata only after capture and retrieval are stable:

- confidence: how strongly the evidence supports the memory;
- importance: how useful the memory is likely to be later;
- freshness: when the source was last confirmed;
- provenance: session, files, Git commit, and writer.

Scores must influence ranking and review priority, not bypass validation or user control.

## Workstream 5: context priming

Add optional session-start and per-turn context priming after retrieval evaluation. Inject
only a compact index and the few selected memories relevant to the current project. Do
not inject the entire vault. Large file-read hints must be cheaper than the full read they
replace.

## Evaluation

Benchmark at least:

- small and large projects;
- repeated file reads;
- noisy debugging sessions;
- multiple projects in one agent history;
- secrets and temporary failures;
- duplicate retries after interrupted writes.

Record:

- baseline versus optimized injected tokens;
- compression size and latency;
- retrieval precision at top 3 and top 10;
- stale-memory and false-memory rates;
- local model and embedding failure recovery.

Do not claim a fixed percentage saving until these measurements exist.

## Final documentation action item

- [x] Rewrite every **open** GitHub issue and every roadmap entry in clear layman language
  with explicit **where**, **why**, **how**, reproduction steps, acceptance criteria,
  implementation details, and verification results, not inferring missing evidence.
  Applied to #13, #14, #15, #16, #17, #18, #27, #28, #29, #33, #34, #35, #36, #37 and the
  #13 roadmap body itself.
- [ ] Extend the same treatment to **closed** issues from the original bug-fix pass
  (#2–#12, #19–#26, #30, #31, #32) — not yet done; those issues predate this
  documentation standard and were closed under the previous format.

## Issue mapping

- #13 — parent roadmap and closeout
- #14 — generic lifecycle hooks and local observation buffering
- #15 — local session consolidation and verification
- #17 — client prompts and integration documentation
- #27 — optional local embeddings and hybrid memory search; the write-path duplicate scan
  and its benchmark are the part still open
- #29 — vault undo plus hook install/uninstall safety gate — **closed**;
  `-InstallHooks`/`-RemoveHooks` wired into `connect-ai-tools.ps1` for Claude Code
- #32 — normalized resilient lifecycle events without an HTTP hook dependency — closed
- #33 — stable project identity, read-only audit, and reversible linking — closed
- #34 — subject-sprawl audit generalized from project-only to every memory kind — closed
- #35 — the same identity model extended to shared-file kinds (preference, profile) via a
  small alias registry, plus dashboard grouping through it — closed
- #36 — preserve rejection reasons across the MCP tool boundary — closed
- #37 — prevent identity-less project prefix merges — closed

Pattern issues #16, #28, and #18 are implemented as a separate parallel track and are all
closed. They do not block the core local capture pipeline. Pattern configuration is
validated through a supported loader, historical backfill supports dry-run and idempotent
review-safe writes, and the backfill client uses the public MCP proposal boundary. Project
writes without an explicit `entity_id` no longer use prefix-based routing, and MCP
rejection reasons remain visible to callers.

Five issues remain open: #13, #14, #15, #17, #27 — see [README.md's roadmap
table](../README.md#roadmap-and-planning) for what specifically blocks each, and [roadmap
#13](https://github.com/vib28/ai-memory-hub/issues/13) for the recommended fix order and
its rationale.
