"""Settings read from environment variables (and an optional local .env file)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse_env_value(raw: str) -> str:
    """'abc  # note' -> 'abc'. Quoted values keep any # inside the quotes. (The old loader kept the comment as part
    of the value, so 'TRANSLATION_PROVIDER=mock   # mock | nllb' was read as a nonsense string.)"""
    raw = raw.strip()
    if raw[:1] in ('"', "'") and raw.count(raw[0]) >= 2:
        return raw[1:raw.index(raw[0], 1)]
    return re.split(r"\s+#", raw, maxsplit=1)[0].strip()


def _load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), parse_env_value(value))


_load_dotenv(ROOT / ".env")


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


@dataclass(frozen=True)
class Settings:
    translation_provider: str
    tts_provider: str
    max_chars: int
    rate_limit_per_minute: int
    db_path: str
    model_dir: str
    nllb_model: str
    allow_model_download: bool
    allowed_origins: tuple
    ocr_provider: str = "auto"
    max_image_bytes: int = 5_000_000
    stun_urls: tuple = ("stun:stun.l.google.com:19302",)
    turn_url: str = ""
    turn_username: str = ""
    turn_credential: str = ""
    max_rooms: int = 50
    max_participants: int = 4
    turn_urls: tuple = ()
    turn_secret: str = ""
    turn_ttl: int = 3600
    access_code: str = ""
    stt_provider: str = "none"
    mms_asr_model: str = "facebook/mms-1b-all"
    max_media_mb: int = 50
    max_media_seconds: int = 1800
    auth_mode: str = "off"
    allow_signup: bool = True
    session_days: int = 30
    max_doc_mb: int = 5
    max_audio_mb: int = 4
    max_large: int = 12
    livekit_url: str = ""
    livekit_key: str = ""
    livekit_secret: str = ""
    livekit_sdk_url: str = "https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"
    telegram_token: str = ""
    telegram_secret: str = ""
    # --- v0.6: cloud translation engines, data sources, networking ---
    google_key: str = ""
    azure_key: str = ""
    azure_region: str = ""
    azure_endpoint: str = "https://api.cognitive.microsofttranslator.com"
    libre_url: str = ""
    libre_key: str = ""
    mymemory_email: str = ""
    cloud_timeout: float = 15.0
    cloud_retries: int = 1
    cache_size: int = 2000
    glossary_dir: str = ""
    glossary_db: str = ""
    data_source_urls: tuple = ()
    data_sync_minutes: int = 0
    host: str = ""
    port: int = 8000
    trust_proxy: bool = False


def get_settings() -> Settings:
    return Settings(
        translation_provider=os.environ.get("TRANSLATION_PROVIDER", "auto").lower(),
        tts_provider=os.environ.get("TTS_PROVIDER", "auto").lower(),
        max_chars=_int("MAX_CHARS", 2000),
        rate_limit_per_minute=_int("RATE_LIMIT_PER_MINUTE", 120),
        db_path=os.environ.get("DB_PATH", str(ROOT / "data" / "history.sqlite3")),
        model_dir=os.environ.get("MODEL_DIR", str(ROOT / "data" / "models")),
        nllb_model=os.environ.get("NLLB_MODEL", "facebook/nllb-200-distilled-600M"),
        allow_model_download=os.environ.get("ALLOW_MODEL_DOWNLOAD", "0") == "1",
        allowed_origins=tuple(
            o.strip() for o in os.environ.get(
                "ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000").split(",") if o.strip()),
        ocr_provider=os.environ.get("OCR_PROVIDER", "auto").lower(),
        max_image_bytes=_int("MAX_IMAGE_MB", 5) * 1_000_000,
        stun_urls=tuple(u.strip() for u in os.environ.get(
            "STUN_URLS", "stun:stun.l.google.com:19302").split(",") if u.strip()),
        turn_url=os.environ.get("TURN_URL", ""),
        turn_username=os.environ.get("TURN_USERNAME", ""),
        turn_credential=os.environ.get("TURN_CREDENTIAL", ""),
        max_rooms=_int("MAX_ROOMS", 50),
        turn_urls=tuple(u.strip() for u in os.environ.get("TURN_URLS", "").split(",") if u.strip()),
        turn_secret=os.environ.get("TURN_SECRET", ""),
        turn_ttl=max(60, _int("TURN_TTL", 3600)),
        access_code=os.environ.get("ACCESS_CODE", ""),
        stt_provider=os.environ.get("STT_PROVIDER", "none").lower(),
        mms_asr_model=os.environ.get("MMS_ASR_MODEL", "facebook/mms-1b-all"),
        max_media_mb=_int("MAX_MEDIA_MB", 50),
        max_media_seconds=_int("MAX_MEDIA_SECONDS", 1800),
        auth_mode=os.environ.get("AUTH_MODE", "off").lower(),
        allow_signup=os.environ.get("ALLOW_SIGNUP", "1") == "1",
        session_days=_int("SESSION_DAYS", 30),
        max_doc_mb=_int("MAX_DOC_MB", 5),
        max_audio_mb=_int("MAX_AUDIO_MB", 4),
        max_large=max(2, min(50, _int("MAX_LARGE_PARTICIPANTS", 12))),
        livekit_url=os.environ.get("LIVEKIT_URL", ""),
        livekit_key=os.environ.get("LIVEKIT_API_KEY", ""),
        livekit_secret=os.environ.get("LIVEKIT_API_SECRET", ""),
        livekit_sdk_url=os.environ.get("LIVEKIT_SDK_URL", "https://cdn.jsdelivr.net/npm/livekit-client@2/dist/livekit-client.umd.min.js"),
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        telegram_secret=os.environ.get("TELEGRAM_WEBHOOK_SECRET", ""),
        google_key=os.environ.get("GOOGLE_TRANSLATE_API_KEY", ""),
        azure_key=os.environ.get("AZURE_TRANSLATOR_KEY", ""),
        azure_region=os.environ.get("AZURE_TRANSLATOR_REGION", ""),
        azure_endpoint=os.environ.get("AZURE_TRANSLATOR_ENDPOINT", "https://api.cognitive.microsofttranslator.com").rstrip("/"),
        libre_url=os.environ.get("LIBRETRANSLATE_URL", "").rstrip("/"),
        libre_key=os.environ.get("LIBRETRANSLATE_API_KEY", ""),
        mymemory_email=os.environ.get("MYMEMORY_EMAIL", ""),
        cloud_timeout=max(2.0, _float("CLOUD_TIMEOUT", 15.0)),
        cloud_retries=max(0, min(3, _int("CLOUD_RETRIES", 1))),
        cache_size=max(0, _int("CACHE_SIZE", 2000)),
        glossary_dir=os.environ.get("GLOSSARY_DIR", str(ROOT / "data" / "glossary")),
        glossary_db=os.environ.get("GLOSSARY_DB", ""),
        data_source_urls=tuple(u.strip() for u in os.environ.get("DATA_SOURCE_URLS", "").split(",") if u.strip()),
        data_sync_minutes=max(0, _int("DATA_SYNC_MINUTES", 0)),
        host=os.environ.get("APP_HOST", ""),
        port=_int("APP_PORT", 8000),
        trust_proxy=os.environ.get("TRUST_PROXY", "0") == "1",
        max_participants=max(2, min(6, _int("MAX_PARTICIPANTS", 4))),   # mesh calls: more than 6 is not practical
    )
