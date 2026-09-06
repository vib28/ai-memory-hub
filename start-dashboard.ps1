param([string]$VaultPath = $env:AI_MEMORY_VAULT, [int]$Port = 8765, [switch]$NoTray)
# Compatibility alias: one application now starts both dashboard and tray.
& (Join-Path $PSScriptRoot "start-memory-hub.ps1") -VaultPath $VaultPath -Port $Port -NoTray:$NoTray
