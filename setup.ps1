$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "Python Launcher was not found. Install Python 3.12 x64 from python.org."
    }
    py -3.12 -m venv $venvPath
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create a Python 3.12 virtual environment."
    }
}

& $pythonPath -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to update pip." }
& $pythonPath -m pip install -e $projectRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to install dependencies." }
& $pythonPath -m yt_music_telegram_sync --setup
if ($LASTEXITCODE -ne 0) {
    Write-Warning "Setup was closed without saving. Run setup.ps1 again to retry."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Installation completed. Open start_tray.vbs to launch the tray app."
