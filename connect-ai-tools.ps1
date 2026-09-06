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
    to Claude Code, Gemini CLI, and Qwen Code when those clients are detected. Kimi and
    Codex hook schemas are not installed automatically until their adapters are verified.

.PARAMETER RemoveHooks
    Remove the ai-memory-hook entry this script installed from Claude Code's
    settings.json, leaving every unrelated hook and setting untouched. Safe to run
    even if no hook was ever installed. Mutually exclusive with -InstallHooks.

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

    [switch]$RemoveHooks
)

if ($InstallHooks -and $RemoveHooks) {
    throw "-InstallHooks and -RemoveHooks are mutually exclusive; pass at most one."
}

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

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

# Claude Code's PostToolUse hooks are the only lifecycle-hook schema this script
# wires up (#29). $CLAUDE_CONFIG_DIR overrides the settings.json location; Claude
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

function Install-ClaudeHook {
    $settingsPath = Get-ClaudeSettingsPath
    $hookCommand = Get-HookCommandPath
    $output = & $Python -m memory_hub.cli hooks-install --settings $settingsPath --event PostToolUse --command $hookCommand 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        $results.Add("[failed]    Claude Code hook install: $($output.Trim())")
        return
    }
    $status = ($output | ConvertFrom-Json).status
    switch ($status) {
        "installed"         { $results.Add("[hooks]     Claude Code hook installed ($settingsPath)") }
        "already_installed" { $results.Add("[hooks]     Claude Code hook already installed ($settingsPath)") }
        default             { $results.Add("[hooks]     Claude Code hook install: $status ($settingsPath)") }
    }
}

function Remove-ClaudeHook {
    $settingsPath = Get-ClaudeSettingsPath
    $output = & $Python -m memory_hub.cli hooks-uninstall --settings $settingsPath 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        $results.Add("[failed]    Claude Code hook removal: $($output.Trim())")
        return
    }
    $status = ($output | ConvertFrom-Json).status
    switch ($status) {
        "removed"   { $results.Add("[hooks]     Claude Code hook removed ($settingsPath)") }
        "not_found" { $results.Add("[hooks]     Claude Code hook already absent ($settingsPath)") }
        default     { $results.Add("[hooks]     Claude Code hook removal: $status ($settingsPath)") }
    }
}

function Install-NestedClientHook {
    param([string]$Client, [string]$SettingsPath, [string]$Event)
    $hookCommand = Get-HookCommandPath
    $output = & $Python -m memory_hub.cli hooks-install --settings $SettingsPath --format nested --event $Event --command $hookCommand 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        $results.Add("[failed]    $Client hook install: $($output.Trim())")
        return
    }
    $status = ($output | ConvertFrom-Json).status
    $results.Add("[hooks]     $Client hook $status ($SettingsPath)")
}

function Remove-NestedClientHook {
    param([string]$Client, [string]$SettingsPath)
    $output = & $Python -m memory_hub.cli hooks-uninstall --settings $SettingsPath --format nested 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) {
        $results.Add("[failed]    $Client hook removal: $($output.Trim())")
        return
    }
    $status = ($output | ConvertFrom-Json).status
    $results.Add("[hooks]     $Client hook $status ($SettingsPath)")
}

function Get-GeminiSettingsPath { return Join-Path $HOME ".gemini\settings.json" }
function Get-QwenSettingsPath { return Join-Path $HOME ".qwen\settings.json" }

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
            if ($InstallHooks) { Install-NestedClientHook "Gemini CLI" (Get-GeminiSettingsPath) "AfterTool" }
            if ($RemoveHooks) { Remove-NestedClientHook "Gemini CLI" (Get-GeminiSettingsPath) }
        }
        else {
            $results.Add("[failed]    Gemini CLI (exit ${LASTEXITCODE}): $($output.Trim())")
        }
    }
    catch {
        if (Test-AlreadyRegistered $_.Exception.Message) {
            Install-Instructions "$HOME\.gemini\GEMINI.md" "gemini.md"
            $results.Add("[connected] Gemini CLI")
            if ($InstallHooks) { Install-NestedClientHook "Gemini CLI" (Get-GeminiSettingsPath) "AfterTool" }
            if ($RemoveHooks) { Remove-NestedClientHook "Gemini CLI" (Get-GeminiSettingsPath) }
        }
        else {
            $results.Add("[failed]    Gemini CLI ($($_.Exception.Message))")
        }
    }
}
else {
    $results.Add("[skipped]   Gemini CLI (not found on PATH)")
    if ($InstallHooks -or $RemoveHooks) { $results.Add("[skipped]   Gemini CLI hooks (Gemini CLI not found on PATH)") }
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
            if ($InstallHooks) { Install-NestedClientHook "Qwen Code" (Get-QwenSettingsPath) "PostToolUse" }
            if ($RemoveHooks) { Remove-NestedClientHook "Qwen Code" (Get-QwenSettingsPath) }
        }
        else {
            $results.Add("[failed]    Qwen Code (exit ${LASTEXITCODE}): $($output.Trim())")
        }
    }
    catch {
        if (Test-AlreadyRegistered $_.Exception.Message) {
            Install-Instructions "$HOME\.qwen\QWEN.md" "qwen.md"
            $results.Add("[connected] Qwen Code")
            if ($InstallHooks) { Install-NestedClientHook "Qwen Code" (Get-QwenSettingsPath) "PostToolUse" }
            if ($RemoveHooks) { Remove-NestedClientHook "Qwen Code" (Get-QwenSettingsPath) }
        }
        else {
            $results.Add("[failed]    Qwen Code ($($_.Exception.Message))")
        }
    }
}
else {
    $results.Add("[skipped]   Qwen Code (not found on PATH)")
    if ($InstallHooks -or $RemoveHooks) { $results.Add("[skipped]   Qwen Code hooks (Qwen Code CLI not found on PATH)") }
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
        }
        else {
            $results.Add("[failed]    Codex CLI (exit ${LASTEXITCODE}): $($output.Trim())")
        }
    }
    catch {
        $results.Add("[failed]    Codex CLI ($($_.Exception.Message))")
    }
}
else {
    $results.Add("[skipped]   Codex CLI (not found)")
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
    }
    catch {
        $results.Add("[failed]    Kimi Code ($($_.Exception.Message))")
    }
}
else {
    $results.Add("[skipped]   Kimi Code (not found on PATH)")
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
    }
    catch {
        $results.Add("[failed]    Hermes Agent ($($_.Exception.Message))")
    }
}
else {
    $results.Add("[skipped]   Hermes Agent (not found on PATH)")
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
