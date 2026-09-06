# Quick start

For Windows users with a repository checkout and Python, Git and uv already installed.

[Full installation](docs/INSTALLATION.md) · [Troubleshooting](docs/TROUBLESHOOTING.md)

## Set up and connect

Run from the repository directory:

~~~powershell
$memoryVault = Join-Path $env:USERPROFILE "Documents\Obsidian\AI-Memory"
.\setup.ps1 -VaultPath $memoryVault
.\connect-ai-tools.ps1 -VaultPath $memoryVault -WriteMode review
.\start-dashboard.ps1 -VaultPath $memoryVault
~~~

Keep the dashboard terminal open. Start a new AI-client session, check memory_policy
reports review, and verify a harmless proposal appears in the review queue.

## Before enabling more

- Use [client setup](docs/CLIENTS.md) if a client is skipped or already registered.
- Read [configuration](docs/CONFIGURATION.md) before choosing auto mode.
- Keep the vault outside the source checkout and back it up.

> [!IMPORTANT]
> This connects shared memory tools. Automatic linked session saves and cross-client
> restoration are [planned first-priority work](docs/automatic-session-continuity.md),
> not installed by these commands.
