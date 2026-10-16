"""Tesseract OCR provider (real OCR, optional).

UNVERIFIED in the build environment. Needs:
  1. The Tesseract program (Windows installer from UB-Mannheim: https://github.com/UB-Mannheim/tesseract/wiki)
     with the language data you want ticked (e.g. Amharic = "amh").
  2. pip install pytesseract pillow
  3. If tesseract.exe is not on PATH, set TESSERACT_CMD in .env to its full path.
Accuracy depends on photo quality. Handwriting and blurry text are not reliably recognised.
"""
from __future__ import annotations

import io
import os

from ..base import OCRProvider, OCRResult, ProviderError

# App language code -> Tesseract language-data name. Whether the data is installed is checked at runtime.
TESS = {
    "am": "amh", "om": "orm", "ti": "tir", "so": "som", "sw": "swa", "ha": "hau", "yo": "yor",
    "ig": "ibo", "en": "eng", "ar": "ara", "fr": "fra", "zh": "chi_sim", "es": "spa", "pt": "por",
    "hi": "hin", "bn": "ben", "ja": "jpn", "ko": "kor", "tr": "tur", "ru": "rus", "de": "deu",
    "it": "ita", "id": "ind", "th": "tha", "vi": "vie", "fa": "fas", "ur": "urd", "nl": "nld",
    "pl": "pol", "uk": "ukr", "el": "ell", "he": "heb", "ta": "tam",
}


class TesseractOCRProvider(OCRProvider):
    name = "tesseract"

    def _module(self):
        import pytesseract
        cmd = os.environ.get("TESSERACT_CMD")
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        return pytesseract

    def available(self):
        try:
            self._module().get_tesseract_version()
            import PIL  # noqa: F401
            return True, "ok"
        except ImportError:
            return False, "Install the Python packages: pip install pytesseract pillow"
        except Exception:  # noqa: BLE001
            return False, "The Tesseract program was not found. Install it and/or set TESSERACT_CMD in .env."

    def recognize(self, image: bytes, language: str) -> OCRResult:
        ok, reason = self.available()
        if not ok:
            raise ProviderError("ocr_unavailable", reason, 503)
        code = TESS.get(language)
        if not code:
            raise ProviderError("ocr_language_unsupported", f"OCR is not mapped for '{language}'.", 422)
        pt = self._module()
        if code not in pt.get_languages(config=""):
            raise ProviderError(
                "ocr_language_missing",
                f"Tesseract language data '{code}' is not installed. Re-run the Tesseract installer "
                f"and tick that language.", 422)
        try:
            from PIL import Image
            img = Image.open(io.BytesIO(image))
            data = pt.image_to_data(img, lang=code, output_type=pt.Output.DICT, timeout=30)
        except Exception as exc:  # noqa: BLE001
            raise ProviderError("ocr_failed", "The image could not be read.", 422) from exc

        lines: dict = {}
        confs = []
        for i, word in enumerate(data["text"]):
            word = word.strip()
            try:
                conf = float(data["conf"][i])
            except (TypeError, ValueError):
                conf = -1
            if not word or conf < 0:
                continue
            confs.append(conf)
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            x, y, w, h = (data[k][i] for k in ("left", "top", "width", "height"))
            ln = lines.setdefault(key, {"words": [], "x0": x, "y0": y, "x1": x + w, "y1": y + h})
            ln["words"].append(word)
            ln["x0"], ln["y0"] = min(ln["x0"], x), min(ln["y0"], y)
            ln["x1"], ln["y1"] = max(ln["x1"], x + w), max(ln["y1"], y + h)
        regions = [{"text": " ".join(v["words"]), "x": v["x0"], "y": v["y0"],
                    "w": v["x1"] - v["x0"], "h": v["y1"] - v["y0"]} for v in lines.values()]
        text = "\n".join(r["text"] for r in regions)
        return OCRResult(text=text, provider=self.name, regions=regions,
                         confidence=round(sum(confs) / len(confs), 1) if confs else None)
