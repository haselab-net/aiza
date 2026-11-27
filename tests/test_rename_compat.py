"""The rename aigw -> aiza (2026-11-23, the deployment notes): what was
started or stored before the switch keeps working (every piece is marked
aigw-legacy in the code).

    python3 -m unittest discover -s tests -v
"""
import http.cookies
import time
import unittest

from test_shared_search import B
import codex_chat
from test_gateway_login import G


class EnvAliasTest(unittest.TestCase):
    def test_old_session_environment_reads_as_new(self):
        env = [b"AIGW_TALKTO=/home/u/sandhome/.aigw/s1/talkto.jsonl", b"PATH=/bin", b"AIZA_X=1"]
        self.assertEqual(B._env_aliases(env),
                         [b"AIZA_TALKTO=/home/u/sandhome/.aiza/s1/talkto.jsonl", b"PATH=/bin", b"AIZA_X=1"])

    def test_old_host_session_environment_reads_as_new(self):
        # host and root sessions keep their files in ~/.aigw-state (2026-11-23: missed at first, so
        # the chat of such a session only caught up at its hooks)
        env = [b"AIGW_TALKTO=/home/u/.aigw-state/sessions/s1/talkto_out.jsonl"]
        self.assertEqual(B._env_aliases(env), [b"AIZA_TALKTO=/home/u/.aiza-state/sessions/s1/talkto_out.jsonl"])

    def test_remote_panes_also_get_the_old_name(self):
        src = (B.__file__ if hasattr(B, "__file__") else "")
        text = open(src, encoding="utf-8").read() if src else ""
        self.assertIn('"-e", f"AIGW_TALKTO_ID={session_id}"', text)


class StoredRecordsTest(unittest.TestCase):
    def test_codex_event_with_the_old_type(self):
        ev = {"type": "agent_output", "text": "OK", "codex_event_id": "e1"}
        for t in ("aiza_codex_event", "aigw_codex_event"):
            self.assertEqual(codex_chat.parse_record({"type": t, "event": ev}, {}, 0), [ev], t)

    def test_stop_return_with_the_old_key(self):
        for key in ("aiza_stop_return", "aigw_stop_return"):
            self.assertTrue(B._codex_task_relevant({"type": "system", key: True, "ts": time.time()}), key)


class LegacyCookieTest(unittest.TestCase):
    def setUp(self):
        self.saved = G.check_and_rotate_session
        self.seen = []
        G.check_and_rotate_session = lambda v: (self.seen.append(v) or ("alice", None, None, None))

    def tearDown(self):
        G.check_and_rotate_session = self.saved

    def who(self, cookie):
        h = G.Handler.__new__(G.Handler)
        jar = http.cookies.SimpleCookie()
        jar.load(cookie)
        h._cookies = lambda: jar
        return h._current_username()

    def test_old_cookie_still_logs_in(self):
        self.assertEqual(self.who("aigw_session=old"), "alice")
        self.assertEqual(self.seen, ["old"])

    def test_new_cookie_wins(self):
        self.who("aigw_session=old; aiza_session=new")
        self.assertEqual(self.seen, ["new"])

    def test_no_cookie(self):
        self.assertIsNone(self.who("other=1"))


if __name__ == "__main__":
    unittest.main()
