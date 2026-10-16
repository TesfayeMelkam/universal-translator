"""A standard-library stand-in for ai_services/main.py, used to test the REAL web page in a REAL browser when FastAPI
cannot be installed. It serves the real frontend and uses the real services (languages, translation pipeline, rooms,
vision/OCR, documents, history, quality check). What it does NOT test: FastAPI itself (see tests/test_glue.py for the
route logic and tests/test_api.py for the real FastAPI when installed)."""
import asyncio
import base64
import hashlib
import json
import mimetypes
import struct
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from ai_services.providers.base import ProviderError                      # noqa: E402
from ai_services.providers.translation.mock import MockTranslationProvider  # noqa: E402
from ai_services.providers.vision.mock import MockOCRProvider              # noqa: E402
from ai_services.providers.vision.tesseract import TesseractOCRProvider    # noqa: E402
from ai_services.rooms import RoomManager                                  # noqa: E402
from ai_services.services.documents import translate_document             # noqa: E402
from ai_services.services.history import HistoryStore                      # noqa: E402
from ai_services.services.pipeline import translate_text                   # noqa: E402
from ai_services.services.quality import run_selftest                      # noqa: E402
from ai_services.services.vision_pipeline import translate_image           # noqa: E402
from ai_services.turn import build_ice_servers, has_relay                  # noqa: E402
from shared.languages import as_dicts                                      # noqa: E402

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("application/manifest+json", ".json")


def ws_frame(text: str) -> bytes:
    data, n = text.encode(), len(text.encode())
    head = bytes([0x81]) + (bytes([n]) if n < 126 else b"\x7e" + struct.pack(">H", n) if n < 65536 else b"\x7f" + struct.pack(">Q", n))
    return head + data


def read_frame(rfile):
    h = rfile.read(2)
    if len(h) < 2:
        return None, None
    op, masked, n = h[0] & 0x0F, h[1] & 0x80, h[1] & 0x7F
    if n == 126:
        n = struct.unpack(">H", rfile.read(2))[0]
    elif n == 127:
        n = struct.unpack(">Q", rfile.read(8))[0]
    mask = rfile.read(4) if masked else b""
    data = rfile.read(n)
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return op, data


class Harness:
    def __init__(self):
        self.provider = MockTranslationProvider()
        tess = TesseractOCRProvider()
        self.ocr = tess if tess.available()[0] else MockOCRProvider()
        self.history = HistoryStore(":memory:")
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.rooms = RoomManager(lambda t, s, g: translate_text(self.provider, t, s, g, 2000), max_participants=4, max_large=12,
                                 caption_limit=(200, 10.0))
        self.server = None

    def run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(30)

    def start(self):
        harness = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            # ---------- helpers
            def send_bytes(self, body, status=200, ctype="application/json", headers=None):
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(body)

            def send_json(self, obj, status=200):
                self.send_bytes(json.dumps(obj).encode(), status)

            def body(self):
                return self.rfile.read(int(self.headers.get("Content-Length") or 0))

            def route(self, method):
                u = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                p = u.path
                h = harness
                try:
                    if method == "GET":
                        if p == "/":
                            return self.static(ROOT / "frontend" / "index.html")
                        if p == "/service-worker.js":
                            return self.static(ROOT / "frontend" / "static" / "service-worker.js")
                        if p.startswith("/static/"):
                            return self.static((ROOT / "frontend" / p.lstrip("/")).resolve())
                        if p == "/health":
                            return self.send_json({"status": "ok", "translation_provider": "mock", "mock": True, "model_ready": True,
                                                   "ocr_provider": h.ocr.name, "ocr_mock": h.ocr.is_mock, "ocr_ready": True})
                        if p == "/api/v1/languages":
                            return self.send_json({"languages": as_dicts()})
                        if p == "/api/v1/capabilities":
                            return self.send_json({"languages": len(as_dicts()), "translation": {"provider": "mock", "mock": True},
                                "tts": False, "tts_provider": None, "stt": False, "ffmpeg": False,
                                "ocr": {"provider": h.ocr.name, "mock": h.ocr.is_mock}, "documents": ["txt", "md", "srt", "vtt", "docx", "pdf"],
                                "limits": {"max_chars": 2000, "max_doc_mb": 5, "max_media_mb": 50, "max_participants": 4, "max_large": 12},
                                "livekit": False, "telegram": False, "auth_mode": "off", "signup": True, "access_code": False})
                        if p == "/api/v1/auth/me":
                            return self.send_json({"auth_mode": "off", "signup": True, "access_code": False, "user": None})
                        if p == "/api/v1/translation/status":
                            return self.send_json({"provider": "mock", "mock": True, "ready": True, "detail": "ok", "model": None,
                                                   "languages_in_catalog": len(as_dicts())})
                        if p == "/api/v1/history":
                            return self.send_json({"items": h.history.list(int(q.get("limit", 50)))})
                        if p.startswith("/api/v1/rooms/"):
                            return self.send_json(h.rooms.info(p.rsplit("/", 1)[1]))
                        if p == "/api/v1/rtc-config":
                            ice = build_ice_servers(type("S", (), {"stun_urls": (), "turn_urls": (), "turn_secret": "", "turn_ttl": 60, "turn_url": ""}), False)
                            return self.send_json({"iceServers": ice, "turn": has_relay(ice), "turnConfigured": False, "maxParticipants": 4})
                        if p.startswith("/ws/rooms/"):
                            return self.websocket(p.rsplit("/", 1)[1])
                    elif method == "POST":
                        raw = self.body()
                        js = json.loads(raw) if raw[:1] == b"{" else {}
                        if p == "/api/v1/translate":
                            r = translate_text(h.provider, js["text"], js.get("source", "auto"), js["target"], 2000)
                            r["id"] = h.history.add(r["source"], r["target"], r["source_text"], r["translation"], r["provider"])
                            return self.send_json(r)
                        if p == "/api/v1/vision/translate":
                            r = translate_image(h.ocr, h.provider, js["image"], js["source"], js["target"], 5_000_000, 2000)
                            return self.send_json(r)
                        if p == "/api/v1/rooms":
                            return self.send_json({"code": h.rooms.create_room(q.get("mode", "mesh"))})
                        if p == "/api/v1/documents/translate":
                            res = translate_document(h.provider, raw, q.get("filename", "document.txt"), q["source"], q["target"])
                            from urllib.parse import quote
                            return self.send_bytes(res.data, 200, res.mime, {
                                "Content-Disposition": f"attachment; filename*=UTF-8''{quote(res.filename)}", "X-Doc-Stats": json.dumps(res.stats),
                                "Access-Control-Expose-Headers": "X-Doc-Stats, Content-Disposition"})
                        if p == "/api/v1/translation/selftest":
                            return self.send_json(run_selftest(h.provider, js.get("languages", ["am"]), None, 2000))
                    elif method == "DELETE" and p == "/api/v1/history":
                        h.history.clear()
                        return self.send_json({"ok": True})
                    self.send_json({"error": {"code": "not_found", "message": "Not found"}}, 404)
                except ProviderError as exc:
                    self.send_json({"error": {"code": exc.code, "message": exc.message}}, exc.status)

            def static(self, path):
                if not path.is_file() or ROOT not in path.parents:
                    return self.send_json({"error": {"code": "not_found", "message": "Not found"}}, 404)
                ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
                self.send_bytes(path.read_bytes(), 200, ctype, {"Cache-Control": "no-store"})

            def do_GET(self):
                self.route("GET")

            def do_POST(self):
                self.route("POST")

            def do_DELETE(self):
                self.route("DELETE")

            # ---------- WebSocket (RFC 6455, text frames only)
            def websocket(self, code):
                origin, host = self.headers.get("Origin"), self.headers.get("Host", "")
                if origin and urlparse(origin).netloc != host:
                    return self.send_bytes(b"", 403)
                key = self.headers.get("Sec-WebSocket-Key", "")
                accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
                self.wfile.write(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                                  f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
                self.wfile.flush()
                self.close_connection = True
                lock, sock = threading.Lock(), self.connection

                async def send(payload):
                    with lock:
                        sock.sendall(ws_frame(json.dumps(payload)))

                participant = room = None
                try:
                    op, data = read_frame(self.rfile)
                    first = json.loads(data)
                    participant, room = harness.run(harness.rooms.join(code, first.get("name", ""), str(first.get("lang", "")), send))
                    while True:
                        op, data = read_frame(self.rfile)
                        if op is None or op == 8:
                            break
                        if op == 9:
                            with lock:
                                sock.sendall(bytes([0x8A, 0]))
                        elif op == 1:
                            harness.run(harness.rooms.handle(room.code, participant.id, json.loads(data)))
                except ProviderError as exc:
                    harness.run(send({"type": "error", "code": exc.code, "message": exc.message, "fatal": True}))
                except (OSError, ValueError):
                    pass
                finally:
                    if participant:
                        harness.run(harness.rooms.leave(room.code, participant.id))

        class Quiet(ThreadingHTTPServer):
            def handle_error(self, request, client_address):      # browsers close sockets abruptly; that is normal
                pass

        self.server = Quiet(("127.0.0.1", 0), H)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def stop(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        self.loop.call_soon_threadsafe(self.loop.stop)


if __name__ == "__main__":
    h = Harness()
    print("harness at", h.start())
    threading.Event().wait()
