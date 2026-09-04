param(
    [Parameter(Mandatory=$true)]
    [string]$VaultPath
)
$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (!(Test-Path $Python)) {
    throw "Virtual environment not found. Run setup.ps1 first."
}
& $Python -m memory_hub.dashboard --vault $VaultPath
