"""Short-lived TURN credentials (the "TURN REST API" scheme used by coturn's `use-auth-secret`).

A TURN relay forwards video when two people cannot connect directly (different networks, strict
firewalls). Static passwords would let anyone who sees them use your server for free forever, so
instead the app hands each caller a username that contains an expiry time and a password that is an
HMAC of that username. coturn recomputes the HMAC with the same secret and rejects expired logins.
The shared secret itself is never sent to browsers.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from typing import List, Optional


def make_turn_credentials(secret: str, ttl: int = 3600, now: Optional[float] = None,
                          label: Optional[str] = None) -> dict:
    expiry = int((time.time() if now is None else now) + ttl)
    username = f"{expiry}:{label or secrets.token_hex(4)}"
    digest = hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
    return {"username": username, "credential": base64.b64encode(digest).decode(), "expires": expiry}


def build_ice_servers(settings, room_exists: bool, now: Optional[float] = None) -> List[dict]:
    """STUN is always offered. A TURN relay is offered only for a real, existing room, so strangers
    cannot farm relay bandwidth just by calling the API."""
    ice: List[dict] = []
    if settings.stun_urls:
        ice.append({"urls": list(settings.stun_urls)})
    if room_exists:
        if settings.turn_urls and settings.turn_secret:
            creds = make_turn_credentials(settings.turn_secret, settings.turn_ttl, now)
            ice.append({"urls": list(settings.turn_urls), "username": creds["username"],
                        "credential": creds["credential"]})
        elif settings.turn_url:                      # older static-password setup
            ice.append({"urls": settings.turn_url, "username": settings.turn_username,
                        "credential": settings.turn_credential})
    return ice


def has_relay(ice_servers: List[dict]) -> bool:
    for server in ice_servers:
        urls = server.get("urls", [])
        urls = [urls] if isinstance(urls, str) else urls
        if any(str(u).startswith(("turn:", "turns:")) for u in urls):
            return True
    return False
