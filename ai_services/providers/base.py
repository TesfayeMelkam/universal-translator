"""Provider contracts. Every AI backend implements one of these so it can be swapped by config."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class ProviderError(Exception):
    """Normalised provider failure. `code` is stable and safe to show to clients."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass
class TranslationResult:
    text: str
    provider: str
    is_mock: bool = False


class TranslationProvider(ABC):
    name: str = "base"
    is_mock: bool = False

    def available(self) -> tuple[bool, str]:
        """Return (ready, reason). Must never claim ready if a model failed to load."""
        return True, "ok"

    def supports(self, source: str, target: str) -> bool:
        return True

    @abstractmethod
    def translate(self, text: str, source: str, target: str) -> TranslationResult: ...


class TTSProvider(ABC):
    name: str = "base"

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    @abstractmethod
    def synthesize(self, text: str, language: str) -> bytes:
        """Return WAV bytes."""


class STTProvider(ABC):
    name: str = "base"

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    @abstractmethod
    def transcribe(self, samples, language: str) -> str:
        """samples: float32 numpy array, mono, 16 kHz, values in [-1, 1]."""


@dataclass
class OCRResult:
    text: str
    provider: str
    is_mock: bool = False
    regions: Optional[list] = None      # [{"text","x","y","w","h"}] when the engine returns boxes
    confidence: Optional[float] = None  # engine's own 0-100 score, only if the engine reports one


class OCRProvider(ABC):
    name: str = "base"
    is_mock: bool = False

    def available(self) -> tuple[bool, str]:
        return True, "ok"

    @abstractmethod
    def recognize(self, image: bytes, language: str) -> OCRResult: ...
