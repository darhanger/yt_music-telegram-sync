@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PROJECT_ROOT=%~dp0"
if not exist "%PROJECT_ROOT%.venv\Scripts\python.exe" (
    echo First run setup.ps1
    pause
    exit /b 1
)
"%PROJECT_ROOT%.venv\Scripts\python.exe" -m yt_music_telegram_sync --console
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
