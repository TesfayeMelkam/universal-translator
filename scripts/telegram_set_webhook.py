"""Tell Telegram where to send messages:  python scripts/telegram_set_webhook.py https://your-public-address"""
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ai_services import config  # noqa: E402,F401  (loads .env)

token, secret = os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
if len(sys.argv) != 2 or not token or not secret:
    sys.exit("Usage: python scripts/telegram_set_webhook.py https://your-public-address\n"
             "and set TELEGRAM_BOT_TOKEN + TELEGRAM_WEBHOOK_SECRET in .env first.")
body = json.dumps({"url": sys.argv[1].rstrip("/") + "/api/v1/integrations/telegram/webhook",
                   "secret_token": secret, "allowed_updates": ["message"]}).encode()
req = urllib.request.Request(f"https://api.telegram.org/bot{token}/setWebhook", data=body, headers={"Content-Type": "application/json"})
print(urllib.request.urlopen(req, timeout=15).read().decode())
