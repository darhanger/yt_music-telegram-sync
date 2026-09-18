param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version,
    [switch]$Push,
    [switch]$SignCommit,
    [switch]$SignTag
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$versionFile = Join-Path $projectRoot "src\yt_music_telegram_sync\__init__.py"
$tag = "v$Version"

function Invoke-Git {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "git $($Arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git was not found in PATH."
}
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Virtual environment was not found. Run .\setup.ps1 -SkipWizard first."
}

Push-Location $projectRoot
try {
    $workingTree = & git status --porcelain
    if ($LASTEXITCODE -ne 0) {
        throw "Unable to read the Git working tree."
    }
    if ($workingTree) {
        throw "The working tree must be clean before creating a release."
    }

    & git show-ref --verify --quiet "refs/tags/$tag"
    if ($LASTEXITCODE -eq 0) {
        throw "Tag $tag already exists."
    }

    $originalContent = [System.IO.File]::ReadAllText($versionFile)
    $pattern = '__version__ = "\d+\.\d+\.\d+"'
    $versionMatches = [regex]::Matches($originalContent, $pattern)
    if ($versionMatches.Count -ne 1) {
        throw "Unable to locate a single __version__ assignment."
    }
    $currentVersion = $versionMatches[0].Value.Split('"')[1]
    $versionChanged = $currentVersion -ne $Version
    $utf8NoBom = [System.Text.UTF8Encoding]::new($false)
    if ($versionChanged) {
        $updatedContent = [regex]::Replace(
            $originalContent,
            $pattern,
            "__version__ = `"$Version`""
        )
        [System.IO.File]::WriteAllText($versionFile, $updatedContent, $utf8NoBom)
    }

    try {
        & $pythonPath -m pip install -e ".[dev]"
        if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
        & $pythonPath -m ruff check .
        if ($LASTEXITCODE -ne 0) { throw "Ruff failed." }
        & $pythonPath -m mypy src
        if ($LASTEXITCODE -ne 0) { throw "mypy failed." }
        & $pythonPath -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
        & $pythonPath -m pip check
        if ($LASTEXITCODE -ne 0) { throw "Dependency check failed." }

        if ($versionChanged) {
            Invoke-Git @("add", "--", $versionFile)
            $commitArguments = @("commit", "-m", "Release $tag")
            if ($SignCommit) {
                $commitArguments += "-S"
            }
            else {
                $commitArguments += "--no-gpg-sign"
            }
            Invoke-Git $commitArguments
        }
        if ($SignTag) {
            Invoke-Git @("tag", "-s", $tag, "-m", "Release $tag")
        }
        else {
            Invoke-Git @("-c", "tag.gpgSign=false", "tag", "-a", $tag, "-m", "Release $tag")
        }
    }
    catch {
        & git diff --quiet HEAD -- $versionFile
        if ($LASTEXITCODE -ne 0) {
            [System.IO.File]::WriteAllText($versionFile, $originalContent, $utf8NoBom)
            & git reset --quiet HEAD -- $versionFile
        }
        throw
    }

    if ($Push) {
        Invoke-Git @("push", "origin", "HEAD")
        Invoke-Git @("push", "origin", $tag)
        Write-Host "Release $tag was pushed. GitHub Actions will publish it automatically."
    }
    else {
        if ($versionChanged) {
            Write-Host "Release commit and tag $tag were created locally."
        }
        else {
            Write-Host "Version is already $Version; tag $tag was created locally."
        }
        Write-Host "Publish them with: git push origin HEAD; git push origin $tag"
    }
}
finally {
    Pop-Location
}
