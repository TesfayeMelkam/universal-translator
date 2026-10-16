"""Runs the REAL route functions of ai_services/main.py through a stand-in for FastAPI (tests/fastapi_shim.py).
Skipped automatically when real FastAPI is installed (then tests/test_api.py exercises the real thing)."""
import asyncio
import base64
import json
import os
import shutil
import time
import unittest
from dataclasses import replace

os.environ["DB_PATH"] = ":memory:"
try:
    import fastapi  # noqa: F401
    REAL = True
except ImportError:
    REAL = False
    from tests import fastapi_shim
    fastapi_shim.install()

if not REAL:
    from ai_services import main as M
    from ai_services.config import get_settings
    from ai_services.providers.base import STTProvider
    from tests.fastapi_shim import Client, WebSocket
    from tests.test_media import HAVE as MEDIA, tone_wav


def settings(**kw):
    base = dict(db_path=":memory:", translation_provider="mock", tts_provider="none", ocr_provider="mock",
                access_code="", auth_mode="off", stt_provider="none", telegram_token="", livekit_url="")
    base.update(kw)
    return replace(get_settings(), **base)


def client(**kw):
    return Client(M.create_app(settings(**kw)))


@unittest.skipIf(REAL, "real FastAPI installed: see tests/test_api.py")
class CoreRoutes(unittest.TestCase):
    def test_capabilities_health_languages(self):
        c = client()
        cap = c.get("/api/v1/capabilities").json()
        self.assertGreaterEqual(cap["languages"], 150)
        self.assertTrue(cap["translation"]["mock"])
        self.assertFalse(cap["stt"])
        self.assertEqual(cap["documents"], ["txt", "md", "srt", "vtt", "docx", "pdf"])
        self.assertTrue(c.get("/health").json()["mock"])
        self.assertGreaterEqual(len(c.get("/api/v1/languages").json()["languages"]), 150)

    def test_translate_errors_and_status(self):
        c = client()
        r = c.post("/api/v1/translate", json_body={"text": "Hello", "source": "en", "target": "am"})
        self.assertEqual(r.json()["translation"], "ሰላም")
        bad = c.post("/api/v1/translate", json_body={"text": "hi", "source": "en", "target": "zz"})
        self.assertEqual((bad.status_code, bad.json()["error"]["code"]), (422, "unknown_language"))
        st = c.get("/api/v1/translation/status").json()
        self.assertTrue(st["mock"] and st["ready"])
        rep = c.post("/api/v1/translation/selftest", json_body={"languages": ["am", "fr"], "phrases": 2}).json()
        self.assertEqual([e["code"] for e in rep["languages"]], ["am", "fr"])
        self.assertTrue(rep["is_mock"])


@unittest.skipIf(REAL, "real FastAPI installed")
class AccessAndAccounts(unittest.TestCase):
    def test_access_code_gates_host_features_only(self):
        c = client(access_code="letmein")
        self.assertEqual(c.post("/api/v1/rooms").status_code, 401)
        self.assertEqual(c.post("/api/v1/rooms", headers={"x-access-code": "bad"}).status_code, 401)
        code = c.post("/api/v1/rooms", headers={"x-access-code": "letmein"}).json()["code"]
        self.assertEqual(c.get(f"/api/v1/rooms/{code}").status_code, 200)      # guests need nothing
        self.assertEqual(c.get("/api/v1/languages").status_code, 200)
        self.assertEqual(c.get("/api/v1/history").status_code, 401)

    def test_accounts_end_to_end(self):
        app = M.create_app(settings(auth_mode="required"))
        a, b = Client(app), Client(app)
        self.assertEqual(a.post("/api/v1/translate", json_body={"text": "Hello", "source": "en", "target": "am"}).json()["error"]["code"], "login_required")
        self.assertEqual(a.post("/api/v1/auth/register", json_body={"username": "abel", "password": "short"}).status_code, 422)
        r = a.post("/api/v1/auth/register", json_body={"username": "abel", "password": "a-long-password"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("ut_session", a.cookies)
        value, flags = r.resp.cookies["ut_session"]
        self.assertTrue(flags["httponly"])
        self.assertEqual(flags["samesite"], "lax")
        self.assertEqual(a.get("/api/v1/auth/me").json()["user"]["username"], "abel")
        a.post("/api/v1/translate", json_body={"text": "Hello", "source": "en", "target": "am"})
        self.assertEqual(len(a.get("/api/v1/history").json()["items"]), 1)
        # a second person never sees the first person's history
        b.post("/api/v1/auth/register", json_body={"username": "sara", "password": "another-long-pass"})
        self.assertEqual(b.get("/api/v1/history").json()["items"], [])
        # cross-site cookie request is refused
        evil = a.post("/api/v1/translate", json_body={"text": "Hello", "source": "en", "target": "am"},
                      headers={"origin": "https://evil.example"})
        self.assertEqual(evil.json()["error"]["code"], "bad_origin")
        # logout, wrong password, lockout
        a.post("/api/v1/auth/logout")
        self.assertEqual(a.get("/api/v1/history").status_code, 401)
        codes = [a.post("/api/v1/auth/login", json_body={"username": "abel", "password": "nope-nope-nope"}).json()["error"]["code"] for _ in range(6)]
        self.assertEqual(codes[0], "bad_login")
        self.assertEqual(codes[-1], "too_many_attempts")

    def test_accounts_off_and_signup_closed(self):
        self.assertEqual(client().post("/api/v1/auth/register", json_body={"username": "abel", "password": "a-long-password"}).status_code, 404)
        c = client(auth_mode="optional", allow_signup=False)
        self.assertEqual(c.post("/api/v1/auth/register", json_body={"username": "abel", "password": "a-long-password"}).status_code, 403)


@unittest.skipIf(REAL, "real FastAPI installed")
class Documents(unittest.TestCase):
    def test_upload_translate_download(self):
        c = client()
        r = c.post("/api/v1/documents/translate", params={"source": "en", "target": "am", "filename": "n.txt"}, data=b"Hello\n\nyes")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content.decode(), "ሰላም\n\nአዎ")
        self.assertIn("n.am.txt", r.headers["Content-Disposition"])
        self.assertTrue(json.loads(r.headers["X-Doc-Stats"])["mock"])

    def test_limits_and_errors(self):
        c = client(max_doc_mb=1)
        big = c.post("/api/v1/documents/translate", params={"source": "en", "target": "am", "filename": "a.txt"}, data=b"x" * 1_100_000)
        self.assertEqual((big.status_code, big.json()["error"]["code"]), (413, "file_too_large"))
        nolen = c.post("/api/v1/documents/translate", params={"source": "en", "target": "am", "filename": "a.txt"}, data=b"Hello", omit_length=True)
        self.assertEqual(nolen.status_code, 411)
        exe = c.post("/api/v1/documents/translate", params={"source": "en", "target": "am", "filename": "a.exe"}, data=b"Hello")
        self.assertEqual(exe.json()["error"]["code"], "unsupported_document")


@unittest.skipIf(REAL, "real FastAPI installed")
class CallsAndLargeCalls(unittest.TestCase):
    def test_rtc_config_and_turn(self):
        c = client(turn_urls=("turn:t.example:3478",), turn_secret="sec")
        code = c.post("/api/v1/rooms").json()["code"]
        self.assertFalse(c.get("/api/v1/rtc-config").json()["turn"])
        real = c.get("/api/v1/rtc-config", params={"room": code}).json()
        self.assertTrue(real["turn"])
        self.assertNotIn("sec", json.dumps(real))

    def test_large_call_needs_livekit(self):
        c = client()
        self.assertEqual(c.post("/api/v1/rooms", params={"mode": "sfu"}).json()["error"]["code"], "livekit_not_configured")
        lk = client(livekit_url="wss://lk.example", livekit_key="KEY", livekit_secret="SEC")
        code = lk.post("/api/v1/rooms", params={"mode": "sfu"}).json()["code"]
        self.assertEqual(lk.get(f"/api/v1/rooms/{code}").json()["mode"], "sfu")
        tok = lk.get("/api/v1/livekit/token", params={"room": code, "name": "Abel"}).json()
        self.assertEqual(tok["url"], "wss://lk.example")
        pad = lambda s: s + "=" * (-len(s) % 4)
        claims = json.loads(base64.urlsafe_b64decode(pad(tok["token"].split(".")[1])))
        self.assertEqual((claims["iss"], claims["video"]["room"], claims["name"]), ("KEY", code, "Abel"))
        mesh = lk.post("/api/v1/rooms").json()["code"]
        self.assertEqual(lk.get("/api/v1/livekit/token", params={"room": mesh}).status_code, 409)
        self.assertEqual(lk.get("/api/v1/livekit/token", params={"room": "AAAAAA"}).status_code, 404)


@unittest.skipIf(REAL, "real FastAPI installed")
class SpeechAndSubtitles(unittest.TestCase):
    def test_not_configured_is_honest(self):
        c = client()
        self.assertEqual(c.post("/api/v1/transcribe", params={"language": "am"}, data=b"x").status_code, 501)
        self.assertEqual(c.post("/api/v1/subtitles", params={"source": "en"}, data=b"x").status_code, 501)

    @unittest.skipUnless(not REAL and MEDIA, "needs ffmpeg + numpy")
    def test_subtitle_job_end_to_end(self):
        class Fake(STTProvider):
            name = "fake"
            def transcribe(self, samples, language):
                return "Hello"
        orig = M.build_stt_provider
        M.build_stt_provider = lambda s: Fake()
        try:
            c = client()
        finally:
            M.build_stt_provider = orig
        wav = tone_wav(3.0)
        self.assertTrue(c.post("/api/v1/transcribe", params={"language": "en"}, data=wav).json()["text"] == "Hello")
        job = c.post("/api/v1/subtitles", params={"source": "en", "target": "am", "filename": "x.wav"}, data=wav).json()["job"]
        for _ in range(100):
            st = c.get(f"/api/v1/jobs/{job}").json()
            if st["status"] in ("done", "error"):
                break
            time.sleep(0.05)
        self.assertEqual(st["status"], "done", st)
        srt = c.get(f"/api/v1/jobs/{job}/download").content.decode()
        self.assertIn("ሰላም", srt)
        self.assertIn("Hello", c.get(f"/api/v1/jobs/{job}/download", params={"which": "source"}).content.decode())
        self.assertEqual(c.get("/api/v1/jobs/nonexistent").status_code, 404)


@unittest.skipIf(REAL, "real FastAPI installed")
class Telegram(unittest.TestCase):
    def test_webhook_secret_and_reply(self):
        sent = []
        orig = M.telegram_sender
        M.telegram_sender = lambda token: (lambda chat, text: sent.append((chat, text)) or True)
        try:
            c = client(telegram_token="123:abc", telegram_secret="whsec")
        finally:
            M.telegram_sender = orig
        upd = {"message": {"chat": {"id": 5, "type": "private"}, "text": "/lang am"}}
        self.assertEqual(c.post("/api/v1/integrations/telegram/webhook", json_body=upd).status_code, 403)
        self.assertEqual(c.post("/api/v1/integrations/telegram/webhook", json_body=upd, headers={"x-telegram-bot-api-secret-token": "wrong"}).status_code, 403)
        ok = {"x-telegram-bot-api-secret-token": "whsec"}
        self.assertEqual(c.post("/api/v1/integrations/telegram/webhook", json_body=upd, headers=ok).status_code, 200)
        c.post("/api/v1/integrations/telegram/webhook", json_body={"message": {"chat": {"id": 5, "type": "private"}, "text": "Hello"}}, headers=ok)
        self.assertTrue(sent[-1][1].startswith("ሰላም"))

    def test_disabled_without_token(self):
        self.assertEqual(client().post("/api/v1/integrations/telegram/webhook", json_body={}).status_code, 404)


@unittest.skipIf(REAL, "real FastAPI installed")
class WebSocketEndpoint(unittest.IsolatedAsyncioTestCase):
    async def test_two_people_talk_and_caption(self):
        app = M.create_app(settings())
        code = (await asyncio.to_thread(Client(app).post, "/api/v1/rooms")).json()["code"]
        handler = app.ws_routes["/ws/rooms/{code}"]
        a, b = WebSocket({"origin": "http://testserver", "host": "testserver"}), WebSocket({"host": "testserver"})
        ta, tb = asyncio.create_task(handler(a, code)), asyncio.create_task(handler(b, code))
        a.push({"type": "join", "name": "Abel", "lang": "en"})
        await asyncio.sleep(0.05)
        b.push({"type": "join", "name": "Sara", "lang": "am"})
        await asyncio.sleep(0.05)
        a.push({"type": "caption", "text": "Hello"})
        a.push({"type": "interim", "text": "thi"})
        a.push({"type": "signal", "to": [m for m in b.sent if m["type"] == "joined"][0]["id"], "data": {"candidate": None}})
        await asyncio.sleep(0.2)
        self.assertEqual([m["translated"] for m in b.sent if m["type"] == "caption"], ["ሰላም"])
        self.assertEqual([m["text"] for m in b.sent if m["type"] == "interim"], ["thi"])
        self.assertEqual(len([m for m in b.sent if m["type"] == "signal"]), 1)
        a.hang_up(); b.hang_up()
        await asyncio.gather(ta, tb)
        self.assertEqual([m["type"] for m in b.sent if m["type"] == "peer_left"], ["peer_left"])

    async def test_guards(self):
        app = M.create_app(settings())
        code = (await asyncio.to_thread(Client(app).post, "/api/v1/rooms")).json()["code"]
        handler = app.ws_routes["/ws/rooms/{code}"]
        evil = WebSocket({"origin": "http://evil.example", "host": "testserver"})
        await handler(evil, code)
        self.assertEqual((evil.closed, evil.accepted), (4403, False))
        first = WebSocket({"host": "testserver"})
        first.push({"type": "caption", "text": "x"})
        await handler(first, code)
        self.assertEqual((first.sent[-1]["code"], first.closed), ("bad_request", 4400))
        missing = WebSocket({"host": "testserver"})
        missing.push({"type": "join", "name": "A", "lang": "en"})
        await handler(missing, "AAAAAA")
        self.assertEqual(missing.sent[-1]["code"], "room_not_found")
        junk = WebSocket({"host": "testserver"})
        junk.push("not json")
        await handler(junk, code)
        self.assertEqual(junk.sent[-1]["code"], "bad_json")


if __name__ == "__main__":
    unittest.main()
