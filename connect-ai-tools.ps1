<#
.SYNOPSIS
    Registers the AI Memory Hub MCP server with every supported AI CLI found on this machine.

.DESCRIPTION
    Detects Claude Code, Gemini CLI, Qwen Code, Codex CLI, and Kimi Code, then:
      1. Registers ai-memory-hub as an MCP server (user/global scope) for each one found.
      2. Installs the matching client-prompts/<tool>.md behavioral instructions into that
         tool's global memory/instructions file, so it knows to search and propose memories
         automatically without being told "remember this" every time.

    Run .\setup.ps1 first — this script requires the .venv it creates.

.PARAMETER VaultPath
    Absolute path to your Obsidian (or plain folder) memory vault. Required.

.PARAMETER WriteMode
    "review" (default) queues AI-proposed memories in the dashboard for approval.
    "auto" writes valid proposals straight to the vault.

.EXAMPLE
    .\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory"

.EXAMPLE
    .\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -WriteMode auto
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$VaultPath,

    [ValidateSet("review", "auto")]
    [string]$WriteMode = "review"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ServerName = "ai-memory-hub"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found at $Python. Run .\setup.ps1 -VaultPath `"$VaultPath`" first."
}
if (-not (Test-Path $VaultPath)) {
    Write-Host "Vault path does not exist yet, creating it: $VaultPath"
    New-Item -ItemType Directory -Force -Path $VaultPath | Out-Null
}

$results = [System.Collections.Generic.List[string]]::new()

function Install-Instructions {
    param([string]$TargetPath, [string]$PromptFile)

    $promptPath = Join-Path $Root "client-prompts\$PromptFile"
    if (-not (Test-Path $promptPath)) { return }
    $content = Get-Content -Raw -Path $promptPath

    $dir = Split-Path $TargetPath -Parent
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    if (Test-Path $TargetPath) {
        $existing = Get-Content -Raw -Path $TargetPath
        if ($existing -notmatch "AI Memory Hub") {
            Add-Content -Path $TargetPath -Value "`n`n$content"
        }
    }
    else {
        Set-Content -Path $TargetPath -Value $content
    }
}

function Find-Codex {
    $cmd = Get-Command codex -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $fallback = Join-Path $env:LOCALAPPDATA "Programs\OpenAI\Codex\bin\codex.exe"
    if (Test-Path $fallback) { return $fallback }
    return $null
}

# npm-installed CLIs on Windows resolve to a .ps1 wrapper by default, and
# PowerShell's argument binder mangles a literal `--` when forwarding $args
# through that wrapper. Invoking the sibling .cmd shim directly sidesteps it.
function Resolve-CliLauncher {
    param([string]$Name)
    $cmdShim = Get-Command "$Name.cmd" -ErrorAction SilentlyContinue
    if ($cmdShim) { return $cmdShim.Source }
    $bare = Get-Command $Name -ErrorAction SilentlyContinue
    if ($bare) { return $bare.Source }
    return $null
}

# --- Claude Code -------------------------------------------------------
$claudeLauncher = Resolve-CliLauncher "claude"
if ($claudeLauncher) {
    & $claudeLauncher mcp add $ServerName -s user `
        -e AI_MEMORY_VAULT="$VaultPath" `
        -e MEMORY_WRITER=claude `
        -e MEMORY_WRITE_MODE=$WriteMode `
        -- "$Python" -m memory_hub.mcp_server | Out-Null
    Install-Instructions "$HOME\.claude\CLAUDE.md" "claude.md"
    $results.Add("[connected] Claude Code")
}
else {
    $results.Add("[skipped]   Claude Code (not found on PATH)")
}

# --- Gemini CLI ----------------------------------------------------------
$geminiLauncher = Resolve-CliLauncher "gemini"
if ($geminiLauncher) {
    & $geminiLauncher mcp add $ServerName -s user `
        -e AI_MEMORY_VAULT="$VaultPath" `
        -e MEMORY_WRITER=gemini `
        -e MEMORY_WRITE_MODE=$WriteMode `
        "$Python" -m memory_hub.mcp_server | Out-Null
    Install-Instructions "$HOME\.gemini\GEMINI.md" "gemini.md"
    $results.Add("[connected] Gemini CLI")
}
else {
    $results.Add("[skipped]   Gemini CLI (not found on PATH)")
}

# --- Qwen Code -----------------------------------------------------------
$qwenLauncher = Resolve-CliLauncher "qwen"
if ($qwenLauncher) {
    & $qwenLauncher mcp add $ServerName -s user `
        -e AI_MEMORY_VAULT="$VaultPath" `
        -e MEMORY_WRITER=qwen `
        -e MEMORY_WRITE_MODE=$WriteMode `
        "$Python" -m memory_hub.mcp_server | Out-Null
    Install-Instructions "$HOME\.qwen\QWEN.md" "qwen.md"
    $results.Add("[connected] Qwen Code")
}
else {
    $results.Add("[skipped]   Qwen Code (not found on PATH)")
}

# --- Codex CLI -------------------------------------------------------------
$codexExe = Find-Codex
if ($codexExe) {
    & $codexExe mcp add $ServerName `
        --env AI_MEMORY_VAULT="$VaultPath" `
        --env MEMORY_WRITER=codex `
        --env MEMORY_WRITE_MODE=$WriteMode `
        -- "$Python" -m memory_hub.mcp_server | Out-Null
    Install-Instructions "$HOME\.codex\AGENTS.md" "codex.md"
    $results.Add("[connected] Codex CLI")
}
else {
    $results.Add("[skipped]   Codex CLI (not found)")
}

# --- Kimi Code -------------------------------------------------------------
if (Get-Command kimi -ErrorAction SilentlyContinue) {
    $kimiHome = if ($env:KIMI_CODE_HOME) { $env:KIMI_CODE_HOME } else { Join-Path $HOME ".kimi-code" }
    $mcpJsonPath = Join-Path $kimiHome "mcp.json"

    if (Test-Path $mcpJsonPath) {
        $config = Get-Content -Raw -Path $mcpJsonPath | ConvertFrom-Json
        if (-not $config.mcpServers) {
            $config | Add-Member -MemberType NoteProperty -Name mcpServers -Value ([PSCustomObject]@{})
        }
    }
    else {
        $config = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
    }

    $entry = [PSCustomObject]@{
        command = $Python
        args    = @("-m", "memory_hub.mcp_server")
        env     = [PSCustomObject]@{
            AI_MEMORY_VAULT   = $VaultPath
            MEMORY_WRITER     = "kimi"
            MEMORY_WRITE_MODE = $WriteMode
        }
    }
    $config.mcpServers | Add-Member -MemberType NoteProperty -Name $ServerName -Value $entry -Force

    if (-not (Test-Path $kimiHome)) { New-Item -ItemType Directory -Force -Path $kimiHome | Out-Null }
    $config | ConvertTo-Json -Depth 10 | Set-Content -Path $mcpJsonPath

    Install-Instructions (Join-Path $kimiHome "AGENTS.md") "kimi.md"
    $results.Add("[connected] Kimi Code")
}
else {
    $results.Add("[skipped]   Kimi Code (not found on PATH)")
}

# --- Summary -----------------------------------------------------------
Write-Host ""
Write-Host "AI Memory Hub connection summary"
Write-Host "================================="
$results | ForEach-Object { Write-Host $_ }
Write-Host ""
Write-Host "Vault:      $VaultPath"
Write-Host "Write mode: $WriteMode"
Write-Host ""
Write-Host "ChatGPT (desktop app) and any other MCP-capable tool without a CLI"
Write-Host "must be connected manually. See client-prompts/ and README.md."
Write-Host ""
Write-Host "Open the dashboard any time with:"
Write-Host "  .\start-dashboard.ps1 -VaultPath `"$VaultPath`""
