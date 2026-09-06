# Installation

This guide gets AI Memory Hub running on Windows with a local Obsidian vault.

## What you need

- Windows PowerShell
- Python 3.10–3.12
- An Obsidian vault folder, or a new folder for AI Memory Hub

## Quick install

From the repository directory:

```powershell
.\setup.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

The setup script creates the virtual environment, installs dependencies, initializes
the vault template, and prepares the local tools.

For a five-minute walkthrough, see [`QUICK_START.md`](../QUICK_START.md).

## Start safely in review mode

```powershell
$env:MEMORY_WRITE_MODE = "review"
.\start-dashboard.ps1 -VaultPath "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory"
```

Open `http://127.0.0.1:8765`. Review mode lets you approve or reject proposed memories
before they enter the vault.

## Connect an AI client

Use the client-specific files in [`client-prompts/`](../client-prompts/). The MCP server
uses these environment variables:

```text
AI_MEMORY_VAULT=C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory
MEMORY_WRITER=claude
MEMORY_WRITE_MODE=review
```

The MCP command is:

```text
<repository>\.venv\Scripts\python.exe -m memory_hub.mcp_server
```

The repository also includes [`connect-ai-tools.ps1`](../connect-ai-tools.ps1) for
connecting supported local clients automatically.

After changing the MCP configuration or prompt instructions, start a new client session.
Most AI tools read their MCP server list and instructions only when the session starts;
an already-open conversation will continue using its previous configuration.

## Verify the installation

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest -q
python -m memory_hub.cli --vault "C:\Users\YOUR_NAME\Documents\Obsidian\AI-Memory" audit
```

The audit should report a healthy vault. Keep review mode enabled until you have checked
what each connected client proposes.

## Optional components

- Enable `MEMORY_WRITE_MODE=auto` only after reviewing proposals.
- Configure Ollama or LM Studio for local consolidation and embeddings.
- Enable opt-in vault history with `history-init` before automatic consolidation.
- Install generic hooks only after reading the safety gates in
  [`ARCHITECTURE.md`](../ARCHITECTURE.md).
- `connect-ai-tools.ps1 -InstallHooks` also installs verified hook entries for Gemini CLI,
  Qwen Code, and Kimi Code. Kimi uses a marked block in `~/.kimi/config.toml`; Codex hook
  configuration is not modified automatically until its schema is verified.

For the full setup walkthrough, see [`INSTALLATION_GUIDE.md`](../INSTALLATION_GUIDE.md).
