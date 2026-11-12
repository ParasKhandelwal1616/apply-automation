# run.ps1 – Windows PowerShell launcher for apply-bot
# Usage:
#   .\run.ps1 open-channel          # First-time Telegram login
#   .\run.ps1 apply-once --limit 80 # Apply to latest posts
#   .\run.ps1 dry-run --limit 20    # Score only, no mail/forms
#   .\run.ps1 watch                 # Keep polling every 90 s
#   .\run.ps1 list                  # Print tracker
#   .\run.ps1 apply-boards          # Search Naukri / Wellfound / WaaS
#   .\run.ps1 linkedin-dm           # LinkedIn referral messages (dry-run)
#   .\run.ps1 linkedin-dm --send    # Send LinkedIn messages
#   .\run.ps1 linkedin-inbox        # Check LinkedIn replies

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ScriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Host "[setup] Creating virtual environment..." -ForegroundColor Cyan
    python -m venv "$ScriptDir\.venv"

    Write-Host "[setup] Installing dependencies..." -ForegroundColor Cyan
    & "$ScriptDir\.venv\Scripts\pip" install -r "$ScriptDir\requirements.txt"

    Write-Host "[setup] Installing Playwright Chromium browser..." -ForegroundColor Cyan
    $env:PLAYWRIGHT_BROWSERS_PATH = "$ScriptDir\data\pw-browsers"
    & "$ScriptDir\.venv\Scripts\playwright" install chromium
}

$env:PLAYWRIGHT_BROWSERS_PATH = "$ScriptDir\data\pw-browsers"
$env:PYTHONPATH = "$ScriptDir\src"

Write-Host "[run] apply_bot $args" -ForegroundColor Green
& $VenvPython -m apply_bot @args
