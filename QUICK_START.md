# AI Memory Hub — 5-Minute Windows Quick Start

For the full walkthrough, read `INSTALLATION_GUIDE.md`.

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

## 4. Connect your AI tools

```powershell
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

This auto-detects and registers the MCP server for every supported host found on your machine:

```text
Claude Code
Codex CLI
Gemini CLI
Qwen Code
Kimi Code
Hermes Agent
```

ChatGPT desktop users run `.\connect-chatgpt-tunnel.ps1` separately (requires one-time OpenAI account setup).

## 5. Start in review mode

```powershell
$env:MEMORY_WRITE_MODE="review"
```

## 6. Open the dashboard

```powershell
.\start-dashboard.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

Your browser opens:

```text
http://127.0.0.1:8765
```

## 7. Test the installation

```powershell
.\.venv\Scripts\Activate.ps1
python -m unittest discover -s tests -v
python -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" audit
```

## 8. Test memory

Tell a connected AI:

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

## 10. Optional: continuity across sessions

Once shared memory works, you can layer on session continuity:

```powershell
# Capture lifecycle events from all six hosts
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" -InstallHooks

# Turn captured evidence into checkpoint/final proposals (background worker)
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" -EnableSessionAuto

# Inject a bounded local checkpoint at each supported client's SessionStart
.\connect-ai-tools.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" -InstallHandoff
```

Each permission is independent — install only what you want.

## 11. Optional: session summaries and pattern memories

Connected clients automatically call `session_write` at the end of each session, producing four-section summaries (Investigated, Learned, Completed, Next Steps).

When a recurring situation matches a pattern in `/patterns.md`, clients can call `propose_pattern_match` to record both a project fact and a global preference rule atomically.

## 12. Six writer identities

Change `MEMORY_WRITER` for each AI:

```text
chatgpt
claude
codex
gemini
qwen
kimi
hermes
```

That's it.
