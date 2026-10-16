"""Translate whole files while keeping their structure.

  .txt .md    paragraph by paragraph (Markdown code fences are left untouched)
  .srt .vtt   subtitle text only; numbers and timings are preserved exactly
  .docx       edits the text inside the Word XML directly, so styles/tables/images stay as they were
  .pdf        text is extracted (needs `pip install pypdf`) and returned as a translated .txt; layout is NOT kept

Everything runs in memory. Files are never stored.
"""
from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass

from ..providers.base import ProviderError, TranslationProvider
from .detect import detect_language
from .pipeline import translate_text

MAX_DOC_CHARS = 60_000
MAX_PARAGRAPHS = 1500
_SENT = re.compile(r"(?<=[.!?።؟。])\s+")


@dataclass
class DocResult:
    data: bytes
    filename: str
    mime: str
    stats: dict


class _Translator:
    """Translates one paragraph at a time with a cache; enforces size limits."""

    def __init__(self, provider: TranslationProvider, source: str, target: str, max_chars: int):
        self.provider, self.source, self.target, self.max_chars = provider, source, target, max_chars
        self.cache: dict = {}
        self.paragraphs = 0
        self.chars = 0
        self.mock = provider.is_mock

    def _one(self, text: str) -> str:
        if text in self.cache:
            return self.cache[text]
        self.chars += len(text)
        if self.chars > MAX_DOC_CHARS:
            raise ProviderError("document_too_long", f"Document has more than {MAX_DOC_CHARS:,} characters of text.", 413)
        out = translate_text(self.provider, text, self.source, self.target, self.max_chars)["translation"]
        self.cache[text] = out
        return out

    def __call__(self, text: str) -> str:
        core = text.strip()
        if not core:
            return text
        lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()):]
        self.paragraphs += 1
        if self.paragraphs > MAX_PARAGRAPHS:
            raise ProviderError("document_too_long", f"Document has more than {MAX_PARAGRAPHS} paragraphs.", 413)
        if len(core) <= self.max_chars:
            return lead + self._one(core) + trail
        chunks, cur = [], ""
        for sent in _SENT.split(core):                      # long paragraph: pack sentences into chunks
            while len(sent) > self.max_chars:               # a single huge "sentence": hard split
                chunks.append(sent[: self.max_chars]); sent = sent[self.max_chars:]
            if cur and len(cur) + 1 + len(sent) > self.max_chars:
                chunks.append(cur); cur = sent
            else:
                cur = f"{cur} {sent}".strip()
        if cur:
            chunks.append(cur)
        return lead + " ".join(self._one(c) for c in chunks) + trail


# ---------------------------------------------------------------- text formats
def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16"):
        try:
            return data.decode(enc)
        except UnicodeError:
            continue
    raise ProviderError("bad_encoding", "Please save the file as UTF-8 text and try again.", 422)


def _plain(text: str, tr, markdown: bool) -> str:
    out, para, fence = [], [], False

    def flush():
        if para:
            out.append(tr("\n".join(para)))
            para.clear()

    for line in text.split("\n"):
        if markdown and line.lstrip().startswith(("```", "~~~")):
            flush(); fence = not fence; out.append(line); continue
        if fence or not line.strip():
            flush(); out.append(line); continue
        para.append(line)
    flush()
    return "\n".join(out)


def _srt(text: str, tr) -> str:
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip("\n"))
    out = []
    for block in blocks:
        lines = block.split("\n")
        t = next((i for i, l in enumerate(lines[:2]) if "-->" in l), None)
        if t is None:
            out.append(block); continue                      # header / NOTE / STYLE block: keep as is
        head, body = lines[: t + 1], " ".join(l.strip() for l in lines[t + 1:])
        out.append("\n".join(head + ([tr(body)] if body else [])))
    return "\n\n".join(out) + "\n"


# ---------------------------------------------------------------- docx / pdf
_P = re.compile(r"<w:p(?:\s[^>]*)?>.*?</w:p>", re.S)
_T = re.compile(r"(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)", re.S)
_PARTS = re.compile(r"word/(document|header\d*|footer\d*|footnotes|endnotes)\.xml$")


def _docx_para(p: str, tr) -> str:
    runs = list(_T.finditer(p))
    if not runs:
        return p
    full = "".join(html.unescape(m.group(2)) for m in runs)
    if not full.strip():
        return p
    out = html.escape(tr(full), quote=False)
    n = {"i": 0}

    def repl(m):
        i, n["i"] = n["i"], n["i"] + 1
        if i:
            return m.group(1) + m.group(3)                    # later runs of the same paragraph: emptied
        opening = m.group(1)
        if "xml:space" not in opening:
            opening = opening[:-1] + ' xml:space="preserve">'
        return opening + out + m.group(3)

    return _T.sub(repl, p)


def _docx(data: bytes, tr) -> bytes:
    try:
        zin = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ProviderError("invalid_document", "That is not a valid .docx file.", 422)
    if "word/document.xml" not in zin.namelist():
        raise ProviderError("invalid_document", "That is not a valid .docx file.", 422)
    if sum(i.file_size for i in zin.infolist()) > 80_000_000:
        raise ProviderError("document_too_large", "The document expands to too much data.", 413)
    new_parts = {}
    for name in zin.namelist():
        if _PARTS.match(name):
            xml = zin.read(name).decode("utf-8")
            new_parts[name] = _P.sub(lambda m: _docx_para(m.group(0), tr), xml).encode("utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zout:
        for info in zin.infolist():
            zout.writestr(info, new_parts.get(info.filename, zin.read(info.filename)))
    return buf.getvalue()


def _pdf(data: bytes, tr) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        raise ProviderError("pdf_unsupported", "PDF support needs: pip install pypdf", 501)
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ProviderError("pdf_encrypted", "Password-protected PDFs are not supported.", 422)
        pages = [(p.extract_text() or "") for p in reader.pages[:100]]
    except ProviderError:
        raise
    except Exception:  # noqa: BLE001
        raise ProviderError("invalid_document", "That PDF could not be read.", 422)
    if not any(p.strip() for p in pages):
        raise ProviderError("no_text_found", "This PDF has no selectable text (it may be scanned). Use the Camera tab (OCR) instead.", 422)
    out = []
    for n, page in enumerate(pages, 1):
        out.append(f"[Page {n}]")
        for para in re.split(r"\n\s*\n", page):
            para = re.sub(r"\s*\n\s*", " ", para).strip()
            if para:
                out.append(tr(para))
        out.append("")
    return "\n\n".join(out).strip() + "\n"


# ---------------------------------------------------------------- entry point
def _safe_name(name: str) -> str:
    name = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "_", (name or "document").split("/")[-1].split("\\")[-1]).strip(". ")
    return name[:100] or "document"


def translate_document(provider: TranslationProvider, data: bytes, filename: str, source: str, target: str,
                       max_chars: int = 1500) -> DocResult:
    if not data:
        raise ProviderError("empty_document", "The file is empty.", 422)
    name = _safe_name(filename)
    stem, _, ext = name.rpartition(".")
    if not stem:
        stem, ext = name, ""
    ext = ext.lower()
    if ext not in {"txt", "md", "srt", "vtt", "docx", "pdf"}:
        raise ProviderError("unsupported_document", "Supported files: .txt .md .srt .vtt .docx .pdf", 415)
    if source == "auto":
        sample = _decode(data[:4000]) if ext in {"txt", "md", "srt", "vtt"} else ""
        guess = detect_language(sample)["language"] if sample else None
        if not guess:
            raise ProviderError("source_required", "Please choose the document's language.", 422)
        source = guess
    tr = _Translator(provider, source, target, max_chars)
    if ext in ("txt", "md"):
        out, mime = _plain(_decode(data), tr, ext == "md").encode("utf-8"), "text/plain; charset=utf-8"
        out_ext = ext
    elif ext in ("srt", "vtt"):
        out, mime = _srt(_decode(data), tr).encode("utf-8"), "text/plain; charset=utf-8"
        out_ext = ext
    elif ext == "docx":
        out, mime, out_ext = _docx(data, tr), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"
    else:
        out, mime, out_ext = _pdf(data, tr).encode("utf-8"), "text/plain; charset=utf-8", "txt"
    return DocResult(out, f"{stem}.{target}.{out_ext}", mime,
                     {"paragraphs": tr.paragraphs, "characters": tr.chars, "mock": tr.mock, "source": source,
                      "target": target, "layout_kept": ext != "pdf"})
