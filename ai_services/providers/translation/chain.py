"""Smart translation: your own data first, then engines in order, with automatic fall-back.

1. Phrasebook / glossary (your data, cloud sheets, corrections)  -> always wins, works offline
2. A small in-memory cache of recent translations                 -> saves quota and time (never written to disk)
3. Engines in the order configured (e.g. google -> azure -> mymemory -> local NLLB)
   * an engine that is unreachable / out of quota / refused is skipped, the next one is tried
   * after repeated failures an engine is paused for a while so users are not kept waiting on a dead service
   * an engine that merely echoes a long input back unchanged is treated as "did not translate"

If nothing can translate, the user gets a clear message, never a fake "[MOCK]" result.
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata
from collections import OrderedDict
from typing import Optional

from shared.languages import get_language
from ..base import ProviderError, TranslationProvider, TranslationResult

SOFT_FAILS = {"engine_unreachable", "engine_error", "engine_rate_limited", "engine_auth"}


def _same(a: str, b: str) -> bool:
    n = lambda s: re.sub(r"\W+", "", unicodedata.normalize("NFKC", s).casefold())
    return bool(n(a)) and n(a) == n(b)


class ChainTranslationProvider(TranslationProvider):
    is_mock = False

    def __init__(self, engines, glossary=None, cache_size: int = 2000, clock=time.monotonic,
                 fail_limit: int = 3, cooldown: float = 60.0, long_cooldown: float = 600.0):
        self.engines = list(engines)
        self.glossary = glossary
        self._clock, self._fail_limit, self._cooldown, self._long = clock, fail_limit, cooldown, long_cooldown
        self._state = {e.name: {"fails": 0, "paused_until": 0.0, "last_error": None, "ok": 0, "failed": 0} for e in self.engines}
        self._cache: "OrderedDict[tuple, TranslationResult]" = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        self.name = " → ".join(e.name for e in self.engines) if self.engines else "phrasebook"

    # ---- status ------------------------------------------------------------------------------
    def available(self) -> tuple:
        """Cheap on purpose (no network, no model loading): the Setup tab shows each engine's real state."""
        if self.engines:
            return True, "ok"
        if self.glossary and self.glossary.stats()["entries"]:
            return True, "phrasebook only (no translation engine configured)"
        return False, "No translation engine is configured. Open .env and set an engine (see README)."

    def describe(self) -> list:
        now = self._clock()
        out = []
        for e in self.engines:
            st = self._state[e.name]
            info = e.info() if hasattr(e, "info") else {"name": e.name, "label": e.name, "where": "this computer",
                                                      "needs_key": False, "sends_text_off_device": False}
            paused = st["paused_until"] > now
            out.append({**info, "state": "paused" if paused else "ready", "last_error": st["last_error"],
                        "ok": st["ok"], "failed": st["failed"]})
        return out

    def warm_up(self) -> None:
        """Ask each online engine which languages it supports (background thread, failures are harmless)."""
        def work():
            for e in self.engines:
                if hasattr(e, "refresh_languages"):
                    e.refresh_languages()
        threading.Thread(target=work, name="engine-languages", daemon=True).start()

    def _static_supports(self, e, source: str, target: str) -> bool:
        if e.name == "nllb":                       # do not load a 3 GB model just to draw the language list
            s, t = get_language(source), get_language(target)
            return bool(s and t and s.nllb and t.nllb)
        return e.supports(source, target)

    def coverage(self, code: str) -> list:
        """Which engines (and the phrasebook) can translate between English and this language."""
        names = [e.name for e in self.engines if code == "en" or self._static_supports(e, "en", code)]
        if self.glossary and code != "en" and code in self.glossary.languages():
            names.append("phrasebook")
        return names

    def unsupported_hint(self, source: str, target: str) -> str:
        for code in (target, source):
            if code != "en" and not self.coverage(code):
                lang = get_language(code)
                return (f"No translation engine supports {lang.english_name if lang else code} yet. "
                        "You can still translate phrases you add under Setup → Data (phrasebook).")
        return f"No translation engine supports {source}→{target}."

    # ---- support / translate -----------------------------------------------------------------
    def supports(self, source: str, target: str) -> bool:
        if self.glossary and self.glossary.can(source, target):
            return True
        return any(e.supports(source, target) for e in self.engines)

    def _cache_get(self, key):
        with self._lock:
            hit = self._cache.get(key)
            if hit is not None:
                self._cache.move_to_end(key)
            return hit

    def _cache_put(self, key, res):
        if self._cache_size <= 0:
            return
        with self._lock:
            self._cache[key] = res
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    def _record_ok(self, e):
        with self._lock:
            st = self._state[e.name]
            st.update(fails=0, paused_until=0.0, last_error=None)
            st["ok"] += 1

    def _record_fail(self, e, exc: ProviderError):
        with self._lock:
            st = self._state[e.name]
            st["failed"] += 1
            st["last_error"] = exc.message
            if exc.code not in SOFT_FAILS:
                return
            st["fails"] += 1
            if exc.code in ("engine_auth", "engine_rate_limited"):
                st["paused_until"] = self._clock() + self._long
            elif st["fails"] >= self._fail_limit:
                st["paused_until"] = self._clock() + self._cooldown

    def translate(self, text: str, source: str, target: str) -> TranslationResult:
        if self.glossary:
            hit = self.glossary.lookup(source, target, text)
            if hit is not None:
                return TranslationResult(hit, "phrasebook")
        key = (source, target, text)
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        usable = [e for e in self.engines if e.supports(source, target)]
        if not usable:
            raise ProviderError("unsupported_pair", self.unsupported_hint(source, target), 422)

        problems: list = []
        echo: Optional[TranslationResult] = None
        attempted = False
        for ignore_pause in (False, True):          # pass 2 only runs if every engine was paused: try them anyway
            if attempted:
                break
            now = self._clock()
            for e in usable:
                if not ignore_pause and self._state[e.name]["paused_until"] > now:
                    continue
                attempted = True
                try:
                    res = e.translate(text, source, target)
                except ProviderError as exc:
                    self._record_fail(e, exc)
                    problems.append(exc.message)
                    continue
                except Exception as exc:  # noqa: BLE001 - an engine bug must not take the app down
                    self._record_fail(e, ProviderError("engine_error", f"{e.name} failed ({type(exc).__name__}).", 502))
                    problems.append(f"{e.name} failed ({type(exc).__name__}).")
                    continue
                if len(text.strip()) >= 12 and _same(text, res.text):
                    echo = echo or res                 # looks untranslated: prefer another engine, keep this as last resort
                    problems.append(f"{e.name} returned the text unchanged.")
                    continue
                self._record_ok(e)
                self._cache_put(key, res)
                return res
        if echo is not None:
            return echo
        detail = " ".join(dict.fromkeys(problems))[:400]
        raise ProviderError("translation_unavailable",
                            "Translation is unavailable right now. " + (detail or "No engine answered.") +
                            " Check the internet connection and the keys in .env (Setup tab shows each engine).", 503)
