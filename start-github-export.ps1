param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$VaultPath,

    [int]$IntervalSeconds = 30
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Run setup.ps1 with your vault path first."
}
$env:AI_MEMORY_VAULT = $VaultPath
Push-Location $PSScriptRoot
try {
    & $Python -m memory_hub.github_export --vault $VaultPath --interval-seconds $IntervalSeconds
    if ($LASTEXITCODE -ne 0) { throw "AI Memory Hub GitHub exporter exited with code $LASTEXITCODE." }
}
finally { Pop-Location }
