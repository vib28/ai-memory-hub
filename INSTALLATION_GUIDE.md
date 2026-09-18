# AI Memory Hub — Detailed Installation & Setup Guide

This guide walks you through installing **AI Memory Hub v0.2.0** from scratch.

You do **not** need to be a Python expert.

The goal is to end up with one shared memory system that can be used by:

- ChatGPT (via tunnel)
- Claude Code
- Codex CLI
- Gemini CLI
- Qwen Code
- Kimi Code
- Hermes Agent
- Cursor and other MCP-capable tools

Your long-term memories remain readable inside an ordinary **Obsidian vault**.

---

# 1. What this software does

AI Memory Hub gives your AI tools a shared persistent memory.

Instead of every AI remembering different things about you, they can all use the same memory store.

The basic flow is:

```text
Claude Code   Codex CLI   Gemini CLI   Qwen Code   Kimi Code   Hermes Agent   Cursor   ChatGPT
   │              │            │           │           │            │            │         │
   └──────────────┴────────────┴───────────┴───────────┴────────────┴────────────┴─────────┘
                                       │
                                       ▼
                               AI Memory Hub (MCP server)
                                       │
                                       ├── filters secrets
                                       ├── rejects weak/transient memories
                                       ├── detects duplicates
                                       ├── manages conflicts
                                       ├── tracks who wrote each memory
                                       │
                                       ▼
                               Obsidian Vault (Markdown)
```

You can choose between two modes.

## Review mode

The AI proposes memories.

You approve or reject them from the dashboard.

This is the recommended mode when you first start using the system.

```text
AI
 ↓
Memory proposal
 ↓
Review Dashboard
 ↓
Approve
 ↓
Obsidian
```

## Automatic mode

Valid durable memories are written directly into your Obsidian vault.

```text
AI
 ↓
Memory proposal
 ↓
Automatic validation
 ↓
Obsidian
```

---

# 2. What gets installed

The package contains:

```text
ai-memory-hub/
│
├── memory_hub/
│   ├── mcp_server.py      # MCP interface for AI clients
│   ├── manager.py         # Validation, policy, memory operations
│   ├── vault.py           # Markdown parsing, routing, file ops
│   ├── index.py           # SQLite search, embeddings, review queue
│   ├── security.py        # Text validation and secret checks
│   ├── capture.py         # Observation receiver and local queue
│   ├── transcript.py      # Opt-in raw event store
│   ├── consolidator.py    # Local-model summaries and fallback
│   ├── worker.py          # Supervised checkpoint worker
│   ├── context_packet.py  # Startup context injection
│   ├── dashboard.py       # Local HTTP server
│   ├── app.py             # Browser dashboard and tray
│   └── ...
│
├── vault_template/
│   ├── AI_INSTRUCTIONS.md
│   ├── MEMORY.md
│   ├── profile.md
│   ├── preferences.md
│   ├── people/
│   ├── projects/
│   ├── topics/
│   ├── decisions/
│   └── archive/
│
├── client-prompts/
│   ├── chatgpt.md
│   ├── claude.md
│   ├── codex.md
│   ├── gemini.md
│   ├── qwen.md
│   ├── kimi.md
│   ├── hermes.md
│   └── generic.md
│
├── hermes/skills/
│   └── ai-memory-hub/
│       └── SKILL.md
│
├── setup.ps1
├── setup.sh
├── start-memory-hub.ps1
├── start-worker.ps1
├── start-github-export.ps1
├── connect-ai-tools.ps1
├── connect-chatgpt-tunnel.ps1
├── pyproject.toml
├── uv.lock
└── README.md
```

---

# 3. Recommended setup

For most Windows users, this is the easiest architecture:

```text
C:\Tools\ai-memory-hub\          ← application code
C:\Users\YOU\Documents\Obsidian\AI-Memory\   ← memory vault
```

Keep the AI Memory Hub software itself separate from the vault.

---

# 4. Requirements

Before installation, make sure you have:

## Required

- Windows 10 or Windows 11
- Python 3.10 or newer (3.12 recommended)
- [uv](https://docs.astral.sh/uv/getting-started/installation/) package manager
- PowerShell
- a writable vault folder
- Git for cloning and version history

## Recommended

- Obsidian Desktop for viewing the vault
- An MCP-capable AI client (Claude Code, Codex CLI, Gemini CLI, Qwen Code, Kimi Code, or Hermes Agent)

---

# 5. Install uv

Open PowerShell.

Check whether uv is already installed:

```powershell
uv --version
```

If not installed:

```powershell
winget install AstralSoftware.uv
```

Close and reopen PowerShell after installation.

---

# 6. Install Python

uv manages Python automatically. Ensure a compatible version is available:

```powershell
uv python list
```

If Python 3.10+ is not installed:

```powershell
uv python install 3.12
```

---

# 7. Get the source

Clone the repository:

```powershell
git clone --branch enhancements/auto-context-pipeline https://github.com/vib28/ai-memory-hub.git
cd ai-memory-hub
```

Or use the `enhancements/roadmap` branch for the latest stable features.

The `enhancements/auto-context-pipeline` branch is the active development branch containing the six-host context hook installer and latest features.

---

# 8. Run the installer

Choose the location of your memory vault.

Example:

```text
C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory
```

Then run:

```powershell
.\setup.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

The installer will:

1. Install dependencies using `uv sync`
2. Create a Python virtual environment
3. Install the AI Memory Hub console scripts (`ai-memory`, `ai-memory-mcp`, `ai-memory-hook`, `ai-memory-worker`, `ai-memory-context`, etc.)
4. Initialize the Obsidian memory vault structure

---

# 9. What the installer creates

Inside the project folder:

```text
.venv\
```

This contains an isolated Python environment for AI Memory Hub.

Inside your Obsidian memory vault:

```text
MEMORY.md
AI_INSTRUCTIONS.md
profile.md
preferences.md
people\
projects\
topics\
decisions\
archive\
```

The software also creates:

```text
.ai-memory-hub\
```

This directory holds the per-vault `config.json`, worker health, capture database, and optional transcript store.

---

# 10. Connect AI tools

The connection helper detects and registers all supported AI clients found on your machine.

## Basic connection (review mode)

```powershell
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

This detects and configures all six supported hosts:

| Client | Version | Registration method |
|--------|---------|-------------------|
| Claude Code | 2.1.276 | `claude mcp add` user scope |
| Codex CLI | 0.155.0 | `codex mcp add` with explicit env |
| Gemini CLI | 0.58.0 | `gemini mcp add` user scope |
| Qwen Code | 0.22.0 | `qwen mcp add` user scope |
| Kimi Code | 2.0.1 | Edits `.kimi-code/mcp.json` |
| Hermes Agent | current | `hermes mcp add` as `ai_memory_hub` |

## Connection flags

The `connect-ai-tools.ps1` script supports these independent switches:

| Flag | Purpose |
|------|---------|
| `-WriteMode review\|auto` | Set write policy (default: review) |
| `-InstallHooks` | Install capture hooks for lifecycle events |
| `-RemoveHooks` | Remove capture hooks |
| `-InstallHandoff` | Install startup context injection for all six hosts |
| `-RemoveHandoff` | Remove startup context injection |
| `-EnableSessionAuto` | Register local checkpoint worker in Windows startup |
| `-DisableSessionAuto` | Remove worker from startup |
| `-EnableGitHubExport` | Enable sanitized GitHub session export |
| `-DisableGitHubExport` | Disable GitHub export |
| `-GitHubRepo owner/name` | GitHub repository for export |
| `-GitHubVisibility public\|private\|internal` | GitHub repository visibility |

## Capture hooks

Capture hooks buffer lifecycle events (session start/end, prompt submission, tool use, compaction, errors) so the worker can create session summaries.

```powershell
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -InstallHooks
```

Supported events per host:

- **Claude Code**: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, PreCompact, PostCompact, Stop, StopFailure, SessionEnd
- **Codex CLI**: SessionStart, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, PreCompact, PostCompact, Stop, Interrupt, SessionEnd
- **Gemini CLI**: SessionStart, SessionEnd, BeforeTool, AfterTool, AfterAgent, PreCompress
- **Qwen Code**: SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Stop, StopFailure, PreCompact, PostCompact
- **Kimi Code**: SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, PostToolUseFailure, Stop, StopFailure, Interrupt, PreCompact, PostCompact, SessionHeartbeat
- **Hermes Agent**: post_tool_call, on_session_end

## Startup handoff

Startup handoff injects a bounded context packet at SessionStart and UserPromptSubmit events. The packet contains:

- Latest goal, decisions, changed files, verified results, and next action
- Checkpoint age
- Warning when evidence is provisional
- Ambiguous work groups listed separately

```powershell
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -InstallHandoff
```

The handoff reader (`ai-memory-context.exe`) is model-free and reads only the local checkpoint manifest.

## Session auto worker

The supervised local worker processes capture observations into checkpoint/final proposals:

```powershell
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -InstallHooks -EnableSessionAuto -WriteMode review
```

The worker can run in `review` (proposals queued for approval) or `auto` (valid proposals written directly) mode.

## GitHub export

Publish sanitized session summaries to a GitHub repository:

```powershell
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -EnableGitHubExport -GitHubRepo "owner/repository" -GitHubVisibility private
```

Only accepted checkpoint/final Markdown sections are exported. Raw transcripts, secrets, and private paths are excluded.

---

# 11. Open the memory vault in Obsidian

Open Obsidian.

Choose:

```text
Open folder as vault
```

Select:

```text
C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory
```

You should see files such as:

```text
MEMORY.md
profile.md
preferences.md
AI_INSTRUCTIONS.md
```

Do not worry if most files are nearly empty.

The memory system fills them gradually.

---

# 12. Test the installation

Inside PowerShell:

Run a vault audit:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" audit
```

You should receive JSON output describing your vault state.

Run the test suite:

```powershell
uv run pytest tests/ -v
```

A healthy installation should show passing tests.

---

# 13. Launch the dashboard

The dashboard gives you a visual interface for memory management.

Run:

```powershell
.\start-memory-hub.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

Your browser should open:

```text
http://127.0.0.1:8765
```

The dashboard is local to your computer.

By default it binds only to:

```text
127.0.0.1
```

That means it is not publicly exposed to your network.

Run without the tray:

```powershell
.\start-memory-hub.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" -NoTray
```

---

# 14. Dashboard features

The dashboard contains four main areas.

## Memories

Shows stored memories.

You can:

- search
- inspect source
- inspect date
- inspect memory ID
- edit a memory
- forget a memory

## Review Queue

Shows proposed memories waiting for approval.

You can:

- approve
- reject

This section is used when:

```text
MEMORY_WRITE_MODE=review
```

## Conflicts

Shows multiple current memories that appear to describe the same subject differently.

Example:

```text
Uses Windows as primary OS.
Uses Fedora as primary OS.
```

You can choose:

```text
Keep this as current
```

The other entry is marked as superseded.

It is not silently destroyed.

## Audit

Checks the vault for problems such as:

- duplicate memory IDs
- index drift
- malformed memory entries
- pending proposals
- possible conflicts

## Settings

Configure per-vault settings including write mode, capture options, worker behavior, LLM endpoints, and dashboard port. Changes take effect for processes started after the change.

---

# 15. Recommended first-run mode

When you first connect AI tools, use:

```text
review
```

This allows you to inspect what the AI considers worth remembering.

Set:

```powershell
$env:MEMORY_WRITE_MODE="review"
```

The flow becomes:

```text
AI notices something durable
        ↓
AI proposes memory
        ↓
Memory Hub validates it
        ↓
Dashboard Review Queue
        ↓
You approve or reject
```

This is the safest way to tune your personal memory policy.

---

# 16. Fully automatic memory mode

Once you are comfortable with the system, switch to:

```powershell
$env:MEMORY_WRITE_MODE="auto"
```

The flow becomes:

```text
AI notices durable information
        ↓
Memory Hub validates it
        ↓
deduplicate
        ↓
secret check
        ↓
canonical routing
        ↓
Obsidian
```

You no longer need to say:

```text
remember this
```

for normal durable information.

---

# 17. Setting environment variables

Environment variables tell the MCP server:

- where the vault is
- which AI is writing
- whether writes are automatic or reviewed

Example for Claude Code:

```powershell
$env:AI_MEMORY_VAULT="C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
$env:MEMORY_WRITER="claude"
$env:MEMORY_WRITE_MODE="review"
```

Example for Codex CLI:

```powershell
$env:MEMORY_WRITER="codex"
```

Example for Gemini CLI:

```powershell
$env:MEMORY_WRITER="gemini"
```

Example for Qwen Code:

```powershell
$env:MEMORY_WRITER="qwen"
```

Example for Kimi Code:

```powershell
$env:MEMORY_WRITER="kimi"
```

Example for Hermes Agent:

```powershell
$env:MEMORY_WRITER="hermes"
```

Writer identities are: `chatgpt`, `claude`, `codex`, `gemini`, `kimi`, `qwen`, `cursor`, `hermes`, `user`, `other`.

Each tool should use its own writer identity.

That allows provenance such as:

```text
source:claude
source:codex
source:gemini
source:qwen
source:kimi
source:hermes
```

---

# 18. New environment variables (v0.2+)

These settings control context injection and session consolidation:

| Variable | Purpose | Default |
|----------|---------|---------|
| `MEMORY_TURN_MAX_CHARS` | Maximum per-prompt delta packet size (chars) | 1500 |
| `MEMORY_INLINE_CONSOLIDATION` | Spawn a detached checkpoint on session-end/stop/compaction | true |
| `MEMORY_HANDOFF_MAX_CHARS` | Maximum serialized startup evidence packet (chars) | 6000 |
| `MEMORY_HANDOFF_CATCHUP_SECONDS` | SessionStart catch-up budget (s) | 2 |

### MEMORY_INLINE_CONSOLIDATION

When `true` (default), the hook receiver starts a one-shot worker child on terminal events so checkpoints exist without the resident worker. Turn off only if you run the resident worker and want it to own all consolidation.

```powershell
$env:MEMORY_INLINE_CONSOLIDATION="false"
```

### MEMORY_TURN_MAX_CHARS

Controls the size of the delta-only context packet injected on each user prompt. Silent when nothing new is relevant.

```powershell
$env:MEMORY_TURN_MAX_CHARS="2000"
```

---

# 19. Start the MCP server manually

Activate the virtual environment:

```powershell
.venv\Scripts\Activate.ps1
```

Or use the console script directly:

```powershell
$env:AI_MEMORY_VAULT="C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
$env:MEMORY_WRITER="claude"
$env:MEMORY_WRITE_MODE="review"

python -m memory_hub.mcp_server
```

If your AI application supports MCP directly, the application normally launches this server itself.

You usually do not need to run it manually every time.

---

# 20. MCP host configuration

Different AI applications use different configuration formats.

A generic example is included at:

```text
examples\mcp-host-config.example.json
```

It looks conceptually like:

```json
{
  "mcpServers": {
    "ai-memory-hub": {
      "command": "C:\\Tools\\ai-memory-hub\\.venv\\Scripts\\python.exe",
      "args": [
        "-m",
        "memory_hub.mcp_server"
      ],
      "env": {
        "AI_MEMORY_VAULT": "C:\\Users\\YOUR_NAME\\Documents\\Obsidian\\AI-Memory",
        "MEMORY_WRITER": "claude",
        "MEMORY_WRITE_MODE": "review"
      }
    }
  }
}
```

Important:

The exact location where this configuration belongs depends on the AI application.

Do not copy a config blindly unless that application's current MCP documentation uses the same format.

---

# 21. Client prompts

The package includes behavior instructions for each AI.

Look inside:

```text
client-prompts\
```

Files include:

```text
chatgpt.md
claude.md
codex.md
gemini.md
qwen.md
kimi.md
hermes.md
generic.md
```

These prompts tell the AI:

- when to search memory
- when not to search memory
- what should be stored
- what should never be stored
- how automatic memory should behave
- how to handle corrections
- how to forget memories

Use the appropriate prompt with each AI tool.

For Hermes Agent, the skill is installed automatically from:

```text
hermes/skills/ai-memory-hub/SKILL.md
```

---

# 22. How automatic memory works

Suppose you tell an AI:

```text
I bought a Lenovo LOQ with an RTX 5060 and 32 GB RAM.
```

The AI may decide this is durable because it could improve future hardware advice.

It sends a proposal similar to:

```text
kind: topic
subject: laptops
tag: stated
text: Uses a Lenovo LOQ laptop with RTX 5060 and 32 GB RAM.
```

Memory Hub checks:

```text
Is it durable?
Is it allowed?
Is it secret?
Does it already exist?
Which file owns it?
```

Then it may store:

```markdown
- [stated] Uses a Lenovo LOQ laptop with RTX 5060 and 32 GB RAM. <!-- mem:abc123 source:claude date:2026-09-04 -->
```

inside something similar to:

```text
topics/laptops.md
```

---

# 23. What should be stored automatically

Good examples:

```text
I prefer concise answers first.
```

```text
I mainly use Python for automation.
```

```text
We decided to use PostgreSQL.
```

```text
I bought a Lenovo LOQ laptop.
```

```text
The project must remain cloud-provider agnostic.
```

```text
I am working on a long-running AI memory project.
```

---

# 24. What should not be stored automatically

Bad examples:

```text
Bitcoin is $70,000 today.
```

That is temporary.

```text
npm gave me error ERESOLVE.
```

Likely temporary.

```text
Here is my API key: ...
```

Never store secrets.

```text
Write me a Python script.
```

Generated code should not become personal memory.

```text
I am annoyed by this bug.
```

Usually transient.

---

# 25. Memory files

## MEMORY.md

This is the index.

It tells AI systems which files exist and what they cover.

Example:

```markdown
| [[profile]] | profile | 2026-09-04 | Stable identity and technology context |
| [[preferences]] | preference | 2026-09-04 | Communication and workflow preferences |
| [[topics/laptops]] | topic | 2026-09-04 | Laptop ownership and hardware preferences |
```

AI systems should read this file first rather than scanning the entire vault.

## profile.md

Stores stable personal context.

## preferences.md

Stores durable AI interaction and workflow preferences.

## projects/

Stores long-running project memory.

## topics/

Stores recurring subject-specific context.

## people/

Stores durable context about people relevant to ongoing work.

## decisions/

Stores important decisions that deserve their own record.

## archive/

Stores inactive material.

---

# 26. Stable memory IDs

Each memory gets an ID.

Example:

```text
mem:9f831ab2c7e1
```

This allows AI tools to refer to the exact memory even if its wording changes.

That makes editing and forgetting safer than trying to find a sentence by text alone.

---

# 27. Provenance

Every memory records who wrote it.

Example:

```markdown
<!-- mem:9f831ab2c7e1 source:claude date:2026-09-04 -->
```

Possible writers:

```text
chatgpt
claude
codex
gemini
qwen
kimi
hermes
cursor
user
other
```

This helps you see where a memory came from.

---

# 28. Editing memory manually in Obsidian

You may edit the Markdown files directly.

However, after manual changes, rebuild the index:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" reindex
```

Then run:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" audit
```

This ensures the SQLite index matches your Markdown files.

---

# 29. Searching memory from the command line

Example:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" search "laptop"
```

Another example:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" search "response style"
```

---

# 30. Adding a memory manually

You can test the memory engine using:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" propose --writer user --kind preference --tag preference --subject response-style --text "Prefers concise answers first, followed by optional detail."
```

Then refresh the dashboard.

---

# 31. Forgetting a memory from the command line

First search for the memory.

Example:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" search "concise answers"
```

Find its memory ID.

Then:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" forget MEMORY_ID
```

Replace:

```text
MEMORY_ID
```

with the actual ID.

The dashboard is easier for normal use.

---

# 32. Optional transcript ingestion

Not every AI tool can call MCP tools directly.

For those tools, the package includes a transcript ingestion option.

The idea is:

```text
conversation transcript
        ↓
memory extractor model
        ↓
candidate memories
        ↓
Memory Hub validation
        ↓
vault
```

This requires a local (or remote) model server that exposes a standard chat-completions API, such as Ollama, LM Studio, llama.cpp's server, or vLLM.

A local model is recommended if you want transcript analysis to remain private.

---

# 33. Configure transcript extraction

Set:

```powershell
$env:MEMORY_LLM_BASE_URL="http://localhost:11434/v1"
$env:MEMORY_LLM_MODEL="YOUR_MODEL"
$env:MEMORY_LLM_API_KEY=""
```

Then:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" ingest ".\conversation.txt" --writer chatgpt
```

This will attempt to extract only durable memories.

---

# 34. Full session transcripts (opt-in)

Enable complete local session recording:

```powershell
$env:MEMORY_TRANSCRIPT_ENABLED=true
```

Set before starting the client hook receiver and the worker; restart both after changing it.

Raw user/agent/tool/system events are stored in a local transcript companion object:

- SQLite at `<vault>/.ai-memory-hub/transcripts.sqlite3`
- Chronological Obsidian Markdown at `<vault>/transcripts/`
- Bidirectional wikilinks to checkpoint/final summaries

This feature is **off by default** and is a separate, sensitive opt-in.

---

# 35. Privacy model

Your canonical memory lives in your Obsidian vault.

The dashboard runs locally.

The SQLite index lives locally.

However, privacy still depends on how you connect your AI tools.

For example:

- if a cloud AI calls your MCP server, some conversation content may already be processed by that AI provider
- if transcript extraction uses a cloud model, the transcript may be sent to that model
- if transcript extraction uses a local model, the extraction can remain local

The Memory Hub itself does not require you to upload the vault to a cloud service.

---

# 36. Secret protection

Memory Hub attempts to reject probable:

- passwords
- API keys
- access tokens
- refresh tokens
- private keys
- seed phrases
- credit/debit card numbers
- obvious account identifiers

This is a safety layer, not a guaranteed enterprise DLP system.

Do not intentionally use the vault as a password manager.

Use a proper password manager for secrets.

---

# 37. Backups

Your important data is the Markdown vault.

Back up:

```text
AI-Memory\
```

You do not necessarily need to back up:

```text
.memory_index.sqlite3
```

because it can be rebuilt.

Recommended backup approaches:

- Git
- OneDrive
- Dropbox
- Syncthing
- Obsidian Sync
- Windows File History

Be careful with sync conflicts if multiple computers write the same vault at the same time.

---

# 38. Multi-computer use

The safest multi-device design is:

```text
AI tools
   ↓
ONE Memory Hub service
   ↓
ONE canonical vault
```

Less safe:

```text
Laptop A writes vault
Laptop B writes vault
Cloud sync merges both
```

That can produce file conflicts.

For one-computer use, the included file locking is usually sufficient.

For serious multi-device use, run one central Memory Hub process and connect all clients to that service.

---

# 39. Updating AI Memory Hub

When a new version is released:

1. Back up your vault.
2. Update the repository (`git pull`).
3. Run `.\setup.ps1 -VaultPath "YOUR_VAULT_PATH"` again.
4. Run:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "YOUR_VAULT_PATH" reindex
```

5. Run:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "YOUR_VAULT_PATH" audit
```

Your Markdown memory should remain independent of the application code.

---

# 40. Uninstalling

To uninstall the software:

Delete the AI Memory Hub program folder.

Example:

```text
C:\Tools\ai-memory-hub
```

Your Obsidian memory vault remains untouched.

If you also want to remove the memory vault, delete it separately.

Be certain you have backups first.

To remove the connection from all clients:

```powershell
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -RemoveHooks -DisableSessionAuto -RemoveHandoff -DisableGitHubExport
```

---

# 41. Resetting the SQLite index

If the index behaves strangely:

Stop the dashboard and MCP server.

Delete:

```text
.memory_index.sqlite3
```

from the vault.

Then rebuild:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" reindex
```

Your Markdown memory is not lost.

---

# 42. Dashboard does not open

Try launching directly:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.dashboard --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

Look for errors in the PowerShell window.

Also check whether port:

```text
8765
```

is already being used.

You can use another port:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.dashboard --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" --port 8766
```

Or set the environment variable:

```powershell
$env:MEMORY_DASHBOARD_PORT=8766
```

Then open:

```text
http://127.0.0.1:8766
```

---

# 43. Python module not found

If you see an error such as:

```text
ModuleNotFoundError
```

make sure the virtual environment is active:

```powershell
.venv\Scripts\Activate.ps1
```

Then reinstall:

```powershell
uv sync
```

---

# 44. MCP server does not start

Check:

```powershell
python --version
```

Then:

```powershell
pip show mcp
```

Make sure your environment variables are set:

```powershell
$env:AI_MEMORY_VAULT
$env:MEMORY_WRITER
$env:MEMORY_WRITE_MODE
```

Then start:

```powershell
python -m memory_hub.mcp_server
```

---

# 45. AI is not remembering anything

Check these possibilities.

## The AI is not actually connected to MCP

The AI must be able to call the memory tools.

## The AI prompt was not installed

Use the relevant prompt from:

```text
client-prompts\
```

For Hermes Agent, verify the skill is installed in its skills directory.

## You are in review mode

Check the dashboard's Review Queue.

The memory may be waiting for approval.

## The information was intentionally filtered

The retention policy rejects transient or unsafe information.

This is expected.

---

# 46. AI is remembering too much

Switch to review mode:

```powershell
$env:MEMORY_WRITE_MODE="review"
```

Inspect what the AI proposes.

You can also tighten the prompt inside:

```text
client-prompts\
```

or:

```text
AI_INSTRUCTIONS.md
```

Examples of stricter policies:

```text
Only store preferences after they are mentioned at least twice.
```

```text
Never automatically store purchases.
```

```text
Only automatically store project decisions and explicit preferences.
```

---

# 47. AI is remembering too little

You can loosen the policy.

For example:

```text
Store durable purchases that may affect future recommendations.
```

or:

```text
Store long-term project status even when it is not explicitly labeled as a decision.
```

Make changes carefully.

The goal is useful memory, not maximum memory.

---

# 48. Recommended operating pattern

For the first week:

```text
MEMORY_WRITE_MODE=review
```

Review proposals occasionally.

Delete weak memories.

Notice which categories are useful.

After you trust the system:

```text
MEMORY_WRITE_MODE=auto
```

Then use the dashboard mainly for:

- inspection
- conflict resolution
- forgetting
- audits

---

# 49. Recommended backup pattern

A practical setup is:

```text
Obsidian Vault
    +
Git or Obsidian Sync
    +
regular Windows backup
```

The vault is just Markdown, so you are not locked into AI Memory Hub.

You can stop using the software and still keep your memory files forever.

---

# 50. Recommended security pattern

Use this hierarchy:

```text
Passwords / API keys
    ↓
Password Manager

AI durable context
    ↓
AI Memory Hub / Obsidian

Temporary notes
    ↓
Normal Obsidian notes

Conversation history
    ↓
AI provider / exports
```

Do not mix these layers.

---

# 51. Recommended final setup

A clean long-term Windows setup could look like:

```text
C:\Tools\ai-memory-hub\
    application code

C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory\
    persistent AI memory
```

Run AI Memory Hub in:

```text
review mode
```

initially.

Connect one AI first, preferably the AI you use most frequently.

Once that works correctly, connect:

```text
Claude Code
Codex CLI
Gemini CLI
Qwen Code
Kimi Code
Hermes Agent
```

one at a time.

This makes troubleshooting much easier than connecting everything simultaneously.

---

# 52. First successful test

A simple end-to-end test is:

Tell one connected AI:

```text
For future coding discussions, I prefer Python examples before JavaScript examples.
```

The AI should propose a durable preference.

In review mode:

1. open the dashboard
2. go to Review Queue
3. approve it
4. open Obsidian
5. inspect `preferences.md`

You should see an entry similar to:

```markdown
- [preference] Prefers Python examples before JavaScript examples. <!-- mem:... source:... date:... -->
```

Then start a new AI session and ask:

```text
Which language should you use first when giving me code examples?
```

If the AI searches the shared memory and answers:

```text
Python
```

your persistent memory loop is working.

---

# 53. The important mental model

AI Memory Hub is not intended to save every sentence you ever say.

It is trying to build a compact model of durable context:

```text
Who are you?
What do you prefer?
What are you working on?
What have you decided?
What constraints matter?
What should future AIs not make you explain again?
```

That is the memory worth carrying forward.

Everything else can remain conversation history.

---

# 54. Troubleshooting checklist

If something is not working, check these in order:

```text
[ ] Python 3.10+ installed
[ ] uv installed
[ ] project cloned correctly
[ ] setup.ps1 completed successfully
[ ] .venv exists
[ ] Obsidian vault exists
[ ] MEMORY.md exists
[ ] connect-ai-tools.ps1 ran successfully
[ ] dashboard starts
[ ] audit reports healthy
[ ] AI_MEMORY_VAULT is correct
[ ] MEMORY_WRITER is correct
[ ] MEMORY_WRITE_MODE is correct
[ ] MCP server starts manually
[ ] AI client is connected to the MCP server
[ ] correct client prompt is installed
[ ] Review Queue checked if using review mode
```

---

# 55. Useful commands cheat sheet

Setup and environment:

```powershell
uv sync
.\setup.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory"
```

Connect clients:

```powershell
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory"
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -WriteMode auto
```

Dashboard:

```powershell
.\start-memory-hub.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory"
```

Audit:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\path\to\AI-Memory" audit
```

Search:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\path\to\AI-Memory" search "topic"
```

Reindex:

```powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault "C:\path\to\AI-Memory" reindex
```

Run MCP server:

```powershell
$env:AI_MEMORY_VAULT="C:\path\to\AI-Memory"
$env:MEMORY_WRITER="claude"
$env:MEMORY_WRITE_MODE="review"
python -m memory_hub.mcp_server
```

Switch to automatic mode:

```powershell
$env:MEMORY_WRITE_MODE="auto"
```

Switch back to review mode:

```powershell
$env:MEMORY_WRITE_MODE="review"
```

---

# 56. Suggested rollout order

Do not connect all AI tools on day one.

Recommended:

```text
Day 1
↓
Install Memory Hub
↓
Open dashboard
↓
Test CLI

Then
↓
Connect your primary AI
↓
Use REVIEW mode
↓
Inspect proposed memories

Then
↓
Connect second AI
↓
Check provenance and conflicts

Then
↓
Connect remaining tools

Finally
↓
Switch to AUTO mode if satisfied
```

This makes the system much easier to trust and debug.

---

# 57. Final recommendation

Start with:

```text
MEMORY_WRITE_MODE=review
```

Use it normally for several days.

The dashboard will teach you what your AI tools consider durable.

Once the proposals consistently look useful rather than noisy, switch to:

```text
MEMORY_WRITE_MODE=auto
```

At that point, the system becomes mostly invisible.

Your AI tools remember the things that matter, while your Obsidian vault remains readable, editable, portable, and under your control.
