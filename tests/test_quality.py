import re
import unittest

from ai_services.providers.base import ProviderError, TranslationProvider, TranslationResult
from ai_services.providers.translation.mock import MockTranslationProvider
from ai_services.services.quality import grade, run_selftest, similarity
from shared.languages import LANGUAGES, get_language


class CatalogScaleTests(unittest.TestCase):
    def test_over_150_languages_with_valid_unique_codes(self):
        self.assertGreaterEqual(len(LANGUAGES), 150)
        codes = [l.code for l in LANGUAGES]
        nllb = [l.nllb for l in LANGUAGES if l.nllb]          # data-only languages (Wolaytta, Sidama ...) have no NLLB code
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(len(nllb), len(set(nllb)))
        for l in LANGUAGES:
            if l.nllb:
                self.assertRegex(l.nllb, r"^[a-z]{3}_[A-Z][a-z]{3}$", l.code)
            self.assertTrue(l.native_name and l.speech_tag, l.code)

    def test_ethiopian_group(self):
        eth = {l.code for l in LANGUAGES if l.group == "ethiopian"}
        self.assertTrue({"am", "om", "ti", "so"} <= eth)
        self.assertTrue({"aa", "wal", "sid", "ktb", "hdy", "gmv", "sgw", "har", "anu", "gez"} <= eth)

    def test_rtl_scripts_are_flagged(self):
        for l in LANGUAGES:
            if l.script in ("Arab", "Hebr"):
                self.assertTrue(l.rtl, l.code)


class SimilarityTests(unittest.TestCase):
    def test_scores(self):
        self.assertEqual(similarity("Hello, how are you?", "hello how are you"), 1.0)
        self.assertLess(similarity("Hello, how are you?", "Where is the hospital"), 0.4)
        self.assertEqual(similarity("", "x"), 0.0)
        self.assertGreater(similarity("Thank you very much", "Thank you so much"), 0.5)

    def test_grades(self):
        self.assertEqual([grade(0.9), grade(0.6), grade(0.1)], ["good", "fair", "poor"])


class SelfTestRunner(unittest.TestCase):
    def test_mock_roundtrip_is_flagged_mock(self):
        rep = run_selftest(MockTranslationProvider(), ["am"], ["Hello", "Thank you"])
        self.assertTrue(rep["is_mock"])
        self.assertEqual(rep["languages"][0]["score"], 1.0)      # greetings round-trip in the phrasebook
        self.assertIn("not prove", rep["disclaimer"])

    def test_echo_model_is_caught(self):
        class Echo(TranslationProvider):
            name = "echo"
            def translate(self, text, s, t):
                return TranslationResult(text, self.name)
        e = run_selftest(Echo(), ["am"], ["Hello there", "Good night", "Thank you"])["languages"][0]
        self.assertEqual(e["unchanged"], 3)
        self.assertEqual(e["grade"], "poor")                      # echoing English must never look "good"

    def test_unsupported_and_errors(self):
        class Picky(TranslationProvider):
            name = "picky"
            def supports(self, s, t):
                return "om" not in (s, t)
            def translate(self, text, s, t):
                if "ti" in (s, t):
                    raise ProviderError("model_unavailable", "down", 503)
                return TranslationResult("x " + text, self.name)
        rep = run_selftest(Picky(), ["om", "ti", "en", "zz"], ["Hello"])
        grades = {e["code"]: e["grade"] for e in rep["languages"]}
        self.assertEqual(grades, {"om": "unsupported", "ti": "error", "en": "unsupported", "zz": "unsupported"})


if __name__ == "__main__":
    unittest.main()
