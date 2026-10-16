"""Audio/video -> subtitles. Speech is cut into fixed windows (default 15 s) and each window is recognised
on its own, so cue timing is APPROXIMATE (window-level, not word-level) and words can be cut at window edges."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from ..providers.base import ProviderError, STTProvider, TranslationProvider
from .audio import SAMPLE_RATE, decode_pcm16, to_float
from .documents import translate_document


@dataclass
class Segment:
    start: float
    end: float
    text: str


def _ts(sec: float) -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_srt(segments: List[Segment]) -> str:
    return "\n".join(f"{i}\n{_ts(s.start)} --> {_ts(s.end)}\n{s.text}\n" for i, s in enumerate(segments, 1))


def transcribe_pcm(stt: STTProvider, pcm: bytes, language: str, chunk_seconds: int = 15,
                   report: Optional[Callable[[float, str], None]] = None, silence_rms: float = 0.004) -> List[Segment]:
    import numpy as np
    total = len(pcm) // 2
    step = chunk_seconds * SAMPLE_RATE
    segs: List[Segment] = []
    for n, a in enumerate(range(0, total, step)):
        b = min(a + step, total)
        samples = to_float(pcm[a * 2: b * 2])
        if report:
            report(a / max(total, 1), f"Listening {a // SAMPLE_RATE}s of {total // SAMPLE_RATE}s")
        if len(samples) < SAMPLE_RATE // 4 or float(np.sqrt(np.mean(samples ** 2))) < silence_rms:
            continue                                  # silence: skip (saves a lot of time)
        text = (stt.transcribe(samples, language) or "").strip()
        if text:
            segs.append(Segment(a / SAMPLE_RATE, b / SAMPLE_RATE, text))
    if not segs:
        raise ProviderError("no_speech_found", "No speech was found in this file.", 422)
    return segs


def make_subtitles(stt: STTProvider, translator: Optional[TranslationProvider], media: bytes, source: str,
                   target: Optional[str], max_seconds: int = 1800, chunk_seconds: int = 15,
                   report: Optional[Callable[[float, str], None]] = None) -> dict:
    pcm = decode_pcm16(media, max_seconds)
    segs = transcribe_pcm(stt, pcm, source, chunk_seconds, report)
    srt = format_srt(segs)
    out = {"source_srt": srt, "srt": srt, "segments": len(segs), "translated": False}
    if target and target != source:
        if translator is None:
            raise ProviderError("no_translator", "No translator configured.", 503)
        if report:
            report(0.95, "Translating")
        doc = translate_document(translator, srt.encode(), "subtitles.srt", source, target)
        out.update(srt=doc.data.decode(), translated=True, mock=doc.stats["mock"])
    if report:
        report(1.0, "Done")
    return out
