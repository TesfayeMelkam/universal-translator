"""Translation self-check. Measures *consistency*, it cannot prove a translation is correct.

Round trip: English -> language X -> English, then compare with the original sentence. A low score means
something is wrong (bad model, unsupported language, garbage). A high score is encouraging but NOT proof of
a perfect translation, because two mistakes can cancel out. Always have a fluent speaker review important text.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Iterable, List, Optional

from shared.languages import get_language
from ..providers.base import ProviderError, TranslationProvider

SELFTEST_PHRASES = [
    "Hello, how are you?",
    "Thank you very much.",
    "Where is the hospital?",
    "I need help, please.",
    "How much does this cost?",
    "I am hungry and thirsty.",
    "The meeting starts at nine o'clock.",
    "Please speak slowly.",
    "My name is Sara and I come from Ethiopia.",
    "We will travel to the city tomorrow.",
]
DEFAULT_LANGS = ["am", "om", "ti", "so"]


def _norm(text: str) -> List[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    return re.findall(r"\w+", text, flags=re.UNICODE)


def similarity(a: str, b: str) -> float:
    ta, tb = _norm(a), _norm(b)
    if not ta or not tb:
        return 0.0
    sa, sb = set(ta), set(tb)
    jaccard = len(sa & sb) / len(sa | sb)
    ratio = SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()
    return round((jaccard + ratio) / 2, 3)


def grade(score: float) -> str:
    return "good" if score >= 0.8 else "fair" if score >= 0.5 else "poor"


def run_selftest(provider: TranslationProvider, languages: Iterable[str], phrases: Optional[List[str]] = None,
                 max_chars: int = 2000) -> dict:
    phrases = list(phrases or SELFTEST_PHRASES)
    report = {"provider": provider.name, "is_mock": provider.is_mock, "languages": [], "phrases": len(phrases),
              "disclaimer": ("Round-trip consistency only. A high score does not prove the translation is correct; "
                             "have a fluent speaker review anything important.")}
    for code in languages:
        lang = get_language(code)
        entry = {"code": code, "name": lang.english_name if lang else code, "details": [], "score": None,
                 "grade": "unsupported", "unchanged": 0, "errors": 0}
        if not lang or code == "en" or not provider.supports("en", code) or not provider.supports(code, "en"):
            report["languages"].append(entry)
            continue
        scores = []
        for phrase in phrases:
            row = {"source": phrase}
            try:
                fwd = provider.translate(phrase, "en", code).text
                back = provider.translate(fwd, code, "en").text
                row.update(translation=fwd, back=back, score=similarity(phrase, back))
                if _norm(fwd) == _norm(phrase):
                    row["unchanged"] = True            # model just echoed English: a classic failure sign
                    entry["unchanged"] += 1
                scores.append(row["score"])
            except ProviderError as exc:
                row.update(error=exc.code)
                entry["errors"] += 1
            entry["details"].append(row)
        if scores:
            entry["score"] = round(sum(scores) / len(scores), 3)
            entry["grade"] = "poor" if entry["unchanged"] > len(phrases) // 2 else grade(entry["score"])
        elif entry["errors"]:
            entry["grade"] = "error"
        report["languages"].append(entry)
    return report
