# Client Compatibility

This document covers the six hosts supported by **ai-memory-hub** and what each one can do.

| Host | Version tested | Registration method | Instruction location |
|---|---|---|---|
| **Claude Code** | 2.1.276 | `mcp add` command | `~/.claude/CLAUDE.md` |
| **Codex CLI** | 0.155.0 | `mcp add` with explicit environment | `~/.codex/AGENTS.md` |
| **Gemini CLI** | 0.58.0 | `mcp add` command | `~/.gemini/GEMINI.md` |
| **Qwen Code** | 0.22.0 | `mcp add` command | `~/.qwen/QWEN.md` |
| **Kimi Code** | 2.0.1 | Edits `.kimi-code/mcp.json` | `AGENTS.md` in that directory |
| **Hermes Agent** | (current) | `mcp add` under `ai_memory_hub` | Skill in Hermes home |

> [!NOTE]
> ChatGPT is also supported via a [tunnel helper](#chatgpt-tunnel) rather than direct stdio, so it is **not** included in the matrix below.

---

## Compatibility Matrix

| Host | MCP Server | Capture Hooks | Startup Handoff |
|------|:----------:|:-------------:|:---------------:|
| Claude Code | ✅ | ✅ | ✅ |
| Codex CLI | ✅ | ✅ | ✅ |
| Gemini CLI | ✅ | ✅ | ✅ |
| Qwen Code | ✅ | ✅ | ✅ |
| Kimi Code | ✅ | ✅ | ✅ |
| Hermes Agent | ✅ | ✅ | ✅ |

**Legend:**
- **MCP Server** — the host can run `memory_hub.mcp_server` as a stdio MCP server.
- **Capture Hooks** — the host supports lifecycle-event capture (session start, prompt/tool/turn, compaction, failure, end).
- **Startup Handoff** — the host injects bounded `SessionStart` context into new sessions.

All six hosts support all three capabilities.

---

## Feature Breakdown

### MCP Server

Each host launches the ai-memory-hub stdio server with the vault path, writer identity, and write mode set as environment variables. The helper script `connect-ai-tools.ps1` registers the server automatically.

| Host | How it connects |
|---|---|
| Claude Code | `claude mcp add ai-memory-hub ...` |
| Codex CLI | `codex mcp add ...` with explicit env vars |
| Gemini CLI | `gemini mcp add ...` |
| Qwen Code | `qwen mcp add ...` |
| Kimi Code | Writes to `.kimi-code/mcp.json` |
| Hermes Agent | `hermes mcp add ...` under `ai_memory_hub` |

### Capture Hooks

Capture hooks observe the host's lifecycle events and forward them to the local worker for storage. The hooks are installed with `-InstallHooks` and removed with `-RemoveHooks`.

| Host | Hook mechanism |
|---|---|
| Claude Code, Gemini, Qwen | JSON settings block (managed) |
| Codex CLI | `hooks.json` file |
| Kimi Code | Marked TOML block in config |
| Hermes Agent | Skill-based receiver |

Captured events include:
- Session start
- Prompt, tool, and turn events
- Compaction
- Failure
- Session end

### Startup Handoff

Handoff injects a bounded `SessionStart` payload into new sessions so the host begins with relevant context. Installed with `-InstallHandoff`, removed with `-RemoveHandoff`.

All six hosts use the same fixture schema validated by `tests/test_handoff.py`.

---

## Quick Setup

Run the Windows helper from the repository directory:

```powershell
$memoryVault = Join-Path $env:USERPROFILE "Documents\Obsidian\AI-Memory"
.\connect-ai-tools.ps1 -VaultPath $memoryVault -WriteMode review
```

This attempts each detected client independently. It is **not** a guarantee about every version of the third-party clients.

---

## Manual MCP Configuration

If your host is not one of the six above, configure it manually. The generic shape is:

```json
{
  "mcpServers": {
    "ai-memory-hub": {
      "command": "C:\\Tools\\ai-memory-hub\\.venv\\Scripts\\python.exe",
      "args": ["-m", "memory_hub.mcp_server"],
      "env": {
        "AI_MEMORY_VAULT": "C:\\Memory\\AI-Memory",
        "MEMORY_WRITER": "other",
        "MEMORY_WRITE_MODE": "review"
      }
    }
  }
}
```

On Linux/macOS, use `.venv/bin/python`. Add [generic instructions](../client-prompts/generic.md) to your host's instruction file. Make sure the prompt's writer label matches `MEMORY_WRITER`.

---

## ChatGPT Tunnel

ChatGPT is supported via a tunnel, not direct stdio. Run:

```powershell
.\connect-chatgpt-tunnel.ps1 -VaultPath $memoryVault -TunnelId $memoryTunnelId -WriteMode review
```

This requires:
- A valid tunnel ID
- `tunnel-client` on PATH
- `CONTROL_PLANE_API_KEY` set securely

> [!WARNING]
> The tunnel routes content through an external service. Local vault storage does not mean retrieved content stays off the connected AI provider.

ChatGPT does **not** support capture hooks or startup handoff because it uses a tunnel, not a local stdio connection.

---

## Refresh or Remove

After a project update, re-run the helper to refresh managed instruction blocks and the Hermes skill. Start a new session or use the host's reload mechanism.

To disconnect, remove only this server's registration and its instruction block or skill. Removing a connection does **not** remove stored memories, pending proposals, or the observation buffer.
