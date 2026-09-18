<#
.SYNOPSIS
    Registers the AI Memory Hub MCP server with every supported AI CLI found on this machine.

.DESCRIPTION
    Detects Claude Code, Gemini CLI, Qwen Code, Codex CLI, Kimi Code, and Hermes Agent, then:
      1. Registers ai-memory-hub as an MCP server (user/global scope) for each one found.
      2. Installs the matching client-prompts/<tool>.md behavioral instructions into that
         tool's global memory/instructions file — or, for Hermes Agent, installs the
         ai-memory-hub SKILL.md into its skills directory — so it knows to search and
         propose memories automatically without being told "remember this" every time.

    Run .\setup.ps1 first — this script requires the .venv it creates.

    A failure connecting one tool never blocks the others — each tool is attempted
    independently and reported in the summary at the end. The script exits with a
    non-zero code if anything failed, so it's safe to check in automation too.

.PARAMETER VaultPath
    Absolute path to your Obsidian (or plain folder) memory vault. Required.

.PARAMETER WriteMode
    "review" (default) queues AI-proposed memories in the dashboard for approval.
    "auto" writes valid proposals straight to the vault.

.PARAMETER InstallHooks
    Also install the generic ai-memory-hook PostToolUse receiver into Claude Code's
    settings.json (see #14/#29). Idempotent: safe to pass on every run. Takes a
    timestamped backup of settings.json before writing and touches only the single
    entry it owns — every other hook and setting is left exactly as found. Applies
    to Claude Code, Gemini CLI, Qwen Code, and Kimi Code when those clients are detected.
    Codex hooks use ~/.codex/hooks.json and are installed with the documented PostToolUse
    nested schema.

.PARAMETER RemoveHooks
    Remove the ai-memory-hook entry this script installed from Claude Code's
    settings.json, leaving every unrelated hook and setting untouched. Safe to run
    even if no hook was ever installed. Mutually exclusive with -InstallHooks.

.PARAMETER InstallHandoff
    Install the model-free SessionStart handoff reader for Claude Code and Codex CLI.
    It reads only the local checkpoint manifest and emits a bounded additionalContext
    packet. It is independent from capture hooks and Windows session-auto startup.

.PARAMETER RemoveHandoff
    Remove only the SessionStart handoff entry owned by this project.

.PARAMETER EnableGitHubExport
    Approve one sanitized GitHub destination/visibility and register the local
    outbox publisher in Windows startup. This is separate from memory write mode,
    capture hooks and session-auto.

.PARAMETER DisableGitHubExport
    Disable the owned GitHub export configuration and startup entry.

.PARAMETER GitHubRepo
    GitHub owner/name approved by -EnableGitHubExport.

.PARAMETER GitHubVisibility
    Approved GitHub repository visibility: public, private or internal.

.PARAMETER EnableSessionAuto
    Register the local checkpoint worker in the current user's Windows startup
    entries. The owned value is hidden, reversible and uses the selected write mode.

.PARAMETER DisableSessionAuto
    Remove only the AI Memory Hub startup value created by -EnableSessionAuto.

.EXAMPLE
    .\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory"

.EXAMPLE
    .\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -WriteMode auto

.EXAMPLE
    .\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -InstallHooks

.EXAMPLE
    .\connect-ai-tools.ps1 -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory" -RemoveHooks
#>

param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$VaultPath,

    [ValidateSet("review", "auto")]
    [string]$WriteMode = "review",

    [switch]$InstallHooks,

    [switch]$RemoveHooks,

    [switch]$InstallHandoff,

    [switch]$RemoveHandoff,

    [switch]$EnableGitHubExport,

    [switch]$DisableGitHubExport,

    [string]$GitHubRepo,

    [ValidateSet("public", "private", "internal")]
    [string]$GitHubVisibility = "private",

    [switch]$EnableSessionAuto,

    [switch]$DisableSessionAuto
)

if (($InstallHooks -and $RemoveHooks) -or ($InstallHandoff -and $RemoveHandoff) -or
    ($EnableSessionAuto -and $DisableSessionAuto) -or ($EnableGitHubExport -and $DisableGitHubExport)) {
    throw "Install/remove switches are mutually exclusive; pass at most one of each pair."
}
if ($EnableGitHubExport -and [string]::IsNullOrWhiteSpace($GitHubRepo)) {
    throw "-GitHubRepo owner/name is required with -EnableGitHubExport."
}

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Root = $PSScriptRoot
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$ServerName = "ai-memory-hub"
$WorkerValueName = "AI Memory Hub Session Worker"
$GitHubExportValueName = "AI Memory Hub GitHub Exporter"

if (-not (Test-Path $Python)) {
    throw "Virtual environment not found at $Python. Run .\setup.ps1 -VaultPath `"$VaultPath`" first."
}
if (-not (Test-Path $VaultPath)) {
    Write-Host "Vault path does not exist yet, creating it: $VaultPath"
    New-Item -ItemType Directory -Force -Path $VaultPath | Out-Null
}

$results = [System.Collections.Generic.List[string]]::new()

function Set-SessionAuto {
    param([bool]$Enable)
    $runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $workerScript = Join-Path $Root "start-worker.ps1"
    if ($Enable) {
        $command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$workerScript`" -VaultPath `"$VaultPath`" -WriteMode $WriteMode"
        New-ItemProperty -Path $runKey -Name $WorkerValueName -Value $command -PropertyType String -Force | Out-Null
        $results.Add("[worker]    session-auto enabled ($WriteMode)")
    }
    else {
        Remove-ItemProperty -Path $runKey -Name $WorkerValueName -ErrorAction SilentlyContinue
        $results.Add("[worker]    session-auto disabled")
    }
}

function Set-GitHubExport {
    param([bool]$Enable)
    $runKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    if ($Enable) {
        $output = & $Python -m memory_hub.cli --vault $VaultPath github-export-config --enable --repo $GitHubRepo --visibility $GitHubVisibility 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "GitHub export configuration failed: $($output.Trim())" }
        $exportScript = Join-Path $Root "start-github-export.ps1"
        $command = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$exportScript`" -VaultPath `"$VaultPath`""
        New-ItemProperty -Path $runKey -Name $GitHubExportValueName -Value $command -PropertyType String -Force | Out-Null
        $results.Add("[export]    GitHub exporter enabled ($GitHubRepo / $GitHubVisibility)")
    }
    else {
        $output = & $Python -m memory_hub.cli --vault $VaultPath github-export-config --disable 2>&1 | Out-String
        if ($LASTEXITCODE -ne 0) { throw "GitHub export configuration disable failed: $($output.Trim())" }
        Remove-ItemProperty -Path $runKey -Name $GitHubExportValueName -ErrorAction SilentlyContinue
        $results.Add("[export]    GitHub exporter disabled; queued outbox retained")
    }
}

# #83: -InstallHooks alone must yield a working pipeline. The resident worker is
# the always-fresh path; one-shot children still run without it. -DisableSessionAuto
# remains the opt-out.
if ($InstallHooks -or $EnableSessionAuto) { if (-not $DisableSessionAuto) { Set-SessionAuto $true } }
if ($DisableSessionAuto) { Set-SessionAuto $false }
if ($EnableGitHubExport) { Set-GitHubExport $true }
if ($DisableGitHubExport) { Set-GitHubExport $false }

function Install-Instructions {
    param([string]$TargetPath, [string]$PromptFile)

    $promptPath = Join-Path $Root "client-prompts\$PromptFile"
    if (-not (Test-Path $promptPath)) { return }
    $content = Get-Content -Raw -Encoding UTF8 -Path $promptPath
    $begin = "<!-- AI_MEMORY_HUB_PROMPT:START -->"
    $end = "<!-- AI_MEMORY_HUB_PROMPT:END -->"
    $managed = "$begin`n$content`n$end`n"

    $dir = Split-Path $TargetPath -Parent
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    if (Test-Path $TargetPath) {
        $existing = Get-Content -Raw -Encoding UTF8 -Path $TargetPath
        $marked = '(?s)<!-- AI_MEMORY_HUB_PROMPT:START -->.*?<!-- AI_MEMORY_HUB_PROMPT:END -->(?:\r?\n)?'
        $legacy = '(?s)# Persistent Memory Instructions.*?Writer identity for this client: `[^\r\n]+`\.?'
        if ($existing -match $marked) {
            $updated = [regex]::Replace($existing, $marked, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $managed })
            Set-Content -Encoding UTF8 -NoNewline -Path $TargetPath -Value $updated
        }
        elseif ($existing -match $legacy) {
            $updated = [regex]::Replace($existing, $legacy, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $managed })
            Set-Content -Encoding UTF8 -NoNewline -Path $TargetPath -Value $updated
        }
        elseif ($existing -notmatch "AI Memory Hub") {
            Add-Content -Encoding UTF8 -Path $TargetPath -Value "`n`n$managed"
        }
    }
    else {
        Set-Content -Encoding UTF8 -Path $TargetPath -Value $managed
    }
}

# Claude Code's documented lifecycle-hook schema is configured by this script
# (#29/#66). $CLAUDE_CONFIG_DIR overrides the settings.json location; Claude
# Code itself falls back to ~/.claude when it is unset, so this mirrors that.
function Get-ClaudeSettingsPath {
    $configDir = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $HOME ".claude" }
    return Join-Path $configDir "settings.json"
}

# The receiver has no `python -m memory_hub.capture` entry point (only the
# `ai-memory-hook` console script does), so this points at the venv's own copy
# directly rather than trusting a PATH lookup a hook runner might not have.
function Get-HookCommandPath {
    $hookExe = Join-Path $Root ".venv\Scripts\ai-memory-hook.exe"
    if (-not (Test-Path $hookExe)) {
        throw "ai-memory-hook not found at $hookExe. Run .\setup.ps1 -VaultPath `"$VaultPath`" first."
    }
    return $hookExe
}

function Get-HandoffCommandPath {
    $handoffExe = Join-Path $Root ".venv\Scripts\ai-memory-handoff.exe"
    if (-not (Test-Path $handoffExe)) {
        throw "ai-memory-handoff not found at $handoffExe. Run .\setup.ps1 -VaultPath `"$VaultPath`" first."
    }
    return $handoffExe
}

function Get-ContextCommandPath {
    $contextExe = Join-Path $Root ".venv\Scripts\ai-memory-context.exe"
    if (-not (Test-Path $contextExe)) {
        throw "ai-memory-context not found at $contextExe. Run .\setup.ps1 -VaultPath `"$VaultPath`" first."
    }
    return $contextExe
}

function Invoke-HubHookInstall {
    param(
        [string]$Format,
        [string]$SettingsPath,
        [string]$Event,
        [string]$Command,
        [string[]]$HookArgs,
        [string]$Label,
        [int]$Timeout = 0,
        [int]$ContextLimit = 0
    )
    $cli = @("-m", "memory_hub.cli", "hooks-install", "--settings", $SettingsPath, "--format", $Format, "--event", $Event, "--command", $Command)
    foreach ($item in $HookArgs) { $cli += "--arg=$item" }
    if ($Timeout -gt 0) { $cli += @("--timeout", "$Timeout") }
    if ($ContextLimit -gt 0) { $cli += @("--additional-context-limit", "$ContextLimit") }
    $output = & $Python @cli 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        $results.Add("[failed]    $Label : $($output.Trim())")
        return
    }
    $status = "installed"
    try { $status = ($output | ConvertFrom-Json).status } catch { }
    $results.Add("[hooks]     $Label $status ($SettingsPath)")
}

function Invoke-HubHookUninstall {
    param([string]$Format, [string]$SettingsPath, [string]$Command, [string]$Label)
    $cli = @("-m", "memory_hub.cli", "hooks-uninstall", "--settings", $SettingsPath, "--format", $Format)
    if ($Command) { $cli += @("--command", $Command) }
    $output = & $Python @cli 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        $results.Add("[failed]    $Label : $($output.Trim())")
        return
    }
    $status = "removed"
    try { $status = ($output | ConvertFrom-Json).status } catch { }
    $results.Add("[hooks]     $Label $status ($SettingsPath)")
}

function Install-CaptureHooks {
    param([string]$Client, [string]$Format, [string]$SettingsPath, [string[]]$Events)
    $command = Get-HookCommandPath
    foreach ($event in $Events) {
        Invoke-HubHookInstall -Format $Format -SettingsPath $SettingsPath -Event $event -Command $command -HookArgs @("--client", $Client) -Label "$Client capture $event"
    }
}

function Install-ContextHooks {
    param([string]$HostName, [string]$Format, [string]$SettingsPath, [string]$StartEvent, [string]$TurnEvent, [int]$ContextLimit = 0)
    $command = Get-ContextCommandPath
    Invoke-HubHookInstall -Format $Format -SettingsPath $SettingsPath -Event $StartEvent -Command $command -HookArgs @("--host", $HostName, "--mode", "start") -Label "$HostName context $StartEvent" -ContextLimit $ContextLimit
    Invoke-HubHookInstall -Format $Format -SettingsPath $SettingsPath -Event $TurnEvent -Command $command -HookArgs @("--host", $HostName, "--mode", "turn") -Label "$HostName context $TurnEvent" -ContextLimit $ContextLimit
}

function Remove-CaptureHooks {
    param([string]$Client, [string]$Format, [string]$SettingsPath)
    Invoke-HubHookUninstall -Format $Format -SettingsPath $SettingsPath -Command (Get-HookCommandPath) -Label "$Client capture removal"
}

function Remove-ContextHooks {
    param([string]$HostName, [string]$Format, [string]$SettingsPath)
    Invoke-HubHookUninstall -Format $Format -SettingsPath $SettingsPath -Command (Get-ContextCommandPath) -Label "$HostName context removal"
    # Existing installs used ai-memory-handoff.exe on SessionStart (#86 replacement).
    $handoff = Join-Path $Root ".venv\Scripts\ai-memory-handoff.exe"
    if (Test-Path $handoff) {
        Invoke-HubHookUninstall -Format $Format -SettingsPath $SettingsPath -Command $handoff -Label "$HostName legacy handoff removal"
    }
}

function Get-GeminiSettingsPath {
    $geminiConfigHome = if ($env:GEMINI_CONFIG_DIR) { $env:GEMINI_CONFIG_DIR } else { Join-Path $HOME ".gemini" }
    return Join-Path $geminiConfigHome "settings.json"
}
function Get-QwenSettingsPath {
    $qwenConfigHome = if ($env:QWEN_CONFIG_DIR) { $env:QWEN_CONFIG_DIR } else { Join-Path $HOME ".qwen" }
    return Join-Path $qwenConfigHome "settings.json"
}
function Get-KimiSettingsPath {
    # Kimi Code 2.0.1 reads ~/.kimi-code/config.toml (see moonshotai.github.io/kimi-code).
    $kimiConfigHome = if ($env:KIMI_CODE_HOME) { $env:KIMI_CODE_HOME } else { Join-Path $HOME ".kimi-code" }
    return Join-Path $kimiConfigHome "config.toml"
}
function Get-LegacyKimiSettingsPath {
    $kimiHome = if ($env:KIMI_CONFIG_DIR) { $env:KIMI_CONFIG_DIR } else { Join-Path $HOME ".kimi" }
    return Join-Path $kimiHome "config.toml"
}
function Get-CodexSettingsPath { return Join-Path $HOME ".codex\hooks.json" }
function Install-ClaudeHook {
    Install-CaptureHooks -Client "claude" -Format "claude" -SettingsPath (Get-ClaudeSettingsPath) -Events @(
        "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
        "PreCompact", "PostCompact", "Stop", "StopFailure", "SessionEnd")
}
function Remove-ClaudeHook { Remove-CaptureHooks -Client "Claude Code" -Format "claude" -SettingsPath (Get-ClaudeSettingsPath) }
function Install-ClaudeHandoff {
    Install-ContextHooks -HostName "claude" -Format "claude" -SettingsPath (Get-ClaudeSettingsPath) -StartEvent "SessionStart" -TurnEvent "UserPromptSubmit"
}
function Remove-ClaudeHandoff { Remove-ContextHooks -HostName "claude" -Format "claude" -SettingsPath (Get-ClaudeSettingsPath) }
function Install-CodexHook {
    Install-CaptureHooks -Client "codex" -Format "codex" -SettingsPath (Get-CodexSettingsPath) -Events @(
        "SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
        "PreCompact", "PostCompact", "Stop", "Interrupt", "SessionEnd")
}
function Remove-CodexHook { Remove-CaptureHooks -Client "Codex CLI" -Format "codex" -SettingsPath (Get-CodexSettingsPath) }
function Install-CodexHandoff {
    Install-ContextHooks -HostName "codex" -Format "codex" -SettingsPath (Get-CodexSettingsPath) -StartEvent "SessionStart" -TurnEvent "UserPromptSubmit" -ContextLimit 3000
}
function Remove-CodexHandoff { Remove-ContextHooks -HostName "codex" -Format "codex" -SettingsPath (Get-CodexSettingsPath) }

function Install-GeminiHooks {
    Install-CaptureHooks -Client "gemini" -Format "nested" -SettingsPath (Get-GeminiSettingsPath) -Events @(
        "SessionStart", "SessionEnd", "BeforeTool", "AfterTool", "AfterAgent", "PreCompress")
}
function Remove-GeminiHooks { Remove-CaptureHooks -Client "Gemini CLI" -Format "nested" -SettingsPath (Get-GeminiSettingsPath) }
function Install-GeminiHandoff {
    Install-ContextHooks -HostName "gemini" -Format "nested" -SettingsPath (Get-GeminiSettingsPath) -StartEvent "SessionStart" -TurnEvent "BeforeAgent"
}
function Remove-GeminiHandoff { Remove-ContextHooks -HostName "gemini" -Format "nested" -SettingsPath (Get-GeminiSettingsPath) }

function Install-QwenHooks {
    Install-CaptureHooks -Client "qwen" -Format "nested" -SettingsPath (Get-QwenSettingsPath) -Events @(
        "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
        "Stop", "StopFailure", "PreCompact", "PostCompact")
}
function Remove-QwenHooks { Remove-CaptureHooks -Client "Qwen Code" -Format "nested" -SettingsPath (Get-QwenSettingsPath) }
function Install-QwenHandoff {
    Install-ContextHooks -HostName "qwen" -Format "nested" -SettingsPath (Get-QwenSettingsPath) -StartEvent "SessionStart" -TurnEvent "UserPromptSubmit"
}
function Remove-QwenHandoff { Remove-ContextHooks -HostName "qwen" -Format "nested" -SettingsPath (Get-QwenSettingsPath) }

function Install-KimiHooks {
    Install-CaptureHooks -Client "kimi" -Format "kimi-toml" -SettingsPath (Get-KimiSettingsPath) -Events @(
        "SessionStart", "SessionEnd", "UserPromptSubmit", "PreToolUse", "PostToolUse", "PostToolUseFailure",
        "Stop", "StopFailure", "Interrupt", "PreCompact", "PostCompact", "SessionHeartbeat")
}
function Remove-KimiHooks {
    Remove-CaptureHooks -Client "Kimi Code" -Format "kimi-toml" -SettingsPath (Get-KimiSettingsPath)
    $legacy = Get-LegacyKimiSettingsPath
    if (Test-Path $legacy) {
        Invoke-HubHookUninstall -Format "kimi-toml" -SettingsPath $legacy -Command (Get-HookCommandPath) -Label "Kimi Code legacy ~/.kimi capture removal"
    }
}
function Install-KimiHandoff {
    Install-ContextHooks -HostName "kimi" -Format "kimi-toml" -SettingsPath (Get-KimiSettingsPath) -StartEvent "SessionStart" -TurnEvent "UserPromptSubmit"
}
function Remove-KimiHandoff { Remove-ContextHooks -HostName "kimi" -Format "kimi-toml" -SettingsPath (Get-KimiSettingsPath) }

function Find-Codex {
    $cmd = Get-Command codex -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { return $cmd.Source }
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
    if ($cmdShim -and $cmdShim.Source) { return $cmdShim.Source }
    $bare = Get-Command $Name -ErrorAction SilentlyContinue
    if ($bare -and $bare.Source) { return $bare.Source }
    return $null
}

# A non-zero exit doesn't always mean failure here — e.g. Claude Code exits
# 1 with "already exists" if the server is already registered. Treat that
# as success too, since the end state (server registered) is what we want.
function Test-AlreadyRegistered {
    param([string]$Output)
    return $Output -match "already exists|already configured|updated in user settings"
}

# --- Claude Code -------------------------------------------------------
$claudeLauncher = Resolve-CliLauncher "claude"
if ($claudeLauncher) {
    try {
        $output = & $claudeLauncher mcp add $ServerName -s user `
            -e AI_MEMORY_VAULT="$VaultPath" `
            -e MEMORY_WRITER=claude `
            -e MEMORY_WRITE_MODE=$WriteMode `
            -- "$Python" -m memory_hub.mcp_server 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -or (Test-AlreadyRegistered $output)) {
            Install-Instructions "$HOME\.claude\CLAUDE.md" "claude.md"
            $results.Add("[connected] Claude Code")
            if ($InstallHooks) { Install-ClaudeHook }
            if ($RemoveHooks) { Remove-ClaudeHook }
            if ($InstallHandoff) { Install-ClaudeHandoff }
            if ($RemoveHandoff) { Remove-ClaudeHandoff }
        }
        else {
            $results.Add("[failed]    Claude Code (exit ${LASTEXITCODE}): $($output.Trim())")
        }
    }
    catch {
        if (Test-AlreadyRegistered $_.Exception.Message) {
            Install-Instructions "$HOME\.claude\CLAUDE.md" "claude.md"
            $results.Add("[connected] Claude Code")
            if ($InstallHooks) { Install-ClaudeHook }
            if ($RemoveHooks) { Remove-ClaudeHook }
            if ($InstallHandoff) { Install-ClaudeHandoff }
            if ($RemoveHandoff) { Remove-ClaudeHandoff }
        }
        else {
            $results.Add("[failed]    Claude Code ($($_.Exception.Message))")
        }
    }
}
else {
    $results.Add("[skipped]   Claude Code (not found on PATH)")
    if ($InstallHooks -or $RemoveHooks) {
        $results.Add("[skipped]   Claude Code hooks (Claude Code CLI not found on PATH)")
    }
    if ($InstallHandoff -or $RemoveHandoff) {
        $results.Add("[skipped]   Claude Code handoff (Claude Code CLI not found on PATH)")
    }
}

# --- Gemini CLI ----------------------------------------------------------
$geminiLauncher = Resolve-CliLauncher "gemini"
if ($geminiLauncher) {
    try {
        $output = & $geminiLauncher mcp add $ServerName -s user `
            -e AI_MEMORY_VAULT="$VaultPath" `
            -e MEMORY_WRITER=gemini `
            -e MEMORY_WRITE_MODE=$WriteMode `
            "$Python" -m memory_hub.mcp_server 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -or (Test-AlreadyRegistered $output)) {
            Install-Instructions "$HOME\.gemini\GEMINI.md" "gemini.md"
            $results.Add("[connected] Gemini CLI")
            if ($InstallHooks) { Install-GeminiHooks }
            if ($RemoveHooks) { Remove-GeminiHooks }
            if ($InstallHandoff) { Install-GeminiHandoff }
            if ($RemoveHandoff) { Remove-GeminiHandoff }
        }
        else {
            $results.Add("[failed]    Gemini CLI (exit ${LASTEXITCODE}): $($output.Trim())")
        }
    }
    catch {
        if (Test-AlreadyRegistered $_.Exception.Message) {
            Install-Instructions "$HOME\.gemini\GEMINI.md" "gemini.md"
            $results.Add("[connected] Gemini CLI")
            if ($InstallHooks) { Install-GeminiHooks }
            if ($RemoveHooks) { Remove-GeminiHooks }
            if ($InstallHandoff) { Install-GeminiHandoff }
            if ($RemoveHandoff) { Remove-GeminiHandoff }
        }
        else {
            $results.Add("[failed]    Gemini CLI ($($_.Exception.Message))")
        }
    }
}
else {
    $results.Add("[skipped]   Gemini CLI (not found on PATH)")
    if ($InstallHooks -or $RemoveHooks) { $results.Add("[skipped]   Gemini CLI hooks (Gemini CLI not found on PATH)") }
    if ($InstallHandoff -or $RemoveHandoff) { $results.Add("[skipped]   Gemini CLI handoff (Gemini CLI not found on PATH)") }
}

# --- Qwen Code -----------------------------------------------------------
$qwenLauncher = Resolve-CliLauncher "qwen"
if ($qwenLauncher) {
    try {
        $output = & $qwenLauncher mcp add $ServerName -s user `
            -e AI_MEMORY_VAULT="$VaultPath" `
            -e MEMORY_WRITER=qwen `
            -e MEMORY_WRITE_MODE=$WriteMode `
            "$Python" -m memory_hub.mcp_server 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -or (Test-AlreadyRegistered $output)) {
            Install-Instructions "$HOME\.qwen\QWEN.md" "qwen.md"
            $results.Add("[connected] Qwen Code")
            if ($InstallHooks) { Install-QwenHooks }
            if ($RemoveHooks) { Remove-QwenHooks }
            if ($InstallHandoff) { Install-QwenHandoff }
            if ($RemoveHandoff) { Remove-QwenHandoff }
        }
        else {
            $results.Add("[failed]    Qwen Code (exit ${LASTEXITCODE}): $($output.Trim())")
        }
    }
    catch {
        if (Test-AlreadyRegistered $_.Exception.Message) {
            Install-Instructions "$HOME\.qwen\QWEN.md" "qwen.md"
            $results.Add("[connected] Qwen Code")
            if ($InstallHooks) { Install-QwenHooks }
            if ($RemoveHooks) { Remove-QwenHooks }
            if ($InstallHandoff) { Install-QwenHandoff }
            if ($RemoveHandoff) { Remove-QwenHandoff }
        }
        else {
            $results.Add("[failed]    Qwen Code ($($_.Exception.Message))")
        }
    }
}
else {
    $results.Add("[skipped]   Qwen Code (not found on PATH)")
    if ($InstallHooks -or $RemoveHooks) { $results.Add("[skipped]   Qwen Code hooks (Qwen Code CLI not found on PATH)") }
    if ($InstallHandoff -or $RemoveHandoff) { $results.Add("[skipped]   Qwen Code handoff (Qwen Code CLI not found on PATH)") }
}

# --- Codex CLI -------------------------------------------------------------
$codexExe = Find-Codex
if ($codexExe) {
    try {
        $output = & $codexExe mcp add $ServerName `
            --env AI_MEMORY_VAULT="$VaultPath" `
            --env MEMORY_WRITER=codex `
            --env MEMORY_WRITE_MODE=$WriteMode `
            -- "$Python" -m memory_hub.mcp_server 2>&1 | Out-String
        if ($LASTEXITCODE -eq 0 -or (Test-AlreadyRegistered $output)) {
            Install-Instructions "$HOME\.codex\AGENTS.md" "codex.md"
            $results.Add("[connected] Codex CLI")
            if ($InstallHooks) { Install-CodexHook }
            if ($RemoveHooks) { Remove-CodexHook }
            if ($InstallHandoff) { Install-CodexHandoff }
            if ($RemoveHandoff) { Remove-CodexHandoff }
        }
        else {
            $results.Add("[failed]    Codex CLI (exit ${LASTEXITCODE}): $($output.Trim())")
        }
    }
    catch {
        if (Test-AlreadyRegistered $_.Exception.Message) {
            Install-Instructions "$HOME\.codex\AGENTS.md" "codex.md"
            $results.Add("[connected] Codex CLI")
            if ($InstallHooks) { Install-CodexHook }
            if ($RemoveHooks) { Remove-CodexHook }
            if ($InstallHandoff) { Install-CodexHandoff }
            if ($RemoveHandoff) { Remove-CodexHandoff }
        }
        else {
            $results.Add("[failed]    Codex CLI ($($_.Exception.Message))")
        }
    }
}
else {
    $results.Add("[skipped]   Codex CLI (not found)")
    if ($InstallHooks -or $RemoveHooks) { $results.Add("[skipped]   Codex CLI hooks (Codex CLI not found)") }
    if ($InstallHandoff -or $RemoveHandoff) { $results.Add("[skipped]   Codex CLI handoff (Codex CLI not found)") }
}

# --- Kimi Code -------------------------------------------------------------
# Kimi has no `mcp add` CLI command, so this edits its mcp.json config file
# directly. Wrapped in its own try/catch so a locked/corrupt config file
# doesn't take down the rest of the script.
if (Get-Command kimi -ErrorAction SilentlyContinue) {
    try {
        $kimiHome = if ($env:KIMI_CODE_HOME) { $env:KIMI_CODE_HOME } else { Join-Path $HOME ".kimi-code" }
        $mcpJsonPath = Join-Path $kimiHome "mcp.json"

        if (Test-Path $mcpJsonPath) {
            try {
                $config = Get-Content -Raw -Path $mcpJsonPath | ConvertFrom-Json
            }
            catch {
                $backupPath = "$mcpJsonPath.bak-$(Get-Date -Format 'yyyyMMddHHmmss')"
                Copy-Item -Path $mcpJsonPath -Destination $backupPath
                Write-Warning "Existing $mcpJsonPath was not valid JSON. Backed it up to $backupPath and starting a fresh config."
                $config = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
            }
        }
        else {
            $config = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
        }

        if (-not ($config.PSObject.Properties.Name -contains "mcpServers")) {
            $config | Add-Member -MemberType NoteProperty -Name mcpServers -Value ([PSCustomObject]@{})
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
        if ($InstallHooks) { Install-KimiHooks }
        if ($RemoveHooks) { Remove-KimiHooks }
        if ($InstallHandoff) { Install-KimiHandoff }
        if ($RemoveHandoff) { Remove-KimiHandoff }
    }
    catch {
        $results.Add("[failed]    Kimi Code ($($_.Exception.Message))")
    }
}
else {
    $results.Add("[skipped]   Kimi Code (not found on PATH)")
    if ($InstallHooks -or $RemoveHooks) { $results.Add("[skipped]   Kimi Code hooks (Kimi Code CLI not found on PATH)") }
    if ($InstallHandoff -or $RemoveHandoff) { $results.Add("[skipped]   Kimi Code handoff (Kimi Code CLI not found on PATH)") }
}

# --- Hermes Agent ------------------------------------------------------------
# Hermes Agent (Nous Research) has a native MCP client and discovers skills by
# scanning its skills/ directory. Two things are needed: register ai-memory-hub
# as an MCP server, AND install the ai-memory-hub SKILL.md (Hermes does not read
# client-prompts/). Hermes needs a distinct server name (ai_memory_hub) because it
# prefixes tools mcp_{server}_{tool}.
$hermesLauncher = Resolve-CliLauncher "hermes"
if ($hermesLauncher) {
    $hermesServer = "ai_memory_hub"
    try {
        $hermesConfig = (& hermes config path 2>&1 | Out-String).Trim()
        if (-not $hermesConfig -or -not (Test-Path $hermesConfig)) {
            throw "Could not resolve Hermes config path ('hermes config path')."
        }
        $hermesHome = Split-Path -Parent $hermesConfig
        $skillDestDir = Join-Path $hermesHome "skills\productivity\ai-memory-hub"
        $skillSource = Join-Path $Root "hermes\skills\ai-memory-hub\SKILL.md"

        $mcpList = (& hermes mcp list 2>&1 | Out-String)
        if ($mcpList -match [regex]::Escape($hermesServer)) {
            $results.Add("[connected] Hermes Agent (server already registered)")
        }
        else {
            # --env MUST precede --args (args is the greedy last option), or the
            # env vars get swallowed into args and the server loses its vault.
            $regOut = "Y" | & $hermesLauncher mcp add $hermesServer `
                --env "AI_MEMORY_VAULT=$VaultPath" `
                --env "MEMORY_WRITER=hermes" `
                --env "MEMORY_WRITE_MODE=$WriteMode" `
                --command $Python `
                --args -m memory_hub.mcp_server 2>&1 | Out-String
            if ($LASTEXITCODE -eq 0 -and $regOut -match "Saved '$hermesServer'") {
                $results.Add("[connected] Hermes Agent")
            }
            else {
                $results.Add("[failed]    Hermes Agent (exit ${LASTEXITCODE}): $($regOut.Trim())")
            }
        }

        # Install the skill regardless (idempotent refresh to this repo's copy).
        if (Test-Path $skillSource) {
            if (-not (Test-Path $skillDestDir)) {
                New-Item -ItemType Directory -Force -Path $skillDestDir | Out-Null
            }
            Copy-Item -Force -Path $skillSource -Destination (Join-Path $skillDestDir "SKILL.md")
            $results.Add("[skill]     Hermes Agent -> $skillDestDir\SKILL.md")
        }
        else {
            $results.Add("[failed]    Hermes Agent (skill source missing: $skillSource)")
        }

        if ($InstallHooks) {
            Install-CaptureHooks -Client "hermes" -Format "hermes-yaml" -SettingsPath $hermesConfig -Events @("post_tool_call", "on_session_end")
        }
        if ($RemoveHooks) {
            Remove-CaptureHooks -Client "Hermes Agent" -Format "hermes-yaml" -SettingsPath $hermesConfig
        }
        if ($InstallHandoff) {
            # Hermes injects only from pre_llm_call; first turn is treated as start (#86).
            Invoke-HubHookInstall -Format "hermes-yaml" -SettingsPath $hermesConfig -Event "pre_llm_call" -Command (Get-ContextCommandPath) -HookArgs @("--host", "hermes", "--mode", "auto") -Label "Hermes Agent context pre_llm_call" -Timeout 20
            $results.Add("[consent]   Hermes will prompt once to approve each (event, command) hook. hooks_auto_accept is not set.")
        }
        if ($RemoveHandoff) {
            Remove-ContextHooks -HostName "hermes" -Format "hermes-yaml" -SettingsPath $hermesConfig
        }
    }
    catch {
        $results.Add("[failed]    Hermes Agent ($($_.Exception.Message))")
    }
}
else {
    $results.Add("[skipped]   Hermes Agent (not found on PATH)")
    if ($InstallHooks -or $RemoveHooks) { $results.Add("[skipped]   Hermes Agent hooks (Hermes not found on PATH)") }
    if ($InstallHandoff -or $RemoveHandoff) { $results.Add("[skipped]   Hermes Agent handoff (Hermes not found on PATH)") }
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
Write-Host "ChatGPT (desktop app): run .\connect-chatgpt-tunnel.ps1 separately."
Write-Host "It needs one-time OpenAI account setup; see README.md."
Write-Host "Any other MCP-capable tool without a CLI must be connected manually."
Write-Host "See client-prompts/ and README.md."
Write-Host ""
Write-Host "IMPORTANT: each tool reads its MCP server list once, at session start."
Write-Host "If you already had a Claude Code / Gemini CLI / Qwen Code / Codex CLI /"
Write-Host "Kimi Code / Hermes Agent session open, close it and start a new one - it"
Write-Host "will not see ai-memory-hub until it does. New sessions pick it up"
Write-Host "automatically (Hermes also auto-loads the skill when relevant)."
if ($results | Where-Object { $_ -like "*Gemini CLI*" -and $_ -like "*connected*" }) {
    Write-Host ""
    Write-Host "Gemini CLI note: it disables ALL MCP servers in a folder it doesn't yet"
    Write-Host "trust. Answer its workspace-trust prompt on first launch there, then"
    Write-Host "check with: gemini mcp list"
}
Write-Host ""
Write-Host "Open the dashboard any time with:"
Write-Host "  .\start-dashboard.ps1 -VaultPath `"$VaultPath`""

if ($results | Where-Object { $_ -like "[failed]*" }) {
    exit 1
}
