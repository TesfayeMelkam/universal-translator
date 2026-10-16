"""Text-to-speech with Meta MMS-TTS (has voices for Amharic, Afaan Oromo, Tigrinya and many more).

UNVERIFIED in the build environment. Needs: pip install transformers torch numpy and one small model per language
(about 150 MB each): python scripts/download_models.py --tts amh orm tir
Voices are single-speaker and robotic-ish; quality is fine for understanding, not for performance.
"""
from __future__ import annotations

import io
import threading
import wave

from ..base import ProviderError, TTSProvider
from ..stt.mms import iso3


class MMSTTSProvider(TTSProvider):
    name = "mms"

    def __init__(self, cache_dir: str, allow_download: bool = False, keep: int = 3):
        self.cache_dir, self.allow_download, self.keep = cache_dir, allow_download, keep
        self._models: dict = {}
        self._lock = threading.Lock()

    def available(self):
        try:
            import numpy, torch, transformers  # noqa: F401
            return True, "ok"
        except ImportError:
            return False, "Install: pip install transformers torch numpy, then download a voice."

    def _get(self, code: str):
        if code in self._models:
            return self._models[code]
        try:
            from transformers import AutoTokenizer, VitsModel
            kw = dict(cache_dir=self.cache_dir, local_files_only=not self.allow_download)
            name = f"facebook/mms-tts-{code}"
            pair = (AutoTokenizer.from_pretrained(name, **kw), VitsModel.from_pretrained(name, **kw))
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("voice_unavailable", f"No voice installed for '{code}'. Run scripts/download_models.py --tts {code}", 422) from exc
        if len(self._models) >= self.keep:
            self._models.pop(next(iter(self._models)))
        self._models[code] = pair
        return pair

    def synthesize(self, text: str, language: str) -> bytes:
        ok, reason = self.available()
        if not ok:
            raise ProviderError("tts_unavailable", reason, 501)
        import numpy as np
        import torch
        with self._lock:
            tok, model = self._get(iso3(language))
            try:
                with torch.no_grad():
                    wav = model(**tok(text, return_tensors="pt")).waveform[0].cpu().numpy()
            except Exception as exc:  # noqa: BLE001
                raise ProviderError("tts_failed", "Speech synthesis failed.", 502) from exc
        pcm = (np.clip(wav, -1, 1) * 32767).astype("<i2").tobytes()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(int(model.config.sampling_rate)); w.writeframes(pcm)
        return buf.getvalue()
