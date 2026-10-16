"""Image pipeline: decode → validate → OCR → translate. Images stay in memory; nothing is written to disk."""
from __future__ import annotations

import base64
import binascii

from shared.languages import get_language
from ..providers.base import OCRProvider, ProviderError, TranslationProvider
from .pipeline import translate_text


def detect_image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def decode_image(payload: str, max_bytes: int) -> bytes:
    if not payload:
        raise ProviderError("invalid_image", "No image was sent.", 422)
    if payload.startswith("data:"):
        _, _, payload = payload.partition(",")
    try:
        data = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProviderError("invalid_image", "The image data is not valid.", 422) from exc
    if len(data) > max_bytes:
        raise ProviderError("image_too_large", f"Image is larger than {max_bytes // 1_000_000} MB.", 413)
    if detect_image_type(data) is None:
        raise ProviderError("unsupported_image_type", "Only PNG, JPEG and WebP images are accepted.", 415)
    return data


def translate_image(ocr: OCRProvider, translator: TranslationProvider, image_payload: str,
                    source: str, target: str, max_bytes: int, max_chars: int) -> dict:
    if source == "auto":
        raise ProviderError("source_required", "Choose the language of the text in the picture.", 422)
    if not get_language(source):
        raise ProviderError("unknown_language", f"Unknown source language '{source}'.", 422)
    image = decode_image(image_payload, max_bytes)
    found = ocr.recognize(image, source)          # OCR = reading the text; it is not translation
    text = (found.text or "").strip()
    if not text:
        raise ProviderError("no_text_found",
                            "No readable text was found. Try a closer, sharper photo with good light.", 422)
    truncated = len(text) > max_chars
    result = translate_text(translator, text[:max_chars], source, target, max_chars)
    result["ocr"] = {"provider": found.provider, "is_mock": found.is_mock, "regions": found.regions,
                     "confidence": found.confidence, "truncated": truncated}
    result["overlay"] = _overlay(translator, found.regions, result["source"], target, max_chars)
    return result


MAX_OVERLAY_REGIONS = 40


def _overlay(translator, regions, source, target, max_chars):
    """Translate every detected line separately so the translation can be drawn exactly where the text was.
    A line that fails to translate is left out; the whole-text translation is still returned."""
    out, cache = [], {}
    for r in (regions or [])[:MAX_OVERLAY_REGIONS]:
        text = (r.get("text") or "").strip()
        if not text or r.get("w", 0) <= 0 or r.get("h", 0) <= 0:
            continue
        if text not in cache:
            try:
                cache[text] = translate_text(translator, text[:max_chars], source, target, max_chars)["translation"]
            except ProviderError:
                cache[text] = None
        if cache[text]:
            out.append({"text": text, "translation": cache[text], "x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]})
    return out
