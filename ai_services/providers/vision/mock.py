"""MOCK OCR for development. It does NOT read the image: it always returns the word "Hello".

It only exists so the camera flow can be tried without installing Tesseract.
"""
from ..base import OCRProvider, OCRResult


class MockOCRProvider(OCRProvider):
    name = "mock"
    is_mock = True

    def recognize(self, image: bytes, language: str) -> OCRResult:
        return OCRResult(text="Hello", provider=self.name, is_mock=True)
