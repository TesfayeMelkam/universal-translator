"""FastAPI application: API + the web UI/PWA, served from one process.

Run:  python -m uvicorn ai_services.main:app --reload
Open: http://127.0.0.1:8000
"""
from __future__ import annotations

import json
import logging
import secrets
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from shared.languages import as_dicts, get_language
from .config import ROOT, Settings, get_settings
from .providers.base import ProviderError
from .auth import UserStore
from .integrations.telegram import ChatStore, TelegramBot, telegram_sender
from .jobs import JobManager
from .livekit_token import make_livekit_token
from .rooms import RoomManager, clean_name, normalize_code
from .security import check_access
from .turn import build_ice_servers, has_relay
from .registry import build_ocr_provider, build_stt_provider, build_translation_provider, build_tts_provider
from .services.audio import decode_pcm16, ffmpeg_available, to_float
from .services.datasources import DataSync
from .services.detect import detect_language
from .services.glossary import Glossary, parse_rows
from .services.documents import translate_document
from .services.history import HistoryStore
from .services.pipeline import translate_text
from .services.quality import DEFAULT_LANGS, run_selftest
from .services.subtitles import make_subtitles
from .services.vision_pipeline import translate_image

log = logging.getLogger("universal_translator")
FRONTEND = ROOT / "frontend"


class TranslateRequest(BaseModel):
    text: str = Field(..., description="Text to translate")
    source: str = Field("auto", description="Language code or 'auto'")
    target: str
    save_history: bool = True


class SelfTestRequest(BaseModel):
    languages: list = Field(default_factory=lambda: list(DEFAULT_LANGS), max_length=8)
    phrases: int = Field(5, ge=1, le=10)


class BatchRequest(BaseModel):
    texts: list = Field(..., max_length=50, description="Up to 50 texts")
    source: str = Field("auto", description="Language code or 'auto'")
    target: str


class GlossaryEntry(BaseModel):
    source: str = Field(..., description="Language code of source_text")
    target: str = Field(..., description="Language code of translation")
    source_text: str = Field(..., max_length=500)
    translation: str = Field(..., max_length=500)


class LibreRequest(BaseModel):
    q: str = Field(..., description="Text (LibreTranslate-compatible field names)")
    source: str = "auto"
    target: str
    format: str = "text"


class DetectRequest(BaseModel):
    text: str


class VisionRequest(BaseModel):
    image: str = Field(..., max_length=12_000_000, description="Base64 (or data URL) PNG/JPEG/WebP")
    source: str = Field(..., description="Language of the text in the picture")
    target: str
    save_history: bool = True


class AuthRequest(BaseModel):
    username: str = Field(..., max_length=64)
    password: str = Field(..., max_length=256)


class SynthesizeRequest(BaseModel):
    text: str = Field(..., max_length=1000)
    language: str


def create_app(settings: Optional[Settings] = None, transport=None) -> FastAPI:
    """`transport` replaces real internet access for cloud engines (used by tests only)."""
    settings = settings or get_settings()
    app = FastAPI(title="Universal Translator", version="0.6.0")
    gdb = settings.glossary_db or (":memory:" if settings.db_path == ":memory:"
                                   else str(Path(settings.db_path).with_name("glossary.sqlite3")))
    glossary = Glossary(gdb)
    data_sync = DataSync(glossary, settings.glossary_dir, settings.data_source_urls, settings.data_sync_minutes)
    provider = build_translation_provider(settings, glossary, transport)
    tts = build_tts_provider(settings)
    ocr = build_ocr_provider(settings)
    history = HistoryStore(settings.db_path)
    users = UserStore(settings.db_path, session_days=settings.session_days)
    stt = build_stt_provider(settings)
    jobs = JobManager()
    livekit_ready = bool(settings.livekit_url and settings.livekit_key and settings.livekit_secret)
    telegram_bot = None
    if settings.telegram_token and settings.telegram_secret:
        chat_db = ":memory:" if settings.db_path == ":memory:" else str(Path(settings.db_path).with_name("telegram.sqlite3"))
        telegram_bot = TelegramBot(lambda text, src, tgt: translate_text(provider, text, src, tgt, settings.max_chars),
                                   telegram_sender(settings.telegram_token), ChatStore(chat_db))
    rooms = RoomManager(
        lambda text, src, tgt: translate_text(provider, text, src, tgt, settings.max_chars),
        max_rooms=settings.max_rooms, max_participants=settings.max_participants, max_large=settings.max_large,
        max_chars=min(settings.max_chars, 1000))
    hits: dict = defaultdict(deque)
    if hasattr(provider, "warm_up"):                 # real server: load folders / cloud data and engine language lists
        data_sync.start_background()
        provider.warm_up()

    def client_ip(request: Request) -> str:
        """Behind a reverse proxy (Caddy, nginx, a tunnel) every request would look like 127.0.0.1 and share one
        rate-limit bucket. With TRUST_PROXY=1 the first X-Forwarded-For address is used instead."""
        if settings.trust_proxy:
            fwd = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
            if fwd:
                return fwd
        return request.client.host if request.client else "unknown"

    def session_user(request: Request) -> Optional[dict]:
        return users.user_for(request.cookies.get("ut_session"))

    def require_access(request: Request, x_access_code: Optional[str] = Header(None)) -> int:
        """Who is calling? A signed-in user passes; otherwise the access code (if one is configured) must match.
        With AUTH_MODE=required only signed-in users (or the access code) may use host features."""
        user = session_user(request)
        if user:
            origin = request.headers.get("origin")      # cookie login: refuse cross-site writes (CSRF defence in depth)
            if request.method in ("POST", "PUT", "DELETE") and origin and urlparse(origin).netloc != request.headers.get("host", "") \
                    and origin not in settings.allowed_origins:
                raise ProviderError("bad_origin", "Cross-site request refused.", 403)
            return user["id"]
        code_ok = bool(settings.access_code) and check_access(settings.access_code, x_access_code)
        if settings.auth_mode == "required":
            if code_ok:
                return 0
            raise ProviderError("login_required", "Please sign in.", 401)
        if settings.access_code and not code_ok:
            raise ProviderError("access_required", "An access code is required for this action.", 401)
        return 0

    async def read_body(request: Request, limit: int) -> bytes:
        declared = request.headers.get("content-length")
        if declared is None:
            raise ProviderError("length_required", "Upload size must be declared.", 411)
        if not declared.isdigit() or int(declared) > limit:
            raise ProviderError("file_too_large", f"File is larger than {limit // 1_000_000} MB.", 413)
        data = await request.body()
        if len(data) > limit:
            raise ProviderError("file_too_large", f"File is larger than {limit // 1_000_000} MB.", 413)
        return data

    protected = [Depends(require_access)]

    app.add_middleware(
        CORSMiddleware, allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type", "X-Access-Code"])

    @app.middleware("http")
    async def guard(request: Request, call_next):
        request_id = uuid.uuid4().hex[:12]
        if (request.url.path.startswith("/api/") or request.url.path in ("/translate", "/languages")) and request.method != "OPTIONS":
            ip = client_ip(request)
            now, q = time.time(), hits[ip]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= settings.rate_limit_per_minute:
                return JSONResponse({"error": {"code": "rate_limited", "message": "Too many requests."}},
                                    status_code=429)
            q.append(now)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ProviderError)
    async def provider_error(_: Request, exc: ProviderError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)

    @app.get("/health")
    def health():
        ready, reason = provider.available()      # cheap for every provider: no network, no model loading
        return {"status": "ok", "translation_provider": provider.name, "mock": provider.is_mock,
                "model_ready": ready, "detail": reason,
                "tts_ready": bool(tts and tts.available()[0]), "stt_ready": bool(stt and stt.available()[0]),
                "ocr_provider": ocr.name, "ocr_mock": ocr.is_mock, "ocr_ready": ocr.available()[0]}

    @app.get("/api/v1/languages")
    def languages():
        items = as_dicts()
        cov = getattr(provider, "coverage", None)
        if cov:                                   # which engines / phrasebook can translate to and from each language
            for d in items:
                names = cov(d["code"])
                d["engines"] = names
                d["data_only"] = names == ["phrasebook"]
                d["available"] = bool(names)
        return {"languages": items}

    @app.post("/api/v1/translate")
    def translate(req: TranslateRequest, uid: int = Depends(require_access)):
        # Sync endpoint: FastAPI runs it in a worker thread, so model inference won't block the event loop.
        result = translate_text(provider, req.text, req.source, req.target, settings.max_chars)
        if req.save_history:
            result["id"] = history.add(result["source"], result["target"], result["source_text"],
                                       result["translation"], result["provider"], uid)
        return result

    @app.post("/api/v1/translate/batch")
    def translate_batch(req: BatchRequest, uid: int = Depends(require_access)):
        """Translate up to 50 texts in one call (for other systems). One bad item does not fail the others."""
        results = []
        for text in list(req.texts)[:50]:
            try:
                results.append({"ok": True, **translate_text(provider, str(text), req.source, req.target, settings.max_chars)})
            except ProviderError as exc:
                results.append({"ok": False, "source_text": str(text), "error": {"code": exc.code, "message": exc.message}})
        return {"results": results}

    # LibreTranslate-compatible endpoints: tools that already speak the LibreTranslate API can point at this server.
    @app.post("/translate")
    def libre_translate(req: LibreRequest, uid: int = Depends(require_access)):
        r = translate_text(provider, req.q, req.source, req.target, settings.max_chars)
        out = {"translatedText": r["translation"]}
        if r["detected"]:
            out["detectedLanguage"] = {"language": r["detected"]["language"], "confidence": 0}
        return out

    @app.get("/languages")
    def libre_languages():
        items = [d for d in languages()["languages"] if d.get("available", True)]
        codes = [d["code"] for d in items]
        return [{"code": d["code"], "name": d["english_name"], "targets": [c for c in codes if c != d["code"]]} for d in items]

    @app.get("/api/v1/translation/status")
    def translation_status():
        ready, detail = provider.available()
        info = {"provider": provider.name, "mock": provider.is_mock, "ready": ready, "detail": detail,
                "model": getattr(provider, "model_name", None), "languages_in_catalog": len(as_dicts())}
        if hasattr(provider, "describe"):
            info["engines"] = provider.describe()
            info["warnings"] = getattr(provider, "warnings", [])
            info["phrasebook_entries"] = glossary.stats()["entries"]
            for eng in provider.engines:         # only report once a local model is really loaded (never load it here)
                if hasattr(eng, "unsupported_codes") and getattr(eng, "_model", None) is not None:
                    info["unsupported_codes"] = eng.unsupported_codes()
        elif ready and hasattr(provider, "unsupported_codes"):
            info["unsupported_codes"] = provider.unsupported_codes()
        return info

    @app.post("/api/v1/translation/selftest", dependencies=protected)
    def translation_selftest(req: SelfTestRequest):
        from .services.quality import SELFTEST_PHRASES
        return run_selftest(provider, [str(c).lower() for c in req.languages], SELFTEST_PHRASES[:req.phrases],
                            settings.max_chars)

    @app.post("/api/v1/vision/translate")
    def vision_translate(req: VisionRequest, uid: int = Depends(require_access)):
        result = translate_image(ocr, provider, req.image, req.source, req.target,
                                 settings.max_image_bytes, settings.max_chars)
        if req.save_history:
            result["id"] = history.add(result["source"], result["target"], result["source_text"],
                                       result["translation"], result["provider"], uid)
        return result

    @app.post("/api/v1/detect", dependencies=protected)
    def detect(req: DetectRequest):
        return detect_language(req.text)

    @app.post("/api/v1/synthesize", dependencies=protected)
    def synthesize(req: SynthesizeRequest):
        if not get_language(req.language):
            raise ProviderError("unknown_language", "Unknown language.", 422)
        if tts is None:
            raise ProviderError("tts_unavailable", "Server TTS is disabled. The web UI uses browser voices.", 501)
        return Response(tts.synthesize(req.text, req.language), media_type="audio/wav")

    @app.get("/api/v1/history")
    def history_list(limit: int = 50, uid: int = Depends(require_access)):
        return {"items": history.list(limit, uid)}

    @app.post("/api/v1/history/{item_id}/favorite")
    def history_fav(item_id: int, uid: int = Depends(require_access)):
        if not history.toggle_favorite(item_id, uid):
            raise ProviderError("not_found", "History item not found.", 404)
        return {"ok": True}

    @app.delete("/api/v1/history")
    def history_clear(uid: int = Depends(require_access)):
        history.clear(uid)
        return {"ok": True}

    # ---- accounts ------------------------------------------------------------
    def start_session(request: Request, uid: int, username: str) -> JSONResponse:
        resp = JSONResponse({"user": {"id": uid, "username": username}})
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        resp.set_cookie("ut_session", users.create_session(uid), max_age=settings.session_days * 86400,
                        httponly=True, samesite="lax", secure=secure, path="/")
        return resp

    @app.get("/api/v1/auth/me")
    def auth_me(request: Request):
        return {"auth_mode": settings.auth_mode, "signup": settings.allow_signup,
                "access_code": bool(settings.access_code), "user": session_user(request)}

    @app.post("/api/v1/auth/register")
    def auth_register(req: AuthRequest, request: Request):
        if settings.auth_mode == "off":
            raise ProviderError("auth_disabled", "Accounts are turned off on this server.", 404)
        if not settings.allow_signup:
            raise ProviderError("signup_closed", "Sign-ups are closed on this server.", 403)
        uid = users.create_user(req.username, req.password)
        return start_session(request, uid, req.username.strip())

    @app.post("/api/v1/auth/login")
    def auth_login(req: AuthRequest, request: Request):
        if settings.auth_mode == "off":
            raise ProviderError("auth_disabled", "Accounts are turned off on this server.", 404)
        uid = users.verify(req.username, req.password, client_ip(request))
        return start_session(request, uid, req.username.strip())

    @app.post("/api/v1/auth/logout")
    def auth_logout(request: Request):
        users.end_session(request.cookies.get("ut_session"))
        resp = JSONResponse({"ok": True})
        resp.delete_cookie("ut_session", path="/")
        return resp

    # ---- documents, speech-to-text, subtitles ------------------------------------
    @app.post("/api/v1/documents/translate")
    async def documents_translate(request: Request, source: str, target: str, filename: str = "document.txt",
                                  uid: int = Depends(require_access)):
        data = await read_body(request, settings.max_doc_mb * 1_000_000)
        res = await run_in_threadpool(translate_document, provider, data, filename, source.lower(), target.lower(),
                                      min(settings.max_chars, 1500))
        return Response(res.data, media_type=res.mime, headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(res.filename)}",
            "X-Doc-Stats": json.dumps(res.stats), "Access-Control-Expose-Headers": "X-Doc-Stats, Content-Disposition"})

    @app.post("/api/v1/transcribe")
    async def transcribe(request: Request, language: str, uid: int = Depends(require_access)):
        if stt is None:
            raise ProviderError("stt_not_configured", "Server speech recognition is not set up (STT_PROVIDER=mms). "
                                "The web UI normally uses the browser's own speech recognition.", 501)
        if not get_language(language):
            raise ProviderError("unknown_language", "Unknown language.", 422)
        data = await read_body(request, settings.max_audio_mb * 1_000_000)

        def work() -> str:
            return stt.transcribe(to_float(decode_pcm16(data, max_seconds=60)), language.lower())
        return {"text": (await run_in_threadpool(work)).strip()}

    @app.post("/api/v1/subtitles")
    async def subtitles_start(request: Request, source: str, target: str = "", filename: str = "media",
                              uid: int = Depends(require_access)):
        if stt is None:
            raise ProviderError("stt_not_configured", "Subtitles need server speech recognition (STT_PROVIDER=mms) and FFmpeg.", 501)
        if not get_language(source) or (target and not get_language(target)):
            raise ProviderError("unknown_language", "Unknown language.", 422)
        data = await read_body(request, settings.max_media_mb * 1_000_000)
        src, tgt = source.lower(), target.lower() or None
        job = jobs.submit(lambda report: make_subtitles(stt, provider, data, src, tgt, settings.max_media_seconds, 15, report), uid)
        return {"job": job}

    @app.get("/api/v1/jobs/{job_id}")
    def job_status(job_id: str, uid: int = Depends(require_access)):
        return jobs.status(job_id, uid)

    @app.get("/api/v1/jobs/{job_id}/download")
    def job_download(job_id: str, which: str = "final", uid: int = Depends(require_access)):
        job = jobs.get(job_id, uid)
        if job.status != "done" or not job.result:
            raise ProviderError("job_not_ready", "The subtitles are not finished yet.", 409)
        srt = job.result["source_srt"] if which == "source" else job.result["srt"]
        return Response(srt.encode("utf-8"), media_type="text/plain; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename*=UTF-8''subtitles.srt"})

    # ---- your own data: phrasebook, files, cloud sources ----------------------------------
    @app.get("/api/v1/data/status", dependencies=protected)
    def data_status():
        return data_sync.status()

    @app.post("/api/v1/data/sync", dependencies=protected)
    def data_sync_now():
        """Re-read data/glossary/ and every DATA_SOURCE_URLS link now."""
        return data_sync.run()

    @app.post("/api/v1/glossary", dependencies=protected)
    def glossary_add(req: GlossaryEntry):
        try:
            glossary.add(req.source, req.target, req.source_text, req.translation, "manual")
        except ValueError as exc:
            raise ProviderError("bad_glossary_entry", str(exc), 422)
        return {"ok": True, "entries": glossary.stats()["entries"]}

    @app.post("/api/v1/glossary/import")
    async def glossary_import(request: Request, name: str = "upload", uid: int = Depends(require_access)):
        """Body = a CSV or JSON file (see ai_services/services/glossary.py for the shapes)."""
        data = await read_body(request, 5_000_000)
        label = "".join(ch for ch in name if ch.isalnum() or ch in "._-")[:40] or "upload"
        return await run_in_threadpool(glossary.import_document, data, f"upload:{label}", "auto", True)

    @app.get("/api/v1/glossary/export", dependencies=protected)
    def glossary_export():
        return Response(glossary.export_csv().encode("utf-8"), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=phrasebook.csv"})

    # ---- Telegram ------------------------------------------------------------------
    @app.post("/api/v1/integrations/telegram/webhook")
    async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: Optional[str] = Header(None)):
        if telegram_bot is None:
            raise ProviderError("not_found", "Not found.", 404)
        if not check_access(settings.telegram_secret, x_telegram_bot_api_secret_token):
            raise ProviderError("forbidden", "Forbidden.", 403)
        try:
            update = await request.json()
        except ValueError:
            raise ProviderError("bad_json", "Invalid JSON.", 400)
        await run_in_threadpool(telegram_bot.handle_update, update)
        return {"ok": True}

    # ---- what this server can do (the web UI adapts to this) ---------------------------
    @app.get("/api/v1/capabilities")
    def capabilities():
        return {"languages": len(as_dicts()),
                "translation": {"provider": provider.name, "mock": provider.is_mock,
                                "engines": [e.name for e in getattr(provider, "engines", [])],
                                "phrasebook_entries": glossary.stats()["entries"]},
                "tts": bool(tts and tts.available()[0]), "tts_provider": tts.name if tts else None,
                "stt": bool(stt and stt.available()[0]), "ffmpeg": ffmpeg_available(),
                "ocr": {"provider": ocr.name, "mock": ocr.is_mock},
                "documents": ["txt", "md", "srt", "vtt", "docx", "pdf"],
                "limits": {"max_chars": settings.max_chars, "max_doc_mb": settings.max_doc_mb,
                           "max_media_mb": settings.max_media_mb, "max_participants": settings.max_participants,
                           "max_large": settings.max_large},
                "livekit": livekit_ready, "telegram": telegram_bot is not None,
                "auth_mode": settings.auth_mode, "signup": settings.allow_signup,
                "access_code": bool(settings.access_code)}

    # ---- video call rooms --------------------------------------------------
    @app.post("/api/v1/rooms", dependencies=protected)
    def room_create(mode: str = "mesh"):
        if mode == "sfu" and not livekit_ready:
            raise ProviderError("livekit_not_configured", "Large calls need a LiveKit server (see deploy/README.md).", 501)
        return {"code": rooms.create_room(mode)}

    @app.get("/api/v1/livekit/token")
    def livekit_token(room: str, name: str = "Guest"):
        if not livekit_ready:
            raise ProviderError("livekit_not_configured", "Large calls are not set up on this server.", 501)
        if rooms.info(room)["mode"] != "sfu":
            raise ProviderError("bad_mode", "This room is a normal call.", 409)
        token = make_livekit_token(settings.livekit_key, settings.livekit_secret, normalize_code(room),
                                   secrets.token_hex(6), clean_name(name))
        return {"url": settings.livekit_url, "token": token, "sdk": settings.livekit_sdk_url}

    @app.get("/api/v1/rooms/{code}")
    def room_info(code: str):
        return rooms.info(code)

    @app.get("/api/v1/rtc-config")
    def rtc_config(room: Optional[str] = None):
        """ICE servers for WebRTC. A TURN relay (short-lived login) is included only for a real room."""
        exists = False
        if room:
            try:
                rooms.info(room)
                exists = True
            except ProviderError:
                exists = False
        ice = build_ice_servers(settings, exists)
        return {"iceServers": ice, "turn": has_relay(ice), "turnConfigured": bool(settings.turn_urls or settings.turn_url),
                "maxParticipants": settings.max_participants}

    def origin_allowed(ws: WebSocket) -> bool:
        origin = ws.headers.get("origin")
        if not origin:
            return True   # non-browser client; browsers always send Origin
        return urlparse(origin).netloc == ws.headers.get("host", "") or origin in settings.allowed_origins

    async def recv_json(ws: WebSocket) -> dict:
        text = await ws.receive_text()
        if len(text) > 20_000:
            raise ProviderError("message_too_large", "Message too large.", 413)
        try:
            data = json.loads(text)
        except ValueError:
            raise ProviderError("bad_json", "Invalid message.", 400)
        if not isinstance(data, dict):
            raise ProviderError("bad_json", "Invalid message.", 400)
        return data

    @app.websocket("/ws/rooms/{code}")
    async def room_socket(ws: WebSocket, code: str):
        if not origin_allowed(ws):
            await ws.close(code=4403)
            return
        await ws.accept()
        participant = room = None
        try:
            first = await recv_json(ws)
            if first.get("type") != "join":
                raise ProviderError("bad_request", "First message must be 'join'.", 400)
            participant, room = await rooms.join(code, first.get("name", ""), str(first.get("lang", "")), ws.send_json)
            while True:
                await rooms.handle(room.code, participant.id, await recv_json(ws))
        except WebSocketDisconnect:
            pass
        except ProviderError as exc:
            try:
                await ws.send_json({"type": "error", "code": exc.code, "message": exc.message, "fatal": True})
                await ws.close(code=4400)
            except Exception:  # noqa: BLE001
                pass
        finally:
            if participant and room:
                await rooms.leave(room.code, participant.id)

    @app.get("/")
    def index():
        return FileResponse(FRONTEND / "index.html")

    @app.get("/service-worker.js")
    def service_worker():  # must be served from the root scope
        return FileResponse(FRONTEND / "static" / "service-worker.js", media_type="application/javascript")

    app.mount("/static", StaticFiles(directory=str(FRONTEND / "static")), name="static")
    return app


app = create_app()
