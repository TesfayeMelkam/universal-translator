"""MOCK translator for development/tests. Not real machine translation.

Knows a tiny phrasebook (greetings) and otherwise returns a clearly marked placeholder,
so nobody mistakes it for a working model.
"""
from __future__ import annotations

from ..base import TranslationProvider, TranslationResult

# Short greetings only. Pivot language is English.
PHRASEBOOK = {
    "hello": {"am": "ሰላም", "om": "Akkam", "ti": "ሰላም", "so": "Salaan", "ar": "مرحبا",
              "fr": "Bonjour", "es": "Hola", "sw": "Habari", "de": "Hallo", "it": "Ciao"},
    "thank you": {"am": "አመሰግናለሁ", "om": "Galatoomi", "ti": "የቐንየለይ", "so": "Mahadsanid",
                  "ar": "شكرا", "fr": "Merci", "es": "Gracias", "sw": "Asante",
                  "de": "Danke", "it": "Grazie"},
    "yes": {"am": "አዎ", "ar": "نعم", "fr": "Oui", "es": "Sí", "de": "Ja", "it": "Sì", "sw": "Ndiyo"},
    "no": {"am": "አይ", "ar": "لا", "fr": "Non", "es": "No", "de": "Nein", "it": "No", "sw": "Hapana"},
}
_REVERSE = {}
for _en, _tr in PHRASEBOOK.items():
    for _code, _word in _tr.items():
        _REVERSE[(_code, _word.lower())] = _en


class MockTranslationProvider(TranslationProvider):
    name = "mock"
    is_mock = True

    def translate(self, text: str, source: str, target: str) -> TranslationResult:
        key = text.strip().lower().rstrip("!.?")
        english = key if source == "en" else _REVERSE.get((source, key))
        if english in PHRASEBOOK:
            if target == "en":
                return TranslationResult(english.capitalize(), self.name, True)
            if target in PHRASEBOOK[english]:
                return TranslationResult(PHRASEBOOK[english][target], self.name, True)
        return TranslationResult(f"[MOCK {source}→{target}] {text}", self.name, True)
