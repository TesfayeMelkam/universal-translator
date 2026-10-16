"""Speech-to-text with Meta MMS (supports Amharic, Afaan Oromo, Tigrinya and ~1100 other languages).

UNVERIFIED in the build environment (no model, no network). Needs:  pip install transformers torch numpy
and a large download (facebook/mms-1b-all, several GB): run  python scripts/download_models.py --model mms-asr
CPU speed is slow (several seconds per 15 s of audio) and accuracy for low-resource languages varies.
"""
from __future__ import annotations

import threading

from shared.languages import get_language
from ..base import ProviderError, STTProvider

ISO3_OVERRIDES = {"om": "orm", "ar": "ara", "fa": "pes", "zh": "cmn", "ms": "zlm", "no": "nob", "sw": "swh",
                  "et": "est", "lv": "lvs", "mn": "khk", "ne": "npi", "uz": "uzn", "az": "azj", "sq": "sqi"}


def iso3(code: str) -> str:
    if code in ISO3_OVERRIDES:
        return ISO3_OVERRIDES[code]
    lang = get_language(code)
    return (lang.nllb or code)[:3] if lang else code


class MMSSTTProvider(STTProvider):
    name = "mms"

    def __init__(self, model_id: str, cache_dir: str, allow_download: bool = False):
        self.model_id, self.cache_dir, self.allow_download = model_id, cache_dir, allow_download
        self._proc = self._model = self._lang = None
        self._lock = threading.Lock()
        self._error = None

    def available(self):
        try:
            import numpy, torch, transformers  # noqa: F401
            return True, "ok"
        except ImportError:
            return False, "Install: pip install transformers torch numpy, then download the model."

    def _load(self):
        if self._model is not None:
            return
        if self._error:
            raise ProviderError("stt_unavailable", self._error, 503)
        try:
            from transformers import AutoProcessor, Wav2Vec2ForCTC
            kw = dict(cache_dir=self.cache_dir, local_files_only=not self.allow_download)
            self._proc = AutoProcessor.from_pretrained(self.model_id, **kw)
            self._model = Wav2Vec2ForCTC.from_pretrained(self.model_id, **kw)
        except Exception as exc:  # noqa: BLE001
            self._error = f"Speech model could not be loaded ({type(exc).__name__}). Run scripts/download_models.py --model mms-asr"
            raise ProviderError("stt_unavailable", self._error, 503) from exc

    def transcribe(self, samples, language: str) -> str:
        ok, reason = self.available()
        if not ok:
            raise ProviderError("stt_unavailable", reason, 501)
        import torch
        with self._lock:
            self._load()
            code = iso3(language)
            if code != self._lang:
                try:
                    self._proc.tokenizer.set_target_lang(code)
                    self._model.load_adapter(code)
                except Exception as exc:  # noqa: BLE001
                    raise ProviderError("stt_language_unsupported", f"The speech model has no '{code}' voice.", 422) from exc
                self._lang = code
            inputs = self._proc(samples, sampling_rate=16000, return_tensors="pt")
            with torch.no_grad():
                logits = self._model(**inputs).logits
            return self._proc.decode(torch.argmax(logits, dim=-1)[0])
