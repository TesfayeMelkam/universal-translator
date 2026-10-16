"""Audio/video -> 16 kHz mono PCM using FFmpeg (must be installed separately: https://ffmpeg.org).
Files go through a temporary file that is always deleted. Nothing is kept."""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from ..providers.base import ProviderError

SAMPLE_RATE = 16000


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def decode_pcm16(data: bytes, max_seconds: int = 1800, timeout: int = 300) -> bytes:
    """Return raw signed 16-bit little-endian mono 16 kHz samples."""
    if not data:
        raise ProviderError("invalid_media", "The file is empty.", 422)
    if not ffmpeg_available():
        raise ProviderError("ffmpeg_missing", "FFmpeg is not installed. Install it and make sure `ffmpeg` is on PATH.", 501)
    fd, path = tempfile.mkstemp(prefix="ut_media_")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        cmd = ["ffmpeg", "-nostdin", "-v", "error", "-i", path, "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE),
               "-t", str(max_seconds + 1), "-f", "s16le", "pipe:1"]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise ProviderError("media_timeout", "Decoding the file took too long.", 408)
        if proc.returncode != 0 or not proc.stdout:
            raise ProviderError("invalid_media", "That file could not be read as audio or video.", 422)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    pcm = proc.stdout
    if len(pcm) // 2 / SAMPLE_RATE > max_seconds:
        raise ProviderError("media_too_long", f"Audio is longer than {max_seconds // 60} minutes.", 413)
    return pcm[: len(pcm) - (len(pcm) % 2)]


def to_float(pcm: bytes):
    import numpy as np
    return np.frombuffer(pcm, dtype="<i2").astype("float32") / 32768.0
