"""LiveKit access tokens (HS256 JWT) so browsers can join a LiveKit media server for LARGE calls.
Mesh calls (everyone connected to everyone) stop being practical above ~4-6 people; an SFU server
(LiveKit) receives each person's video once and forwards it. Self-host: see deploy/livekit.yaml."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Optional


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_livekit_token(api_key: str, api_secret: str, room: str, identity: str, name: str = "",
                       ttl: int = 3600, now: Optional[float] = None) -> str:
    t = int(time.time() if now is None else now)
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    payload = _b64(json.dumps({
        "iss": api_key, "sub": identity, "name": name, "nbf": t, "exp": t + ttl,
        "video": {"room": room, "roomJoin": True, "canPublish": True, "canSubscribe": True, "canPublishData": True},
    }, separators=(",", ":")).encode())
    sig = hmac.new(api_secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64(sig)}"
