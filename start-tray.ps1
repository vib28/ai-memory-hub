param(
    [ValidateNotNullOrEmpty()]
    [string]$VaultPath = (Join-Path $env:USERPROFILE "OneDrive\Documents\Memory")
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$Python = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Python)) {
    throw "Virtual environment not found at $Python. Run .\setup.ps1 -VaultPath `"$VaultPath`" first."
}
if (-not (Test-Path $VaultPath)) {
    Write-Warning "Vault path does not exist yet: $VaultPath. Run .\setup.ps1 -VaultPath `"$VaultPath`" to initialize it first."
}

$proc = Start-Process -FilePath $Python -ArgumentList @("-m", "memory_hub.tray", "--vault", $VaultPath) -PassThru

# pythonw.exe has no console, so a crash on startup (e.g. a missing
# dependency) would otherwise fail completely silently. Give it a moment
# and check it's still alive before declaring success.
Start-Sleep -Milliseconds 750
if ($proc.HasExited) {
    throw "The tray process exited immediately (code $($proc.ExitCode)) — it likely failed to start. Run .\start-dashboard.ps1 -VaultPath `"$VaultPath`" instead to see the actual error output."
}

Write-Host "Tray icon launched (PID $($proc.Id))."
