"""SQLite translation history (standard library only). Single-user local mode."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path


class HistoryStore:
    def __init__(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS history (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                       source TEXT NOT NULL, target TEXT NOT NULL,
                       source_text TEXT NOT NULL, translated_text TEXT NOT NULL,
                       provider TEXT NOT NULL, favorite INTEGER NOT NULL DEFAULT 0)""")
            cols = [r[1] for r in self._conn.execute("PRAGMA table_info(history)")]
            if "user_id" not in cols:                       # upgrade an older database in place
                self._conn.execute("ALTER TABLE history ADD COLUMN user_id INTEGER NOT NULL DEFAULT 0")
            self._conn.commit()

    def add(self, source, target, source_text, translated_text, provider, user_id: int = 0) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO history (source,target,source_text,translated_text,provider,user_id) VALUES (?,?,?,?,?,?)",
                (source, target, source_text, translated_text, provider, user_id))
            self._conn.commit()
            return cur.lastrowid

    def list(self, limit: int = 50, user_id: int = 0) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id,created_at,source,target,source_text,translated_text,provider,favorite "
                "FROM history WHERE user_id = ? ORDER BY id DESC LIMIT ?", (user_id, max(1, min(limit, 200)))).fetchall()
        keys = ["id", "created_at", "source", "target", "source_text", "translated_text", "provider", "favorite"]
        return [dict(zip(keys, r)) for r in rows]

    def toggle_favorite(self, item_id: int, user_id: int = 0) -> bool:
        with self._lock:
            cur = self._conn.execute("UPDATE history SET favorite = 1 - favorite WHERE id = ? AND user_id = ?", (item_id, user_id))
            self._conn.commit()
            return cur.rowcount > 0

    def clear(self, user_id: int = 0) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM history WHERE user_id = ?", (user_id,))
            self._conn.commit()
