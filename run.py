"""One-click start for PyCharm: open this file and press the green ▶ Run button.

It checks that the needed packages are installed (and offers to install them),
starts the server, and opens your browser at http://127.0.0.1:8000
"""
import importlib.util
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from ai_services.config import ROOT as _ROOT  # noqa: E402,F401  (also loads .env)

LAN = os.environ.get("LAN_MODE", "0") == "1"      # 1 = other devices on your Wi-Fi can connect
# APP_HOST=0.0.0.0 lets other devices connect (same as LAN_MODE=1); APP_PORT changes the port (default 8000).
HOST = os.environ.get("APP_HOST") or ("0.0.0.0" if LAN else "127.0.0.1")
try:
    PORT = int(os.environ.get("APP_PORT", "8000"))
except ValueError:
    PORT = 8000
LAN = LAN or HOST not in ("127.0.0.1", "localhost")
CERT, KEY = ROOT / "certs" / "cert.pem", ROOT / "certs" / "key.pem"
HTTPS = CERT.is_file() and KEY.is_file()
URL = f"{'https' if HTTPS else 'http'}://127.0.0.1:{PORT}"
ENV_FILE = ROOT / ".env"


def missing_packages() -> list:
    return [m for m in ("fastapi", "uvicorn", "pydantic", "websockets") if importlib.util.find_spec(m) is None]


def port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((HOST, PORT)) == 0


def ensure_packages() -> bool:
    missing = missing_packages()
    if not missing:
        return True
    print(f"Missing Python packages: {', '.join(missing)}")
    print(f"Python being used: {sys.executable}")
    if input("Install them now with pip (needs internet)? [y/N] ").strip().lower() != "y":
        print(f'Install manually:  "{sys.executable}" -m pip install -r requirements.txt')
        return False
    code = subprocess.call([sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")])
    if code != 0:
        print("pip failed. Check your internet connection and read the error above.")
        return False
    return not missing_packages()


def fix_mock_setting() -> None:
    """Old .env files say TRANSLATION_PROVIDER=mock: the app then only knows a few greetings and "does not translate".
    Offer to switch it to `auto` (real online translation)."""
    if not ENV_FILE.is_file():
        return
    text = ENV_FILE.read_text(encoding="utf-8")
    m = re.search(r"^TRANSLATION_PROVIDER\s*=\s*mock\b.*$", text, flags=re.M | re.I)
    if not m:
        return
    print("\nYour .env has TRANSLATION_PROVIDER=mock. That is a DEMO mode that only knows a few greetings,")
    print("so most text will NOT be translated.")
    try:
        answer = input("Switch to real translation now (TRANSLATION_PROVIDER=auto, needs internet)? [Y/n] ").strip().lower()
    except EOFError:
        return
    if answer in ("", "y", "yes"):
        ENV_FILE.write_text(text[:m.start()] + "TRANSLATION_PROVIDER=auto" + text[m.end():], encoding="utf-8")
        os.environ["TRANSLATION_PROVIDER"] = "auto"
        print("Done. (Add a Google/Azure key in .env for better quality, see README.)\n")


def main() -> int:
    if sys.version_info < (3, 10):
        print(f"Python 3.10+ is required (you have {sys.version.split()[0]}).")
        return 1
    if not ensure_packages():
        return 1
    fix_mock_setting()
    if port_in_use():
        print(f"Port {PORT} is already in use — the app is probably already running: {URL}")
        webbrowser.open(URL)
        return 0
    import uvicorn
    threading.Thread(target=lambda: (time.sleep(2), webbrowser.open(URL)), daemon=True).start()
    print(f"Starting Universal Translator at {URL}  (press the red ■ Stop button to quit)")
    if LAN:
        print("LAN_MODE is ON: anyone on your network can open this app (it has no login).")
        if not HTTPS:
            print("Note: phones/other PCs cannot use the camera over plain http. See README 'Video calls'.")
    kwargs = {"ssl_certfile": str(CERT), "ssl_keyfile": str(KEY)} if HTTPS else {}
    uvicorn.run("ai_services.main:app", host=HOST, port=PORT, log_level="info", **kwargs)
    return 0


if __name__ == "__main__":
    sys.exit(main())
