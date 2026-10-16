"""Optional shared access code. When ACCESS_CODE is set, creating rooms, translating text/images,
speech and history require it. Guests who only JOIN a call with a room code do not need it."""
from __future__ import annotations

import hmac
from typing import Optional


def check_access(configured: str, provided: Optional[str]) -> bool:
    if not configured:
        return True                       # no code configured = open (fine for localhost)
    return hmac.compare_digest(configured.encode(), (provided or "").encode())
