<p align="right">English | <a href="CONTRIBUTING_RU.md">Русский</a></p>

# Contributing

Thank you for your interest in the project. Before starting a substantial change, open an issue describing the problem and the proposed solution.

## Local development

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Keep changes small and focused, preserve the existing architecture and naming, and add regression tests for new behavior. Pull requests must pass the Windows CI matrix for Python 3.11–3.14.

## Pull requests

- Explain the user-visible behavior and any compatibility implications.
- Do not combine unrelated refactoring with a feature or bug fix.
- Update both `README.md` and `README_RU.md` when behavior or setup changes.
- Keep `CONTRIBUTING.md` and `CONTRIBUTING_RU.md` equivalent.

## Releases

Maintainers create a release with a clean working tree:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\release.ps1 -Version 1.2.0 -Push
```

Every successful push to `main` automatically creates a prerelease with a unique tag such as `v1.1.0-build.5.1`. The script above is for stable releases: it updates the application version, runs all checks, creates a release commit when the version changes and the matching `v1.2.0` tag, then pushes both when `-Push` is specified. Pushing the stable tag starts the same release workflow, which verifies the tag, builds the wheel and source archive, and publishes a regular GitHub Release with generated notes.

Commits and tags are unsigned by default so the script also works with a non-interactive GPG setup. Add `-SignCommit -SignTag` when a configured GPG agent is available.

Use semantic versioning: patch for compatible fixes, minor for compatible features, and major for breaking changes.

## Security and privacy

Never include Telegram sessions, API keys, API hashes, phone numbers, configuration files, or personal log fragments in issues, commits, screenshots, or test fixtures. If credentials were exposed, revoke or rotate them before publishing the repository.
