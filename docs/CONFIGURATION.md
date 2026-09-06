# Configuration

Set configuration on the process that uses it. Environment variables in one terminal
do not automatically update an already-running MCP server.

[Client setup](CLIENTS.md) · [Architecture](../ARCHITECTURE.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Server settings

| Variable | Purpose | Current default |
| --- | --- | --- |
| AI_MEMORY_VAULT | Absolute vault directory | MCP server: memory-vault under its working directory |
| MEMORY_WRITER | Provenance for the connected client | other |
| MEMORY_WRITE_MODE | MCP proposal policy: review or auto | auto; invalid values also fall back to auto |
| MEMORY_VAULT_HISTORY | Commit paths from successful MCP consolidation | false |
| MEMORY_CAPTURE_DB | Local observation database | User-home .ai-memory-hub/observations.sqlite3 |
| MEMORY_LLM_BASE_URL | Chat-completions endpoint base | Unset |
| MEMORY_LLM_MODEL | Consolidation/extraction model name | Unset |
| MEMORY_LLM_API_KEY | Optional transcript-extractor authorization | Unset; not used by the consolidator |
| MEMORY_EMBED_BASE_URL | Embeddings endpoint base | Unset, so embeddings are disabled |
| MEMORY_EMBED_MODEL | Embedding model name | nomic-embed-text |

See [mcp_server.py](../memory_hub/mcp_server.py),
[capture.py](../memory_hub/capture.py), [extractor.py](../memory_hub/extractor.py),
[consolidator.py](../memory_hub/consolidator.py) and [embeddings.py](../memory_hub/embeddings.py).

## Choose the write mode explicitly

~~~powershell
$env:AI_MEMORY_VAULT = Join-Path $env:USERPROFILE "Documents\Obsidian\AI-Memory"
$env:MEMORY_WRITER = "codex"
$env:MEMORY_WRITE_MODE = "review"
.\.venv\Scripts\python.exe -m memory_hub.mcp_server
~~~

This starts a stdio server waiting for an MCP client; it is not a web page.
Usually the host launches it using [registered configuration](CLIENTS.md).

Review queues proposals for approval. Auto attempts to store accepted proposals without
that approval step. Both retain validation and duplicate/update handling.

> [!WARNING]
> The administrative CLI's propose, supersede and ingest commands call manager methods
> directly and do not honor MCP review mode. Explicit deletion/linking and dashboard
> approval are also separate actions. Review is not a blanket prohibition on all writes.

Writer identities are chatgpt, claude, codex, gemini, kimi, qwen, cursor, hermes, user and
other. A writer identifies provenance, not which clients may read the memory.

## Optional local models

Set the exact model identifier exposed by your local server. For a server configured
with an OpenAI-compatible API under localhost port 1234:

~~~powershell
$env:MEMORY_LLM_BASE_URL = "http://127.0.0.1:1234/v1"
$env:MEMORY_LLM_MODEL = "<loaded-chat-model>"
$env:MEMORY_EMBED_BASE_URL = "http://127.0.0.1:1234/v1"
$env:MEMORY_EMBED_MODEL = "<loaded-embedding-model>"
~~~

The bracketed model names are placeholders, not commands to run unchanged. The code
adds /chat/completions or /embeddings to the base URL; do not include those suffixes twice.

Consolidation without a configured language model uses a deterministic fallback.
Transcript extraction requires a configured language model. Embeddings are optional;
search can use keyword matching alone.

These URLs are not restricted to loopback by the provider code. Choosing a remote
endpoint sends content there. Keep credentials out of example files and memory entries.

## Optional vault history

Initialize history on a dedicated vault before enabling consolidation commits:

~~~powershell
$memoryVault = Join-Path $env:USERPROFILE "Documents\Obsidian\AI-Memory"
.\.venv\Scripts\python.exe -m memory_hub.cli --vault $memoryVault history-init
~~~

Then pass MEMORY_VAULT_HISTORY=true to the MCP server and restart it.
The connection helper does not expose every environment setting as a parameter;
check the host's resulting server configuration.

History does not automatically commit every kind of memory operation. It is not a
backup of ignored pending-review databases or the external capture buffer.
See [undo and backup](USAGE.md#undo-and-backup).

## Settings that do not exist yet

There is no installed token-threshold worker, session-only auto-policy variable,
automatic GitHub exporter or complete startup handoff configuration. Proposed settings
in [the continuity plan](automatic-session-continuity.md) are design, not usable flags.
