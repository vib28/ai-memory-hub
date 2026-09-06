# Frequently Asked Questions

## Does this require a cloud memory subscription?

No. The vault, index, capture buffer, and optional embeddings can all run locally. A local
Ollama- or LM Studio-compatible model is optional.

## Which AI tools are supported?

Any client that can call the MCP server can use the shared memory layer. Prompt templates
for common clients are in [`client-prompts/`](../client-prompts/).

## Where is the canonical data stored?

In ordinary Markdown files inside your Obsidian vault. SQLite is a disposable search index,
not the source of truth.

## Why does review mode exist?

It prevents an AI client from writing directly to the vault without your approval. It is the
recommended starting mode and is especially useful when multiple AI clients share one vault.

## Does the system automatically delete duplicate memories?

No. Exact duplicates are blocked, and likely updates are routed for review. Merging,
superseding, or deleting existing memories requires an explicit action.

## Why do project entries need an `entity_id`?

Different clients may use different names for the same project. An explicit `entity_id`
provides a stable identity. If it is omitted, similar names remain separate rather than
being silently merged.

## What happens if SQLite is damaged?

The index can be rebuilt from the Markdown vault:

```powershell
python -m memory_hub.cli --vault "<vault>" reindex
```

## Are hooks enabled automatically?

No. Hook installation and automatic vault writes are opt-in safety decisions. Read
[`ARCHITECTURE.md`](../ARCHITECTURE.md) before enabling them.

## Where are bugs and future work tracked?

GitHub issues and roadmap entries use a separate structured format for implementation
tracking. The user-facing documentation format in this directory does not replace those
engineering records.
