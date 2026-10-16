"""Call rooms (2..N people, full-mesh WebRTC): signalling relay + translated live captions.

Pure asyncio logic (no FastAPI imports) so it can be unit-tested with fake connections.
Video/audio travel peer-to-peer (WebRTC); this server only relays small signalling messages and
translates caption text. Nothing is recorded or stored: rooms live in memory and vanish when empty.
"""
from __future__ import annotations

import asyncio
import re
import secrets
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, Optional

from shared.languages import get_language
from .providers.base import ProviderError

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no I, O, 0, 1 (easy to read aloud)
CODE_LEN = 6
_CODE_RE = re.compile(rf"^[{ALPHABET}]{{{CODE_LEN}}}$")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")

Send = Callable[[dict], Awaitable[None]]
Translate = Callable[[str, str, str], dict]


@dataclass
class Participant:
    id: str
    name: str
    lang: str
    send: Send
    caption_times: deque = field(default_factory=deque)
    interim_times: deque = field(default_factory=deque)

    def public(self) -> dict:
        return {"id": self.id, "name": self.name, "lang": self.lang}


@dataclass
class Room:
    code: str
    created: float
    participants: Dict[str, Participant] = field(default_factory=dict)
    mode: str = "mesh"                    # mesh = peer-to-peer video | sfu = large call through a media server


def normalize_code(code: str) -> str:
    code = (code or "").strip().upper()
    if not _CODE_RE.match(code):
        raise ProviderError("bad_room_code", "Room codes are 6 letters/numbers.", 422)
    return code


def clean_name(name: str) -> str:
    name = _CTRL.sub("", str(name or "")).strip()[:30]
    return name or "Guest"


class RoomManager:
    def __init__(self, translate: Optional[Translate], max_rooms: int = 50, max_participants: int = 4, max_large: int = 12,
                 unused_ttl: float = 600, max_chars: int = 1000,
                 caption_limit: tuple = (30, 30.0), clock: Callable[[], float] = time.monotonic):
        self.translate = translate
        self.max_rooms = max_rooms
        self.max_participants = max_participants
        self.max_large = max_large
        self.unused_ttl = unused_ttl
        self.max_chars = max_chars
        self.caption_limit = caption_limit      # (messages, seconds)
        self.clock = clock
        self.rooms: Dict[str, Room] = {}

    # ---- room lifecycle -------------------------------------------------
    def _purge(self) -> None:
        now = self.clock()
        for code in [c for c, r in self.rooms.items() if not r.participants and now - r.created > self.unused_ttl]:
            del self.rooms[code]

    def limit(self, room: Room) -> int:
        return self.max_large if room.mode == "sfu" else self.max_participants

    def create_room(self, mode: str = "mesh") -> str:
        if mode not in ("mesh", "sfu"):
            raise ProviderError("bad_mode", "Unknown room type.", 422)
        self._purge()
        if len(self.rooms) >= self.max_rooms:
            raise ProviderError("rooms_full", "Too many active rooms. Try again later.", 503)
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN))
            if code not in self.rooms:
                break
        self.rooms[code] = Room(code, self.clock(), mode=mode)
        return code

    def info(self, code: str) -> dict:
        room = self._get(normalize_code(code))
        n = len(room.participants)
        return {"exists": True, "participants": n, "full": n >= self.limit(room), "max": self.limit(room),
                "mode": room.mode}

    def _get(self, code: str) -> Room:
        room = self.rooms.get(code)
        if not room:
            raise ProviderError("room_not_found", "That room does not exist or has ended.", 404)
        return room

    # ---- join / leave ---------------------------------------------------
    async def join(self, code: str, name: str, lang: str, send: Send) -> tuple[Participant, Room]:
        room = self._get(normalize_code(code))
        if not get_language(lang):
            raise ProviderError("unknown_language", "Please choose a valid language.", 422)
        if len(room.participants) >= self.limit(room):
            raise ProviderError("room_full", f"This call is full ({self.limit(room)} people maximum).", 409)
        p = Participant(secrets.token_hex(4), clean_name(name), lang.strip().lower(), send)
        others = [o.public() for o in room.participants.values()]
        room.participants[p.id] = p
        await self._safe(p, {"type": "joined", "id": p.id, "room": room.code, "you": p.public(), "peers": others,
                              "max": self.limit(room), "mode": room.mode})
        await self._broadcast(room, p.id, {"type": "peer_joined", "peer": p.public()})
        return p, room

    async def leave(self, code: str, pid: str) -> None:
        room = self.rooms.get(code)
        if not room or pid not in room.participants:
            return
        del room.participants[pid]
        await self._broadcast(room, pid, {"type": "peer_left", "id": pid})
        if not room.participants:
            del self.rooms[code]

    # ---- messages -------------------------------------------------------
    async def handle(self, code: str, pid: str, msg: dict) -> None:
        room = self.rooms.get(code)
        if not room or pid not in room.participants:
            return
        me = room.participants[pid]
        try:
            kind = msg.get("type")
            if kind == "signal":
                await self._signal(room, me, msg)
            elif kind == "caption":
                await self._caption(room, me, msg.get("text"))
            elif kind == "interim":
                await self._interim(room, me, msg.get("text"))
            elif kind == "lang":
                lang = str(msg.get("lang", "")).strip().lower()
                if not get_language(lang):
                    raise ProviderError("unknown_language", "Unknown language.", 422)
                me.lang = lang
                await self._broadcast(room, me.id, {"type": "peer_lang", "id": me.id, "lang": lang})
            elif kind == "ping":
                await self._safe(me, {"type": "pong"})
            else:
                raise ProviderError("unknown_message", "Unknown message type.", 400)
        except ProviderError as exc:
            await self._safe(me, {"type": "error", "code": exc.code, "message": exc.message})

    async def _signal(self, room: Room, me: Participant, msg: dict) -> None:
        """Relay WebRTC setup data to ONE named peer (group calls are a mesh of 1-to-1 links)."""
        if room.mode == "sfu":
            raise ProviderError("bad_signal", "This is a large call: video goes through the media server.", 400)
        to = msg.get("to")
        target = room.participants.get(to) if isinstance(to, str) else None
        if target is None or target.id == me.id:
            raise ProviderError("bad_target", "That person is not in the call.", 404)
        data = msg.get("data")
        if not isinstance(data, dict):
            raise ProviderError("bad_signal", "Invalid signalling data.", 400)
        sdp, cand = data.get("sdp"), data.get("candidate", "missing")
        if isinstance(sdp, dict) and sdp.get("type") in ("offer", "answer") and isinstance(sdp.get("sdp"), str):
            clean = {"sdp": {"type": sdp["type"], "sdp": sdp["sdp"]}}
        elif cand is None or isinstance(cand, dict):
            clean = {"candidate": cand}
        else:
            raise ProviderError("bad_signal", "Invalid signalling data.", 400)
        await self._safe(target, {"type": "signal", "from": me.id, "data": clean})

    async def _interim(self, room: Room, me: Participant, text) -> None:
        """Words still being spoken. Relayed as-is (NOT translated: that would be slow and costly) so others
        can see someone is talking; the translated caption follows when the sentence ends."""
        text = str(text or "")[:300]
        now = self.clock()
        while me.interim_times and now - me.interim_times[0] > 5.0:
            me.interim_times.popleft()
        if len(me.interim_times) >= 25:
            return                                    # too chatty: silently drop (it is only a preview)
        me.interim_times.append(now)
        await self._broadcast(room, me.id, {"type": "interim", "from": me.id, "name": me.name,
                                            "text": text, "lang": me.lang})

    async def _caption(self, room: Room, me: Participant, text) -> None:
        text = str(text or "").strip()
        if not text:
            return
        if len(text) > self.max_chars:
            raise ProviderError("text_too_long", f"Caption longer than {self.max_chars} characters.", 413)
        limit, window = self.caption_limit
        now = self.clock()
        while me.caption_times and now - me.caption_times[0] > window:
            me.caption_times.popleft()
        if len(me.caption_times) >= limit:
            raise ProviderError("rate_limited", "Too many captions too fast.", 429)
        me.caption_times.append(now)

        await self._safe(me, {"type": "caption_self", "text": text, "lang": me.lang})
        others = [o for o in room.participants.values() if o.id != me.id]
        target_lang = {o.id: o.lang for o in others}      # snapshot: a language change mid-translation can't break this caption
        src_lang = me.lang

        async def one(lang: str):
            try:
                if self.translate is None:
                    raise ProviderError("no_translator", "No translator configured.", 503)
                res = await asyncio.to_thread(self.translate, text, src_lang, lang)
                return lang, (res["translation"], bool(res.get("is_mock")), None)
            except ProviderError as exc:
                return lang, (None, False, exc)
            except Exception:  # noqa: BLE001
                return lang, (None, False, ProviderError("translation_failed", "Translation failed.", 502))

        langs = sorted({l for l in target_lang.values() if l != src_lang})
        results = dict(await asyncio.gather(*(one(l) for l in langs)))
        for code, exc in {v[2].code: v[2] for v in results.values() if v[2]}.items():
            await self._safe(me, {"type": "error", "code": code, "message": exc.message})
        for other in others:
            lang = target_lang[other.id]
            out = {"type": "caption", "from": me.id, "name": me.name, "original": text, "source": src_lang,
                   "target": lang, "translated": text, "is_mock": False, "translation_failed": False}
            if lang != src_lang:
                tr, mock, exc = results[lang]
                out["translated"], out["is_mock"], out["translation_failed"] = tr, mock, exc is not None
            await self._safe(other, out)

    # ---- helpers --------------------------------------------------------
    async def _broadcast(self, room: Room, exclude: str, payload: dict) -> None:
        for p in list(room.participants.values()):
            if p.id != exclude:
                await self._safe(p, payload)

    @staticmethod
    async def _safe(p: Participant, payload: dict) -> None:
        try:
            await p.send(payload)
        except Exception:  # noqa: BLE001 - a dead socket must not break the other person's call
            pass
