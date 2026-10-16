"""v0.6: cloud engines (fake network), failover chain, phrasebook, data sources, detection, new routes.
No real internet is used: every network call goes through a fake transport."""
import json
import os
import tempfile
import unittest
from dataclasses import replace
from urllib.parse import parse_qs, urlparse

os.environ.setdefault("DB_PATH", ":memory:")

from ai_services.config import get_settings
from ai_services.providers.base import ProviderError
from ai_services.providers.translation import cloud
from ai_services.providers.translation.chain import ChainTranslationProvider
from ai_services.registry import build_translation_provider
from ai_services.services import datasources
from ai_services.services.detect import detect_language
from ai_services.services.glossary import Glossary, normalize, parse_rows
from shared.languages import DATA_ONLY_ETHIOPIAN, get_language


class FakeNet:
    """Stands in for the internet. `routes` maps a URL fragment to a function(method, url, body) -> (status, obj)."""

    def __init__(self, routes=None, down=False):
        self.routes, self.down, self.calls = routes or {}, down, []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        if self.down:
            raise OSError("network is down")
        for frag, fn in self.routes.items():
            if frag in url:
                status, obj = fn(method, url, body)
                return status, (obj if isinstance(obj, bytes) else json.dumps(obj).encode())
        return 404, b"{}"


def google_ok(prefix="G:"):
    def fn(method, url, body):
        if "/languages" in url:
            return 200, {"data": {"languages": [{"language": c} for c in ("en", "am", "om", "ti", "so", "aa", "fr", "zh-CN", "iw")]}}
        d = json.loads(body)
        return 200, {"data": {"translations": [{"translatedText": prefix + d["q"]}]}}
    return fn


NOSLEEP = dict(sleep=lambda s: None)


class EngineTests(unittest.TestCase):
    def test_google_request_and_answer(self):
        net = FakeNet({"translation.googleapis.com": google_ok()})
        g = cloud.GoogleEngine("KEY", transport=net, **NOSLEEP)
        self.assertEqual(g.translate("Hello", "en", "am").text, "G:Hello")
        method, url, headers, body = net.calls[0]
        self.assertIn("key=KEY", url)
        self.assertEqual(json.loads(body), {"q": "Hello", "source": "en", "target": "am", "format": "text"})

    def test_google_asks_the_engine_which_languages_it_has(self):
        g = cloud.GoogleEngine("K", transport=FakeNet({"googleapis": google_ok()}), **NOSLEEP)
        self.assertTrue(g.supports("en", "wal") is False)         # 3-letter code: not assumed before the list is known
        self.assertTrue(g.refresh_languages())
        self.assertTrue(g.supports("en", "aa"))                    # in this fake list
        self.assertFalse(g.supports("en", "ja"))                   # not in the list -> unsupported, not guessed
        self.assertEqual(g.code_for("zh"), "zh-CN")
        self.assertEqual(g.code_for("he"), "iw")                   # old Google code, only because the list has "iw"

    def test_azure_headers_and_answer(self):
        def fn(method, url, body):
            return 200, [{"translations": [{"text": "AZ:" + json.loads(body)[0]["Text"], "to": "am"}]}]
        net = FakeNet({"microsofttranslator": fn})
        a = cloud.AzureEngine("AKEY", "westeurope", transport=net, **NOSLEEP)
        self.assertEqual(a.translate("Hi", "en", "am").text, "AZ:Hi")
        _, url, headers, _ = net.calls[0]
        self.assertEqual(headers["Ocp-Apim-Subscription-Key"], "AKEY")
        self.assertEqual(headers["Ocp-Apim-Subscription-Region"], "westeurope")
        q = parse_qs(urlparse(url).query)
        self.assertEqual((q["from"], q["to"]), (["en"], ["am"]))

    def test_libretranslate_and_mymemory(self):
        lt = cloud.LibreEngine("https://lt.example/", "k", transport=FakeNet(
            {"lt.example/translate": lambda m, u, b: (200, {"translatedText": "L:" + json.loads(b)["q"]})}), **NOSLEEP)
        self.assertEqual(lt.translate("Hi", "en", "fr").text, "L:Hi")
        mm = cloud.MyMemoryEngine("me@x.org", transport=FakeNet({"mymemory": lambda m, u, b: (
            200, {"responseStatus": 200, "responseData": {"translatedText": "M:&#39;" + parse_qs(urlparse(u).query)["q"][0]}})}), **NOSLEEP)
        self.assertEqual(mm.translate("Hi", "en", "so").text, "M:'Hi")          # HTML entities decoded

    def test_mymemory_quota_message_is_not_returned_as_a_translation(self):
        warn = {"mymemory": lambda m, u, b: (200, {"responseStatus": 200, "responseData": {
            "translatedText": "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS FOR TODAY"}})}
        with self.assertRaises(ProviderError) as cm:
            cloud.MyMemoryEngine(transport=FakeNet(warn), **NOSLEEP).translate("Hi", "en", "am")
        self.assertEqual(cm.exception.code, "engine_rate_limited")

    def test_error_mapping_and_retry(self):
        net = FakeNet(down=True)
        g = cloud.GoogleEngine("K", transport=net, retries=2, **NOSLEEP)
        with self.assertRaises(ProviderError) as cm:
            g.translate("Hi", "en", "am")
        self.assertEqual((cm.exception.code, len(net.calls)), ("engine_unreachable", 3))
        for status, code in ((403, "engine_auth"), (429, "engine_rate_limited"), (500, "engine_error"), (400, "engine_rejected")):
            e = cloud.GoogleEngine("K", transport=FakeNet({"google": lambda m, u, b, s=status: (s, b"{}")}), retries=0, **NOSLEEP)
            with self.assertRaises(ProviderError) as cm:
                e.translate("Hi", "en", "am")
            self.assertEqual(cm.exception.code, code, status)

    def test_temporary_failure_then_success(self):
        state = {"n": 0}

        def flaky(m, u, b):
            state["n"] += 1
            return (500, b"") if state["n"] == 1 else google_ok()(m, u, b)
        g = cloud.GoogleEngine("K", transport=FakeNet({"google": flaky}), retries=1, **NOSLEEP)
        self.assertEqual(g.translate("Hi", "en", "am").text, "G:Hi")

    def test_long_text_is_split_and_layout_kept(self):
        net = FakeNet({"mymemory": lambda m, u, b: (200, {"responseStatus": 200, "responseData": {"translatedText": "<" + parse_qs(urlparse(u).query)["q"][0] + ">"}})})
        mm = cloud.MyMemoryEngine(transport=net, **NOSLEEP)
        text = "First sentence here. " * 40 + "\n\nSecond paragraph."
        out = mm.translate(text, "en", "fr").text
        self.assertGreater(len(net.calls), 2)
        for _, url, _, _ in net.calls:
            self.assertLessEqual(len(parse_qs(urlparse(url).query)["q"][0].encode()), 450)
        self.assertIn("\n\n", out)
        self.assertTrue(out.rstrip().endswith("<Second paragraph.>"))

    def test_chunk_planner_handles_huge_words_and_non_latin(self):
        pieces = cloud.plan_chunks("ሀ" * 600, 450, lambda s: len(s.encode()))
        self.assertTrue(all(len(p.encode()) <= 450 for p, do in pieces if do))
        self.assertEqual("".join(p for p, _ in pieces), "ሀ" * 600)           # nothing added, nothing lost
        zh = "你好世界。" * 300                                                  # Chinese: no spaces anywhere
        planned = cloud.plan_chunks(zh, 450, lambda s: len(s.encode()))
        self.assertEqual("".join(p for p, _ in planned), zh)
        self.assertTrue(all(len(p.encode()) <= 450 for p, _ in planned))
        text = "One two three. " * 100
        self.assertEqual("".join(p for p, _ in cloud.plan_chunks(text, 120)), text)


class ChainTests(unittest.TestCase):
    def setUp(self):
        self.gl = Glossary(":memory:")

    def chain(self, *engines, **kw):
        return ChainTranslationProvider(list(engines), self.gl, **kw)

    def test_phrasebook_beats_engines_and_works_offline(self):
        net = FakeNet(down=True)
        self.gl.add("en", "wal", "Good morning", "<verified>")
        ch = self.chain(cloud.GoogleEngine("K", transport=net, **NOSLEEP))
        self.assertEqual(ch.translate("good morning!", "en", "wal").text, "<verified>")
        self.assertEqual(ch.translate("<verified>", "wal", "en").text, "Good morning")        # reverse direction
        self.assertEqual(net.calls, [])

    def test_pivot_through_english(self):
        self.gl.add("en", "am", "Water", "ውሃ")
        self.gl.add("en", "wal", "Water", "<w>")
        self.assertEqual(self.chain().translate("ውሃ", "am", "wal").text, "<w>")

    def test_falls_back_to_next_engine(self):
        bad = cloud.GoogleEngine("K", transport=FakeNet(down=True), retries=0, **NOSLEEP)
        good = cloud.MyMemoryEngine(transport=FakeNet({"mymemory": lambda m, u, b: (200, {"responseStatus": 200, "responseData": {"translatedText": "ok"}})}), **NOSLEEP)
        ch = self.chain(bad, good)
        r = ch.translate("Hello there friend", "en", "am")
        self.assertEqual((r.text, r.provider, r.is_mock), ("ok", "mymemory", False))
        self.assertEqual(ch.describe()[0]["failed"], 1)

    def test_all_engines_down_gives_a_clear_error_not_a_fake_translation(self):
        ch = self.chain(cloud.GoogleEngine("K", transport=FakeNet(down=True), retries=0, **NOSLEEP))
        with self.assertRaises(ProviderError) as cm:
            ch.translate("Hello", "en", "am")
        self.assertEqual((cm.exception.code, cm.exception.status), ("translation_unavailable", 503))
        self.assertNotIn("MOCK", cm.exception.message)

    def test_dead_engine_is_paused_then_retried_after_cooldown(self):
        now = {"t": 0.0}
        net = FakeNet(down=True)
        bad = cloud.GoogleEngine("K", transport=net, retries=0, **NOSLEEP)
        good = cloud.MyMemoryEngine(transport=FakeNet({"mymemory": lambda m, u, b: (200, {"responseStatus": 200, "responseData": {"translatedText": "ok"}})}), **NOSLEEP)
        ch = self.chain(bad, good, clock=lambda: now["t"], cache_size=0)
        for _ in range(3):
            ch.translate("Hello there friend", "en", "am")
        self.assertEqual(len(net.calls), 3)
        ch.translate("Hello there friend", "en", "am")
        self.assertEqual(len(net.calls), 3, "paused engine must be skipped")
        self.assertEqual(ch.describe()[0]["state"], "paused")
        now["t"] = 61
        ch.translate("Hello there friend", "en", "am")
        self.assertEqual(len(net.calls), 4, "tried again after the cool-down")

    def test_all_paused_still_tries_instead_of_locking_out(self):
        now = {"t": 0.0}
        net = FakeNet(down=True)
        ch = self.chain(cloud.GoogleEngine("K", transport=net, retries=0, **NOSLEEP), clock=lambda: now["t"], cache_size=0)
        for _ in range(5):
            with self.assertRaises(ProviderError):
                ch.translate("Hello", "en", "am")
        self.assertEqual(len(net.calls), 5)

    def test_unchanged_echo_prefers_another_engine(self):
        echo = cloud.MyMemoryEngine(transport=FakeNet({"mymemory": lambda m, u, b: (200, {"responseStatus": 200, "responseData": {"translatedText": parse_qs(urlparse(u).query)["q"][0]}})}), **NOSLEEP)
        good = cloud.GoogleEngine("K", transport=FakeNet({"google": google_ok("X:")}), **NOSLEEP)
        r = self.chain(echo, good).translate("How are you today my friend", "en", "am")
        self.assertEqual(r.provider, "google")
        only = self.chain(echo).translate("How are you today my friend", "en", "am")
        self.assertEqual(only.provider, "mymemory")              # nothing better: the echo is still returned

    def test_cache_saves_quota(self):
        net = FakeNet({"google": google_ok()})
        ch = self.chain(cloud.GoogleEngine("K", transport=net, **NOSLEEP))
        ch.translate("Hello there", "en", "am")
        ch.translate("Hello there", "en", "am")
        self.assertEqual(len([c for c in net.calls if c[0] == "POST"]), 1)

    def test_unsupported_language_says_what_to_do(self):
        ch = self.chain(cloud.GoogleEngine("K", transport=FakeNet({"google": google_ok()}), **NOSLEEP))
        with self.assertRaises(ProviderError) as cm:
            ch.translate("Hello", "en", "sid")
        self.assertEqual(cm.exception.code, "unsupported_pair")
        self.assertIn("Sidama", cm.exception.message)
        self.assertIn("phrasebook", cm.exception.message.lower())

    def test_coverage_is_honest_about_data_only_languages(self):
        g = cloud.GoogleEngine("K", transport=FakeNet(), **NOSLEEP)
        ch = self.chain(g)
        self.assertEqual(ch.coverage("wal"), [])
        self.gl.add("en", "wal", "Hello", "<hi>")
        self.assertEqual(ch.coverage("wal"), ["phrasebook"])
        self.assertIn("google", ch.coverage("am"))

    def test_no_engine_and_empty_phrasebook_is_reported_not_ready(self):
        self.assertFalse(self.chain().available()[0])
        self.gl.add("en", "wal", "Hello", "<hi>")
        self.assertTrue(self.chain().available()[0])


class RegistryTests(unittest.TestCase):
    def test_auto_uses_keys_that_exist(self):
        s = get_settings()
        self.assertEqual(build_translation_provider(replace(s, translation_provider="auto", google_key="", azure_key="", libre_url="")).name, "mymemory")
        self.assertEqual(build_translation_provider(replace(s, translation_provider="auto", google_key="k", azure_key="a")).name, "google → azure → mymemory")

    def test_mock_stays_available_and_unknown_engines_warn(self):
        s = get_settings()
        self.assertTrue(build_translation_provider(replace(s, translation_provider="mock")).is_mock)
        p = build_translation_provider(replace(s, translation_provider="google,bogus"))
        self.assertEqual(p.engines, [])
        self.assertEqual(len(p.warnings), 2)


class GlossaryTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize("  Hello,   World!! "), "hello, world")
        self.assertEqual(normalize("ሰላም።"), "ሰላም")

    def test_long_and_wide_csv_and_json(self):
        gl = Glossary()
        rep = gl.import_document("source_lang,target_lang,source_text,translation\nen,am,Water,ውሃ\nen,xx,Bad,bad\n", "t1")
        self.assertEqual((rep["added"], rep["skipped"]), (1, 1))
        rep = gl.import_document("en,om,ti\nFood,Nyaata,ምግቢ\nSchool,Mana barumsaa,ቤት ትምህርቲ\n", "t2")
        self.assertEqual(rep["added"], 6)                      # 3 language pairs x 2 rows
        self.assertEqual(gl.lookup("om", "ti", "nyaata"), "ምግቢ")
        rep = gl.import_document(json.dumps({"entries": [{"en": "Doctor", "am": "ሐኪም"}]}), "t3")
        self.assertEqual(gl.lookup("en", "am", "doctor"), "ሐኪም")
        rep = gl.import_document(json.dumps([{"source": "en", "target": "so", "text": "Thanks", "translation": "Mahadsanid"}]), "t4")
        self.assertEqual(gl.lookup("en", "so", "Thanks!"), "Mahadsanid")

    def test_bad_input_is_reported_not_crashed(self):
        self.assertEqual(parse_rows("{not json", "json")[0], [])
        gl = Glossary()
        rep = gl.import_document("", "x")
        self.assertEqual(rep["added"], 0)
        rep = gl.import_document(f"en,am\n{'a' * 501},x\n", "y")
        self.assertEqual(rep["skipped"], 1)
        self.assertIn("longer", rep["errors"][0])
        with self.assertRaises(ValueError):
            gl.add("en", "en", "a", "b")

    def test_replace_origin_removes_deleted_rows(self):
        gl = Glossary()
        gl.import_document("en,am\nA,አ\nB,ለ\n", "src", replace_origin=True)
        gl.import_document("en,am\nA,አ\n", "src", replace_origin=True)
        self.assertIsNone(gl.lookup("en", "am", "B"))
        self.assertEqual(gl.lookup("en", "am", "A"), "አ")

    def test_manual_correction_overrides_and_export(self):
        gl = Glossary()
        gl.import_document("en,am\nHello,old\n", "src")
        gl.add("en", "am", "Hello", "new")
        self.assertEqual(gl.lookup("en", "am", "hello"), "new")
        self.assertIn("new", gl.export_csv())
        self.assertEqual(gl.stats()["entries"], 1)


class DataSourceTests(unittest.TestCase):
    def test_cloud_url_sync_replace_and_failures(self):
        gl = Glossary()
        docs = {"https://sheets.example/a.csv": b"en,wal\nHello,<hi>\n"}

        def fetch(url, timeout):
            if url in docs:
                return docs[url]
            raise OSError("unreachable")
        sync = datasources.DataSync(gl, "", ["https://sheets.example/a.csv", "https://down.example/x.csv"], fetcher=fetch)
        last = sync.run()
        self.assertEqual([r["ok"] for r in last["results"]], [True, False])
        self.assertEqual(gl.lookup("en", "wal", "hello"), "<hi>")
        docs["https://sheets.example/a.csv"] = b"en,wal\nBye,<bye>\n"
        sync.run()
        self.assertIsNone(gl.lookup("en", "wal", "hello"))        # removed in the cloud -> removed here
        self.assertEqual(gl.lookup("en", "wal", "bye"), "<bye>")
        self.assertNotIn("token", json.dumps(sync.status()))

    def test_only_http_urls_and_folder_loading(self):
        with self.assertRaises(ValueError):
            datasources.fetch_url("file:///etc/passwd")
        gl = Glossary()
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "health.csv"), "w", encoding="utf-8").write("en,am\nDoctor,ሐኪም\n")
            open(os.path.join(d, "_ignored.csv"), "w", encoding="utf-8").write("en,am\nX,ኤክስ\n")
            open(os.path.join(d, "bad.json"), "w", encoding="utf-8").write("{oops")
            res = datasources.load_folder(gl, d)
        self.assertEqual(gl.lookup("en", "am", "doctor"), "ሐኪም")
        self.assertIsNone(gl.lookup("en", "am", "x"))
        self.assertEqual(sorted(r["source"] for r in res), ["file:bad.json", "file:health.csv"])

    def test_origin_never_contains_the_query_string(self):
        self.assertNotIn("SECRET", datasources.origin_for_url("https://s3.example/b.csv?X-Amz-Signature=SECRET"))


class DetectionTests(unittest.TestCase):
    def test_languages_sharing_a_script(self):
        cases = {"Akkam jirta? Galatoomi, ani nagaa dha": "om", "Waa maxay magacaaga iyo sidee tahay": "so",
                 "Habari yako, asante sana": "sw", "Bonjour, je suis content": "fr", "Hello, how are you?": "en",
                 "ኣብ ኢትዮጵያ እዩ": "ti", "እኔ ኢትዮጵያ ነው": "am", "ሰላም": "am"}
        for text, code in cases.items():
            self.assertEqual(detect_language(text)["language"], code, text)
        self.assertTrue(detect_language("Akkam jirta")["ambiguous"])


class EnvTests(unittest.TestCase):
    def test_inline_comments_and_quotes(self):
        from ai_services.config import parse_env_value as v
        self.assertEqual(v("mock        # mock | nllb"), "mock")
        self.assertEqual(v(' "a # b" '), "a # b")
        self.assertEqual(v("https://x.org/a#frag"), "https://x.org/a#frag")     # no space before # -> kept
        self.assertEqual(v("'k'  # note"), "k")
        self.assertEqual(v(""), "")


class CatalogTests(unittest.TestCase):
    def test_new_ethiopian_languages_exist_and_have_no_pretend_model(self):
        for code in DATA_ONLY_ETHIOPIAN:
            lang = get_language(code)
            self.assertIsNotNone(lang, code)
            self.assertEqual(lang.group, "ethiopian")
            self.assertIsNone(lang.nllb, code)


if __name__ == "__main__":
    unittest.main()
