"""Hugging Face NLLB-200 translation provider (real model, optional).

UNVERIFIED IN THE BUILD ENVIRONMENT: it needs `pip install transformers torch sentencepiece`
and a downloaded model, neither of which was possible when this project was generated.
Run `python scripts/download_models.py` first, then set TRANSLATION_PROVIDER=nllb.
The model is loaded lazily and never downloaded on app start-up.
"""
from __future__ import annotations

import threading

from shared.languages import get_language
from ..base import ProviderError, TranslationProvider, TranslationResult


class NLLBTranslationProvider(TranslationProvider):
    name = "nllb"

    def __init__(self, model_name: str, cache_dir: str, allow_download: bool = False):
        self.model_name = model_name
        self.cache_dir = cache_dir
        self.allow_download = allow_download
        self._tok = None
        self._model = None
        self._error = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is not None:
            return
        if self._error:
            raise ProviderError("model_unavailable", self._error, 503)
        with self._lock:
            if self._model is not None:
                return
            try:
                from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
                local_only = not self.allow_download
                self._tok = AutoTokenizer.from_pretrained(
                    self.model_name, cache_dir=self.cache_dir, local_files_only=local_only)
                self._model = AutoModelForSeq2SeqLM.from_pretrained(
                    self.model_name, cache_dir=self.cache_dir, local_files_only=local_only)
            except Exception as exc:  # noqa: BLE001 - normalise any load failure
                self._error = (f"NLLB model could not be loaded ({type(exc).__name__}). "
                               "Install transformers/torch and run scripts/download_models.py.")
                raise ProviderError("model_unavailable", self._error, 503) from exc

    def available(self):
        try:
            self._load()
            return True, "ok"
        except ProviderError as exc:
            return False, exc.message

    def _known(self, nllb_code: str) -> bool:
        """True if the loaded tokenizer really has this language token (guards against a wrong code)."""
        try:
            self._load()
        except ProviderError:
            return True        # model not loadable: let translate() report the real problem
        unk = self._tok.unk_token_id
        tid = self._tok.convert_tokens_to_ids(nllb_code)
        return tid is not None and tid != unk

    def unsupported_codes(self) -> list:
        from shared.languages import LANGUAGES
        return [l.code for l in LANGUAGES if l.nllb and not self._known(l.nllb)]

    def supports(self, source: str, target: str) -> bool:
        s, t = get_language(source), get_language(target)
        return bool(s and t and s.nllb and t.nllb and self._known(s.nllb) and self._known(t.nllb))

    def translate(self, text: str, source: str, target: str) -> TranslationResult:
        self._load()
        s, t = get_language(source), get_language(target)
        try:
            self._tok.src_lang = s.nllb
            inputs = self._tok(text, return_tensors="pt", truncation=True, max_length=512)
            out = self._model.generate(
                **inputs, forced_bos_token_id=self._tok.convert_tokens_to_ids(t.nllb), max_length=512)
            return TranslationResult(self._tok.batch_decode(out, skip_special_tokens=True)[0], self.name)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("translation_failed", "The translation model failed.", 502) from exc
