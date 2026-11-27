"""The gateway's login sessions (the deployment notes, the design notes): a signed
cookie checked against the server-side store, rotated every 5 minutes,
a superseded cookie accepted for a short grace (and pointed at the chain's
tip), reused after it the whole chain revoked, an expired or tampered or
unknown one simply "not logged in", a store that cannot be read failing
closed, and a long-open stream cut off once its session ends.

    python3 -m unittest discover -s tests -v
"""
import getpass
import json
import tempfile
import time as real_time
import unittest
from pathlib import Path

from test_gateway_login import load_gateway

G = load_gateway()
ME = getpass.getuser()          # a real account: the gateway checks it exists


class Clock:
    """G.time for these tests: time() is ours, the rest the real module's."""
    def __init__(self):
        self.now = 1_800_000_000

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(real_time, name)


class SessionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "secret").write_bytes(b"s" * 32)
        self.saved = {k: getattr(G, k) for k in ("COOKIE_SECRET_FILE", "SESSION_STORE_PATH", "SESSION_STORE_LOCK_PATH", "time")}
        G.COOKIE_SECRET_FILE = str(d / "secret")
        G.SESSION_STORE_PATH = d / "sessions.json"
        G.SESSION_STORE_LOCK_PATH = d / ".lock"
        self.clock = G.time = Clock()

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(G, k, v)
        self.tmp.cleanup()

    def login(self):
        cookie, exp = G.make_session_cookie(ME)
        return cookie

    @staticmethod
    def value(header):
        """The cookie value of a Set-Cookie header."""
        return header.split(";", 1)[0].split("=", 1)[1]

    def store(self):
        return json.loads(G.SESSION_STORE_PATH.read_text())

    def test_a_fresh_login_is_logged_in_and_not_rotated(self):
        c = self.login()
        user, header, jti, chain = G.check_and_rotate_session(c)
        self.assertEqual(user, ME)
        self.assertIsNone(header)
        self.assertTrue(jti and chain)
        self.assertEqual(oct(G.SESSION_STORE_PATH.stat().st_mode & 0o777), "0o600")

    def test_rotation_after_five_minutes_keeps_the_chain_and_its_end(self):
        c = self.login()
        _, _, jti0, chain = G.check_and_rotate_session(c)
        self.clock.now += G.SESSION_ROTATE_INTERVAL
        user, header, jti1, chain1 = G.check_and_rotate_session(c)
        self.assertEqual((user, chain1), (ME, chain))
        self.assertNotEqual(jti1, jti0)
        self.assertIn("HttpOnly", header)
        new = self.value(header)
        self.assertEqual(G.check_and_rotate_session(new)[:1], (ME,))
        s = self.store()["sessions"]
        self.assertEqual(s[jti0]["absolute_exp"], s[jti1]["absolute_exp"])   # the chain's end does not move

    def test_the_old_cookie_within_the_grace_gets_the_tip(self):
        c = self.login()
        self.clock.now += G.SESSION_ROTATE_INTERVAL
        _, header, tip, _ = G.check_and_rotate_session(c)
        self.clock.now += G.SESSION_REUSE_GRACE
        user, again, jti, _ = G.check_and_rotate_session(c)     # a second tab, a beat behind
        self.assertEqual((user, jti), (ME, tip))
        self.assertEqual(self.value(again), self.value(header))

    def test_the_old_cookie_after_the_grace_revokes_the_whole_chain(self):
        c = self.login()
        self.clock.now += G.SESSION_ROTATE_INTERVAL
        _, header, _, chain = G.check_and_rotate_session(c)
        self.clock.now += G.SESSION_REUSE_GRACE + 1
        self.assertEqual(G.check_and_rotate_session(c), (None, None, None, None))   # someone has a copy
        self.assertEqual(G.check_and_rotate_session(self.value(header)), (None, None, None, None))
        self.assertIn(chain, self.store()["revoked_chains"])

    def test_another_login_is_not_touched_by_a_revoked_chain(self):
        a, b = self.login(), self.login()
        self.clock.now += G.SESSION_ROTATE_INTERVAL
        G.check_and_rotate_session(a)
        self.clock.now += G.SESSION_REUSE_GRACE + 1
        G.check_and_rotate_session(a)
        self.assertEqual(G.check_and_rotate_session(b)[0], ME)

    def test_past_its_end_a_login_is_over(self):
        c = self.login()
        self.clock.now += G.SESSION_ABSOLUTE_TTL + 1
        self.assertEqual(G.check_and_rotate_session(c), (None, None, None, None))

    def test_the_cookies_own_end_holds_even_if_the_store_says_more(self):
        # Defense in depth: a store written by something else (or restored
        # from an old copy) cannot make an expired cookie valid again.
        c = self.login()
        jti = json.loads(G.unsign(c))["jti"]
        data = self.store()
        data["sessions"][jti]["absolute_exp"] += 10 * G.SESSION_ABSOLUTE_TTL
        G.SESSION_STORE_PATH.write_text(json.dumps(data))
        self.clock.now += G.SESSION_ABSOLUTE_TTL + 1
        self.assertEqual(G.check_and_rotate_session(c), (None, None, None, None))

    def test_tampered_unsigned_and_unknown_cookies_are_not_logged_in(self):
        c = self.login()
        enc, mac = c.rsplit(".", 1)
        payload = json.loads(G.unsign(c))
        for bad in (enc + "." + "0" * 64, enc, "", "x.y",
                    G.sign(json.dumps(dict(payload, u="root" if ME != "root" else "nobody"))),   # someone else's name
                    G.sign(json.dumps(dict(payload, jti="f" * 32))),                             # no such session
                    G.sign(json.dumps(dict(payload, u="no-such-user-xyz")))):
            self.assertEqual(G.check_and_rotate_session(bad), (None, None, None, None), bad[:20])

    def test_a_store_that_cannot_be_read_fails_closed(self):
        c = self.login()
        G.SESSION_STORE_PATH.write_text("{not json")
        self.assertEqual(G.check_and_rotate_session(c), (None, None, None, None))
        with self.assertRaises(RuntimeError):
            G.make_session_cookie(ME)                 # and no new login over it

    def test_a_long_stream_is_cut_off_once_its_session_ends(self):
        c = self.login()
        _, _, jti, chain = G.check_and_rotate_session(c)
        self.clock.now += G.SESSION_ROTATE_INTERVAL
        G.check_and_rotate_session(c)                 # another request rotated the chain under the stream
        self.assertTrue(G._session_touch(jti, ME))    # a superseded jti alone does not end the stream
        self.assertFalse(G._session_touch(jti, "someone-else"))
        self.clock.now += G.SESSION_ABSOLUTE_TTL
        self.assertFalse(G._session_touch(jti, ME))

    def test_logging_out_revokes_the_chain(self):
        c = self.login()
        _, _, _, chain = G.check_and_rotate_session(c)
        G._revoke_session_from_cookie(c)
        self.assertEqual(G.check_and_rotate_session(c), (None, None, None, None))
        self.assertIn(chain, self.store()["revoked_chains"])


if __name__ == "__main__":
    unittest.main()
