"""Chooses providers from configuration."""
from __future__ import annotations

from .config import Settings
from .providers.base import TTSProvider, TranslationProvider
from .providers.translation.mock import MockTranslationProvider


ONLINE_ORDER = ("google", "azure", "libretranslate", "mymemory")


def _online_engine(name: str, s: Settings, transport=None):
    """(engine or None, warning or None). A missing key is a warning, never a crash."""
    from .providers.translation import cloud
    kw = dict(transport=transport, timeout=s.cloud_timeout, retries=s.cloud_retries)
    if name == "google":
        return (cloud.GoogleEngine(s.google_key, **kw), None) if s.google_key else (None, "google: GOOGLE_TRANSLATE_API_KEY is empty")
    if name == "azure":
        return (cloud.AzureEngine(s.azure_key, s.azure_region, s.azure_endpoint, **kw), None) if s.azure_key else \
            (None, "azure: AZURE_TRANSLATOR_KEY is empty")
    if name in ("libretranslate", "libre"):
        return (cloud.LibreEngine(s.libre_url, s.libre_key, **kw), None) if s.libre_url else (None, "libretranslate: LIBRETRANSLATE_URL is empty")
    if name == "mymemory":
        return cloud.MyMemoryEngine(s.mymemory_email, **kw), None
    return None, f"unknown translation engine '{name}'"


def build_translation_provider(s: Settings, glossary=None, transport=None) -> TranslationProvider:
    """TRANSLATION_PROVIDER = mock | nllb | auto | a comma list such as  google,mymemory,nllb

    auto = every online engine that is configured (google, azure, libretranslate by their keys/URL) and then the free
    MyMemory. Anything except plain `mock` is wrapped in the chain: phrasebook first, then the engines with fall-back."""
    tokens = [t for t in s.translation_provider.replace(" ", "").split(",") if t]
    if tokens in (["mock"], []):
        return MockTranslationProvider()
    engines, warnings = [], []
    for tok in tokens:
        names = ONLINE_ORDER if tok == "auto" else (tok,)
        for name in names:
            if name == "nllb":
                from .providers.translation.nllb import NLLBTranslationProvider
                engines.append(NLLBTranslationProvider(s.nllb_model, s.model_dir, s.allow_model_download))
                continue
            if name == "mock":
                warnings.append("mock was ignored in a list: it only knows a few greetings")
                continue
            eng, warn = _online_engine(name, s, transport)
            if eng is not None and all(e.name != eng.name for e in engines):
                engines.append(eng)
            elif warn and tok != "auto":                  # in `auto`, engines without a key are simply not used
                warnings.append(warn)
    from .providers.translation.chain import ChainTranslationProvider
    chain = ChainTranslationProvider(engines, glossary, cache_size=s.cache_size)
    chain.warnings = warnings
    return chain


def build_tts_provider(s: Settings):
    if s.tts_provider == "mms":
        from .providers.tts.mms import MMSTTSProvider
        return MMSTTSProvider(s.model_dir, s.allow_model_download)
    if s.tts_provider in ("pyttsx3", "auto"):
        from .providers.tts.pyttsx3_provider import Pyttsx3TTSProvider
        p: TTSProvider = Pyttsx3TTSProvider()
        return p
    return None


def build_ocr_provider(s: Settings):
    """auto = real Tesseract if it is usable, otherwise the clearly-labelled mock."""
    from .providers.vision.mock import MockOCRProvider
    if s.ocr_provider == "mock":
        return MockOCRProvider()
    from .providers.vision.tesseract import TesseractOCRProvider
    real = TesseractOCRProvider()
    if s.ocr_provider == "tesseract" or real.available()[0]:
        return real
    return MockOCRProvider()


def build_stt_provider(s: Settings):
    """None unless configured: server speech recognition needs a large model."""
    if s.stt_provider == "mms":
        from .providers.stt.mms import MMSSTTProvider
        return MMSSTTProvider(s.mms_asr_model, s.model_dir, s.allow_model_download)
    return None
