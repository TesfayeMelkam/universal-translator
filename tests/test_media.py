"""Audio/video + subtitle pipeline. Uses real FFmpeg and numpy when installed (skipped otherwise)."""
import io
import math
import os
import shutil
import struct
import subprocess
import tempfile
import time
import unittest
import wave

from ai_services.jobs import JobManager
from ai_services.providers.base import ProviderError, STTProvider
from ai_services.providers.translation.mock import MockTranslationProvider
from ai_services.services import audio
from ai_services.services.subtitles import Segment, format_srt, make_subtitles

HAVE = shutil.which("ffmpeg") is not None
try:
    import numpy  # noqa: F401
except ImportError:
    HAVE = False


def tone_wav(seconds=3.0, rate=22050, freq=440, amp=0.5):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", int(amp * 32767 * math.sin(2 * math.pi * freq * i / rate)))
                               for i in range(int(seconds * rate))))
    return buf.getvalue()


def silent_wav(seconds=2.0):
    return tone_wav(seconds, amp=0.0)


class FakeSTT(STTProvider):
    name = "fake"
    def __init__(self, text="Hello"):
        self.text, self.calls = text, []
    def transcribe(self, samples, language):
        self.calls.append((len(samples), language))
        return self.text


class PureTests(unittest.TestCase):
    def test_srt_format(self):
        s = format_srt([Segment(0, 15, "Hello"), Segment(3661.5, 3675.25, "Bye")])
        self.assertEqual(s, "1\n00:00:00,000 --> 00:00:15,000\nHello\n\n2\n01:01:01,500 --> 01:01:15,250\nBye\n")


@unittest.skipUnless(HAVE, "ffmpeg/numpy not installed")
class MediaTests(unittest.TestCase):
    def test_decode_resamples_to_16k_mono(self):
        pcm = audio.decode_pcm16(tone_wav(3.0, rate=22050))
        self.assertAlmostEqual(len(pcm) / 2 / audio.SAMPLE_RATE, 3.0, delta=0.1)

    def test_video_file_audio_track(self):
        d = tempfile.mkdtemp()
        out = os.path.join(d, "t.mp4")
        r = subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=duration=2:size=64x64:rate=5",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-shortest", "-pix_fmt", "yuv420p", out],
                           capture_output=True)
        if r.returncode != 0:
            self.skipTest("this ffmpeg cannot make a test mp4")
        pcm = audio.decode_pcm16(open(out, "rb").read())
        self.assertAlmostEqual(len(pcm) / 2 / audio.SAMPLE_RATE, 2.0, delta=0.2)

    def test_bad_input(self):
        for data, code in [(b"", "invalid_media"), (b"definitely not media" * 50, "invalid_media")]:
            with self.assertRaises(ProviderError) as cm:
                audio.decode_pcm16(data)
            self.assertEqual(cm.exception.code, code)

    def test_too_long(self):
        with self.assertRaises(ProviderError) as cm:
            audio.decode_pcm16(tone_wav(3.0), max_seconds=1)
        self.assertEqual(cm.exception.code, "media_too_long")

    def test_subtitles_windows_and_timing(self):
        stt = FakeSTT("Hello")
        r = make_subtitles(stt, None, tone_wav(3.0), "en", None, chunk_seconds=1)
        self.assertEqual(r["segments"], 3)
        self.assertIn("1\n00:00:00,000 --> 00:00:01,000\nHello", r["srt"])
        self.assertIn("3\n00:00:02,000 --> 00:00:03,0", r["srt"])
        self.assertTrue(all(lang == "en" for _, lang in stt.calls))
        self.assertFalse(r["translated"])

    def test_silence_is_skipped(self):
        stt = FakeSTT()
        with self.assertRaises(ProviderError) as cm:
            make_subtitles(stt, None, silent_wav(2.0), "en", None, chunk_seconds=1)
        self.assertEqual(cm.exception.code, "no_speech_found")
        self.assertEqual(stt.calls, [])                              # the model was never even asked

    def test_translated_subtitles_keep_timing(self):
        r = make_subtitles(FakeSTT("Hello"), MockTranslationProvider(), tone_wav(2.0), "en", "am", chunk_seconds=1)
        self.assertTrue(r["translated"] and r["mock"])
        self.assertIn("00:00:00,000 --> 00:00:01,000\nሰላም", r["srt"])
        self.assertIn("Hello", r["source_srt"])

    def test_progress_reported(self):
        seen = []
        make_subtitles(FakeSTT(), None, tone_wav(3.0), "en", None, chunk_seconds=1, report=lambda p, n: seen.append(p))
        self.assertEqual(seen[-1], 1.0)
        self.assertEqual(seen, sorted(seen))


class JobTests(unittest.TestCase):
    def test_success_error_and_ownership(self):
        jm = JobManager(run_async=False)
        ok = jm.submit(lambda report: (report(0.5, "half"), {"segments": 2})[1], owner=1)
        self.assertEqual(jm.status(ok, 1)["status"], "done")
        self.assertEqual(jm.status(ok, 1)["segments"], 2)
        with self.assertRaises(ProviderError):
            jm.status(ok, 2)                                           # someone else's job
        def boom(report):
            raise ProviderError("no_speech_found", "none", 422)
        bad = jm.submit(boom)
        self.assertEqual(jm.status(bad)["error"]["code"], "no_speech_found")
        def crash(report):
            raise RuntimeError("secret internal detail")
        st = jm.status(jm.submit(crash))
        self.assertEqual(st["error"]["code"], "job_failed")
        self.assertNotIn("secret", str(st))

    def test_busy_limit_and_threads(self):
        jm = JobManager(max_running=1)
        gate = []
        jid = jm.submit(lambda report: (time.sleep(0.3), {})[1])
        with self.assertRaises(ProviderError) as cm:
            jm.submit(lambda report: {})
        self.assertEqual(cm.exception.code, "busy")
        for _ in range(50):
            if jm.status(jid)["status"] == "done":
                break
            time.sleep(0.05)
        self.assertEqual(jm.status(jid)["status"], "done")


if __name__ == "__main__":
    unittest.main()
