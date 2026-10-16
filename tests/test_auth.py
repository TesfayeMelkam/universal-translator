import os
import sqlite3
import tempfile
import unittest

from ai_services.auth import UserStore, check_password, hash_password
from ai_services.providers.base import ProviderError
from ai_services.services.history import HistoryStore


class Clock:
    t = 1000.0
    def __call__(self):
        return self.t


def code(fn, *a, **k):
    try:
        fn(*a, **k)
    except ProviderError as exc:
        return exc.code
    return None


class PasswordTests(unittest.TestCase):
    def test_hash_is_salted_and_verifies(self):
        a, b = hash_password("correct horse battery"), hash_password("correct horse battery")
        self.assertNotEqual(a, b)
        self.assertNotIn("correct", a)
        self.assertTrue(check_password("correct horse battery", a))
        self.assertFalse(check_password("correct horse batterY", a))
        self.assertFalse(check_password("x", "garbage"))


class UserTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.u = UserStore(":memory:", clock=self.clock, session_days=1, max_failures=3, lock_seconds=60)

    def test_register_validation(self):
        self.assertEqual(code(self.u.create_user, "ab", "longenoughpass"), "bad_username")
        self.assertEqual(code(self.u.create_user, "bad name!", "longenoughpass"), "bad_username")
        self.assertEqual(code(self.u.create_user, "abel", "short"), "weak_password")
        self.assertEqual(code(self.u.create_user, "samepassword", "samepassword"), "weak_password")
        uid = self.u.create_user("Abel", "a-long-password")
        self.assertEqual(code(self.u.create_user, "abel", "another-long-pass"), "username_taken")   # case-insensitive
        self.assertEqual(self.u.verify("ABEL", "a-long-password"), uid)

    def test_wrong_password_and_unknown_user_look_the_same(self):
        self.u.create_user("sara", "a-long-password")
        self.assertEqual(code(self.u.verify, "sara", "wrong-password"), "bad_login")
        self.assertEqual(code(self.u.verify, "nobody", "wrong-password"), "bad_login")

    def test_lockout_then_recovery(self):
        uid = self.u.create_user("sara", "a-long-password")
        for _ in range(3):
            self.u.verify  # noqa: B018
            code(self.u.verify, "sara", "bad-password-x", "1.2.3.4")
        self.assertEqual(code(self.u.verify, "sara", "a-long-password", "9.9.9.9"), "too_many_attempts")
        self.clock.t += 61
        self.assertEqual(self.u.verify("sara", "a-long-password", "9.9.9.9"), uid)

    def test_sessions(self):
        uid = self.u.create_user("sara", "a-long-password")
        tok = self.u.create_session(uid)
        self.assertEqual(self.u.user_for(tok), {"id": uid, "username": "sara"})
        self.assertIsNone(self.u.user_for("nope"))
        self.assertIsNone(self.u.user_for(None))
        self.u.end_session(tok)
        self.assertIsNone(self.u.user_for(tok))
        tok2 = self.u.create_session(uid)
        self.clock.t += 86401
        self.assertIsNone(self.u.user_for(tok2))                      # expired

    def test_nothing_secret_stored_in_plaintext(self):
        path = os.path.join(tempfile.mkdtemp(), "u.sqlite3")
        u = UserStore(path)
        uid = u.create_user("sara", "my-very-secret-pw")
        tok = u.create_session(uid)
        raw = b"".join(open(path, "rb").read() for _ in [0])
        self.assertNotIn(b"my-very-secret-pw", raw)
        self.assertNotIn(tok.encode(), raw)


class PerUserHistoryTests(unittest.TestCase):
    def test_isolation(self):
        h = HistoryStore(":memory:")
        a = h.add("en", "am", "Hello", "ሰላም", "mock", user_id=1)
        h.add("en", "fr", "Hello", "Bonjour", "mock", user_id=2)
        h.add("en", "de", "Hello", "Hallo", "mock")                      # anonymous
        self.assertEqual([r["target"] for r in h.list(user_id=1)], ["am"])
        self.assertEqual([r["target"] for r in h.list(user_id=2)], ["fr"])
        self.assertEqual([r["target"] for r in h.list()], ["de"])
        self.assertFalse(h.toggle_favorite(a, user_id=2))                 # cannot touch someone else's row
        self.assertTrue(h.toggle_favorite(a, user_id=1))
        h.clear(user_id=1)
        self.assertEqual(h.list(user_id=1), [])
        self.assertEqual(len(h.list(user_id=2)), 1)

    def test_old_database_is_upgraded(self):
        path = os.path.join(tempfile.mkdtemp(), "old.sqlite3")
        c = sqlite3.connect(path)
        c.execute("""CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source TEXT, target TEXT, source_text TEXT, translated_text TEXT, provider TEXT, favorite INTEGER NOT NULL DEFAULT 0)""")
        c.execute("INSERT INTO history (source,target,source_text,translated_text,provider) VALUES ('en','am','Hello','ሰላም','mock')")
        c.commit(); c.close()
        h = HistoryStore(path)
        self.assertEqual(h.list()[0]["translated_text"], "ሰላም")         # old rows belong to the shared user 0


if __name__ == "__main__":
    unittest.main()
