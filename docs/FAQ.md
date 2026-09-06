# Frequently asked questions

[Documentation](README.md) · [Architecture](../ARCHITECTURE.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Is a memory subscription required?

No. The vault and databases run locally, and language/embedding models are optional.
Your chosen AI clients or remote endpoints may have separate costs.

## Do I need Obsidian?

No. A writable Markdown folder is enough. Obsidian is a convenient way to read and
organize the accepted memories.

## Can Codex read a preference written by Claude?

Yes, when both clients use the same vault and have access through the memory server.
Writer identity records provenance; it does not restrict a preference to that writer.

## Will switching tools restore my entire conversation?

Not today. Clients can retrieve stored memories and session summaries. Automatic
periodic saves and startup handoff are the [first-priority plan](automatic-session-continuity.md),
not implemented runtime behavior. The design transfers useful task state, not a
guaranteed verbatim replay of everything said.

## Do vectors make handoff automatic?

No. Vectors can help find related stored text. They do not capture missing events,
schedule a save or inject context into a new client.

## How much does this save in tokens?

No cross-tool saving percentage has been demonstrated. The required
[paired benchmark](session-handoff-benchmark.md) compares matched Claude/Codex tasks
with context passing enabled and disabled, including overhead and task quality.

## Is review mode always the default?

The connection helpers select review. A directly started MCP server falls back to auto
if its mode is missing or invalid. Configure it explicitly. Administrative CLI writes
are not governed by MCP review mode; see [configuration](CONFIGURATION.md).

## Are duplicate-looking entries automatically merged?

No automatic semantic merge is intended. Identity audits flag candidates and linking
requires an explicit action. Write-time duplicate suppression exists, including an
open cross-project session defect. Similar titles alone do not prove identical facts.

## Can I delete SQLite and rebuild everything?

No. Accepted-memory search rows are rebuildable. Pending review payloads and
unsummarized observations are not reconstructible from accepted Markdown.
See [backup and recovery](USAGE.md#undo-and-backup).

## Is everything private because it is local?

Local storage is not encryption. Connected AI clients receive whatever memories they
retrieve, and configured model endpoints receive content sent to them. Choose endpoints
and clients deliberately; secret checks cannot recognize every sensitive string.

## Are session summaries automatically posted to GitHub?

No. Sanitized automatic publication is planned after local continuity. It will require
a configured destination and explicit export permission. Raw transcripts are not the
default export.

## Why are issues formatted differently from these guides?

Guides help someone understand and operate the project. Issues and roadmaps retain the
prescribed seven-section engineering format. Historical fix/release records are retained
rather than rewritten as current capability claims.
