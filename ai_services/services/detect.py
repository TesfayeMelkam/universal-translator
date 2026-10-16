"""Heuristic language guess. NOT a real language-ID model.

Step 1 tells scripts apart (Ethiopic, Arabic, Han ...). Step 2 (v0.6) uses small lists of very common words to
separate languages that share a script: Amharic vs Tigrinya (Ethiopic) and English / Afaan Oromo / Somali / Swahili /
French / Spanish / German / Italian / Portuguese (Latin). It can be wrong on short or mixed text, so `ambiguous` stays
true for those scripts and the person can always pick the language by hand.
"""
from __future__ import annotations

import re

RANGES = [
    ("am", 0x1200, 0x139F, True),    # Ethiopic (am/ti share it)
    ("ar", 0x0600, 0x06FF, True),    # Arabic script (ar/fa/ur)
    ("hi", 0x0900, 0x097F, True),
    ("bn", 0x0980, 0x09FF, False),
    ("ta", 0x0B80, 0x0BFF, False),
    ("th", 0x0E00, 0x0E7F, False),
    ("he", 0x0590, 0x05FF, False),
    ("el", 0x0370, 0x03FF, False),
    ("ko", 0xAC00, 0xD7AF, False),
    ("ja", 0x3040, 0x30FF, False),
    ("zh", 0x4E00, 0x9FFF, True),    # Han (zh/ja)
    ("ru", 0x0400, 0x04FF, True),    # Cyrillic (ru/uk)
]


_ETHIOPIC_WORDS = {
    "am": {"ነው", "ናቸው", "እና", "ውስጥ", "አለ", "አይደለም", "ምን", "እኔ", "እንዴት", "ላይ", "ወደ", "ነበር", "ነኝ", "አንድ", "የለም", "ይህ", "እባክህ", "እባክሽ"},
    "ti": {"እዩ", "እዮም", "ኢዩ", "ኣብ", "ናይ", "ኣይኮነን", "እንታይ", "ኣነ", "ከመይ", "እየ", "ድማ", "ኮይኑ", "ኣለዎ", "ኣለኒ", "ኢዮም", "በጃኹም", "የቐንየለይ"},
}
_LATIN_WORDS = {
    "en": {"the", "and", "is", "are", "of", "to", "in", "that", "it", "you", "for", "with", "this", "what", "where", "how", "my", "have", "not", "please", "hello", "hi", "thank", "thanks"},
    "om": {"fi", "kan", "akka", "jira", "keessa", "irra", "kana", "sun", "isaa", "isaan", "ani", "ati", "nan", "nuti", "jedhu", "waan", "yoo", "garuu", "immoo", "hin", "dha", "miti", "ture", "mana", "maal", "eessa", "akkam", "galatoomi", "nagaa", "baga", "bakka"},
    "so": {"iyo", "waa", "oo", "ka", "ku", "ee", "ayaa", "aan", "waxaa", "waxay", "uu", "ay", "kale", "sida", "laakiin", "haddii", "soo", "wuu", "way", "maxaa", "goorma", "halkee", "mahadsanid", "salaan", "fadlan"},
    "sw": {"na", "ya", "wa", "kwa", "ni", "katika", "hii", "huo", "sana", "habari", "asante", "karibu", "tafadhali", "sijui", "wapi", "nini", "gani", "mimi", "wewe"},
    "fr": {"le", "la", "les", "et", "est", "des", "un", "une", "que", "pour", "pas", "vous", "je", "nous", "dans", "bonjour", "merci", "avec", "sont"},
    "es": {"el", "los", "las", "y", "es", "que", "en", "una", "por", "para", "no", "con", "hola", "gracias", "donde", "dónde", "como", "cómo", "está"},
    "de": {"der", "die", "das", "und", "ist", "nicht", "ich", "du", "ein", "eine", "zu", "mit", "wie", "wo", "hallo", "danke", "bitte"},
    "it": {"il", "che", "di", "è", "per", "non", "con", "ciao", "grazie", "dove", "come", "sono", "una", "della"},
    "pt": {"os", "as", "é", "um", "uma", "para", "não", "com", "olá", "obrigado", "obrigada", "onde", "como", "você", "estou"},
}
_TOKEN = re.compile(r"[\w'ʼ’]+", re.UNICODE)


def _tokens(text: str) -> list:
    return [t.casefold() for t in _TOKEN.findall(text)]


def _refine(best: str, text: str) -> str:
    """Pick between languages that share a script, from common words. Falls back to `best`."""
    toks = _tokens(text)
    if best == "am":                                   # Ethiopic: Amharic or Tigrinya
        ti = sum(t in _ETHIOPIC_WORDS["ti"] for t in toks) + text.count("ኣ")      # ኣ is typical of Tigrinya spelling
        am = sum(t in _ETHIOPIC_WORDS["am"] for t in toks)
        return "ti" if ti > am else "am"
    if best == "en":                                   # Latin script
        scores = {code: sum(t in words for t in toks) for code, words in _LATIN_WORDS.items()}
        top = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        if top[0][1] >= 1 and top[0][1] > top[1][1]:
            return top[0][0]
    return best


def detect_language(text: str) -> dict:
    counts: dict = {}
    for ch in text:
        cp = ord(ch)
        for code, lo, hi, _amb in RANGES:
            if lo <= cp <= hi:
                counts[code] = counts.get(code, 0) + 1
                break
        else:
            if ch.isalpha() and cp < 0x250:
                counts["en"] = counts.get("en", 0) + 1
    if not counts:
        return {"language": None, "method": "script-heuristic", "ambiguous": True}
    best = _refine(max(counts, key=counts.get), text)
    ambiguous = best in {"en", "am", "ti", "om", "so", "sw", "fr", "es", "de", "it", "pt", "ar", "hi", "zh", "ru"}
    return {"language": best, "method": "script-heuristic", "ambiguous": ambiguous}
