"""TURN credentials and access-code tests (standard library only)."""
import base64
import hashlib
import hmac
import unittest
from dataclasses import dataclass

from ai_services.security import check_access
from ai_services.turn import build_ice_servers, has_relay, make_turn_credentials


@dataclass
class S:
    stun_urls: tuple = ("stun:stun.example.org:3478",)
    turn_url: str = ""
    turn_username: str = ""
    turn_credential: str = ""
    turn_urls: tuple = ("turn:turn.example.org:3478?transport=udp", "turn:turn.example.org:3478?transport=tcp")
    turn_secret: str = "s3cret"
    turn_ttl: int = 600


class TurnTests(unittest.TestCase):
    def test_credentials_match_coturn_scheme(self):
        c = make_turn_credentials("s3cret", ttl=600, now=1_000_000, label="abcd")
        self.assertEqual(c["username"], "1000600:abcd")
        want = base64.b64encode(hmac.new(b"s3cret", b"1000600:abcd", hashlib.sha1).digest()).decode()
        self.assertEqual(c["credential"], want)
        self.assertEqual(c["expires"], 1_000_600)

    def test_each_login_is_unique_and_secret_never_leaks(self):
        a, b = make_turn_credentials("s3cret"), make_turn_credentials("s3cret")
        self.assertNotEqual(a["username"], b["username"])
        self.assertNotIn("s3cret", str(build_ice_servers(S(), True)))

    def test_turn_only_for_existing_room(self):
        self.assertFalse(has_relay(build_ice_servers(S(), room_exists=False)))
        ice = build_ice_servers(S(), room_exists=True, now=1000)
        self.assertTrue(has_relay(ice))
        relay = [s for s in ice if "username" in s][0]
        self.assertTrue(relay["username"].startswith("1600:"))      # now + ttl
        self.assertEqual(len(relay["urls"]), 2)

    def test_stun_always_there_and_can_be_disabled(self):
        self.assertEqual(build_ice_servers(S(), False)[0]["urls"], ["stun:stun.example.org:3478"])
        self.assertEqual(build_ice_servers(S(stun_urls=()), False), [])

    def test_static_password_fallback(self):
        s = S(turn_urls=(), turn_secret="", turn_url="turn:old:3478", turn_username="u", turn_credential="p")
        relay = [x for x in build_ice_servers(s, True) if "username" in x][0]
        self.assertEqual((relay["urls"], relay["username"], relay["credential"]), ("turn:old:3478", "u", "p"))
        self.assertTrue(has_relay(build_ice_servers(s, True)))
        self.assertFalse(has_relay(build_ice_servers(s, False)))

    def test_no_turn_configured(self):
        self.assertFalse(has_relay(build_ice_servers(S(turn_urls=(), turn_secret=""), True)))


class AccessTests(unittest.TestCase):
    def test_open_when_not_configured(self):
        self.assertTrue(check_access("", None))
        self.assertTrue(check_access("", "anything"))

    def test_code_required_when_configured(self):
        self.assertTrue(check_access("abc123", "abc123"))
        for bad in [None, "", "abc12", "abc1234", "ABC123", "abc123 "]:
            self.assertFalse(check_access("abc123", bad), bad)

    def test_non_ascii_does_not_crash(self):
        self.assertFalse(check_access("abc", "ሰላም"))
        self.assertTrue(check_access("ሰላም", "ሰላም"))


if __name__ == "__main__":
    unittest.main()
