"""API tests. Need: pip install fastapi httpx pytest. Skipped automatically if missing."""
import unittest

try:
    from fastapi.testclient import TestClient
    from ai_services.config import Settings
    from ai_services.main import create_app
    HAVE = True
except ImportError:  # pragma: no cover
    HAVE = False


@unittest.skipUnless(HAVE, "fastapi/httpx not installed")
class ApiTests(unittest.TestCase):
    def setUp(self):
        s = Settings("mock", "none", 50, 1000, ":memory:", "data/models",
                     "facebook/nllb-200-distilled-600M", False, ("http://localhost:8000",), "mock", 5_000_000)
        self.c = TestClient(create_app(s))

    def test_health(self):
        r = self.c.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()["mock"])
        self.assertFalse(r.json()["tts_ready"])

    def test_languages(self):
        self.assertGreaterEqual(len(self.c.get("/api/v1/languages").json()["languages"]), 30)

    def test_translate_and_history(self):
        r = self.c.post("/api/v1/translate", json={"text": "Hello", "source": "en", "target": "am"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["translation"], "ሰላም")
        items = self.c.get("/api/v1/history").json()["items"]
        self.assertEqual(len(items), 1)
        self.assertEqual(self.c.delete("/api/v1/history").status_code, 200)
        self.assertEqual(self.c.get("/api/v1/history").json()["items"], [])

    def test_errors_are_structured(self):
        r = self.c.post("/api/v1/translate", json={"text": "hi", "source": "en", "target": "zz"})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(r.json()["error"]["code"], "unknown_language")
        r = self.c.post("/api/v1/translate", json={"text": "x" * 51, "source": "en", "target": "am"})
        self.assertEqual(r.status_code, 413)

    def test_unavailable_features_are_honest(self):
        self.assertEqual(self.c.post("/api/v1/transcribe").status_code, 501)

    def test_vision_translate(self):
        from tests.test_vision import PNG_B64
        r = self.c.post("/api/v1/vision/translate", json={"image": PNG_B64, "source": "en", "target": "am"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["translation"], "ሰላም")
        self.assertTrue(r.json()["ocr"]["is_mock"])
        bad = self.c.post("/api/v1/vision/translate", json={"image": "aGVsbG8=", "source": "en", "target": "am"})
        self.assertEqual(bad.status_code, 415)

    def test_index_and_manifest(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        self.assertEqual(self.c.get("/static/manifest.json").status_code, 200)
        self.assertEqual(self.c.get("/service-worker.js").status_code, 200)


@unittest.skipUnless(HAVE, "fastapi/httpx not installed")
class RoomApiTests(unittest.TestCase):
    def setUp(self):
        s = Settings("mock", "none", 50, 1000, ":memory:", "data/models",
                     "facebook/nllb-200-distilled-600M", False, ("http://localhost:8000",), "mock", 5_000_000)
        self.c = TestClient(create_app(s))

    def test_create_info_and_rtc_config(self):
        code = self.c.post("/api/v1/rooms").json()["code"]
        self.assertEqual(len(code), 6)
        self.assertEqual(self.c.get(f"/api/v1/rooms/{code}").json()["participants"], 0)
        self.assertEqual(self.c.get("/api/v1/rooms/AAAAAA").status_code, 404)
        self.assertIn("iceServers", self.c.get("/api/v1/rtc-config").json())

    def test_two_people_caption_flow(self):
        code = self.c.post("/api/v1/rooms").json()["code"]
        with self.c.websocket_connect(f"/ws/rooms/{code}") as a:
            a.send_json({"type": "join", "name": "Abel", "lang": "en"})
            self.assertEqual(a.receive_json()["type"], "joined")
            with self.c.websocket_connect(f"/ws/rooms/{code}") as b:
                b.send_json({"type": "join", "name": "Sara", "lang": "am"})
                self.assertEqual(b.receive_json()["type"], "joined")
                self.assertEqual(a.receive_json()["type"], "peer_joined")
                a.send_json({"type": "caption", "text": "Hello"})
                self.assertEqual(a.receive_json()["type"], "caption_self")
                cap = b.receive_json()
                self.assertEqual(cap["translated"], "ሰላም")

    def test_bad_first_message_and_bad_origin(self):
        code = self.c.post("/api/v1/rooms").json()["code"]
        with self.c.websocket_connect(f"/ws/rooms/{code}") as a:
            a.send_json({"type": "caption", "text": "x"})
            self.assertEqual(a.receive_json()["code"], "bad_request")
        with self.assertRaises(Exception):
            with self.c.websocket_connect(f"/ws/rooms/{code}", headers={"origin": "http://evil.example"}):
                pass


@unittest.skipUnless(HAVE, "fastapi/httpx not installed")
class GroupApiTests(unittest.TestCase):
    def setUp(self):
        s = Settings("mock", "none", 50, 1000, ":memory:", "data/models",
                     "facebook/nllb-200-distilled-600M", False, ("http://localhost:8000",), "mock", 5_000_000,
                     max_participants=3)
        self.c = TestClient(create_app(s))

    def test_three_join_fourth_refused_and_targeted_signal(self):
        code = self.c.post("/api/v1/rooms").json()["code"]
        self.assertEqual(self.c.get("/api/v1/rtc-config").json()["maxParticipants"], 3)
        with self.c.websocket_connect(f"/ws/rooms/{code}") as a, \
             self.c.websocket_connect(f"/ws/rooms/{code}") as b, \
             self.c.websocket_connect(f"/ws/rooms/{code}") as c:
            a.send_json({"type": "join", "name": "A", "lang": "en"}); ida = a.receive_json()["id"]
            b.send_json({"type": "join", "name": "B", "lang": "am"}); idb = b.receive_json()["id"]
            a.receive_json()                                    # peer_joined (B)
            c.send_json({"type": "join", "name": "C", "lang": "fr"}); idc = c.receive_json()["id"]
            a.receive_json(); b.receive_json()                  # peer_joined (C)
            a.send_json({"type": "signal", "to": idc, "data": {"sdp": {"type": "offer", "sdp": "x"}}})
            got = c.receive_json()
            self.assertEqual((got["type"], got["from"]), ("signal", ida))
            self.assertEqual(self.c.get(f"/api/v1/rooms/{code}").json()["full"], True)
            with self.c.websocket_connect(f"/ws/rooms/{code}") as d:
                d.send_json({"type": "join", "name": "D", "lang": "en"})
                self.assertEqual(d.receive_json()["code"], "room_full")


@unittest.skipUnless(HAVE, "fastapi/httpx not installed")
class NetworkApiTests(unittest.TestCase):
    def make(self, **kw):
        from dataclasses import replace
        s = Settings("mock", "none", 50, 1000, ":memory:", "data/models",
                     "facebook/nllb-200-distilled-600M", False, ("http://localhost:8000",), "mock", 5_000_000)
        return TestClient(create_app(replace(s, **kw)))

    def test_access_code_protects_host_actions_but_not_joining(self):
        c = self.make(access_code="letmein")
        self.assertEqual(c.post("/api/v1/rooms").status_code, 401)
        self.assertEqual(c.post("/api/v1/rooms", headers={"X-Access-Code": "wrong"}).status_code, 401)
        ok = c.post("/api/v1/rooms", headers={"X-Access-Code": "letmein"})
        self.assertEqual(ok.status_code, 200)
        code = ok.json()["code"]
        self.assertEqual(c.get(f"/api/v1/rooms/{code}").status_code, 200)         # guests need no code
        self.assertEqual(c.get("/api/v1/languages").status_code, 200)
        self.assertEqual(c.post("/api/v1/translate", json={"text": "Hello", "source": "en", "target": "am"}).status_code, 401)
        self.assertEqual(c.get("/api/v1/history").status_code, 401)
        self.assertEqual(c.get("/health").status_code, 200)

    def test_turn_credentials_only_for_real_room(self):
        c = self.make(turn_urls=("turn:t.example:3478",), turn_secret="sec")
        code = c.post("/api/v1/rooms").json()["code"]
        no_room = c.get("/api/v1/rtc-config").json()
        fake = c.get("/api/v1/rtc-config?room=AAAAAA").json()
        real = c.get(f"/api/v1/rtc-config?room={code}").json()
        self.assertFalse(no_room["turn"])
        self.assertFalse(fake["turn"])
        self.assertTrue(real["turn"])
        self.assertNotIn("sec", str(real))
        self.assertTrue(real["turnConfigured"])
