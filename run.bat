@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=src
set PLAYWRIGHT_BROWSERS_PATH=%~dp0data\pw-browsers

if not exist ".venv\Scripts\python.exe" (
    echo [setup] Virtual environment not found. Creating...
    python -m venv .venv
    call .venv\Scripts\pip install -r requirements.txt
    call .venv\Scripts\playwright install chromium
)

.venv\Scripts\python.exe -m apply_bot %*
