"""Vision pipeline tests (standard library only). Uses a genuine generated PNG, not an empty file."""
import base64
import struct
import unittest
import zlib

from ai_services.providers.base import OCRProvider, OCRResult, ProviderError
from ai_services.providers.translation.mock import MockTranslationProvider
from ai_services.providers.vision.mock import MockOCRProvider
from ai_services.services.vision_pipeline import decode_image, detect_image_type, translate_image


def make_png(w=8, h=8) -> bytes:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


PNG_B64 = base64.b64encode(make_png()).decode()
T = MockTranslationProvider()


class Empty(OCRProvider):
    name = "empty"
    def recognize(self, image, language):
        return OCRResult(text="   ", provider=self.name)


class Boxes(OCRProvider):
    name = "boxes"
    def recognize(self, image, language):
        return OCRResult("Thank you", self.name, regions=[{"text": "Thank you", "x": 1, "y": 2, "w": 3, "h": 4}], confidence=91.5)


class VisionTests(unittest.TestCase):
    def test_image_types(self):
        self.assertEqual(detect_image_type(make_png()), "png")
        self.assertEqual(detect_image_type(b"\xff\xd8\xff\xe0abc"), "jpeg")
        self.assertEqual(detect_image_type(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "webp")
        self.assertIsNone(detect_image_type(b"GIF89a"))

    def test_data_url_accepted(self):
        self.assertEqual(decode_image("data:image/png;base64," + PNG_B64, 10_000), make_png())

    def test_rejections(self):
        cases = [("", "invalid_image"), ("!!!notbase64", "invalid_image"),
                 (base64.b64encode(b"hello world not an image").decode(), "unsupported_image_type"),
                 (PNG_B64, "image_too_large")]
        for payload, code in cases:
            limit = 10 if code == "image_too_large" else 10_000
            with self.assertRaises(ProviderError) as cm:
                decode_image(payload, limit)
            self.assertEqual(cm.exception.code, code)

    def test_full_flow_with_mock(self):
        r = translate_image(MockOCRProvider(), T, PNG_B64, "en", "am", 10_000, 100)
        self.assertEqual(r["translation"], "ሰላም")
        self.assertTrue(r["ocr"]["is_mock"])

    def test_regions_and_confidence_passed_through(self):
        r = translate_image(Boxes(), T, PNG_B64, "en", "fr", 10_000, 100)
        self.assertEqual(r["translation"], "Merci")
        self.assertEqual(r["ocr"]["regions"][0]["w"], 3)
        self.assertEqual(r["ocr"]["confidence"], 91.5)

    def test_no_text_found(self):
        with self.assertRaises(ProviderError) as cm:
            translate_image(Empty(), T, PNG_B64, "en", "am", 10_000, 100)
        self.assertEqual(cm.exception.code, "no_text_found")

    def test_source_required_and_unknown(self):
        for src, code in [("auto", "source_required"), ("xx", "unknown_language")]:
            with self.assertRaises(ProviderError) as cm:
                translate_image(MockOCRProvider(), T, PNG_B64, src, "am", 10_000, 100)
            self.assertEqual(cm.exception.code, code)


if __name__ == "__main__":
    unittest.main()


class OverlayTests(unittest.TestCase):
    def test_each_line_translated_with_its_box(self):
        class TwoLines(OCRProvider):
            name = "two"
            def recognize(self, image, language):
                return OCRResult("Hello\nThank you", self.name, regions=[
                    {"text": "Hello", "x": 5, "y": 6, "w": 70, "h": 20},
                    {"text": "Thank you", "x": 5, "y": 40, "w": 120, "h": 22},
                    {"text": "", "x": 0, "y": 0, "w": 5, "h": 5},          # empty: skipped
                    {"text": "bad", "x": 0, "y": 0, "w": 0, "h": 0}])      # zero-size box: skipped
        r = translate_image(TwoLines(), T, PNG_B64, "en", "am", 10_000, 100)
        self.assertEqual([(o["text"], o["translation"], o["x"], o["y"]) for o in r["overlay"]],
                         [("Hello", "ሰላም", 5, 6), ("Thank you", "አመሰግናለሁ", 5, 40)])

    def test_failed_line_is_dropped_not_fatal(self):
        class Flaky(MockTranslationProvider):
            def translate(self, text, s, t):
                if text == "Thank you":
                    raise ProviderError("translation_failed", "x", 502)
                return super().translate(text, s, t)
        class Lines(OCRProvider):
            name = "l"
            def recognize(self, image, language):
                return OCRResult("Hello", self.name, regions=[{"text": "Hello", "x": 1, "y": 1, "w": 9, "h": 9},
                                                              {"text": "Thank you", "x": 1, "y": 20, "w": 9, "h": 9}])
        r = translate_image(Lines(), Flaky(), PNG_B64, "en", "am", 10_000, 100)
        self.assertEqual([o["text"] for o in r["overlay"]], ["Hello"])

    def test_no_regions_means_empty_overlay(self):
        self.assertEqual(translate_image(MockOCRProvider(), T, PNG_B64, "en", "am", 10_000, 100)["overlay"], [])
