"""v0.6 routes: engines in the API, batch, LibreTranslate-compatible endpoints, phrasebook, data sync.
Runs against the stand-in (tests/fastapi_shim.py) or, when installed, the real FastAPI + httpx."""
import unittest
from dataclasses import replace

try:                                                    # same module object whichever way the tests are started
    import test_glue as G                                # (python -m unittest discover -s tests)
    from test_cloud import FakeNet, google_ok
except ImportError:
    from tests import test_glue as G                     # (python -m unittest tests.test_cloud_routes)
    from tests.test_cloud import FakeNet, google_ok

from ai_services.config import get_settings
from ai_services.main import create_app

REAL = G.REAL
if REAL:
    try:
        from fastapi.testclient import TestClient
    except ImportError:                                # pragma: no cover
        TestClient = None


class Api:
    def __init__(self, transport=None, **kw):
        base = dict(db_path=":memory:", glossary_db=":memory:", glossary_dir="", data_source_urls=(), tts_provider="none",
                    ocr_provider="mock", access_code="", auth_mode="off", stt_provider="none", telegram_token="",
                    livekit_url="", translation_provider="google", google_key="KEY", cache_size=0)
        base.update(kw)
        app = create_app(replace(get_settings(), **base), transport)
        self.c = TestClient(app) if REAL else G.Client(app)

    def get(self, path, **kw):
        return self.c.get(path, **kw)

    def post(self, path, json=None, data=None, params=None, headers=None):
        if REAL:
            return self.c.post(path, json=json, content=data, params=params, headers=headers)
        return self.c.post(path, json_body=json, data=data, params=params, headers=headers)


@unittest.skipIf(REAL and TestClient is None, "httpx not installed")
class CloudRoutes(unittest.TestCase):
    def api(self, **kw):
        return Api(FakeNet({"googleapis": google_ok()}), **kw)

    def test_translate_uses_engine_and_reports_it(self):
        r = self.api().post("/api/v1/translate", json={"text": "Hello", "source": "en", "target": "am"}).json()
        self.assertEqual((r["translation"], r["provider"], r["is_mock"]), ("G:Hello", "google", False))

    def test_status_and_languages_show_engines_and_data_only_languages(self):
        a = self.api()
        st = a.get("/api/v1/translation/status").json()
        self.assertEqual(st["engines"][0]["name"], "google")
        self.assertTrue(st["engines"][0]["sends_text_off_device"])
        self.assertNotIn("KEY", str(st))                                   # secrets never leave the server
        langs = {l["code"]: l for l in a.get("/api/v1/languages").json()["languages"]}
        self.assertIn("google", langs["am"]["engines"])
        self.assertFalse(langs["wal"]["available"])                        # honest: no engine, no data yet
        a.post("/api/v1/glossary", json={"source": "en", "target": "wal", "source_text": "Hello", "translation": "<hi>"})
        langs = {l["code"]: l for l in a.get("/api/v1/languages").json()["languages"]}
        self.assertTrue(langs["wal"]["data_only"])

    def test_phrasebook_import_export_and_sync(self):
        a = self.api()
        self.assertEqual(a.post("/api/v1/translate", json={"text": "Hello", "source": "en", "target": "wal"}).status_code, 422)
        csv = "en,wal\nHello,<hi>\nThank you,<thanks>\n".encode()
        rep = a.post("/api/v1/glossary/import", data=csv, params={"name": "my file!.csv"}).json()
        self.assertEqual((rep["added"], rep["skipped"]), (2, 0))
        r = a.post("/api/v1/translate", json={"text": "thank you.", "source": "en", "target": "wal"}).json()
        self.assertEqual((r["translation"], r["provider"]), ("<thanks>", "phrasebook"))
        back = a.post("/api/v1/translate", json={"text": "<hi>", "source": "wal", "target": "en"}).json()
        self.assertEqual(back["translation"], "Hello")
        exp = a.get("/api/v1/glossary/export")
        self.assertIn("<thanks>", exp.content.decode())
        self.assertEqual(a.get("/api/v1/data/status").json()["entries"], 2)
        self.assertIn("results", a.post("/api/v1/data/sync").json())

    def test_bad_glossary_entry_is_rejected(self):
        r = self.api().post("/api/v1/glossary", json={"source": "en", "target": "zz", "source_text": "a", "translation": "b"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (422, "bad_glossary_entry"))

    def test_batch_isolates_failures(self):
        out = self.api().post("/api/v1/translate/batch", json={"texts": ["Hello", "", "Thanks"], "source": "en", "target": "am"}).json()["results"]
        self.assertEqual([x["ok"] for x in out], [True, False, True])
        self.assertEqual(out[0]["translation"], "G:Hello")
        self.assertEqual(out[1]["error"]["code"], "empty_text")

    def test_libretranslate_compatible_endpoints(self):
        a = self.api()
        r = a.post("/translate", json={"q": "Hello", "source": "en", "target": "am"}).json()
        self.assertEqual(r["translatedText"], "G:Hello")
        langs = a.get("/languages").json()
        self.assertTrue(any(l["code"] == "am" for l in langs))
        self.assertFalse(any(l["code"] == "wal" for l in langs))

    def test_all_engines_down_is_a_503_with_a_clear_message(self):
        a = Api(FakeNet(down=True), cloud_retries=0)
        r = a.post("/api/v1/translate", json={"text": "Hello", "source": "en", "target": "am"})
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (503, "translation_unavailable"))
        self.assertNotIn("MOCK", r.json()["error"]["message"])
        self.assertTrue(a.get("/health").json()["status"] == "ok")          # the app itself stays healthy

    def test_data_endpoints_need_the_access_code_when_one_is_set(self):
        a = self.api(access_code="letmein")
        for path in ("/api/v1/data/status",):
            self.assertEqual(a.get(path).status_code, 401)
        self.assertEqual(a.post("/api/v1/glossary", json={"source": "en", "target": "am", "source_text": "a", "translation": "b"}).status_code, 401)
        self.assertEqual(a.post("/translate", json={"q": "Hi", "source": "en", "target": "am"}).status_code, 401)
        ok = a.get("/api/v1/data/status", headers={"x-access-code": "letmein"})
        self.assertEqual(ok.status_code, 200)

    def test_mock_mode_still_works_as_before(self):
        a = Api(translation_provider="mock")
        self.assertEqual(a.post("/api/v1/translate", json={"text": "Hello", "source": "en", "target": "am"}).json()["translation"], "ሰላም")
        self.assertNotIn("engines", a.get("/api/v1/languages").json()["languages"][0])


if __name__ == "__main__":
    unittest.main()
