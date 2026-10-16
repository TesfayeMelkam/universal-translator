# Run from the project root in the PyCharm terminal:  .\scripts\setup_windows.ps1
$ErrorActionPreference = "Stop"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { Write-Host "Python not found. Install Python 3.10+ from python.org (tick 'Add to PATH')." -ForegroundColor Red; exit 1 }
$v = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ([version]$v -lt [version]"3.10") { Write-Host "Python $v is too old; need 3.10+." -ForegroundColor Red; exit 1 }
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example" }
Write-Host "Setup finished. Start the app with:  .\scripts\run_dev.ps1" -ForegroundColor Green
