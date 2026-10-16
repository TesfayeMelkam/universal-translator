"""Load translation data from files and from the cloud into the Glossary.

Sources (all optional)
* Folder   GLOSSARY_DIR (default data/glossary/): every *.csv / *.json file, read at start-up and on "Sync".
* Cloud    DATA_SOURCE_URLS=url1,url2 : any link that returns CSV or JSON, for example
              - Google Sheets: File -> Share -> Publish to web -> CSV   (or .../export?format=csv for a shared sheet)
              - GitHub raw files, S3 / Azure Blob / Google Cloud Storage links (a pre-signed URL works for private data)
              - your own API that returns the CSV/JSON shape described in glossary.py
Only the server owner can set URLs (environment variable); web users cannot make the server fetch arbitrary
addresses. Re-syncing REPLACES what that same source gave before, so a phrase you delete in the sheet also
disappears here.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from .glossary import Glossary

log = logging.getLogger("universal_translator.data")
MAX_BYTES = 10_000_000
Fetcher = Callable[[str, float], bytes]


def fetch_url(url: str, timeout: float = 20.0) -> bytes:
    """Download a CSV/JSON document (http/https only, size-limited)."""
    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("Only http(s) addresses are allowed.")
    req = urllib.request.Request(url, headers={"User-Agent": "UniversalTranslator/0.6", "Accept": "text/csv,application/json,*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 (scheme checked above; URL set by the owner)
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("The file is larger than 10 MB.")
    return data


def origin_for_url(url: str) -> str:
    p = urlparse(url)
    return f"url:{p.hostname or 'unknown'}:{hashlib.sha1(url.encode()).hexdigest()[:8]}"     # never store query strings (may hold tokens)


def load_folder(glossary: Glossary, folder: str) -> list[dict]:
    results = []
    root = Path(folder) if folder else None
    if not root or not root.is_dir():
        return results
    for path in sorted(root.iterdir()):
        if path.suffix.lower() not in (".csv", ".json") or path.name.startswith(("_", ".")):
            continue
        entry = {"source": f"file:{path.name}", "ok": True, "added": 0, "skipped": 0, "errors": []}
        try:
            rep = glossary.import_document(path.read_bytes(), origin=f"file:{path.name}",
                                           fmt="json" if path.suffix.lower() == ".json" else "csv", replace_origin=True)
            entry.update(added=rep["added"], skipped=rep["skipped"], errors=rep["errors"])
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the others
            entry.update(ok=False, errors=[f"{type(exc).__name__}: {exc}"])
        results.append(entry)
    return results


def sync_urls(glossary: Glossary, urls, fetcher: Fetcher = fetch_url, timeout: float = 20.0) -> list[dict]:
    results = []
    for url in urls:
        origin = origin_for_url(url)
        entry = {"source": f"{urlparse(url).hostname}{urlparse(url).path}", "ok": True, "added": 0, "skipped": 0, "errors": []}
        try:
            rep = glossary.import_document(fetcher(url, timeout), origin=origin, replace_origin=True)
            entry.update(added=rep["added"], skipped=rep["skipped"], errors=rep["errors"])
        except urllib.error.HTTPError as exc:
            entry.update(ok=False, errors=[f"The server answered {exc.code}. Check that the link is public or pre-signed."])
        except Exception as exc:  # noqa: BLE001
            entry.update(ok=False, errors=[f"{type(exc).__name__}: could not download ({exc})"[:200]])
        results.append(entry)
    return results


class DataSync:
    """Runs folder + cloud loads, remembers the last result for the Setup tab, optionally repeats on a timer."""

    def __init__(self, glossary: Glossary, folder: str = "", urls=(), minutes: int = 0, fetcher: Fetcher = fetch_url):
        self.glossary, self.folder, self.urls, self.minutes, self.fetcher = glossary, folder, tuple(urls), minutes, fetcher
        self.last: dict = {"at": None, "results": []}
        self._lock = threading.Lock()
        self._started = False

    def run(self) -> dict:
        with self._lock:
            results = load_folder(self.glossary, self.folder) + sync_urls(self.glossary, self.urls, self.fetcher)
            self.last = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}
            return self.last

    def start_background(self) -> None:
        """Initial load without blocking start-up, then every `minutes` if set."""
        if self._started:
            return
        self._started = True

        def loop():
            while True:
                try:
                    self.run()
                except Exception:  # noqa: BLE001
                    log.exception("data sync failed")
                if self.minutes <= 0:
                    return
                time.sleep(self.minutes * 60)
        threading.Thread(target=loop, name="data-sync", daemon=True).start()

    def status(self) -> dict:
        return {"sources": {"folder": self.folder or None, "urls": [urlparse(u).hostname for u in self.urls]},
                "auto_sync_minutes": self.minutes, "last": self.last, **self.glossary.stats()}
