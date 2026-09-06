# AI Memory Hub v0.2

## New
- Local browser dashboard bound to 127.0.0.1
- Windows system-tray launcher
- Pending-memory review queue
- `MEMORY_WRITE_MODE=auto|review`
- Approve/reject proposed memories
- Edit stored memories while preserving stable IDs
- One-click forget
- Potential conflict detection by kind + subject
- One-click conflict resolution by superseding competing active entries
- Audit now reports pending items and potential conflicts
- Additional tests for dashboard/review workflows

## Validation
- 7 unit tests passed
- Python source tree compiled successfully

## Recommended first-run mode
Use `MEMORY_WRITE_MODE=review` initially, inspect what each AI tries to retain, then switch to `auto` once the retention behavior matches your preferences.
# Local Memory v1 work on `enhancements/roadmap`

The enhancement branch now contains the first local-memory slices:

- generic crash-safe observation buffering through `ai-memory-hook`;
- local SLM session consolidation with deterministic fallback;
- `session_consolidate` MCP integration that preserves review/auto policy;
- optional local embeddings and hybrid FTS/vector retrieval;
- tracked implementation plan at [`docs/local-memory-plan.md`](docs/local-memory-plan.md).

Automatic hook installation and vault undo remain safety gates before enabling automatic
vault writes by default. See issue [#29](https://github.com/vib28/ai-memory-hub/issues/29).
