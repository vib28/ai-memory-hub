# Manual Hook Configuration Template

This template provides a generic hook configuration for MCP clients that aren't directly supported by `connect-ai-tools.ps1`. It configures the `ai-memory-hook` receiver to capture PostToolUse events and forward them to the AI Memory Hub worker.

## Usage

Copy the template to your client's configuration directory and adjust the paths:

```json
{
  "mcpServers": {
    "ai-memory-hub": {
      "command": "<PATH_TO_PYTHON>",
      "args": ["-m", "memory_hub.mcp_server"],
      "env": {
        "AI_MEMORY_VAULT": "<PATH_TO_VAULT>",
        "MEMORY_WRITER": "<client-name>",
        "MEMORY_WRITE_MODE": "review"
      }
    }
  },
  "hooks": {
    "PostToolUse": [
      {
        "type": "command",
        "command": "<PATH_TO_AI_MEMORY_HOOK>",
        "args": ["--client", "<client-name>"],
        "ai_memory_hub_managed": true
      }
    ]
  }
}
```

Replace:
- `<PATH_TO_PYTHON>` — full path to `.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` (Linux/macOS)
- `<PATH_TO_VAULT>` — your Obsidian or plain-folder vault path
- `<client-name>` — a short identifier for your client (e.g. `my-custom-client`)
- `<PATH_TO_AI_MEMORY_HOOK>` — full path to the `ai-memory-hook` binary in the venv

## How It Works

The hook fires after every tool call. The `ai-memory-hook` receiver:
1. Reads the tool name, inputs, and outputs from stdin
2. Forwards them to the local observation buffer
3. The resident worker processes the buffer asynchronously

This is the same receiver used by all natively-supported clients — the template just lets you wire it into a client that `connect-ai-tools.ps1` doesn't auto-detect.

## Session Start Context

To also get session-start context injection, add a `SessionStart` hook:

```json
{
  "type": "command",
  "command": "<PATH_TO_AI_MEMORY_CONTEXT>",
  "args": ["--host", "<client-name>", "--mode", "start"],
  "ai_memory_hub_managed": true
}
 ```

Use `ai-memory-context` (or `ai-memory-handoff` in older installs) from the same venv.

## Supported Clients

This template works with any MCP client that:
- Reads a JSON/TOML/YAML config file for hooks
- Supports `command`-type hooks (spawns a process per event)
- Passes hook event data on stdin as JSON

If your client uses a different hook mechanism (e.g., webhook HTTP endpoints, gRPC, or a plugin SDK), this template won't apply — consult your client's documentation for how to invoke external commands on lifecycle events.
