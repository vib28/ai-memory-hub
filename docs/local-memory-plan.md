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
- Documentation and tests for the above paths.

### In progress

- Client-specific lifecycle-hook adapters and installation/removal wiring.
- Normalize resilient lifecycle events using the external reference project's useful
  patterns—event naming, fail-open behavior, bounded delivery, and retry awareness—
  while keeping AI Memory Hub's local SQLite buffer and avoiding a required HTTP server
  dependency ([#32](https://github.com/vib28/ai-memory-hub/issues/32)).
- Session-start and per-turn context priming.
- End-to-end host-client adapters.

### Safety gate now implemented

- Opt-in vault Git initialization and status inspection.
- Disposable index, WAL/SHM, lock, and temporary-file ignores.
- Session-ID commit support for successful automated consolidation.
- Provider-neutral JSON hook installation/removal with timestamped backups and managed-entry preservation.

Automated commits refuse to mix with pre-staged user changes.

Hook installation/uninstallation and end-to-end verification remain before automatic
capture is enabled by default.

### Not yet implemented

- Confidence and importance scoring.
- Graph-aware retrieval and reranking.
- Full token-savings benchmark.
- Automatic hook enablement in the default installer.

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

- [ ] Rewrite every GitHub issue, including closed issues, and every roadmap entry in
  clear layman language with explicit **where**, **why**, **how**, reproduction steps,
  acceptance criteria, implementation details, and verification results. Do not infer
  missing evidence; mark it as unavailable or ask for clarification. Complete this
  after the implementation work and testing are finished.

## Issue mapping

- #14 — generic lifecycle hooks and local observation buffering
- #15 — local session consolidation and verification
- #27 — optional local embeddings and hybrid memory search
- #29 — vault undo plus hook install/uninstall safety gate
- #32 — normalized resilient lifecycle events without an HTTP hook dependency
- #17 — client prompts and integration documentation
- #13 — parent roadmap and closeout

Pattern issues #16, #18, and #28 remain separate work and do not block the core local
capture pipeline except where they depend on the established MCP write boundary.
