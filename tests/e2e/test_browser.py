"""Real-browser tests (Chromium via Playwright, fake camera/microphone) against tests/e2e/harness.py.
Run:  python -m unittest tests.e2e.test_browser -v      (needs: pip install playwright && playwright install chromium)
Skipped automatically when Playwright or Chromium is not available."""
import os
import struct
import tempfile
import unittest
import zlib

try:
    from playwright.sync_api import sync_playwright
    HAVE = True
except ImportError:
    HAVE = False

from tests.e2e.harness import Harness

FAKE_SPEECH = """
window.SpeechRecognition = class {
  constructor() { this.continuous = false; this.interimResults = false; this.lang = ""; }
  start() { window.__sr = this; if (this.onstart) this.onstart(); }
  stop() { if (this.onend) this.onend(); }
  abort() { this.stop(); }
};
window.__say = (text, final = true) => {
  const sr = window.__sr; if (!sr || !sr.onresult) return false;
  sr.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: text }], { isFinal: final })] }); return true;
};
"""
ARGS = ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "--autoplay-policy=no-user-gesture-required",
        "--disable-features=WebRtcHideLocalIpsWithMdns"]
OUT = os.environ.get("E2E_SHOTS", "")


def png_with_text(text="Hello", size=(420, 140)):
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
    except OSError:
        font = ImageFont.load_default()
    d.text((20, 25), text, fill="black", font=font)
    path = os.path.join(tempfile.mkdtemp(), "sign.png")
    img.save(path)
    return path


@unittest.skipUnless(HAVE, "playwright not installed")
class BrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = Harness()
        cls.url = cls.h.start()
        cls.pw = sync_playwright().start()
        try:
            cls.browser = cls.pw.chromium.launch(args=ARGS)
        except Exception as exc:  # noqa: BLE001
            cls.pw.stop()
            raise unittest.SkipTest(f"Chromium unavailable: {exc}")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.h.stop()

    def new_page(self, **ctx_kw):
        ctx = self.browser.new_context(permissions=["camera", "microphone"], **ctx_kw)
        ctx.add_init_script(FAKE_SPEECH)
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.goto(self.url)
        page.wait_for_function("window.__ready === true", timeout=15000)
        self.addCleanup(ctx.close)
        return page

    def tab(self, page, name):
        page.click(f'.tabs button[data-tab="{name}"]')

    def shot(self, page, name):
        if OUT:
            os.makedirs(OUT, exist_ok=True)
            page.screenshot(path=os.path.join(OUT, name + ".png"), full_page=False)

    # ------------------------------------------------------------------ the page
    def test_loads_with_150_plus_languages_and_no_js_errors(self):
        p = self.new_page()
        self.assertGreaterEqual(p.eval_on_selector_all("#srcLang option", "o => o.length"), 150)
        self.assertGreaterEqual(p.eval_on_selector_all("#tgtLang optgroup", "g => g.length"), 3)
        self.assertEqual(p.errors, [])
        self.shot(p, "01_text_desktop")

    def wait_text(self, page, selector, text):
        page.wait_for_function("([s, t]) => document.querySelector(s).textContent.trim() === t", arg=[selector, text], timeout=10000)

    def test_amharic_interface(self):
        p = self.new_page()
        p.select_option("#uiLang", "am")
        self.wait_text(p, "#translateBtn", "ተርጉም")
        self.assertEqual(p.inner_text('.tabs button[data-tab="text"] span[data-i18n]'), "ጽሑፍ")
        self.assertEqual(p.get_attribute("html", "lang"), "am")
        self.assertEqual(p.title(), "ሁለንተናዊ ተርጓሚ")
        p.reload(); p.wait_for_function("window.__ready === true")
        self.wait_text(p, "#translateBtn", "ተርጉም")                      # choice is remembered
        self.shot(p, "02_amharic")
        p.select_option("#uiLang", "om")                                  # draft locale: translated keys + English fallback
        self.wait_text(p, "#translateBtn", "Hiiki")
        self.assertIn("Voice settings", p.inner_text("summary"))
        self.assertEqual(p.errors, [])

    def test_text_translation_history_and_detect_chip(self):
        p = self.new_page()
        p.select_option("#srcLang", "en"); p.select_option("#tgtLang", "am")
        p.fill("#inputText", "Hello"); p.click("#translateBtn")
        p.wait_for_function("document.getElementById('outputBox').textContent === 'ሰላም'")
        self.tab(p, "history")
        p.wait_for_selector("#historyList .msg")
        self.assertIn("ሰላም", p.inner_text("#historyList"))
        self.tab(p, "text"); p.fill("#inputText", ""); p.select_option("#srcLang", "auto")
        p.type("#inputText", "ሰላም")
        p.wait_for_function("document.getElementById('detectChip').textContent.includes('አማርኛ')", timeout=5000)
        self.assertFalse(p.is_hidden("#detectChip"))
        # recent languages float to the top
        p.reload(); p.wait_for_function("window.__ready === true")
        self.assertEqual(p.eval_on_selector("#tgtLang optgroup", "g => g.label"), "Recent")
        self.assertEqual(p.errors, [])

    def test_error_messages_are_shown_not_swallowed(self):
        p = self.new_page()
        p.select_option("#srcLang", "en"); p.select_option("#tgtLang", "en")
        p.fill("#inputText", "Hello"); p.click("#translateBtn")
        p.wait_for_selector("#outputBox.err")
        self.assertIn("same", p.inner_text("#outputBox").lower())

    # ------------------------------------------------------------------ documents / camera
    def test_document_translation_download(self):
        p = self.new_page()
        self.tab(p, "docs")
        p.select_option("#srcLang", "en"); p.select_option("#tgtLang", "am")
        path = os.path.join(tempfile.mkdtemp(), "note.txt")
        open(path, "w", encoding="utf-8").write("Hello\n\nyes")
        p.set_input_files("#docFile", path)
        self.assertFalse(p.is_disabled("#docTranslate"))
        with p.expect_download() as dl:
            p.click("#docTranslate")
        d = dl.value
        self.assertEqual(d.suggested_filename, "note.am.txt")
        self.assertEqual(open(d.path(), encoding="utf-8").read(), "ሰላም\n\nአዎ")
        p.wait_for_function("document.getElementById('docStatus').textContent.includes('note.am.txt')")
        self.assertIn("Demo mode", p.inner_text("#docStatus"))          # the mock is disclosed
        self.shot(p, "03_docs")
        self.assertEqual(p.errors, [])

    def test_unsupported_document_shows_error(self):
        p = self.new_page()
        self.tab(p, "docs")
        path = os.path.join(tempfile.mkdtemp(), "x.exe"); 
        with open(path, "wb") as fh: fh.write(b"hello")
        p.select_option("#srcLang", "en")
        p.set_input_files("#docFile", path); p.click("#docTranslate")
        p.wait_for_selector("#docStatus.err")

    def test_camera_photo_translation_with_overlay(self):
        p = self.new_page()
        self.tab(p, "camera")
        p.select_option("#srcLang", "en"); p.select_option("#tgtLang", "am")
        p.set_input_files("#camFile", png_with_text("Hello"))
        p.wait_for_function("!document.getElementById('camTranslate').disabled")
        p.click("#camTranslate")
        p.wait_for_function("document.getElementById('camTranslation').textContent.length > 0", timeout=30000)
        self.assertEqual(p.inner_text("#camTranslation"), "ሰላም")                 # real Tesseract read the PNG
        p.wait_for_selector("#camResult:not([hidden])")
        # the overlay canvas really differs from the plain photo
        dark_before = p.evaluate("""() => { const i = document.getElementById('camPreview'); const c = document.createElement('canvas');
            c.width = i.naturalWidth; c.height = i.naturalHeight; const g = c.getContext('2d'); g.drawImage(i, 0, 0);
            const d = g.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let k = 0; k < d.length; k += 4) if (d[k] < 80) n++; return n; }""")
        dark_after = p.evaluate("""() => { const c = document.getElementById('camResult'); const g = c.getContext('2d');
            const d = g.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let k = 0; k < d.length; k += 4) if (d[k] < 80) n++; return n; }""")
        self.assertGreater(dark_before, 500)
        self.assertNotEqual(dark_before, dark_after)
        self.assertFalse(p.is_hidden("#camDownload"))
        self.shot(p, "04_camera_overlay")
        self.assertEqual(p.errors, [])

    def test_setup_tab_runs_quality_check_and_discloses_mock(self):
        p = self.new_page()
        self.tab(p, "setup")
        p.wait_for_selector("#setupInfo .msg")
        self.assertIn("DEMO", p.inner_text("#setupInfo"))
        p.click("#runSelfTest")
        p.wait_for_function("document.getElementById('selfTestResult').textContent.includes('does not prove')", timeout=20000)
        self.shot(p, "05_setup")
        self.assertEqual(p.errors, [])

    # ------------------------------------------------------------------ network / app behaviour
    def test_offline_badge_and_low_data_toggle(self):
        p = self.new_page()
        self.assertIn("Online", p.inner_text("#netBadge"))
        p.context.set_offline(True)
        p.wait_for_function("document.getElementById('netBadge').textContent.includes('Offline')")
        p.context.set_offline(False)
        p.wait_for_function("document.getElementById('netBadge').textContent.includes('Online')")
        p.click("#lowDataBtn")
        self.assertEqual(p.evaluate("localStorage.getItem('ut_lowdata')"), "1")
        self.assertEqual(p.get_attribute("#lowDataBtn", "aria-pressed"), "true")

    def test_share_target_and_tab_shortcut(self):
        ctx = self.browser.new_context(); self.addCleanup(ctx.close)
        p = ctx.new_page(); p.goto(self.url + "/?text=Shared%20words&tab=text")
        p.wait_for_function("window.__ready === true")
        self.assertEqual(p.input_value("#inputText"), "Shared words")
        q = ctx.new_page(); q.goto(self.url + "/?tab=docs"); q.wait_for_function("window.__ready === true")
        self.assertFalse(q.is_hidden("#tab-docs"))

    def test_mobile_layout_has_bottom_tab_bar(self):
        p = self.new_page(viewport={"width": 390, "height": 800}, is_mobile=True, has_touch=True)
        box = p.eval_on_selector(".tabs", "e => { const r = e.getBoundingClientRect(); return [r.top, r.bottom, innerHeight, getComputedStyle(e).position]; }")
        self.assertEqual(box[3], "fixed")
        self.assertGreater(box[0], box[2] * 0.8)
        self.assertEqual(p.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), True, "no sideways scrolling")
        self.shot(p, "06_mobile")

    def test_dark_mode_screenshot(self):
        p = self.new_page(color_scheme="dark")
        self.shot(p, "07_dark")
        self.assertEqual(p.errors, [])

    # ------------------------------------------------------------------ calls
    def join_call(self, page, lang, name, code=None):
        self.tab(page, "call")
        page.select_option("#callLang", lang); page.fill("#callName", name); page.check("#callConsent")
        if code:
            page.fill("#callCode", code); page.click("#callJoin")
        else:
            page.click("#callCreate")
        page.wait_for_selector("#callStage:not([hidden])")
        return page.inner_text("#callRoom")

    def remote_video_ok(self, page, n):
        page.wait_for_function(
            f"[...document.querySelectorAll('.tile.remote video')].filter(v => v.videoWidth > 0).length === {n}", timeout=30000)

    def test_two_person_video_call_with_translated_and_live_captions(self):
        a, b = self.new_page(), self.new_page()
        code = self.join_call(a, "en", "Abel")
        self.assertEqual(len(code), 6)
        self.join_call(b, "am", "Sara", code)
        self.remote_video_ok(a, 1); self.remote_video_ok(b, 1)             # real WebRTC, fake cameras, both directions
        self.assertIn("2 of 4", a.inner_text("#callStatus"))
        self.shot(a, "08_call_two")
        self.assertTrue(a.evaluate("window.__say('hel', false)"))           # still speaking: live caption
        b.wait_for_function("document.getElementById('capOverlay').textContent.includes('… Abel: hel')", timeout=10000)
        self.assertTrue(a.evaluate("window.__say('Hello', true)"))          # sentence finished: translated caption
        b.wait_for_function("document.getElementById('capOverlay').textContent.includes('ሰላም')", timeout=10000)
        self.assertNotIn("… Abel", b.inner_text("#capOverlay"))              # live line replaced
        self.assertIn("Hello", a.inner_text("#capOverlay"))                  # speaker sees own caption
        self.assertTrue(b.evaluate("window.__say('ሰላም', true)"))
        a.wait_for_function("document.getElementById('capOverlay').textContent.includes('Hello')", timeout=10000)
        self.assertEqual(a.errors + b.errors, [])
        a.click("#cLeave")
        b.wait_for_function("document.querySelectorAll('.tile.remote').length === 0", timeout=10000)
        self.assertIn("Waiting", b.inner_text("#waitMsg"))

    def test_three_person_group_call(self):
        pages = [self.new_page() for _ in range(3)]
        code = self.join_call(pages[0], "en", "A")
        self.join_call(pages[1], "am", "B", code)
        self.join_call(pages[2], "fr", "C", code)
        for pg in pages:
            self.remote_video_ok(pg, 2)
            self.assertEqual(pg.get_attribute("#videoGrid", "data-n"), "2")
            self.assertIn("3 of 4", pg.inner_text("#callStatus"))
        self.assertTrue(pages[0].evaluate("window.__say('Hello', true)"))
        pages[1].wait_for_function("document.getElementById('capOverlay').textContent.includes('ሰላም')", timeout=10000)
        pages[2].wait_for_function("document.getElementById('capOverlay').textContent.includes('Bonjour')", timeout=10000)
        self.shot(pages[0], "09_call_three")
        for pg in pages:
            self.assertEqual(pg.errors, [])

    def test_fifth_person_is_refused_and_bad_codes_explained(self):
        pages = [self.new_page() for _ in range(5)]
        code = self.join_call(pages[0], "en", "A")
        for i, pg in enumerate(pages[1:4], 1):
            self.join_call(pg, "en", f"P{i}", code)
        last = pages[4]
        self.tab(last, "call"); last.check("#callConsent"); last.fill("#callCode", code); last.click("#callJoin")
        last.wait_for_function("document.getElementById('banner').textContent.includes('full')", timeout=10000)
        self.assertTrue(last.is_hidden("#callStage"))
        self.tab(last, "call"); last.fill("#callCode", "AAAAAA"); last.click("#callJoin")
        last.wait_for_function("document.getElementById('banner').textContent.toLowerCase().includes('not exist')", timeout=10000)

    def test_audio_only_join_has_no_camera_and_still_captions(self):
        a, b = self.new_page(), self.new_page()
        self.tab(a, "call"); a.check("#callAudioOnly")
        code = self.join_call(a, "en", "A")
        self.join_call(b, "am", "B", code)
        a.wait_for_function("document.querySelectorAll('.tile.remote').length === 1", timeout=15000)
        self.assertTrue(a.is_disabled("#cCam"))
        self.assertTrue(a.evaluate("window.__say('Hello', true)"))
        b.wait_for_function("document.getElementById('capOverlay').textContent.includes('ሰላም')", timeout=10000)

    def test_connection_check_button_runs(self):
        p = self.new_page()
        self.tab(p, "call"); p.click("#callNetCheck")
        p.wait_for_function("document.getElementById('netResult').textContent.length > 3", timeout=15000)
        self.assertEqual(p.errors, [])


if __name__ == "__main__":
    unittest.main()
