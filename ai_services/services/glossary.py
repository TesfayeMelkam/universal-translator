"""Phrasebook / glossary: YOUR OWN translation data, checked before any translation engine.

Why it exists
* Languages with no machine-translation engine (Wolaytta, Sidama, Afar, Ge'ez ...) can still work for the
  phrases you add (health, school, government, business phrases ...).
* You can correct an engine: an entry here always wins over Google/Azure/NLLB.
* Data can come from files in data/glossary/ or from a cloud URL (Google Sheets "publish as CSV", GitHub raw,
  S3 / Azure Blob / any https link), see services/datasources.py.

Matching is exact on the whole text after normalising case, spaces and end punctuation. It does not
"understand" grammar: it is a lookup table, not a translator. Quality = quality of the data you put in.

Accepted files
* Long CSV:  source_lang,target_lang,source_text,translation
* Wide CSV:  one column per language, one row per phrase:   en,am,om,ti,wal   (columns must be language codes)
* JSON:      a list of objects (long or wide shape above) or {"entries": [...]}
"""
from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import threading
import unicodedata
from pathlib import Path
from typing import Iterable, Optional

from shared.languages import get_language

MAX_TEXT = 500
MAX_ROWS = 200_000
MAX_WIDE_COLUMNS = 12
_ALIASES = {"source_lang": {"source_lang", "source", "from", "src", "src_lang"},
            "target_lang": {"target_lang", "target", "to", "tgt", "tgt_lang"},
            "source_text": {"source_text", "text", "phrase", "original"},
            "translation": {"translation", "translated", "translated_text", "target_text"}}
_END = re.compile(r"[\s.!?¿¡።፧፨፡።،؟。！？…]+$")


def normalize(text: str) -> str:
    """Key used for matching: NFKC, lower-case, collapsed spaces, no trailing punctuation."""
    t = unicodedata.normalize("NFKC", text or "").casefold()
    t = re.sub(r"\s+", " ", t).strip()
    return _END.sub("", t)


def _canon(header: str) -> str:
    h = (header or "").strip().lower().lstrip("\ufeff").replace(" ", "_")
    for canon, names in _ALIASES.items():
        if h in names:
            return canon
    return h


class ImportReport(dict):
    """{'added': n, 'skipped': n, 'errors': [first few messages]}"""


def parse_rows(data: "bytes | str", fmt: str = "auto") -> tuple[list[tuple[str, str, str, str]], list[str]]:
    """Turn a CSV/JSON document into (src, tgt, source_text, translation) rows plus a list of problems."""
    text = data.decode("utf-8-sig", errors="replace") if isinstance(data, (bytes, bytearray)) else data
    text = text.lstrip("\ufeff")
    if fmt == "auto":
        fmt = "json" if text.lstrip()[:1] in "[{" else "csv"
    problems: list[str] = []
    records: list[dict] = []
    if fmt == "json":
        try:
            obj = json.loads(text)
        except ValueError as exc:
            return [], [f"Not valid JSON: {exc}"]
        if isinstance(obj, dict):
            obj = obj.get("entries", [obj])
        if not isinstance(obj, list):
            return [], ["JSON must be a list of entries or {\"entries\": [...]}"]
        records = [{_canon(str(k)): str(v) for k, v in r.items() if v is not None} for r in obj if isinstance(r, dict)]
    else:
        sample = text[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            return [], ["The file is empty."]
        reader.fieldnames = [_canon(h) for h in reader.fieldnames]
        records = [{k: (v or "") for k, v in r.items() if k} for r in reader]
    rows: list[tuple[str, str, str, str]] = []
    for n, rec in enumerate(records[:MAX_ROWS], start=1):
        if {"source_lang", "target_lang", "source_text", "translation"} <= rec.keys():
            pairs = [(rec["source_lang"].strip().lower(), rec["target_lang"].strip().lower(),
                      rec["source_text"], rec["translation"])]
        else:                                           # wide: language-code columns
            cols = [(k, v) for k, v in rec.items() if get_language(k) and (v or "").strip()]
            if len(cols) < 2:
                if any(rec.values()):
                    problems.append(f"row {n}: needs at least two language columns with text")
                continue
            if len(cols) > MAX_WIDE_COLUMNS:
                problems.append(f"row {n}: too many language columns (max {MAX_WIDE_COLUMNS})")
                continue
            pairs = [(a[0], b[0], a[1], b[1]) for i, a in enumerate(cols) for b in cols[i + 1:]]
        rows.extend(pairs)
    if len(records) > MAX_ROWS:
        problems.append(f"Only the first {MAX_ROWS} rows were read.")
    return rows, problems


class Glossary:
    def __init__(self, path: str = ":memory:"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS glossary (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       src TEXT NOT NULL, tgt TEXT NOT NULL, skey TEXT NOT NULL, text TEXT NOT NULL,
                       tkey TEXT NOT NULL, translation TEXT NOT NULL, origin TEXT NOT NULL DEFAULT 'manual',
                       updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                       UNIQUE (src, tgt, skey))""")
            self._conn.execute("CREATE INDEX IF NOT EXISTS ix_rev ON glossary (tgt, src, tkey)")
            self._conn.commit()
        self._langs: Optional[set] = None

    # ---- writing -----------------------------------------------------------------------------
    @staticmethod
    def _valid(src: str, tgt: str, text: str, tr: str) -> Optional[str]:
        if not get_language(src) or not get_language(tgt):
            return f"unknown language code '{src}' or '{tgt}'"
        if src == tgt:
            return "source and target language are the same"
        if not (text or "").strip() or not (tr or "").strip():
            return "empty text"
        if len(text) > MAX_TEXT or len(tr) > MAX_TEXT:
            return f"text longer than {MAX_TEXT} characters"
        return None

    def add(self, src: str, tgt: str, text: str, translation: str, origin: str = "manual") -> None:
        src, tgt, text, translation = src.strip().lower(), tgt.strip().lower(), text.strip(), translation.strip()
        err = self._valid(src, tgt, text, translation)
        if err:
            raise ValueError(err)
        with self._lock:
            self._insert(src, tgt, text, translation, origin)
            self._conn.commit()
            self._langs = None

    def _insert(self, src, tgt, text, translation, origin) -> None:
        self._conn.execute(
            "INSERT INTO glossary (src,tgt,skey,text,tkey,translation,origin) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(src,tgt,skey) DO UPDATE SET text=excluded.text, tkey=excluded.tkey, "
            "translation=excluded.translation, origin=excluded.origin, updated=CURRENT_TIMESTAMP",
            (src, tgt, normalize(text), text, normalize(translation), translation, origin))

    def import_rows(self, rows: Iterable[tuple], origin: str = "import", replace_origin: bool = False,
                    problems: Optional[list] = None) -> ImportReport:
        """Insert rows. With replace_origin=True the previous rows of the same origin are removed first, so a
        phrase deleted from your cloud spreadsheet also disappears here on the next sync (all-or-nothing)."""
        added, skipped, errors = 0, 0, list(problems or [])
        with self._lock:
            try:
                if replace_origin:
                    self._conn.execute("DELETE FROM glossary WHERE origin = ?", (origin,))
                for src, tgt, text, tr in rows:
                    src, tgt = (src or "").strip().lower(), (tgt or "").strip().lower()
                    err = self._valid(src, tgt, text, tr)
                    if err:
                        skipped += 1
                        if len(errors) < 8:
                            errors.append(err)
                        continue
                    self._insert(src, tgt, text.strip(), tr.strip(), origin)
                    added += 1
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            self._langs = None
        return ImportReport(added=added, skipped=skipped, errors=errors[:8])

    def import_document(self, data: "bytes | str", origin: str, fmt: str = "auto", replace_origin: bool = False) -> ImportReport:
        rows, problems = parse_rows(data, fmt)
        return self.import_rows(rows, origin, replace_origin, problems)

    def delete_origin(self, origin: str) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM glossary WHERE origin = ?", (origin,))
            self._conn.commit()
            self._langs = None
            return cur.rowcount

    # ---- reading -----------------------------------------------------------------------------
    def _direct(self, src: str, tgt: str, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT translation FROM glossary WHERE src=? AND tgt=? AND skey=?", (src, tgt, key)).fetchone()
        if row:
            return row[0]
        row = self._conn.execute("SELECT text FROM glossary WHERE src=? AND tgt=? AND tkey=? ORDER BY id LIMIT 1", (tgt, src, key)).fetchone()
        return row[0] if row else None

    def lookup(self, src: str, tgt: str, text: str, pivot: str = "en") -> Optional[str]:
        key = normalize(text)
        if not key or src == tgt:
            return None
        with self._lock:
            hit = self._direct(src, tgt, key)
            if hit is None and pivot not in (src, tgt):          # am -> en -> om through the English side
                mid = self._direct(src, pivot, key)
                if mid is not None:
                    hit = self._direct(pivot, tgt, normalize(mid))
            return hit

    def languages(self) -> set:
        with self._lock:
            if self._langs is None:
                rows = self._conn.execute("SELECT src FROM glossary UNION SELECT tgt FROM glossary").fetchall()
                self._langs = {r[0] for r in rows}
            return set(self._langs)

    def can(self, src: str, tgt: str, pivot: str = "en") -> bool:
        """True if there is at least some data connecting the two languages (direct, reverse or through English)."""
        with self._lock:
            def pair(a, b):
                return self._conn.execute("SELECT 1 FROM glossary WHERE (src=? AND tgt=?) OR (src=? AND tgt=?) LIMIT 1",
                                          (a, b, b, a)).fetchone() is not None
            return pair(src, tgt) or (pivot not in (src, tgt) and pair(src, pivot) and pair(pivot, tgt))

    def count(self, code: str) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM glossary WHERE src=? OR tgt=?", (code, code)).fetchone()[0]

    def stats(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM glossary").fetchone()[0]
            origins = dict(self._conn.execute("SELECT origin, COUNT(*) FROM glossary GROUP BY origin").fetchall())
            langs: dict = {}
            for src, tgt, n in self._conn.execute("SELECT src, tgt, COUNT(*) FROM glossary GROUP BY src, tgt"):
                langs[src] = langs.get(src, 0) + n
                langs[tgt] = langs.get(tgt, 0) + n
        return {"entries": total, "origins": origins, "languages": langs}

    def export_csv(self) -> str:
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow(["source_lang", "target_lang", "source_text", "translation", "origin"])
        with self._lock:
            for row in self._conn.execute("SELECT src,tgt,text,translation,origin FROM glossary ORDER BY src,tgt,id"):
                w.writerow(row)
        return out.getvalue()
