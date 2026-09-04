param(
    [Parameter(Mandatory=$true)]
    [string]$VaultPath
)
$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (!(Test-Path $Python)) {
    throw "Virtual environment not found. Run setup.ps1 first."
}
Start-Process -FilePath $Python -ArgumentList @("-m","memory_hub.tray","--vault",$VaultPath)
