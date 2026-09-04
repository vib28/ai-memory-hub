<#
.SYNOPSIS
    One-line bootstrap installer for AI Memory Hub — the script `irm | iex` downloads and runs.

.DESCRIPTION
    Meant to be run remotely, before you have a local copy of the repo:

        irm https://raw.githubusercontent.com/vib28/ai-memory-hub/master/install.ps1 | iex

    It downloads the repo (via git clone if git is available, otherwise a plain zip
    download — no dependencies required either way), then runs setup.ps1 and, unless
    told not to, connect-ai-tools.ps1 against it.

    If you already have the repo cloned, use .\setup.ps1 directly instead — this script
    is specifically for getting a first copy onto a machine that doesn't have one yet.

.PARAMETER InstallPath
    Where to put the repo. Defaults to "$HOME\ai-memory-hub". If this already exists
    and looks like a previous install of this repo, it's updated in place rather than
    re-downloaded.

.PARAMETER VaultPath
    Absolute path to your Obsidian (or plain folder) memory vault.
    Defaults to "$HOME\Documents\Obsidian\AI-Memory".

.PARAMETER Branch
    Branch to download. Defaults to "master".

.PARAMETER SkipConnect
    Skip running connect-ai-tools.ps1 after setup — just install and initialize the vault.

.EXAMPLE
    irm https://raw.githubusercontent.com/vib28/ai-memory-hub/master/install.ps1 | iex

.EXAMPLE
    # `| iex` alone can't pass parameters — build a scriptblock from the
    # downloaded text instead, then invoke that with normal arguments.
    & ([scriptblock]::Create((irm https://raw.githubusercontent.com/vib28/ai-memory-hub/master/install.ps1))) `
        -InstallPath "C:\Tools\ai-memory-hub" -VaultPath "C:\Users\YOU\Documents\Obsidian\AI-Memory"
#>

param(
    [ValidateNotNullOrEmpty()]
    [string]$InstallPath = (Join-Path $HOME "ai-memory-hub"),

    [ValidateNotNullOrEmpty()]
    [string]$VaultPath = (Join-Path $HOME "Documents\Obsidian\AI-Memory"),

    [ValidateNotNullOrEmpty()]
    [string]$Branch = "master",

    [switch]$SkipConnect
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoUrl = "https://github.com/vib28/ai-memory-hub.git"
$ZipUrl = "https://github.com/vib28/ai-memory-hub/archive/refs/heads/$Branch.zip"

function Get-RepoViaGit {
    if (Test-Path (Join-Path $InstallPath ".git")) {
        Write-Host "Existing install found at $InstallPath — updating it..."
        Push-Location $InstallPath
        try {
            git fetch origin $Branch
            if ($LASTEXITCODE -ne 0) { throw "git fetch failed (exit code $LASTEXITCODE)." }
            git checkout $Branch
            if ($LASTEXITCODE -ne 0) { throw "git checkout failed (exit code $LASTEXITCODE)." }
            git pull origin $Branch
            if ($LASTEXITCODE -ne 0) { throw "git pull failed (exit code $LASTEXITCODE)." }
        }
        finally {
            Pop-Location
        }
    }
    else {
        Write-Host "Cloning into $InstallPath..."
        git clone --branch $Branch $RepoUrl $InstallPath
        if ($LASTEXITCODE -ne 0) { throw "git clone failed (exit code $LASTEXITCODE)." }
    }
}

function Get-RepoViaZip {
    Write-Host "git not found — downloading a zip archive instead..."
    if (Test-Path $InstallPath) {
        $existing = Get-ChildItem -Path $InstallPath -Force -ErrorAction SilentlyContinue
        if ($existing) {
            throw "InstallPath '$InstallPath' already exists and is not empty, and git isn't available to update it in place. Pick a different -InstallPath, remove the existing folder, or install git and re-run."
        }
    }

    $tempZip = Join-Path ([System.IO.Path]::GetTempPath()) "ai-memory-hub-$Branch-$([guid]::NewGuid()).zip"
    $tempExtract = Join-Path ([System.IO.Path]::GetTempPath()) "ai-memory-hub-extract-$([guid]::NewGuid())"

    try {
        Write-Host "Downloading $ZipUrl..."
        Invoke-WebRequest -Uri $ZipUrl -OutFile $tempZip -UseBasicParsing

        Write-Host "Extracting..."
        Expand-Archive -Path $tempZip -DestinationPath $tempExtract -Force

        # GitHub's zip contains one top-level folder named "ai-memory-hub-<branch>".
        $extractedRoot = Get-ChildItem -Path $tempExtract -Directory | Select-Object -First 1
        if (-not $extractedRoot) {
            throw "Downloaded archive didn't contain the expected folder structure."
        }

        $parent = Split-Path $InstallPath -Parent
        if ($parent -and -not (Test-Path $parent)) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Move-Item -Path $extractedRoot.FullName -Destination $InstallPath -Force
    }
    finally {
        Remove-Item -Path $tempZip -Force -ErrorAction SilentlyContinue
        Remove-Item -Path $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "AI Memory Hub installer"
Write-Host "========================"
Write-Host "Install path: $InstallPath"
Write-Host "Vault path:   $VaultPath"
Write-Host ""

if (Get-Command git -ErrorAction SilentlyContinue) {
    Get-RepoViaGit
}
else {
    Get-RepoViaZip
}

$SetupScript = Join-Path $InstallPath "setup.ps1"
if (-not (Test-Path $SetupScript)) {
    throw "setup.ps1 not found at $SetupScript — the download may have failed or landed in an unexpected layout."
}

Write-Host ""
Write-Host "Running setup.ps1..."
& $SetupScript -VaultPath $VaultPath

if (-not $SkipConnect) {
    $ConnectScript = Join-Path $InstallPath "connect-ai-tools.ps1"
    Write-Host ""
    Write-Host "Connecting AI tools installed on this machine..."
    & $ConnectScript -VaultPath $VaultPath
}

Write-Host ""
Write-Host "Installed at: $InstallPath"
Write-Host "Open the dashboard any time with:"
Write-Host "  cd `"$InstallPath`""
Write-Host "  .\start-dashboard.ps1 -VaultPath `"$VaultPath`""
