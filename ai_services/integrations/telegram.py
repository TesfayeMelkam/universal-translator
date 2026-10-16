"""Telegram bot: send it a message, get a translation back.

Setup (needs a public https address, see deploy/README.md or scripts/share_online.ps1):
  1. Talk to @BotFather, create a bot, put TELEGRAM_BOT_TOKEN in .env
  2. Put a random TELEGRAM_WEBHOOK_SECRET in .env
  3. python scripts/telegram_set_webhook.py https://YOUR-ADDRESS
UNVERIFIED against the real Telegram service (no internet in the build environment); the message handling is unit-tested
with a fake sender. Plain text is only translated in private chats; in groups the bot answers commands only.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import urllib.request
from collections import defaultdict, deque
from typing import Callable, Optional

from shared.languages import LANGUAGES, get_language
from ..providers.base import ProviderError

HELP = ("Send me text and I translate it.\n/lang <code or name> - language to translate INTO (default: en)\n"
        "/from <code or name|auto> - language you write in (default: auto)\n/languages - list codes\n"
        "Voice, photos and files are not supported here yet.")


class ChatStore:
    def __init__(self, path: str = ":memory:"):
        self._c = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._c.execute("CREATE TABLE IF NOT EXISTS chats (chat_id INTEGER PRIMARY KEY, source TEXT NOT NULL DEFAULT 'auto', target TEXT NOT NULL DEFAULT 'en')")
            self._c.commit()

    def get(self, chat_id: int) -> tuple:
        with self._lock:
            row = self._c.execute("SELECT source, target FROM chats WHERE chat_id = ?", (chat_id,)).fetchone()
        return row or ("auto", "en")

    def set(self, chat_id: int, source: Optional[str] = None, target: Optional[str] = None) -> None:
        s, t = self.get(chat_id)
        with self._lock:
            self._c.execute("INSERT OR REPLACE INTO chats VALUES (?,?,?)", (chat_id, source or s, target or t))
            self._c.commit()


def telegram_sender(token: str) -> Callable[[int, str], bool]:
    def send(chat_id: int, text: str) -> bool:
        req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage",
                                     data=json.dumps({"chat_id": chat_id, "text": text[:4000]}).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status == 200
        except Exception:  # noqa: BLE001 - never crash the webhook because Telegram was slow
            return False
    return send


class TelegramBot:
    def __init__(self, translate: Callable[[str, str, str], dict], send: Callable[[int, str], bool],
                 store: Optional[ChatStore] = None, rate: tuple = (10, 60.0), clock=time.time, max_chars: int = 1000):
        self.translate, self.send, self.store = translate, send, store or ChatStore()
        self.rate, self.clock, self.max_chars = rate, clock, max_chars
        self._hits = defaultdict(deque)

    @staticmethod
    def _lang(arg: str) -> Optional[str]:
        arg = (arg or "").strip().lower()
        if arg == "auto":
            return "auto"
        l = get_language(arg) or next((x for x in LANGUAGES if x.english_name.lower() == arg), None)
        return l.code if l else None

    def _limited(self, chat_id: int) -> bool:
        n, window = self.rate
        q, now = self._hits[chat_id], self.clock()
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= n:
            return True
        q.append(now)
        return False

    def handle_update(self, update: dict) -> Optional[str]:
        msg = (update or {}).get("message") or (update or {}).get("edited_message")
        if not isinstance(msg, dict) or "chat" not in msg:
            return None
        chat_id, private = msg["chat"].get("id"), msg["chat"].get("type") == "private"
        text = msg.get("text")
        if not isinstance(chat_id, int):
            return None
        if self._limited(chat_id):
            return self._reply(chat_id, "Slow down a little, please.")
        if not text:
            return self._reply(chat_id, "I can translate text messages only.") if private else None
        if text.startswith("/"):
            cmd, _, arg = text.partition(" ")
            cmd = cmd.split("@")[0].lower()
            return self._command(chat_id, cmd, arg)
        if not private:
            return None                                           # stay quiet in groups
        if len(text) > self.max_chars:
            return self._reply(chat_id, f"Please send at most {self.max_chars} characters.")
        source, target = self.store.get(chat_id)
        try:
            r = self.translate(text, source, target)
        except ProviderError as exc:
            return self._reply(chat_id, exc.message)
        out = r["translation"] + ("\n(demo mode: not a real translation)" if r.get("is_mock") else "")
        return self._reply(chat_id, out)

    def _command(self, chat_id: int, cmd: str, arg: str) -> str:
        if cmd in ("/start", "/help"):
            return self._reply(chat_id, HELP)
        if cmd == "/languages":
            return self._reply(chat_id, "Codes: " + ", ".join(l.code for l in LANGUAGES))
        if cmd in ("/lang", "/from"):
            code = self._lang(arg)
            if not code or (cmd == "/lang" and code == "auto"):
                return self._reply(chat_id, "Unknown language. Send /languages to see the codes.")
            self.store.set(chat_id, **({"target": code} if cmd == "/lang" else {"source": code}))
            name = "automatic" if code == "auto" else get_language(code).english_name
            return self._reply(chat_id, f"{'Translating into' if cmd == '/lang' else 'You write in'}: {name}")
        return self._reply(chat_id, "Unknown command. Send /help.")

    def _reply(self, chat_id: int, text: str) -> str:
        self.send(chat_id, text)
        return text
