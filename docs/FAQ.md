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

Not the entire conversation. Clients can retrieve stored memories and session summaries;
the optional worker and supported Claude/Codex startup handoff restore bounded useful
task state after explicit setup. The design does not promise verbatim replay of everything
said or startup automation for unsupported clients.

## Do vectors make handoff automatic?

No. Vectors can help find related stored text. They do not capture missing events,
schedule a save or inject context into a new client.

## How much does this save in tokens?

No provider-backed cross-tool saving percentage has been demonstrated. The required
[paired benchmark](session-handoff-benchmark.md) compares matched Claude/Codex tasks
with context passing enabled and disabled, including overhead and task quality. A
no-paid-call deterministic replay is available in the [versioned report](benchmark-results/handoff-replay-v1.md);
its estimates are regression evidence, not a billing or universal-savings claim.

## Why are the embedding and chat models separate?

They solve different problems. The embedding model turns text into vectors for search
and related-memory ranking; it does not write human-readable memory. The local chat
model consolidates captured evidence into the four session sections and extracts
durable candidates. Either role can be unavailable: keyword search and deterministic
evidence-only checkpointing continue. A full verbatim transcript is a separate
default-off local feature and does not require an embedding model; see
[full-session-transcripts](full-session-transcripts.md).

## What is checkpoint metadata?

Checkpoint metadata is the machine-readable identity and navigation around a session
block: work-group ID, checkpoint ID, sequence, entry type, source/host session IDs,
project, worktree, changed files, evidence bounds, token basis, state and previous/next/
final links. It lets retries be idempotent and lets a later client select the right
project-scoped evidence without treating a checkpoint as a full transcript. The
human-readable four sections remain in Markdown beside that metadata. If exact
supported provider events are required, enable the separate opt-in transcript
companion; the transcript links to the summary and remains excluded from ordinary
retrieval and GitHub export.

## How do I enable a full session transcript?

Set `MEMORY_TRANSCRIPT_ENABLED=true` plus the intended `AI_MEMORY_VAULT` before
starting the hook receiver and worker, then restart those processes. Review the
sensitivity warning and the local retention/deletion rules in
[full-session-transcripts](full-session-transcripts.md) first. The default remains
off, and a provider can only record events it actually emits.

## Is review mode always the default?

The connection helpers select review. A directly started MCP server falls back to auto
if its mode is missing or invalid. Configure it explicitly. Administrative CLI writes
are not governed by MCP review mode; see [configuration](CONFIGURATION.md).

## Are duplicate-looking entries automatically merged?

No automatic semantic merge is intended. Identity audits flag candidates and linking
requires an explicit action. Exact duplicates are suppressed; close matches become
reviewable updates. Embeddings are advisory and cannot delete a memory. Identical
session summaries in distinct projects remain separate.

## Can I delete SQLite and rebuild everything?

No. Accepted-memory search rows are rebuildable. Pending review payloads and
unsummarized observations are not reconstructible from accepted Markdown.
See [backup and recovery](USAGE.md#undo-and-backup).

## Is everything private because it is local?

Local storage is not encryption. Connected AI clients receive whatever memories they
retrieve, and configured model endpoints receive content sent to them. Choose endpoints
and clients deliberately; secret checks cannot recognize every sensitive string.

## Are session summaries automatically posted to GitHub?

Yes, after explicit `-EnableGitHubExport` destination/visibility approval. The local
outbox publishes accepted sanitized checkpoint/final summaries, not raw transcripts,
pending review proposals or private paths. GitHub is optional and is not required for
local handoff.

## Why are issues formatted differently from these guides?

Guides help someone understand and operate the project. Issues and roadmaps retain the
prescribed seven-section engineering format. Historical fix/release records are retained
rather than rewritten as current capability claims.
