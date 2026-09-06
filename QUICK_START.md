# AI Memory Hub — 5-Minute Windows Quick Start

For the full walkthrough, read `INSTALLATION_GUIDE.md`.

This installs shared memory access, not yet unattended session handoff. Automatic linked
checkpoints and Claude/Codex restoration are the [first-priority plan](docs/automatic-session-continuity.md).

## 1. Install Python

```powershell
winget install Python.Python.3.12
```

Restart PowerShell afterward.

## 2. Extract AI Memory Hub

Example:

```text
C:\Tools\ai-memory-hub
```

## 3. Open PowerShell in that folder

Then run:

```powershell
.\setup.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

## 4. Start in review mode

```powershell
$env:MEMORY_WRITE_MODE="review"
```

## 5. Open the dashboard

```powershell
.\start-dashboard.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

Your browser opens:

```text
http://127.0.0.1:8765
```

## 6. Test the installation

```powershell
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
python -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" audit
```

## 7. Connect one AI tool

Use its file from:

```text
client-prompts\
```

Configure the MCP server with:

```text
command:
C:\Tools\ai-memory-hub\.venv\Scripts\python.exe

arguments:
-m
memory_hub.mcp_server
```

Environment:

```text
AI_MEMORY_VAULT=C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory
MEMORY_WRITER=chatgpt
MEMORY_WRITE_MODE=review
```

Change `MEMORY_WRITER` for each AI:

```text
chatgpt
claude
gemini
kimi
cursor
```

## 8. Test memory

Tell the AI:

```text
For future coding questions, I prefer Python examples before JavaScript.
```

Check the dashboard Review Queue.

Approve the memory.

Then start a fresh AI conversation and ask which language it should use first.

If it retrieves "Python", the loop works.

## 9. Later, enable full automatic memory

```powershell
$env:MEMORY_WRITE_MODE="auto"
```

That's it.
