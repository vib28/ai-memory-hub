param(
    [Parameter(Mandatory=$true)]
    [string]$VaultPath
)

$ErrorActionPreference = "Stop"

Write-Host "Creating virtual environment..."
python -m venv .venv

$Python = Join-Path $PWD ".venv\Scripts\python.exe"
$Pip = Join-Path $PWD ".venv\Scripts\pip.exe"

Write-Host "Installing dependencies..."
& $Python -m pip install --upgrade pip
& $Pip install -e .

Write-Host "Initializing vault..."
& $Python -m memory_hub.cli --vault $VaultPath init

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
