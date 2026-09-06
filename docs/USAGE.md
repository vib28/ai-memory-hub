# Usage

AI Memory Hub follows a simple loop:

```text
capture → validate → review or store → search → reuse
```

The Obsidian Markdown vault is the readable source of truth. SQLite indexes and local
capture buffers are disposable and can be rebuilt.

## Everyday use

Ask a connected AI client to remember a durable preference, project decision, or constraint.
In review mode, open the dashboard and approve or reject the proposal. Start a new AI
conversation and ask about the same topic to verify retrieval.

Session summaries use four sections:

- Investigated
- Learned
- Completed
- Next Steps

Keep the combined summary under 1500 characters. The client prompts in
[`client-prompts/`](../client-prompts/) contain the shared rules for each AI tool.

## Review and automatic modes

Review mode is the default recommendation:

```powershell
$env:MEMORY_WRITE_MODE = "review"
```

After reviewing the queue and confirming the vault is behaving correctly:

```powershell
$env:MEMORY_WRITE_MODE = "auto"
```

Always inspect the application-level result. A successful MCP transport call does not
necessarily mean the memory was stored.

## Search and audit

```powershell
python -m memory_hub.cli --vault "<vault>" search "project decision"
python -m memory_hub.cli --vault "<vault>" audit
python -m memory_hub.cli --vault "<vault>" reindex
python -m memory_hub.cli --vault "<vault>" project-audit
```

Search uses SQLite FTS5 and can optionally use local embeddings. The Markdown files remain
authoritative if the disposable index must be rebuilt.

## Project identity

Use an explicit `entity_id` when several names refer to the same project. Without one,
similar-looking project subjects remain separate; the system does not silently merge them.
Use `project-audit` to find possible name splits and `project-link` for an explicit,
reversible link.

## Pattern backfill

Historical pattern backfill is review-safe and supports a no-write preview:

```powershell
python scripts/backfill_patterns.py --vault "<vault>" --dry-run
python scripts/backfill_patterns.py --vault "<vault>"
```

The real run follows `MEMORY_WRITE_MODE`, and repeated runs skip already queued or stored
proposals.

If a consolidation process stops after claiming observations but before completing them,
the next consolidation run returns those `processing` rows to retryable state. A failed
model or write remains retryable and records its last error in the local buffer.

## Undo history

Vault history is opt-in:

```powershell
python -m memory_hub.cli --vault "<vault>" history-init
python -m memory_hub.cli --vault "<vault>" history-status
```

Automatic consolidation commits only the Markdown paths it changed and refuses to mix with
pre-staged user changes.

## More detailed references

- [`ARCHITECTURE.md`](../ARCHITECTURE.md) — boundaries, safety rules, and data flow
- [`local-memory-plan.md`](local-memory-plan.md) — implementation roadmap
- [`FIXLOG.md`](../FIXLOG.md) — verified bug fixes
- [`INSTALLATION_GUIDE.md`](../INSTALLATION_GUIDE.md) — complete setup walkthrough
