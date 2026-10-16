import asyncio
import base64
import hashlib
import hmac
import json
import unittest

from ai_services.integrations.telegram import ChatStore, TelegramBot
from ai_services.livekit_token import make_livekit_token
from ai_services.providers.base import ProviderError
from ai_services.providers.translation.mock import MockTranslationProvider
from ai_services.rooms import RoomManager
from ai_services.services.pipeline import translate_text

MOCK = MockTranslationProvider()


def tfn(text, s, t):
    return translate_text(MOCK, text, s, t, 1000)


class LiveKitTokenTests(unittest.TestCase):
    def test_token_is_a_valid_hs256_jwt(self):
        tok = make_livekit_token("APIkey", "s3cret", "ROOM42", "user-1", "Abel", ttl=600, now=1_700_000_000)
        h, p, s = tok.split(".")
        pad = lambda x: x + "=" * (-len(x) % 4)
        self.assertEqual(json.loads(base64.urlsafe_b64decode(pad(h))), {"alg": "HS256", "typ": "JWT"})
        claims = json.loads(base64.urlsafe_b64decode(pad(p)))
        self.assertEqual((claims["iss"], claims["sub"], claims["name"]), ("APIkey", "user-1", "Abel"))
        self.assertEqual((claims["nbf"], claims["exp"]), (1_700_000_000, 1_700_000_600))
        self.assertEqual(claims["video"]["room"], "ROOM42")
        self.assertTrue(claims["video"]["roomJoin"])
        want = base64.urlsafe_b64encode(hmac.new(b"s3cret", f"{h}.{p}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        self.assertEqual(s, want)
        self.assertNotIn("s3cret", tok)


class Conn:
    def __init__(self):
        self.msgs = []
    async def send(self, m):
        self.msgs.append(m)


class LargeRoomTests(unittest.IsolatedAsyncioTestCase):
    async def test_sfu_room_limit_mode_and_no_p2p_signalling(self):
        rm = RoomManager(tfn, max_participants=4, max_large=6)
        code = rm.create_room("sfu")
        self.assertEqual(rm.info(code), {"exists": True, "participants": 0, "full": False, "max": 6, "mode": "sfu"})
        conns = [Conn() for _ in range(6)]
        ps = [(await rm.join(code, f"P{i}", "en", c.send))[0] for i, c in enumerate(conns)]
        self.assertEqual(conns[0].msgs[0]["mode"], "sfu")
        with self.assertRaises(ProviderError) as cm:
            await rm.join(code, "late", "en", Conn().send)
        self.assertEqual(cm.exception.code, "room_full")
        await rm.handle(code, ps[0].id, {"type": "signal", "to": ps[1].id, "data": {"candidate": None}})
        self.assertEqual(conns[0].msgs[-1]["code"], "bad_signal")
        await rm.handle(code, ps[0].id, {"type": "caption", "text": "Hello"})   # captions still work
        self.assertEqual(len([m for m in conns[3].msgs if m["type"] == "caption"]), 1)

    def test_mesh_default_and_bad_mode(self):
        rm = RoomManager(tfn)
        self.assertEqual(rm.info(rm.create_room())["mode"], "mesh")
        with self.assertRaises(ProviderError):
            rm.create_room("weird")


class TelegramTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.t = [1000.0]
        self.bot = TelegramBot(tfn, lambda c, m: self.sent.append((c, m)) or True, ChatStore(),
                               rate=(5, 60.0), clock=lambda: self.t[0])

    def msg(self, text, chat=7, kind="private"):
        return {"update_id": 1, "message": {"chat": {"id": chat, "type": kind}, "text": text}}

    def test_flow_set_language_and_translate(self):
        self.bot.handle_update(self.msg("/start"))
        self.assertIn("/lang", self.sent[-1][1])
        self.bot.handle_update(self.msg("/lang Amharic"))
        self.assertIn("Amharic", self.sent[-1][1])
        self.bot.handle_update(self.msg("Hello"))
        self.assertTrue(self.sent[-1][1].startswith("ሰላም"))
        self.assertIn("demo mode", self.sent[-1][1])                      # mock must be disclosed
        self.bot.handle_update(self.msg("/lang@MyBot fr"))
        self.bot.handle_update(self.msg("Hello"))
        self.assertTrue(self.sent[-1][1].startswith("Bonjour"))

    def test_settings_are_per_chat(self):
        self.bot.handle_update(self.msg("/lang am", chat=1))
        self.bot.handle_update(self.msg("/lang fr", chat=2))
        self.bot.handle_update(self.msg("Hello", chat=1))
        self.bot.handle_update(self.msg("Hello", chat=2))
        self.assertTrue(self.sent[-2][1].startswith("ሰላም") and self.sent[-1][1].startswith("Bonjour"))

    def test_bad_input_gets_friendly_answers(self):
        self.bot.handle_update(self.msg("/lang klingon"))
        self.assertIn("Unknown language", self.sent[-1][1])
        self.bot.handle_update(self.msg("/lang auto"))
        self.assertIn("Unknown language", self.sent[-1][1])
        self.bot.handle_update(self.msg("x" * 1001))
        self.assertIn("at most", self.sent[-1][1])
        self.bot.handle_update({"message": {"chat": {"id": 7, "type": "private"}, "photo": []}})
        self.assertIn("text messages only", self.sent[-1][1])
        self.bot.handle_update(self.msg("/nope"))
        self.assertIn("Unknown command", self.sent[-1][1])

    def test_same_language_and_groups(self):
        self.bot.handle_update(self.msg("/lang en"))
        self.bot.handle_update(self.msg("Hello"))                          # detected as English, target English
        self.assertIn("same", self.sent[-1][1].lower())
        n = len(self.sent)
        self.bot.handle_update(self.msg("Hello there everyone", chat=-5, kind="group"))
        self.assertEqual(len(self.sent), n)                                # silent in groups
        self.bot.handle_update(self.msg("/help", chat=-5, kind="group"))
        self.assertEqual(len(self.sent), n + 1)                            # but commands work

    def test_rate_limit_and_junk_updates(self):
        for _ in range(5):
            self.bot.handle_update(self.msg("/help"))
        self.bot.handle_update(self.msg("/help"))
        self.assertIn("Slow down", self.sent[-1][1])
        self.t[0] += 61
        self.bot.handle_update(self.msg("/help"))
        self.assertIn("/lang", self.sent[-1][1])
        n = len(self.sent)
        for junk in [None, {}, {"message": None}, {"message": {"text": "hi"}}, {"message": {"chat": {"id": "x"}, "text": "hi"}}]:
            self.assertIsNone(self.bot.handle_update(junk))
        self.assertEqual(len(self.sent), n)


if __name__ == "__main__":
    unittest.main()
