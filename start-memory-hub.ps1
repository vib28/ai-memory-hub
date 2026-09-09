param(
    [string]$VaultPath = $env:AI_MEMORY_VAULT,
    # MEMORY_DASHBOARD_PORT overrides the default; a malformed value falls back
    # safely to 8765 rather than failing param binding (#81).
    [int]$Port = $(if ($env:MEMORY_DASHBOARD_PORT -and ($env:MEMORY_DASHBOARD_PORT -as [int])) { [int]$env:MEMORY_DASHBOARD_PORT } else { 8765 }),
    [switch]$NoTray
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if (-not $VaultPath) {
    $VaultPath = Join-Path $env:USERPROFILE "OneDrive\Documents\Memory"
}
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Run setup.ps1 with your vault path first."
}
$AppArgs = @("-m", "memory_hub.app", "--vault", $VaultPath, "--port", $Port)
if ($NoTray) { $AppArgs += "--no-tray" }
Push-Location $PSScriptRoot
try {
    & $Python @AppArgs
    if ($LASTEXITCODE -ne 0) { throw "AI Memory Hub exited with code $LASTEXITCODE." }
}
finally { Pop-Location }
