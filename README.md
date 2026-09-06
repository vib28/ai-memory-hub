# AI Memory Hub

Shared, local-first memory for AI tools. Store accepted preferences, decisions and
project notes as readable Markdown, then retrieve them through one MCP server.

[Installation](docs/INSTALLATION.md) · [Connect a client](docs/CLIENTS.md) ·
[Usage](docs/USAGE.md) · [Architecture](ARCHITECTURE.md) · [Roadmap](docs/local-memory-plan.md)

[![CI](https://github.com/vib28/ai-memory-hub/actions/workflows/ci.yml/badge.svg)](https://github.com/vib28/ai-memory-hub/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

## What this project does

AI clients can share durable context without maintaining separate memory stores.
The vault is an ordinary folder that can also be opened in Obsidian. MCP—the Model
Context Protocol—is the interface a connected AI uses to search or propose memories.

A preference written by Claude is available to Codex and other connected clients.
The writer records where it came from; it is not an access restriction.

- Save preferences, project facts, decisions, people, topics and session summaries.
- Review proposed changes in a local dashboard before accepting them.
- Search with SQLite keyword search and optional local embeddings.
- Inspect identity conflicts and possible duplicates without automatic merging.
- Keep optional Git history for accepted vault changes.

> [!IMPORTANT]
> Automatic periodic session saves and automatic Claude/Codex handoff are **planned,
> not implemented**. They are the [first-priority work](docs/automatic-session-continuity.md).
> Current hook buffering, summary tools and prompt instructions are building blocks,
> not a complete unattended service.

## Current state

| Area | Available now | Limitation |
| --- | --- | --- |
| Shared memory | MCP tools and Markdown vault | Clients must connect to the same vault |
| Review | Dashboard approval and proposal history | Set the MCP write mode explicitly |
| Sessions | Four-section summaries and historical import | No linked token-batch chain yet |
| Capture | Local observation queue and hook configuration helpers | Native adapters and queue safety need fixes |
| Retrieval | Keyword search and optional vectors | Context budget/project isolation need correction |
| Undo | Opt-in local Git history | Not a backup of pending capture or review data |
| Token savings | Component context-size benchmark | No measured cross-tool savings claim |

Known capture, identity and context defects are tracked in
[the continuity plan](docs/automatic-session-continuity.md#reproduction-steps).
The required [two-tool benchmark](docs/session-handoff-benchmark.md) compares matched
sessions with context passing enabled and disabled.

## Quick start

Run these commands from an existing clone's repository directory. Install Python,
Git and [uv](https://docs.astral.sh/uv/getting-started/installation/) first.
For a fresh clone, follow [installation](docs/INSTALLATION.md).

~~~powershell
$memoryVault = Join-Path $env:USERPROFILE "Documents\Obsidian\AI-Memory"
.\setup.ps1 -VaultPath $memoryVault
.\connect-ai-tools.ps1 -VaultPath $memoryVault -WriteMode review
.\start-dashboard.ps1 -VaultPath $memoryVault
~~~

The setup creates the environment and initializes missing vault files. The connection
script attempts supported installed clients. The dashboard runs locally, normally at
[localhost:8765](http://127.0.0.1:8765). Start a new client session after connecting.

> [!WARNING]
> The connection script defaults to review, but a directly started MCP server defaults
> to auto if its mode is missing or invalid. Always configure
> `MEMORY_WRITE_MODE=review` when you want approval before proposals are stored.
> Direct administrative CLI commands have different behavior; see [configuration](docs/CONFIGURATION.md).

## Connect your AI tools

The Windows connection script has setup paths for Claude Code, Codex CLI, Gemini CLI,
Qwen Code, Kimi Code and Hermes Agent. Other stdio MCP clients can be configured manually.
ChatGPT has a separate optional tunnel helper.

Connection support is not proof that every client version supports automatic hooks.
See [client setup and limitations](docs/CLIENTS.md) for what the scripts actually configure.

## How it works

~~~text
AI client -> MCP tools -> validation and write policy
                              |             |
                           review        accepted write
                              |             |
                           approval ----> Markdown vault
                                            |
                                      search index
~~~

Accepted Markdown memories are the durable record. Search data can be rebuilt.
Unprocessed capture observations and pending proposals cannot be recreated from
accepted Markdown alone; include them in your backup plan.

## Requirements

- Python 3.10 or newer; the CI matrix covers 3.10, 3.11 and 3.12.
- uv for the repository environment and dependency installation.
- PowerShell for the Windows setup helpers; a separate shell setup script exists.
- A writable vault folder. Obsidian is optional.
- Git for cloning, development and optional vault history.
- An MCP-capable client for live memory access.

No memory-service subscription is required. Your chosen AI clients may have their own
usage charges. Local language and embedding models are optional and use your hardware.

## Documentation

| Read this | When you need |
| --- | --- |
| [Documentation index](docs/README.md) | A map of all guides |
| [Installation](docs/INSTALLATION.md) | Environment, vault and first verification |
| [Client connections](docs/CLIENTS.md) | MCP registration and behavioral instructions |
| [Configuration](docs/CONFIGURATION.md) | Write modes, endpoints and environment variables |
| [Usage](docs/USAGE.md) | Review, search, sessions, imports and undo |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Symptoms, checks and safe recovery |
| [FAQ](docs/FAQ.md) | Short answers and limits |
| [Architecture](ARCHITECTURE.md) | Modules, data flow and boundaries |
| [Contributing](CONTRIBUTING.md) | Development checks and issue workflow |

## Roadmap and planning

[Roadmap #61](https://github.com/vib28/ai-memory-hub/issues/61) prioritizes linked session
checkpoints and automatic handoff. [Acceptance #62](https://github.com/vib28/ai-memory-hub/issues/62)
requires matched Claude/Codex token and task-quality measurements.

Use the [tracked roadmap](docs/local-memory-plan.md) for order and dependencies, and
the [GitHub project](https://github.com/users/vib28/projects/1) for open and closed work.
Issues and planning documents retain their prescribed seven-section format.

[FIXLOG](FIXLOG.md) and [release notes](RELEASE_NOTES_v0.2.md) are historical records,
not proof that later features are complete.

## License

[Apache License 2.0](LICENSE).
