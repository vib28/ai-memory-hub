param(
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()]
    [string]$VaultPath
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv was not found on PATH. Install uv (see README.md / INSTALLATION_GUIDE.md), open a new terminal, then re-run this script."
}

# Run everything relative to the script's own directory, not the caller's
# working directory — otherwise invoking this via a full path from elsewhere
# creates .venv in the wrong place.
Push-Location $PSScriptRoot
try {
    Write-Host "Creating virtual environment and installing dependencies with uv..."
    uv sync
    if ($LASTEXITCODE -ne 0) {
        throw "uv dependency installation failed (exit code $LASTEXITCODE). Check the output above."
    }

    $Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
    if (-not (Test-Path $Python)) {
        throw "Virtual environment creation reported success, but $Python is missing."
    }

    Write-Host "Initializing vault..."
    & $Python -m memory_hub.cli --vault $VaultPath init
    if ($LASTEXITCODE -ne 0) {
        throw "Vault initialization failed (exit code $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Done."
Write-Host "Vault: $VaultPath"
Write-Host ""
Write-Host "Activate with:"
Write-Host "  .\.venv\Scripts\Activate.ps1"
Write-Host ""
Write-Host "Run MCP server with:"
Write-Host "  `$env:AI_MEMORY_VAULT=`"$VaultPath`""
Write-Host "  `$env:MEMORY_WRITER=`"chatgpt`""
Write-Host "  python -m memory_hub.mcp_server"
Write-Host ""
Write-Host "Or connect every AI tool this machine has installed:"
Write-Host "  .\connect-ai-tools.ps1 -VaultPath `"$VaultPath`""
