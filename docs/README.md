# Documentation

Find the guide that matches where you are right now.

| I want to… | Start here |
|---|---|
| Understand what this project does | [Project README](../README.md) |
| Install and connect my first AI client | [Installation](INSTALLATION.md) |
| Open the dashboard and review memories | [Dashboard](DASHBOARD.md) |
| Learn how to search, propose, and approve memory | [Usage](USAGE.md) |
| Configure write mode, models, and environment | [Configuration](CONFIGURATION.md) |
| Set up automatic session continuity | [Automatic continuity](automatic-session-continuity.md) |
| Fix something that isn't working | [Troubleshooting](TROUBLESHOOTING.md) |
| Read short answers to common questions | [FAQ](FAQ.md) |
| Understand the code and contribute | [Architecture](../ARCHITECTURE.md) · [Contributing](../CONTRIBUTING.md) |

## By user journey

### 1. Setup — get running in minutes

| Step | Guide | What you'll do |
|---|---|---|
| 1 | [Installation](INSTALLATION.md) | Clone the repo, create a vault, connect an AI client |
| 2 | [Client connections](CLIENTS.md) | Verify your host (Claude, Codex, Gemini, Qwen, Kimi, Hermes) |
| 3 | [Configuration](CONFIGURATION.md) | Choose review or auto write mode; set optional models |
| 4 | [Dashboard](DASHBOARD.md) | Start the local launcher and open the browser workspace |

> **Tip:** Prove one harmless review proposal before enabling any optional pipeline.

### 2. Daily use — review, search, and organize memory

| Guide | Purpose |
|---|---|
| [Usage](USAGE.md) | Propose, review, search, import, link projects, and undo |
| [Dashboard](DASHBOARD.md) | Unified launcher, full-memory reader, tag and link lookups |
| [Full session transcripts](full-session-transcripts.md) | Opt-in exact event record; disabled by default |

### 3. Continuity — automatic session capture and handoff

| Guide | Purpose |
|---|---|
| [Automatic session continuity](automatic-session-continuity.md) | Capture, worker, checkpoint, and cross-client startup handoff |
| [Continuity closeout](continuity-closeout.md) | Evidence record for the completed local pipeline |

**Supported hosts:** Claude Code · Codex CLI · Gemini CLI · Qwen Code · Kimi Code · Hermes Agent

**Pipeline status (this branch):**

| Capability | Status |
|---|---|
| Shared MCP memory and Markdown vault | ✅ Available |
| Review queue and dashboard | ✅ Available |
| Optional embeddings and local chat model | ✅ Available when configured |
| Lifecycle capture and supervised worker | ✅ Available behind explicit setup |
| Full verbatim session transcript | ✅ Available behind `MEMORY_TRANSCRIPT_ENABLED=true` |
| Claude/Codex model-free startup handoff | ✅ Available behind explicit setup |
| Sanitized GitHub session outbox | ✅ Available behind explicit destination approval |
| Live cross-tool token/cost certification | ⏳ Not complete — see [benchmark protocol](session-handoff-benchmark.md) |

### 4. Recovery — diagnose and fix problems

| Guide | Purpose |
|---|---|
| [Troubleshooting](TROUBLESHOOTING.md) | Missing tools, locked files, configuration drift |
| [FAQ](FAQ.md) | Do I need Obsidian? Can tools share memory? What does handoff restore? |

### 5. Development — understand, extend, and measure

| Guide | Purpose |
|---|---|
| [Architecture](../ARCHITECTURE.md) | Module map, storage layout, and boundaries |
| [Contributing](../CONTRIBUTING.md) | Development checks and issue workflow |
| [Quick start](../QUICK_START.md) | Short Windows entry point |
| [Setup guide](../INSTALLATION_GUIDE.md) | Guided route through the installation references |
| [Local memory plan](local-memory-plan.md) | Implementation roadmap and issue tracking |
| [Issue priority order](issue-priority-order.md) | Canonical execution sequence for open issues |
| [Vault documentation standards](vault-documentation-standards.md) | Template quality and per-kind entry rules |
| [Two-tool handoff benchmark](session-handoff-benchmark.md) | Replay protocol for paired context-passing measurement |
| [Benchmark results](benchmark-results/handoff-replay-v1.md) | Synthetic protocol evidence — not live billing certification |

## Quick concepts

| Term | Meaning |
|---|---|
| **Vault** | The ordinary Markdown directory holding accepted memory |
| **Writer** | Provenance label such as `claude` or `codex`; not an access-control list |
| **Review mode** | Proposals wait for dashboard approval before acceptance |
| **Auto mode** | Validated proposals accepted without dashboard approval |
| **Capture** | Bounded lifecycle evidence stored before summarization |
| **Checkpoint** | An accepted or pending periodic session state |
| **Handoff** | Bounded local checkpoint context injected at supported startup events |
| **Outbox** | Retryable GitHub delivery state; separate from accepted Markdown |
| **Transcript** | Opt-in chronological event record; separate from bounded capture |

If a guide uses one of these terms differently, treat it as a documentation bug.

## Writing conventions

User guides use descriptive headings, relative repository links, language-tagged code
blocks, and alerts for meaningful cautions. Commands and expected output stay separate.
Tables summarize repeated comparisons; they don't replace every paragraph.

Follow [GitHub's writing and formatting guidance](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github).
Do not change issue templates, client prompts, or vault-record formats merely to restyle a guide.
