"""Optional server-side text-to-speech through the operating system voices (pyttsx3).

On Windows this uses SAPI5 voices. Installed voices decide which languages work;
most Windows PCs have English only unless you add language packs. UNVERIFIED here (no Windows).
The web UI uses the browser's speechSynthesis by default, which needs no server TTS.
"""
from __future__ import annotations

import os
import tempfile

from ..base import ProviderError, TTSProvider


class Pyttsx3TTSProvider(TTSProvider):
    name = "pyttsx3"

    def available(self):
        try:
            import pyttsx3  # noqa: F401
            return True, "ok"
        except ImportError:
            return False, "pyttsx3 is not installed (pip install pyttsx3)."

    def synthesize(self, text: str, language: str) -> bytes:
        ok, reason = self.available()
        if not ok:
            raise ProviderError("tts_unavailable", reason, 501)
        try:
            import pythoncom  # Windows only: needed when SAPI runs in a worker thread
            pythoncom.CoInitialize()
        except ImportError:
            pass
        import pyttsx3
        try:
            engine = pyttsx3.init()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("tts_failed", "The system voice engine could not start.", 502) from exc
        for voice in engine.getProperty("voices"):
            langs = [str(x).lower() for x in (getattr(voice, "languages", []) or [])]
            if any(language.lower() in l for l in langs) or language.lower() in (voice.id or "").lower():
                engine.setProperty("voice", voice.id)
                break
        else:
            if language != "en":
                raise ProviderError("voice_unavailable", f"No installed voice for '{language}'.", 422)
        fd, path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            engine.save_to_file(text, path)
            engine.runAndWait()
            with open(path, "rb") as fh:
                data = fh.read()
            if not data:
                raise ProviderError("tts_failed", "The voice engine produced no audio.", 502)
            return data
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("tts_failed", "Speech synthesis failed.", 502) from exc
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
