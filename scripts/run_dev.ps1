# Starts the app on http://127.0.0.1:8000
if (-not (Test-Path .\.venv\Scripts\python.exe)) { Write-Host "Run .\scripts\setup_windows.ps1 first." -ForegroundColor Red; exit 1 }
$busy = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($busy) { Write-Host "Port 8000 is already in use (app probably running): http://127.0.0.1:8000" -ForegroundColor Yellow; exit 0 }
Start-Job { Start-Sleep 3; Start-Process "http://127.0.0.1:8000" } | Out-Null
& .\.venv\Scripts\python.exe -m uvicorn ai_services.main:app --reload --host 127.0.0.1 --port 8000
