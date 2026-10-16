# Share THIS PC's app with a friend over the internet, using a free Cloudflare "quick tunnel".
# Start run.py (green play button in PyCharm) first. Then run this script in the PyCharm terminal.
# UNVERIFIED: written without Windows/cloudflared available.
$ErrorActionPreference = "Stop"
$hasCode = (Test-Path .env) -and (Select-String -Path .env -Pattern '^\s*ACCESS_CODE\s*=\s*\S+' -Quiet)
if (-not $hasCode) {
  Write-Host "Set an access code first. Add this line to your .env file and restart run.py:" -ForegroundColor Yellow
  Write-Host "    ACCESS_CODE=choose-a-long-secret" -ForegroundColor Yellow
  Write-Host "Without it, anyone who finds the public link could use your translator."
  exit 1
}
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
  Write-Host "cloudflared is not installed. Install it with:  winget install --id Cloudflare.cloudflared" -ForegroundColor Yellow
  Write-Host "(or download it from https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/ )"
  exit 1
}
Write-Host "A public https:// address will appear below. Open it yourself, start a call, and send your friend the invite link."
Write-Host "Your friend does NOT need the access code. Press Ctrl+C here to stop sharing." -ForegroundColor Green
Write-Host "If a call says 'connection refused' add that https address to ALLOWED_ORIGINS in .env and restart run.py."
cloudflared tunnel --url http://127.0.0.1:8000
