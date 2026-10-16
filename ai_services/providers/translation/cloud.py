"""Online translation engines. Standard library only: nothing to `pip install`.

Engine            Needs                                   Notes
google            GOOGLE_TRANSLATE_API_KEY                Best coverage of Amharic, Afaan Oromo, Tigrinya, Somali (paid after free quota)
azure             AZURE_TRANSLATOR_KEY (+ _REGION)        Microsoft Translator (free tier available)
libretranslate    LIBRETRANSLATE_URL (+ _API_KEY)         Open source; self-host it for full privacy
mymemory          nothing (MYMEMORY_EMAIL raises quota)   Free, no sign-up, small daily quota, uneven quality for low-resource languages

PRIVACY: using any of these SENDS THE TEXT YOU TRANSLATE to that service. The Setup tab says so.
Which languages an engine handles is asked from the engine itself (when it offers a list); nothing here
claims quality. Run Setup -> "Run quality check" and have a fluent speaker review important text.

Every network call has a timeout, retries on temporary failures and reports problems as ProviderError so the
chain (chain.py) can fall back to the next engine.
"""
from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Callable, Optional
from urllib.parse import quote, urlencode

from ..base import ProviderError, TranslationProvider, TranslationResult
from shared.languages import get_language

Transport = Callable[[str, str, Optional[dict], Optional[bytes], float], tuple]


def default_transport(method: str, url: str, headers: Optional[dict], body: Optional[bytes], timeout: float) -> tuple:
    """(status, body). Network failures raise OSError; HTTP error statuses are returned, not raised."""
    req = urllib.request.Request(url, data=body, method=method, headers={"User-Agent": "UniversalTranslator/0.6", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:      # noqa: S310 (fixed https endpoints or owner-configured URL)
            return resp.status, resp.read(5_000_000)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(200_000)


# ---- splitting long text -----------------------------------------------------------------------
# Chunks are exact substrings of the input (whitespace stays attached to the text before it), so joining the
# translated chunks rebuilds the layout and never inserts a space into languages written without spaces.
_BREAK = re.compile(r"(?<=[.!?።፧؟])\s+|(?<=[。！？])\s*")
_WORD = re.compile(r"\S+\s*|\s+")


def _atoms(line: str) -> list:
    out, pos = [], 0
    for m in _BREAK.finditer(line):
        if m.end() > pos:
            out.append(line[pos:m.end()])
            pos = m.end()
    if pos < len(line):
        out.append(line[pos:])
    return out


def _split_line(line: str, limit: int, measure) -> list:
    if measure(line) <= limit:
        return [line]
    chunks, cur = [], ""
    for atom in _atoms(line):
        if measure(cur + atom) <= limit:
            cur += atom
            continue
        if cur:
            chunks.append(cur)
            cur = ""
        if measure(atom) <= limit:
            cur = atom
            continue
        for word in _WORD.findall(atom):                    # a sentence longer than the limit: pack words
            if measure(cur + word) <= limit:
                cur += word
                continue
            if cur:
                chunks.append(cur)
                cur = ""
            while measure(word) > limit:                    # one enormous "word" (e.g. Chinese without spaces)
                k = len(word)
                while k > 1 and measure(word[:k]) > limit:
                    k -= 1
                chunks.append(word[:k])
                word = word[k:]
            cur = word
    if cur:
        chunks.append(cur)
    return chunks


def plan_chunks(text: str, limit: int, measure=len) -> list:
    """[(piece, translate?)]; non-translated pieces are the newlines / blank lines that keep the layout."""
    out: list = []
    for i, line in enumerate(text.split("\n")):
        if i:
            out.append(("\n", False))
        if not line.strip():
            out.append((line, False))
            continue
        out.extend((chunk, True) for chunk in _split_line(line, limit, measure))
    return out


# ---- base ---------------------------------------------------------------------------------------
class CloudEngine(TranslationProvider):
    name = "cloud"
    label = "Cloud"
    where = ""                       # who receives the text, shown in Setup
    needs_key = False
    sends_text_off_device = True
    max_chunk = 4500

    def __init__(self, transport: Optional[Transport] = None, timeout: float = 15.0, retries: int = 1, sleep=time.sleep):
        self._transport = transport or default_transport
        self.timeout, self.retries, self._sleep = timeout, retries, sleep
        self._known: Optional[set] = None
        self._known_lock = threading.Lock()

    # -- hooks for subclasses
    def measure(self, s: str) -> int:
        return len(s)

    def candidates(self, code: str) -> list:
        return [code]

    def _fetch_known(self) -> Optional[set]:
        return None

    def _translate_chunk(self, text: str, source: str, target: str) -> str:
        raise NotImplementedError

    # -- language support
    def code_for(self, code: str) -> Optional[str]:
        cands = self.candidates(code)
        if self._known is not None:
            return next((c for c in cands if c in self._known), None)
        # Before the engine's own language list is known: assume ISO 639-1 (2-letter) codes work, not 3-letter ones.
        return cands[0] if cands and len(cands[0].split("-")[0]) == 2 else None

    def refresh_languages(self) -> bool:
        try:
            known = self._fetch_known()
        except (ProviderError, ValueError, KeyError, TypeError):
            return False
        if known:
            with self._known_lock:
                self._known = set(known)
            return True
        return False

    def supports(self, source: str, target: str) -> bool:
        return bool(get_language(source) and get_language(target) and self.code_for(source) and self.code_for(target))

    def available(self) -> tuple:
        return True, "ok"

    def info(self) -> dict:
        return {"name": self.name, "label": self.label, "where": self.where, "needs_key": self.needs_key,
                "sends_text_off_device": True, "language_list_loaded": self._known is not None}

    # -- HTTP with retry
    def _request(self, method: str, url: str, headers: Optional[dict] = None, body: Optional[bytes] = None) -> bytes:
        last: Optional[ProviderError] = None
        for attempt in range(self.retries + 1):
            try:
                status, data = self._transport(method, url, headers, body, self.timeout)
            except OSError as exc:
                last = ProviderError("engine_unreachable", f"{self.label}: cannot reach the service ({type(exc).__name__}).", 503)
            else:
                if status == 200:
                    return data
                detail = data[:160].decode("utf-8", "replace").strip() if data else ""
                if status in (401, 403):
                    raise ProviderError("engine_auth", f"{self.label}: the API key was refused ({status}).", 502)
                if status == 429:
                    last = ProviderError("engine_rate_limited", f"{self.label}: daily/minute quota reached.", 429)
                elif status >= 500:
                    last = ProviderError("engine_error", f"{self.label}: service error {status}.", 502)
                else:
                    raise ProviderError("engine_rejected", f"{self.label} rejected the request ({status}): {detail}", 502)
            if attempt < self.retries:
                self._sleep(0.4 * (attempt + 1))
        raise last or ProviderError("engine_error", f"{self.label} failed.", 502)

    def _json(self, method: str, url: str, headers=None, payload=None):
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        h = {"Content-Type": "application/json; charset=utf-8", **(headers or {})}
        try:
            return json.loads(self._request(method, url, h, body))
        except ValueError as exc:
            raise ProviderError("engine_error", f"{self.label} sent an unreadable answer.", 502) from exc

    def translate(self, text: str, source: str, target: str) -> TranslationResult:
        s, t = self.code_for(source), self.code_for(target)
        if not s or not t:
            raise ProviderError("unsupported_pair", f"{self.label} does not support {source}→{target}.", 422)
        parts = []
        for piece, do in plan_chunks(text, self.max_chunk, self.measure):
            if not do:
                parts.append(piece)
                continue
            core = piece.strip()                              # engines may trim spaces: put the original ones back
            lead, trail = piece[:len(piece) - len(piece.lstrip())], piece[len(piece.rstrip()):]
            parts.append(lead + self._translate_chunk(core, s, t) + trail)
        return TranslationResult("".join(parts), self.name)


# ---- engines ------------------------------------------------------------------------------------
class GoogleEngine(CloudEngine):
    name, label, where, needs_key = "google", "Google Cloud Translation", "Google", True
    _BASE = "https://translation.googleapis.com/language/translate/v2"
    _MAP = {"zh": ["zh-CN", "zh"], "zh-hant": ["zh-TW"], "he": ["he", "iw"], "jv": ["jv", "jw"], "tl": ["tl", "fil"],
            "kmr": ["ku"], "no": ["no", "nb"]}

    def __init__(self, api_key: str, **kw):
        super().__init__(**kw)
        self._key = api_key

    def candidates(self, code):
        return self._MAP.get(code, [code])

    def _fetch_known(self):
        data = self._json("GET", f"{self._BASE}/languages?key={quote(self._key)}&target=en")
        return {x["language"] for x in data["data"]["languages"]}

    def _translate_chunk(self, text, source, target):
        data = self._json("POST", f"{self._BASE}?key={quote(self._key)}",
                          payload={"q": text, "source": source, "target": target, "format": "text"})
        try:
            return data["data"]["translations"][0]["translatedText"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("engine_error", "Google Translation sent an unexpected answer.", 502) from exc


class AzureEngine(CloudEngine):
    name, label, where, needs_key = "azure", "Microsoft Translator", "Microsoft", True
    _MAP = {"zh": ["zh-Hans"], "zh-hant": ["zh-Hant"], "no": ["nb"], "tl": ["fil"], "sr": ["sr-Cyrl", "sr-Latn"],
            "mn": ["mn-Cyrl", "mn-Mong"]}

    def __init__(self, api_key: str, region: str = "", endpoint: str = "https://api.cognitive.microsofttranslator.com", **kw):
        super().__init__(**kw)
        self._key, self._region, self._endpoint = api_key, region, endpoint.rstrip("/")

    def candidates(self, code):
        return self._MAP.get(code, [code])

    def _headers(self):
        h = {"Ocp-Apim-Subscription-Key": self._key}
        if self._region:
            h["Ocp-Apim-Subscription-Region"] = self._region
        return h

    def _fetch_known(self):
        data = self._json("GET", f"{self._endpoint}/languages?api-version=3.0&scope=translation")
        return set(data["translation"].keys())

    def _translate_chunk(self, text, source, target):
        url = f"{self._endpoint}/translate?{urlencode({'api-version': '3.0', 'from': source, 'to': target, 'textType': 'plain'})}"
        data = self._json("POST", url, headers=self._headers(), payload=[{"Text": text}])
        try:
            return data[0]["translations"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError("engine_error", "Microsoft Translator sent an unexpected answer.", 502) from exc


class LibreEngine(CloudEngine):
    name, label, needs_key = "libretranslate", "LibreTranslate", False
    max_chunk = 3000
    _MAP = {"zh": ["zh", "zh-Hans"], "zh-hant": ["zt", "zh-Hant"], "no": ["nb"]}

    def __init__(self, url: str, api_key: str = "", **kw):
        super().__init__(**kw)
        self._url, self._key = url.rstrip("/"), api_key
        self.where = self._url.split("//")[-1].split("/")[0]

    def candidates(self, code):
        return self._MAP.get(code, [code])

    def _fetch_known(self):
        data = self._json("GET", f"{self._url}/languages")
        return {x["code"] for x in data}

    def _translate_chunk(self, text, source, target):
        payload = {"q": text, "source": source, "target": target, "format": "text"}
        if self._key:
            payload["api_key"] = self._key
        data = self._json("POST", f"{self._url}/translate", payload=payload)
        try:
            return data["translatedText"]
        except (KeyError, TypeError) as exc:
            raise ProviderError("engine_error", "LibreTranslate sent an unexpected answer.", 502) from exc


class MyMemoryEngine(CloudEngine):
    name, label, where, needs_key = "mymemory", "MyMemory (free)", "translated.net (MyMemory)", False
    max_chunk = 450                                         # the service allows 500 BYTES per request

    def __init__(self, email: str = "", **kw):
        super().__init__(**kw)
        self._email = email

    def measure(self, s):
        return len(s.encode("utf-8"))

    def candidates(self, code):
        return {"zh": ["zh-CN"], "zh-hant": ["zh-TW"]}.get(code, [code])

    def _translate_chunk(self, text, source, target):
        q = {"q": text, "langpair": f"{source}|{target}"}
        if self._email:
            q["de"] = self._email
        data = self._json("GET", f"https://api.mymemory.translated.net/get?{urlencode(q)}", headers={})
        try:
            status = int(data.get("responseStatus", 200))
            out = data["responseData"]["translatedText"]
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise ProviderError("engine_error", "MyMemory sent an unexpected answer.", 502) from exc
        if status == 429 or "MYMEMORY WARNING" in out.upper():
            raise ProviderError("engine_rate_limited", "MyMemory: free daily quota reached (set MYMEMORY_EMAIL for more).", 429)
        if status != 200:
            raise ProviderError("engine_rejected", f"MyMemory could not translate this ({status}).", 502)
        return html.unescape(out)
