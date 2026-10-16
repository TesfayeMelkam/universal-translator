"""Measure how consistent the configured translator is, per language.

    python scripts/check_translation.py                 # Amharic, Oromo, Tigrinya, Somali
    python scripts/check_translation.py --langs am om fr sw --phrases 10
    python scripts/check_translation.py --all           # every language the provider supports (slow)

Writes data/translation_report.json. In mock mode every score only tells you the mock is a mock.
This is a round-trip consistency check, NOT proof of correctness: have a fluent speaker review important text.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ai_services.config import get_settings            # noqa: E402
from ai_services.registry import build_translation_provider  # noqa: E402
from ai_services.services.quality import DEFAULT_LANGS, SELFTEST_PHRASES, run_selftest  # noqa: E402
from shared.languages import LANGUAGES                  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", nargs="*", default=DEFAULT_LANGS)
    ap.add_argument("--phrases", type=int, default=5)
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    s = get_settings()
    provider = build_translation_provider(s)
    ready, detail = provider.available()
    print(f"Provider: {provider.name}{' (MOCK - not real translation)' if provider.is_mock else ''} | ready: {ready} | {detail}")
    if not ready:
        print("Model is not ready. Install transformers/torch/sentencepiece and run scripts/download_models.py")
        return 1
    langs = [l.code for l in LANGUAGES if l.code != "en"] if a.all else a.langs
    rep = run_selftest(provider, langs, SELFTEST_PHRASES[:a.phrases], s.max_chars)
    print(f"\n{'language':<26}{'score':>7}  grade")
    for e in rep["languages"]:
        sc = "-" if e["score"] is None else f"{e['score']:.2f}"
        extra = f"   ({e['unchanged']} echoed unchanged)" if e["unchanged"] else ""
        print(f"{e['name']:<26}{sc:>7}  {e['grade']}{extra}")
    out = ROOT / "data" / "translation_report.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nFull report: {out}\n{rep['disclaimer']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
