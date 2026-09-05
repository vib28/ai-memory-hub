<#
.SYNOPSIS
    Bridges AI Memory Hub's local MCP server to ChatGPT via OpenAI's official Secure MCP Tunnel.

.DESCRIPTION
    ChatGPT's Developer Mode connects to local (stdio) MCP servers through OpenAI's first-party
    `tunnel-client` tool: an outbound-only bridge, so nothing is exposed to the public internet.
    This script configures a tunnel-client profile pointed at this repo's MCP server and starts it.

    Before running this, do the one-time account setup in your browser (see README.md):
      1. Create a Runtime API key with Tunnels Read+Use permission:
         https://platform.openai.com/settings/organization/api-keys
      2. Create a tunnel ID:
         https://platform.openai.com/settings/organization/tunnels
      3. Install tunnel-client for Windows:
         https://github.com/openai/tunnel-client/releases

    Run .\setup.ps1 first — this script requires the .venv it creates.

.PARAMETER VaultPath
    Absolute path to your Obsidian (or plain folder) memory vault. Required.

.PARAMETER TunnelId
    The tunnel ID you created at platform.openai.com/settings/organization/tunnels. Required.

.PARAMETER ApiKey
    Your Runtime API key (Tunnels Read+Use permission). Required unless CONTROL_PLANE_API_KEY
    is already set in the environment.

.PARAMETER WriteMode
    "review" (default) or "auto". See README.md.

.EXAMPLE
    .\connect-chatgpt-tunnel.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" `
        -TunnelId "tunnel_0123456789abcdef0123456789abcdef" `
        -ApiKey (Read-Host "Runtime API key")
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$VaultPath,

    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$TunnelId,

    [string]$ApiKey = $env:CONTROL_PLANE_API_KEY,

    [ValidateSet("review", "auto")]
    [string]$WriteMode = "review"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
# Not named $Profile — that's a PowerShell automatic variable (your $PROFILE
# script path) and shadowing it is asking for trouble.
$ProfileName = "ai-memory-hub"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found at $Python. Run .\setup.ps1 -VaultPath `"$VaultPath`" first."
}
if (-not (Get-Command tunnel-client -ErrorAction SilentlyContinue)) {
    throw "tunnel-client not found on PATH. Install it from https://github.com/openai/tunnel-client/releases first."
}
if (-not $ApiKey) {
    throw "No API key provided. Pass -ApiKey, or set `$env:CONTROL_PLANE_API_KEY before running this script."
}
if ($TunnelId -notmatch "^tunnel_[a-z0-9]{32}$") {
    throw "TunnelId '$TunnelId' doesn't look right — it should be 'tunnel_' followed by 32 lowercase letters/digits. Copy it exactly from https://platform.openai.com/settings/organization/tunnels."
}
if (-not (Test-Path $VaultPath)) {
    Write-Host "Vault path does not exist yet, creating it: $VaultPath"
    New-Item -ItemType Directory -Force -Path $VaultPath | Out-Null
}

$env:CONTROL_PLANE_API_KEY = $ApiKey
# Passed through to the child process tunnel-client launches for --mcp-command.
$env:AI_MEMORY_VAULT = $VaultPath
$env:MEMORY_WRITER = "chatgpt"
$env:MEMORY_WRITE_MODE = $WriteMode

# tunnel-client parses --mcp-command with shell-word rules where backslash
# is an escape character, which silently eats a Windows-style path (e.g.
# "C:\Users\..." becomes "C:Users..."). Forward slashes survive intact, and
# Windows accepts them in paths just as well as backslashes.
$PythonForMcpCommand = $Python -replace '\\', '/'

tunnel-client init `
    --profile $ProfileName `
    --tunnel-id $TunnelId `
    --mcp-command "`"$PythonForMcpCommand`" -m memory_hub.mcp_server" `
    --force
if ($LASTEXITCODE -ne 0) {
    throw "tunnel-client init failed (exit code $LASTEXITCODE). Double-check -TunnelId and -ApiKey. See the output above."
}

Write-Host ""
Write-Host "Checking the profile..."
tunnel-client doctor --profile $ProfileName --explain
if ($LASTEXITCODE -ne 0) {
    throw "tunnel-client doctor reported a problem (exit code $LASTEXITCODE). Fix the issue above before running 'tunnel-client run --profile $ProfileName' yourself."
}

Write-Host ""
Write-Host "Starting the tunnel. Leave this window open — closing it disconnects ChatGPT."
Write-Host "In ChatGPT: Settings > Connectors > Advanced > Developer mode > + > Connection: Tunnel > select `"$ProfileName`"."
Write-Host ""
tunnel-client run --profile $ProfileName
if ($LASTEXITCODE -ne 0) {
    throw "tunnel-client run exited with code $LASTEXITCODE. See the output above."
}
