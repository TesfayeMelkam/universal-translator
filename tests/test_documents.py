import io
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile

from ai_services.providers.base import ProviderError
from ai_services.providers.translation.mock import MockTranslationProvider
from ai_services.services import documents as D

P = MockTranslationProvider()
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def tr(data, name, s="en", t="am"):
    return D.translate_document(P, data, name, s, t)


def make_docx(paragraph_runs, extra=None):
    paras = "".join("<w:p><w:pPr><w:jc w:val=\"left\"/></w:pPr>" + "".join(
        f'<w:r><w:rPr><w:b/></w:rPr><w:t>{r}</w:t></w:r>' for r in runs) + "</w:p>" for runs in paragraph_runs)
    doc = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document xmlns:w="{W}" '
           f'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
           f'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" mc:Ignorable="w14">'
           f'<w:body>{paras}<w:p/><w:sectPr/></w:body></w:document>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", doc)
        z.writestr("word/media/pic.bin", b"\x00\x01binary")
        for k, v in (extra or {}).items():
            z.writestr(k, v)
    return buf.getvalue()


class TextTests(unittest.TestCase):
    def test_txt_keeps_structure(self):
        r = tr(b"Hello\n\nThank you\nyes\n\n\nno", "note.txt")
        self.assertEqual(r.data.decode(), "ሰላም\n\n[MOCK en→am] Thank you\nyes\n\n\nአይ")
        self.assertEqual(r.filename, "note.am.txt")
        self.assertTrue(r.stats["mock"])

    def test_markdown_code_fence_untouched(self):
        r = tr(b"Hello\n\n```\nthank you\n```\n\nyes", "a.md")
        self.assertEqual(r.data.decode(), "ሰላም\n\n```\nthank you\n```\n\nአዎ")

    def test_srt_timings_preserved(self):
        srt = b"1\n00:00:01,000 --> 00:00:02,500\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nThank\nyou\n"
        out = tr(srt, "s.srt").data.decode()
        self.assertIn("1\n00:00:01,000 --> 00:00:02,500\nሰላም", out)
        self.assertIn("2\n00:00:03,000 --> 00:00:04,000\nአመሰግናለሁ", out)       # two lines joined, then translated
        self.assertEqual(re.findall(r"\d\d:\d\d:\d\d,\d{3} --> \d\d:\d\d:\d\d,\d{3}", out),
                         ["00:00:01,000 --> 00:00:02,500", "00:00:03,000 --> 00:00:04,000"])

    def test_vtt_header_and_notes_kept(self):
        vtt = b"WEBVTT\n\nNOTE keep me\n\n00:01.000 --> 00:02.000\nHello\n"
        out = tr(vtt, "v.vtt").data.decode()
        self.assertTrue(out.startswith("WEBVTT\n\nNOTE keep me\n\n00:01.000 --> 00:02.000\nሰላም"))

    def test_utf8_bom_and_bad_encoding(self):
        self.assertEqual(tr(b"\xef\xbb\xbfHello", "a.txt").data.decode(), "ሰላም")
        with self.assertRaises(ProviderError) as cm:
            tr(b"\xff\xfe\x00\xd8 bad", "a.txt")
        self.assertEqual(cm.exception.code, "bad_encoding")

    def test_long_paragraph_is_chunked(self):
        seen = []
        class Spy(MockTranslationProvider):
            def translate(self, text, s, t):
                seen.append(len(text)); return super().translate(text, s, t)
        text = " ".join(f"This is sentence number {i}." for i in range(200)).encode()
        D.translate_document(Spy(), text, "long.txt", "en", "am", max_chars=300)
        self.assertGreater(len(seen), 5)
        self.assertLessEqual(max(seen), 300)

    def test_duplicate_paragraphs_translated_once(self):
        calls = []
        class Spy(MockTranslationProvider):
            def translate(self, text, s, t):
                calls.append(text); return super().translate(text, s, t)
        D.translate_document(Spy(), b"Hello\n\nHello\n\nHello", "d.txt", "en", "am")
        self.assertEqual(calls, ["Hello"])


class LimitsTests(unittest.TestCase):
    def test_errors(self):
        for data, name, code in [(b"", "a.txt", "empty_document"), (b"x", "a.exe", "unsupported_document"),
                                 (b"not a zip", "a.docx", "invalid_document"), (b"x", "noext", "unsupported_document")]:
            with self.assertRaises(ProviderError) as cm:
                tr(data, name)
            self.assertEqual(cm.exception.code, code, name)

    def test_too_long(self):
        old = D.MAX_DOC_CHARS
        D.MAX_DOC_CHARS = 50
        try:
            with self.assertRaises(ProviderError) as cm:
                tr(b"Paragraph one is here.\n\nParagraph two is here.\n\nParagraph three is here.", "a.txt")
            self.assertEqual(cm.exception.code, "document_too_long")
        finally:
            D.MAX_DOC_CHARS = old

    def test_filename_cannot_escape(self):
        self.assertEqual(tr(b"Hello", "../../etc/pass:wd.txt").filename, "pass_wd.am.txt")

    def test_auto_source_for_amharic(self):
        self.assertEqual(D.translate_document(P, "ሰላም".encode(), "a.txt", "auto", "en").data.decode(), "Hello")


class DocxTests(unittest.TestCase):
    def test_runs_merged_translated_and_package_intact(self):
        src = make_docx([["Hel", "lo"], ["Thank you"], ["   "]])
        r = tr(src, "letter.docx")
        zin, zout = zipfile.ZipFile(io.BytesIO(src)), zipfile.ZipFile(io.BytesIO(r.data))
        self.assertEqual(zin.namelist(), zout.namelist())
        self.assertEqual(zin.read("word/media/pic.bin"), zout.read("word/media/pic.bin"))
        xml = zout.read("word/document.xml").decode()
        root = ET.fromstring(xml)                                       # still well-formed XML
        texts = ["".join(t.text or "" for t in p.iter(f"{{{W}}}t")) for p in root.iter(f"{{{W}}}p")]
        self.assertEqual([t for t in texts if t], ["ሰላም", "አመሰግናለሁ", "   "])
        self.assertIn('mc:Ignorable="w14"', xml)                          # namespace prefixes untouched
        self.assertIn("<w:b/>", xml)                                      # formatting kept
        self.assertEqual(r.filename, "letter.am.docx")

    def test_special_characters_escaped(self):
        r = D.translate_document(P, make_docx([["a &amp; b &lt; c"]]), "x.docx", "en", "fr")
        xml = zipfile.ZipFile(io.BytesIO(r.data)).read("word/document.xml").decode()
        ET.fromstring(xml)
        self.assertIn("[MOCK en→fr] a &amp; b &lt; c", xml)

    def test_opens_in_python_docx_if_installed(self):
        try:
            import docx
        except ImportError:
            self.skipTest("python-docx not installed")
        r = tr(make_docx([["Hello"], ["yes"]]), "a.docx")
        d = docx.Document(io.BytesIO(r.data))
        self.assertEqual([p.text for p in d.paragraphs if p.text], ["ሰላም", "አዎ"])


class PdfTests(unittest.TestCase):
    def test_pdf_via_pypdf_if_installed(self):
        try:
            import pypdf  # noqa: F401
        except ImportError:
            with self.assertRaises(ProviderError) as cm:
                tr(b"%PDF-1.4", "a.pdf")
            self.assertEqual(cm.exception.code, "pdf_unsupported")
            return
        with self.assertRaises(ProviderError):
            tr(b"%PDF-1.4 broken", "a.pdf")


if __name__ == "__main__":
    unittest.main()
