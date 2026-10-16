"""Room/caption logic tests (standard library only, fake connections)."""
import unittest

from ai_services.providers.base import ProviderError
from ai_services.providers.translation.mock import MockTranslationProvider
from ai_services.rooms import RoomManager, clean_name, normalize_code
from ai_services.services.pipeline import translate_text

MOCK = MockTranslationProvider()


def translate(text, s, t):
    return translate_text(MOCK, text, s, t, 1000)


class Conn:
    def __init__(self):
        self.msgs = []

    async def send(self, m):
        self.msgs.append(m)

    def of(self, kind):
        return [m for m in self.msgs if m["type"] == kind]


class Clock:
    t = 0.0
    def __call__(self):
        return self.t


class GroupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []

        def counting(text, s, t):
            self.calls.append((s, t))
            return translate(text, s, t)
        self.rm = RoomManager(counting, max_participants=3)
        self.code = self.rm.create_room()
        self.c = [Conn(), Conn(), Conn(), Conn()]

    async def three(self, langs=("en", "am", "fr")):
        ps = []
        for conn, lang, name in zip(self.c, langs, "ABC"):
            p, _ = await self.rm.join(self.code, name, lang, conn.send)
            ps.append(p)
        return ps

    async def test_three_can_join_fourth_rejected(self):
        await self.three()
        with self.assertRaises(ProviderError) as cm:
            await self.rm.join(self.code, "D", "en", self.c[3].send)
        self.assertEqual(cm.exception.code, "room_full")
        self.assertEqual(self.rm.info(self.code)["max"], 3)
        self.assertTrue(self.rm.info(self.code)["full"])

    async def test_newcomer_sees_everyone_and_all_are_told(self):
        a, b, c = await self.three()
        self.assertEqual([p["name"] for p in self.c[2].of("joined")[0]["peers"]], ["A", "B"])
        self.assertEqual([m["peer"]["id"] for m in self.c[0].of("peer_joined")], [b.id, c.id])
        self.assertEqual([m["peer"]["id"] for m in self.c[1].of("peer_joined")], [c.id])

    async def test_signal_goes_only_to_addressed_peer(self):
        a, b, c = await self.three()
        await self.rm.handle(self.code, a.id, {"type": "signal", "to": c.id,
                                               "data": {"sdp": {"type": "offer", "sdp": "x"}}})
        self.assertEqual(len(self.c[2].of("signal")), 1)
        self.assertEqual(self.c[2].of("signal")[0]["from"], a.id)
        self.assertEqual(self.c[1].of("signal"), [])
        self.assertEqual(self.c[0].of("signal"), [])

    async def test_signal_to_unknown_or_self_rejected(self):
        a, b, c = await self.three()
        for to in ["nobody", a.id, None]:
            await self.rm.handle(self.code, a.id, {"type": "signal", "to": to, "data": {"candidate": None}})
        self.assertEqual([m["code"] for m in self.c[0].of("error")], ["bad_signal"] * 3)

    async def test_each_listener_gets_own_language(self):
        a, b, c = await self.three(("en", "am", "fr"))
        await self.rm.handle(self.code, a.id, {"type": "caption", "text": "Hello"})
        self.assertEqual(self.c[1].of("caption")[0]["translated"], "ሰላም")
        self.assertEqual(self.c[2].of("caption")[0]["translated"], "Bonjour")
        self.assertEqual(self.c[0].of("caption")[0:0], [])

    async def test_same_target_language_translated_once(self):
        a, b, c = await self.three(("en", "fr", "fr"))
        await self.rm.handle(self.code, a.id, {"type": "caption", "text": "Hello"})
        self.assertEqual(self.calls, [("en", "fr")])
        self.assertEqual(self.c[1].of("caption")[0]["translated"], "Bonjour")
        self.assertEqual(self.c[2].of("caption")[0]["translated"], "Bonjour")

    async def test_failure_reports_once_and_still_delivers(self):
        def boom(*_):
            raise ProviderError("model_unavailable", "down", 503)
        self.rm.translate = boom
        a, b, c = await self.three(("en", "fr", "fr"))
        await self.rm.handle(self.code, a.id, {"type": "caption", "text": "Hi"})
        self.assertEqual(len(self.c[0].of("error")), 1)
        self.assertTrue(self.c[1].of("caption")[0]["translation_failed"])
        self.assertEqual(self.c[2].of("caption")[0]["original"], "Hi")

    async def test_middle_person_leaving_keeps_others_connected(self):
        a, b, c = await self.three()
        await self.rm.leave(self.code, b.id)
        self.assertEqual(self.c[0].of("peer_left")[0]["id"], b.id)
        self.assertEqual(self.c[2].of("peer_left")[0]["id"], b.id)
        self.assertIn(self.code, self.rm.rooms)
        await self.rm.handle(self.code, a.id, {"type": "caption", "text": "Hello"})
        self.assertEqual(len(self.c[2].of("caption")), 1)
        self.assertEqual(self.c[1].of("caption"), [])


class RoomTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = Clock()
        self.rm = RoomManager(translate, max_rooms=2, max_participants=2, clock=self.clock, caption_limit=(3, 10.0))
        self.code = self.rm.create_room()
        self.a, self.b = Conn(), Conn()

    async def two(self, la="en", lb="am"):
        pa, _ = await self.rm.join(self.code, "Abel", la, self.a.send)
        pb, _ = await self.rm.join(self.code, "Sara", lb, self.b.send)
        return pa, pb

    def test_code_format(self):
        self.assertEqual(len(self.code), 6)
        self.assertEqual(normalize_code(" " + self.code.lower() + " "), self.code)
        for bad in ["", "ABC", "ABCDEF1", "ABCDE0", "ab cd!"]:
            with self.assertRaises(ProviderError):
                normalize_code(bad)

    async def test_join_notifies_peers(self):
        pa, pb = await self.two()
        self.assertEqual(self.a.of("joined")[0]["peers"], [])
        self.assertEqual(self.b.of("joined")[0]["peers"][0]["name"], "Abel")
        self.assertEqual(self.a.of("peer_joined")[0]["peer"]["id"], pb.id)

    async def test_room_full_and_missing(self):
        await self.two()
        with self.assertRaises(ProviderError) as cm:
            await self.rm.join(self.code, "X", "en", Conn().send)
        self.assertEqual(cm.exception.code, "room_full")
        with self.assertRaises(ProviderError) as cm:
            await self.rm.join("AAAAAA", "X", "en", Conn().send)
        self.assertEqual(cm.exception.code, "room_not_found")

    async def test_bad_language_rejected(self):
        with self.assertRaises(ProviderError) as cm:
            await self.rm.join(self.code, "X", "xx", Conn().send)
        self.assertEqual(cm.exception.code, "unknown_language")

    async def test_signal_relay_and_validation(self):
        pa, pb = await self.two()
        offer = {"sdp": {"type": "offer", "sdp": "v=0..."}}
        await self.rm.handle(self.code, pa.id, {"type": "signal", "to": pb.id, "data": offer, "evil": "x"})
        got = self.b.of("signal")[0]
        self.assertEqual(got["from"], pa.id)
        self.assertEqual(got["data"], offer)
        await self.rm.handle(self.code, pb.id, {"type": "signal", "to": pa.id, "data": {"candidate": {"candidate": "c"}}})
        self.assertEqual(len(self.a.of("signal")), 1)
        await self.rm.handle(self.code, pa.id, {"type": "signal", "to": pb.id, "data": {"sdp": {"type": "evil", "sdp": "x"}}})
        self.assertEqual(self.a.of("error")[-1]["code"], "bad_signal")
        self.assertEqual(len(self.b.of("signal")), 1)   # nothing leaked

    async def test_caption_translated_to_peer_language(self):
        pa, pb = await self.two("en", "am")
        await self.rm.handle(self.code, pa.id, {"type": "caption", "text": "Hello"})
        cap = self.b.of("caption")[0]
        self.assertEqual((cap["original"], cap["translated"], cap["target"]), ("Hello", "ሰላም", "am"))
        self.assertTrue(cap["is_mock"])
        self.assertEqual(self.a.of("caption_self")[0]["text"], "Hello")
        self.assertEqual(self.a.of("caption"), [])

    async def test_same_language_no_translation(self):
        pa, pb = await self.two("en", "en")
        await self.rm.handle(self.code, pa.id, {"type": "caption", "text": "Good luck"})
        cap = self.b.of("caption")[0]
        self.assertEqual(cap["translated"], "Good luck")
        self.assertFalse(cap["is_mock"])

    async def test_translation_failure_still_delivers_original(self):
        def boom(*_):
            raise ProviderError("model_unavailable", "model down", 503)
        self.rm.translate = boom
        pa, pb = await self.two("en", "am")
        await self.rm.handle(self.code, pa.id, {"type": "caption", "text": "Hello"})
        cap = self.b.of("caption")[0]
        self.assertTrue(cap["translation_failed"])
        self.assertIsNone(cap["translated"])
        self.assertEqual(cap["original"], "Hello")
        self.assertEqual(self.a.of("error")[0]["code"], "model_unavailable")

    async def test_caption_rate_limit_and_length(self):
        pa, pb = await self.two()
        for _ in range(3):
            await self.rm.handle(self.code, pa.id, {"type": "caption", "text": "hello"})
        await self.rm.handle(self.code, pa.id, {"type": "caption", "text": "hello"})
        self.assertEqual(self.a.of("error")[-1]["code"], "rate_limited")
        self.clock.t += 11
        await self.rm.handle(self.code, pa.id, {"type": "caption", "text": "x" * 1001})
        self.assertEqual(self.a.of("error")[-1]["code"], "text_too_long")

    async def test_language_change(self):
        pa, pb = await self.two("en", "am")
        await self.rm.handle(self.code, pb.id, {"type": "lang", "lang": "fr"})
        self.assertEqual(self.a.of("peer_lang")[0]["lang"], "fr")
        await self.rm.handle(self.code, pa.id, {"type": "caption", "text": "Hello"})
        self.assertEqual(self.b.of("caption")[0]["translated"], "Bonjour")

    async def test_unknown_message_and_ping(self):
        pa, _ = await self.two()
        await self.rm.handle(self.code, pa.id, {"type": "nope"})
        self.assertEqual(self.a.of("error")[-1]["code"], "unknown_message")
        await self.rm.handle(self.code, pa.id, {"type": "ping"})
        self.assertEqual(len(self.a.of("pong")), 1)

    async def test_leave_notifies_and_cleans_up(self):
        pa, pb = await self.two()
        await self.rm.leave(self.code, pa.id)
        self.assertEqual(self.b.of("peer_left")[0]["id"], pa.id)
        self.assertIn(self.code, self.rm.rooms)
        await self.rm.leave(self.code, pb.id)
        self.assertNotIn(self.code, self.rm.rooms)

    async def test_dead_socket_does_not_break_other_side(self):
        async def dead(_):
            raise RuntimeError("closed")
        await self.rm.join(self.code, "A", "en", dead)
        pb, _ = await self.rm.join(self.code, "B", "am", self.b.send)
        await self.rm.handle(self.code, pb.id, {"type": "caption", "text": "ሰላም"})
        self.assertEqual(len(self.b.of("caption_self")), 1)

    async def test_room_limit_and_unused_expiry(self):
        self.rm.create_room()
        with self.assertRaises(ProviderError) as cm:
            self.rm.create_room()
        self.assertEqual(cm.exception.code, "rooms_full")
        self.clock.t += 601
        self.rm.create_room()   # expired empty rooms were purged

    def test_name_cleaning(self):
        self.assertEqual(clean_name("  \x00Abe\nl "), "Abel")
        self.assertEqual(clean_name(""), "Guest")
        self.assertEqual(len(clean_name("x" * 100)), 30)


class GroupTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.calls = []

        def counting(text, s, t):
            self.calls.append((s, t))
            return translate(text, s, t)

        self.rm = RoomManager(counting, max_participants=4)
        self.code = self.rm.create_room()
        self.conns = [Conn() for _ in range(4)]
        self.p = []

    async def join(self, n, langs):
        for i in range(n):
            p, _ = await self.rm.join(self.code, f"P{i}", langs[i], self.conns[i].send)
            self.p.append(p)

    async def test_four_join_fifth_refused_and_everyone_told(self):
        await self.join(4, ["en", "am", "fr", "es"])
        self.assertEqual(len(self.conns[3].of("joined")[0]["peers"]), 3)
        self.assertEqual(self.conns[3].of("joined")[0]["max"], 4)
        self.assertEqual(len(self.conns[0].of("peer_joined")), 3)
        with self.assertRaises(ProviderError) as cm:
            await self.rm.join(self.code, "P5", "en", Conn().send)
        self.assertEqual(cm.exception.code, "room_full")
        self.assertTrue(self.rm.info(self.code)["full"])

    async def test_signal_goes_only_to_the_named_peer(self):
        await self.join(3, ["en", "am", "fr"])
        offer = {"sdp": {"type": "offer", "sdp": "v=0"}}
        await self.rm.handle(self.code, self.p[0].id, {"type": "signal", "to": self.p[2].id, "data": offer})
        self.assertEqual(len(self.conns[2].of("signal")), 1)
        self.assertEqual(self.conns[2].of("signal")[0]["from"], self.p[0].id)
        self.assertEqual(self.conns[1].of("signal"), [])
        self.assertEqual(self.conns[0].of("signal"), [])

    async def test_bad_signal_targets(self):
        await self.join(2, ["en", "am"])
        for to in [None, "nobody", self.p[0].id, 123]:
            await self.rm.handle(self.code, self.p[0].id, {"type": "signal", "to": to, "data": {"candidate": None}})
            self.assertEqual(self.conns[0].of("error")[-1]["code"], "bad_target")
        self.assertEqual(self.conns[1].of("signal"), [])

    async def test_caption_reaches_everyone_in_their_language(self):
        await self.join(4, ["en", "am", "fr", "fr"])
        await self.rm.handle(self.code, self.p[0].id, {"type": "caption", "text": "Hello"})
        self.assertEqual(self.conns[1].of("caption")[0]["translated"], "ሰላም")
        self.assertEqual(self.conns[2].of("caption")[0]["translated"], "Bonjour")
        self.assertEqual(self.conns[3].of("caption")[0]["translated"], "Bonjour")
        self.assertEqual(self.conns[0].of("caption"), [])
        self.assertEqual(sorted(self.calls), [("en", "am"), ("en", "fr")])   # French translated once, not twice

    async def test_same_language_members_get_original_untranslated(self):
        await self.join(3, ["en", "en", "am"])
        await self.rm.handle(self.code, self.p[0].id, {"type": "caption", "text": "Thank you"})
        self.assertEqual(self.conns[1].of("caption")[0]["translated"], "Thank you")
        self.assertEqual(self.conns[2].of("caption")[0]["translated"], "አመሰግናለሁ")
        self.assertEqual(self.calls, [("en", "am")])

    async def test_one_failed_language_does_not_block_others(self):
        def flaky(text, s, t):
            if t == "fr":
                raise ProviderError("model_unavailable", "down", 503)
            return translate(text, s, t)
        self.rm.translate = flaky
        await self.join(3, ["en", "am", "fr"])
        await self.rm.handle(self.code, self.p[0].id, {"type": "caption", "text": "Hello"})
        self.assertEqual(self.conns[1].of("caption")[0]["translated"], "ሰላም")
        bad = self.conns[2].of("caption")[0]
        self.assertTrue(bad["translation_failed"])
        self.assertEqual(bad["original"], "Hello")
        self.assertEqual(len(self.conns[0].of("error")), 1)

    async def test_member_leaves_room_continues(self):
        await self.join(3, ["en", "am", "fr"])
        await self.rm.leave(self.code, self.p[1].id)
        self.assertEqual(self.conns[0].of("peer_left")[0]["id"], self.p[1].id)
        self.assertEqual(self.conns[2].of("peer_left")[0]["id"], self.p[1].id)
        self.assertIn(self.code, self.rm.rooms)
        await self.rm.handle(self.code, self.p[0].id, {"type": "caption", "text": "Hello"})
        self.assertEqual(len(self.conns[2].of("caption")), 1)
        self.assertEqual(self.conns[1].of("caption"), [])


class InterimTests(unittest.IsolatedAsyncioTestCase):
    async def test_interim_relayed_untranslated_and_rate_limited(self):
        rm = RoomManager(translate, max_participants=3)
        code = rm.create_room()
        a, b, c = Conn(), Conn(), Conn()
        pa, _ = await rm.join(code, "A", "en", a.send)
        pb, _ = await rm.join(code, "B", "am", b.send)
        pc, _ = await rm.join(code, "C", "fr", c.send)
        await rm.handle(code, pa.id, {"type": "interim", "text": "hel"})
        for conn in (b, c):
            m = conn.of("interim")[0]
            self.assertEqual((m["text"], m["lang"], m["name"]), ("hel", "en", "A"))
        self.assertEqual(a.of("interim"), [])                       # never echoed to the speaker
        self.assertEqual(b.of("caption"), [])                       # interim is not a caption
        for _ in range(60):
            await rm.handle(code, pa.id, {"type": "interim", "text": "x"})
        self.assertLessEqual(len(b.of("interim")), 25)              # preview floods are dropped
        self.assertEqual(a.of("error"), [])                         # ...silently, no error spam
        await rm.handle(code, pa.id, {"type": "interim", "text": "y" * 1000})
        self.assertTrue(all(len(m["text"]) <= 300 for m in b.of("interim")))


class SimClient:
    """Follows the same handshake rules as frontend/static/js/video-call.js (no real video)."""
    def __init__(self, rm, code, name, lang):
        self.rm, self.code, self.name, self.lang = rm, code, name, lang
        self.me = None
        self.my_id = None      # learned from the 'joined' message, exactly like the browser does
        self.linked = {}       # peer id -> "offer-sent" | "answered" | "connected"
        self.log = []

    async def send(self, m):
        self.log.append(m)
        if m["type"] == "joined":
            self.my_id = m["id"]
        elif m["type"] == "peer_joined":                      # we were here first: we make the offer
            self.linked[m["peer"]["id"]] = "offer-sent"
            await self.rm.handle(self.code, self.my_id, {"type": "signal", "to": m["peer"]["id"],
                                                         "data": {"sdp": {"type": "offer", "sdp": "x"}}})
        elif m["type"] == "signal" and "sdp" in m["data"]:
            if m["data"]["sdp"]["type"] == "offer":         # we answer whoever offered
                self.linked[m["from"]] = "answered"
                await self.rm.handle(self.code, self.my_id, {"type": "signal", "to": m["from"],
                                                             "data": {"sdp": {"type": "answer", "sdp": "y"}}})
            else:
                self.linked[m["from"]] = "connected"

    async def join(self):
        self.me, _ = await self.rm.join(self.code, self.name, self.lang, self.send)


class MeshHandshakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_people_form_six_links(self):
        rm = RoomManager(translate, max_participants=4)
        code = rm.create_room()
        clients = [SimClient(rm, code, f"P{i}", "en") for i in range(4)]
        for c in clients:
            await c.join()
        ids = [c.my_id for c in clients]
        for i, a in enumerate(clients):
            for j, b in enumerate(clients):
                if i < j:   # earlier joiner offers, later joiner answers
                    self.assertEqual(a.linked[ids[j]], "connected", (i, j))
                    self.assertEqual(b.linked[ids[i]], "answered", (i, j))
        offers = sum(1 for c in clients for m in c.log
                     if m["type"] == "signal" and m["data"]["sdp"]["type"] == "offer")
        self.assertEqual(offers, 6)          # 4 people -> 6 links, never duplicated
        self.assertEqual(sum(len(c.linked) for c in clients), 12)

    async def test_rejoin_after_leaving_relinks(self):
        rm = RoomManager(translate, max_participants=3)
        code = rm.create_room()
        a, b, c = (SimClient(rm, code, n, "en") for n in "ABC")
        await a.join(); await b.join(); await c.join()
        await rm.leave(code, b.my_id)
        b2 = SimClient(rm, code, "B2", "en")
        await b2.join()
        self.assertEqual(a.linked[b2.my_id], "connected")
        self.assertEqual(c.linked[b2.my_id], "connected")


if __name__ == "__main__":
    unittest.main()
