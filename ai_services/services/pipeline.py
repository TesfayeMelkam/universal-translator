"""Translation pipeline: validate → (detect) → provider → result."""
from __future__ import annotations

from shared.languages import get_language
from ..providers.base import ProviderError, TranslationProvider
from .detect import detect_language


def translate_text(provider: TranslationProvider, text: str, source: str, target: str, max_chars: int) -> dict:
    text = (text or "").strip()
    if not text:
        raise ProviderError("empty_text", "Please enter some text to translate.", 422)
    if len(text) > max_chars:
        raise ProviderError("text_too_long", f"Text is longer than {max_chars} characters.", 413)

    detected = None
    if source == "auto":
        detected = detect_language(text)
        if not detected["language"]:
            raise ProviderError("detect_failed", "Could not detect the language; please choose it.", 422)
        source = detected["language"]

    if not get_language(source):
        raise ProviderError("unknown_language", f"Unknown source language '{source}'.", 422)
    if not get_language(target):
        raise ProviderError("unknown_language", f"Unknown target language '{target}'.", 422)
    if source == target:
        raise ProviderError("same_language", "Source and target languages are the same.", 422)
    if not provider.supports(source, target):
        hint = getattr(provider, "unsupported_hint", None)
        raise ProviderError("unsupported_pair", hint(source, target) if hint else
                            f"Provider '{provider.name}' does not support {source}→{target}.", 422)

    result = provider.translate(text, source, target)
    return {
        "source": source,
        "target": target,
        "source_text": text,
        "translation": result.text,
        "provider": result.provider,
        "is_mock": result.is_mock,
        "detected": detected,
        "rtl": get_language(target).rtl,
    }
