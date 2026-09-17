param(
    [switch]$SkipWizard
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPath = Join-Path $projectRoot ".venv"
$pythonPath = Join-Path $venvPath "Scripts\python.exe"

function Find-CompatiblePython {
    $candidates = @(
        [PSCustomObject]@{ Command = "py"; Arguments = @("-3.12") },
        [PSCustomObject]@{ Command = "py"; Arguments = @("-3.13") },
        [PSCustomObject]@{ Command = "py"; Arguments = @("-3.14") },
        [PSCustomObject]@{ Command = "py"; Arguments = @("-3.11") },
        [PSCustomObject]@{ Command = "py"; Arguments = @() },
        [PSCustomObject]@{ Command = "python"; Arguments = @() },
        [PSCustomObject]@{ Command = "python3"; Arguments = @() }
    )

    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate.Command -ErrorAction SilentlyContinue)) {
            continue
        }
        $arguments = @($candidate.Arguments)
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "SilentlyContinue"
            $null = & $candidate.Command @arguments -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>&1
            $probeExitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($probeExitCode -eq 0) {
            return $candidate
        }
    }
    return $null
}

function Install-PythonWithWinget {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        return $false
    }

    Write-Host "Python 3.11 or newer was not found."
    $answer = Read-Host "Install the recommended Python 3.12 with winget? [Y/N]"
    if ($answer -notmatch "(?i)^(y|yes|д|да)$") {
        return $false
    }

    & winget install --id Python.Python.3.12 -e --scope user --accept-source-agreements --accept-package-agreements
    return $LASTEXITCODE -eq 0
}

if (-not (Test-Path -LiteralPath $pythonPath)) {
    $python = Find-CompatiblePython
    if ($null -eq $python -and (Install-PythonWithWinget)) {
        $python = Find-CompatiblePython
    }
    if ($null -eq $python) {
        throw @"
Python 3.11 or newer was not found.
Install Python 3.12 x64 and run this script again:
  winget install --id Python.Python.3.12 -e
Download page: https://www.python.org/downloads/windows/
"@
    }

    $arguments = @($python.Arguments)
    $version = & $python.Command @arguments -c "import platform; print(platform.python_version())"
    Write-Host "Using Python $version via: $($python.Command) $($arguments -join ' ')"
    & $python.Command @arguments -m venv $venvPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonPath)) {
        throw "Failed to create the Python virtual environment at $venvPath."
    }
}

& $pythonPath -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Failed to update pip." }
& $pythonPath -m pip install -e $projectRoot
if ($LASTEXITCODE -ne 0) { throw "Failed to install dependencies." }

if (-not $SkipWizard) {
    & $pythonPath -m yt_music_telegram_sync --setup
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Setup was closed without saving. Run setup.ps1 again to retry."
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "Installation completed. Open start_tray.vbs to launch the tray app."
