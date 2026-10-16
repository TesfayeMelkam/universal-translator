"""Core tests: need only the standard library (run with `python -m unittest` or pytest)."""
import unittest

from shared.languages import LANGUAGES, get_language, search
from ai_services.providers.base import ProviderError
from ai_services.providers.translation.mock import MockTranslationProvider
from ai_services.services.detect import detect_language
from ai_services.services.history import HistoryStore
from ai_services.services.pipeline import translate_text

P = MockTranslationProvider()


class CatalogTests(unittest.TestCase):
    def test_at_least_30_languages(self):
        self.assertGreaterEqual(len(LANGUAGES), 30)

    def test_codes_unique_and_required_present(self):
        codes = [l.code for l in LANGUAGES]
        self.assertEqual(len(codes), len(set(codes)))
        for c in ["am", "om", "ti", "so", "en", "ar", "fr", "zh", "sw", "ur"]:
            self.assertIn(c, codes)

    def test_metadata_complete(self):
        for l in LANGUAGES:
            self.assertTrue(l.english_name and l.native_name and l.script and l.speech_tag, l.code)
            self.assertIn(l.group, {"ethiopian", "african", "world"})

    def test_rtl_flags(self):
        for c in ["ar", "fa", "ur", "he"]:
            self.assertTrue(get_language(c).rtl)
        self.assertFalse(get_language("am").rtl)

    def test_search_native_and_english(self):
        self.assertEqual(search("amhar")[0].code, "am")
        self.assertEqual(search("አማርኛ")[0].code, "am")
        self.assertEqual(search("zzzz"), [])


class PipelineTests(unittest.TestCase):
    def test_known_phrase(self):
        r = translate_text(P, "Hello", "en", "am", 100)
        self.assertEqual(r["translation"], "ሰላም")
        self.assertTrue(r["is_mock"])

    def test_reverse_phrase(self):
        self.assertEqual(translate_text(P, "ሰላም", "am", "en", 100)["translation"], "Hello")

    def test_unknown_text_is_marked_as_mock(self):
        r = translate_text(P, "A long unknown sentence", "en", "fr", 100)
        self.assertTrue(r["translation"].startswith("[MOCK en→fr]"))

    def test_auto_detect(self):
        r = translate_text(P, "ሰላም", "auto", "en", 100)
        self.assertEqual(r["source"], "am")
        self.assertEqual(r["translation"], "Hello")

    def test_errors(self):
        for text, s, t, code in [("", "en", "am", "empty_text"), ("x" * 11, "en", "am", "text_too_long"),
                                 ("hi", "xx", "am", "unknown_language"), ("hi", "en", "xx", "unknown_language"),
                                 ("hi", "en", "en", "same_language")]:
            with self.assertRaises(ProviderError) as cm:
                translate_text(P, text, s, t, 10)
            self.assertEqual(cm.exception.code, code)

    def test_unsupported_pair(self):
        class Picky(MockTranslationProvider):
            def supports(self, s, t):
                return False
        with self.assertRaises(ProviderError) as cm:
            translate_text(Picky(), "hi", "en", "am", 100)
        self.assertEqual(cm.exception.code, "unsupported_pair")


class DetectTests(unittest.TestCase):
    def test_scripts(self):
        self.assertEqual(detect_language("ሰላም")["language"], "am")
        self.assertEqual(detect_language("مرحبا")["language"], "ar")
        self.assertEqual(detect_language("こんにちは")["language"], "ja")
        self.assertEqual(detect_language("안녕하세요")["language"], "ko")
        self.assertIsNone(detect_language("12345 !!!")["language"])

    def test_latin_is_flagged_ambiguous(self):
        self.assertTrue(detect_language("hello")["ambiguous"])


class HistoryTests(unittest.TestCase):
    def test_add_list_favorite_clear(self):
        h = HistoryStore(":memory:")
        i = h.add("en", "am", "Hello", "ሰላም", "mock")
        self.assertEqual(h.list()[0]["translated_text"], "ሰላም")
        self.assertTrue(h.toggle_favorite(i))
        self.assertEqual(h.list()[0]["favorite"], 1)
        self.assertFalse(h.toggle_favorite(9999))
        h.clear()
        self.assertEqual(h.list(), [])


if __name__ == "__main__":
    unittest.main()
