param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$VaultPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found at $Python. Run .\setup.ps1 -VaultPath `"$VaultPath`" first."
}
if (-not (Test-Path $VaultPath)) {
    Write-Warning "Vault path does not exist yet: $VaultPath. Run .\setup.ps1 -VaultPath `"$VaultPath`" to initialize it, or continue if you expect the dashboard to create it."
}

& $Python -m memory_hub.dashboard --vault $VaultPath
if ($LASTEXITCODE -ne 0) {
    throw "The dashboard exited with an error (code $LASTEXITCODE). See the output above for details."
}
