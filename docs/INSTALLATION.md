# Installation

Install the repository environment, initialize a vault, then connect a client.

[Documentation](README.md) · [Client connections](CLIENTS.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Before you start

You need Python 3.10+, Git, [uv](https://docs.astral.sh/uv/getting-started/installation/),
and a writable folder for your memories. Obsidian can open that folder but is not required.

These examples target Windows PowerShell. Commands assume you are in the repository
directory. Use a dedicated vault outside the source repository and outside another
Git worktree, especially if you intend to enable vault history.

> [!NOTE]
> This guide describes the enhancement branch. The bootstrap installer's default branch
> is master, which may not contain the same features.

## Get the source

For a fresh checkout of the branch described here:

~~~powershell
git clone --branch enhancements/roadmap https://github.com/vib28/ai-memory-hub.git
cd ai-memory-hub
~~~

If you already have a checkout, keep it. Inspect its branch and local changes before
updating; do not clone over it or discard edits.

## Create the environment and vault

Choose the vault path once and reuse it throughout setup:

~~~powershell
$memoryVault = Join-Path $env:USERPROFILE "Documents\Obsidian\AI-Memory"
.\setup.ps1 -VaultPath $memoryVault
~~~

The script runs uv sync, creates the repository environment and initializes missing
vault-template files. It does not install development-test dependencies, overwrite
existing vault instructions, or start an automatic checkpoint worker.

If scripts are blocked, consult your organization's PowerShell policy. Do not disable
security controls globally just to run this setup.

## Connect in review mode

~~~powershell
.\connect-ai-tools.ps1 -VaultPath $memoryVault -WriteMode review
~~~

Read the connection summary. It attempts supported CLIs found on the machine;
skipped or failed clients are not connected. See [client connections](CLIENTS.md)
for manual configuration and optional ChatGPT setup.

Start a fresh client session after configuration changes. Verify that the client can
see AI Memory Hub's tools and that memory_policy reports review mode.

## Open the dashboard

~~~powershell
.\start-dashboard.ps1 -VaultPath $memoryVault
~~~

The dashboard normally opens at [localhost:8765](http://127.0.0.1:8765).
Keep the terminal open while using it. The optional Windows tray launcher is:

~~~powershell
.\start-tray.ps1 -VaultPath $memoryVault
~~~

The tray is a launcher, not the planned background checkpoint service.

## Check the installation

Run a non-destructive vault audit:

~~~powershell
.\.venv\Scripts\python.exe -m memory_hub.cli --vault $memoryVault audit
~~~

Read the returned findings rather than assuming a zero exit code proves every
integration works. In a test vault, ask the connected client to propose a harmless
preference and verify that it appears in the review queue before approval.

Development tests need additional dependencies; see [Contributing](../CONTRIBUTING.md).

## Linux or macOS source setup

The repository includes a shell setup helper. Run it from the repository root:

~~~bash
bash setup.sh /absolute/path/to/AI-Memory
~~~

Configure a stdio MCP host manually using the environment's Python executable at
`.venv/bin/python`. The PowerShell multi-client connection helper is Windows-oriented.
This documentation rewrite does not certify all client/platform combinations.

## Optional bootstrap installer

[install.ps1](../install.ps1) can obtain the repository, run setup and connect clients.
Read it before running it. It accepts InstallPath, VaultPath, Branch and SkipConnect;
Branch defaults to master. The explicit source workflow above makes the selected
branch visible and avoids executing a downloaded script without inspection.

## Update and remove

Before updating, back up accepted Markdown plus pending review/capture databases,
stop processes using the environment, and inspect git status. Update your selected
branch, run setup again, then refresh the [client connections](CLIENTS.md#refresh-or-remove-a-connection).

To disconnect, remove the named MCP registration through the host's supported settings
and remove only AI Memory Hub's managed instruction block or Hermes skill.
Hook removal is separate and has [known limitations](CLIENTS.md#hooks-are-not-yet-unattended-handoff).
Do not delete the vault to uninstall the client integration.
