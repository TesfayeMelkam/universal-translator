"""Small built-in accounts: username + password, cookie sessions, per-user history.

Security choices (standard library only):
  * passwords: scrypt with a random salt per user; only the hash is stored; compared in constant time
  * sessions: random 256-bit token in an HttpOnly cookie; only its SHA-256 is stored; expires; logout deletes it
  * login attempts are throttled per username and per client address
  * no e-mail, so there is NO password reset: an admin must delete the user row (documented limitation)
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Callable, Optional

from .providers.base import ProviderError

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
MIN_PASSWORD = 10
_N, _R, _P = 2 ** 14, 8, 1


def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return "scrypt${}${}${}${}${}".format(_N, _R, _P, base64.b64encode(salt).decode(), base64.b64encode(dk).decode())


def check_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32)
        return hmac.compare_digest(calc, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password("dummy-password-for-timing")      # so unknown usernames cost the same time as wrong passwords


class UserStore:
    def __init__(self, path: str, clock: Callable[[], float] = time.time, session_days: int = 30,
                 max_failures: int = 5, lock_seconds: int = 300):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self.clock, self.session_seconds = clock, session_days * 86400
        self.max_failures, self.lock_seconds = max_failures, lock_seconds
        self._fails = defaultdict(deque)
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE, pw TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL,
                    expires REAL NOT NULL);""")
            self._conn.commit()

    # ---- accounts ----
    def create_user(self, username: str, password: str) -> int:
        username = (username or "").strip()
        if not USERNAME_RE.match(username):
            raise ProviderError("bad_username", "Username must be 3-32 letters, numbers, dot, dash or underscore.", 422)
        if len(password or "") < MIN_PASSWORD or len(password) > 200:
            raise ProviderError("weak_password", f"Password must be {MIN_PASSWORD}-200 characters.", 422)
        if password.lower() == username.lower():
            raise ProviderError("weak_password", "Password must not be your username.", 422)
        with self._lock:
            try:
                cur = self._conn.execute("INSERT INTO users (username, pw, created) VALUES (?,?,?)",
                                         (username, hash_password(password), self.clock()))
                self._conn.commit()
                return cur.lastrowid
            except sqlite3.IntegrityError:
                raise ProviderError("username_taken", "That username is already taken.", 409)

    def _throttled(self, keys) -> bool:
        now = self.clock()
        for k in keys:
            q = self._fails[k]
            while q and now - q[0] > self.lock_seconds:
                q.popleft()
            if len(q) >= self.max_failures:
                return True
        return False

    def verify(self, username: str, password: str, client: str = "") -> int:
        keys = [("u", (username or "").lower()), ("c", client)]
        if self._throttled(keys):
            raise ProviderError("too_many_attempts", "Too many failed logins. Try again in a few minutes.", 429)
        with self._lock:
            row = self._conn.execute("SELECT id, pw FROM users WHERE username = ?", (username or "",)).fetchone()
        ok = check_password(password or "", row[1] if row else _DUMMY)
        if row and ok:
            for k in keys:
                self._fails[k].clear()
            return row[0]
        for k in keys:
            self._fails[k].append(self.clock())
        raise ProviderError("bad_login", "Wrong username or password.", 401)

    # ---- sessions ----
    @staticmethod
    def _h(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._conn.execute("INSERT INTO sessions VALUES (?,?,?)", (self._h(token), user_id, self.clock() + self.session_seconds))
            self._conn.execute("DELETE FROM sessions WHERE expires < ?", (self.clock(),))
            self._conn.commit()
        return token

    def user_for(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT u.id, u.username, s.expires FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = ?",
                (self._h(token),)).fetchone()
        if not row or row[2] < self.clock():
            return None
        return {"id": row[0], "username": row[1]}

    def end_session(self, token: Optional[str]) -> None:
        if token:
            with self._lock:
                self._conn.execute("DELETE FROM sessions WHERE token_hash = ?", (self._h(token),))
                self._conn.commit()
