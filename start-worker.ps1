param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$VaultPath,

    [ValidateSet("review", "auto")]
    [string]$WriteMode = "review",

    [string]$BufferPath = $env:MEMORY_CAPTURE_DB
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    throw "Run setup.ps1 with your vault path first."
}
$env:AI_MEMORY_VAULT = $VaultPath
$env:MEMORY_WRITE_MODE = $WriteMode
if ($BufferPath) { $env:MEMORY_CAPTURE_DB = $BufferPath }
Push-Location $PSScriptRoot
try {
    & $Python -m memory_hub.worker
    if ($LASTEXITCODE -ne 0) { throw "AI Memory Hub worker exited with code $LASTEXITCODE." }
}
finally { Pop-Location }
