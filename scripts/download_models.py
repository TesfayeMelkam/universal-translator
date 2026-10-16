"""Download AI models on request (never automatic). Everything here is large; each step asks first.

    python scripts/download_models.py --model nllb-600m            # translation, ~3 GB
    python scripts/download_models.py --model mms-asr              # server speech recognition, several GB
    python scripts/download_models.py --tts amh orm tir            # server voices, ~150 MB each

Needs: pip install transformers torch sentencepiece numpy   (UNVERIFIED in the build environment: no internet)
Licences: NLLB-200 and MMS weights are CC-BY-NC 4.0 (non-commercial). Check before commercial use.
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MODELS = {
    "nllb-600m": {"id": "facebook/nllb-200-distilled-600M", "disk_gb": 3.0, "ram_gb": 4, "kind": "nllb"},
    "mms-asr": {"id": "facebook/mms-1b-all", "disk_gb": 5.0, "ram_gb": 8, "kind": "asr"},
}


def fetch(kind: str, model_id: str, cache: str) -> None:
    if kind == "nllb":
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        AutoTokenizer.from_pretrained(model_id, cache_dir=cache)
        AutoModelForSeq2SeqLM.from_pretrained(model_id, cache_dir=cache)
    elif kind == "asr":
        from transformers import AutoProcessor, Wav2Vec2ForCTC
        AutoProcessor.from_pretrained(model_id, cache_dir=cache)
        Wav2Vec2ForCTC.from_pretrained(model_id, cache_dir=cache)
    else:                                              # tts
        from transformers import AutoTokenizer, VitsModel
        AutoTokenizer.from_pretrained(model_id, cache_dir=cache)
        VitsModel.from_pretrained(model_id, cache_dir=cache)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=MODELS)
    p.add_argument("--tts", nargs="*", metavar="ISO3", help="voices to fetch, e.g. amh orm tir")
    p.add_argument("--cache-dir", default=str(ROOT / "data" / "models"))
    a = p.parse_args()
    jobs = []
    if a.model:
        m = MODELS[a.model]
        jobs.append((m["kind"], m["id"], m["disk_gb"], m["ram_gb"]))
    for code in a.tts or []:
        jobs.append(("tts", f"facebook/mms-tts-{code}", 0.2, 2))
    if not jobs:
        p.print_help()
        return 0
    Path(a.cache_dir).mkdir(parents=True, exist_ok=True)
    need = sum(j[2] for j in jobs)
    free = shutil.disk_usage(a.cache_dir).free / 1e9
    print(f"About to download: {', '.join(j[1] for j in jobs)}\nNeeds ~{need:.1f} GB disk (free: {free:.1f} GB); RAM for the biggest: ~{max(j[3] for j in jobs)} GB.")
    if free < need * 1.5:
        print("Not enough free disk space.")
        return 1
    if input("Download now? [y/N] ").strip().lower() != "y":
        return 0
    for kind, mid, *_ in jobs:
        try:
            print(f"-> {mid}")
            fetch(kind, mid, a.cache_dir)
        except Exception as exc:  # noqa: BLE001
            print(f"   failed: {type(exc).__name__}: {exc}")
            return 1
    print("Done. Set in .env as needed: TRANSLATION_PROVIDER=nllb  STT_PROVIDER=mms  TTS_PROVIDER=mms   then restart.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
