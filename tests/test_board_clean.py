"""What the page gets of the blackboard (the deployment notes, 2026-11-28):
board.json is writable by everyone with a shell on the host, so board_view
hands the page only known fields, each of its type and length, and the
looked-up words (source, state, ended_why) only from their lists -- why:
the page puts some of them in markup.

    python3 -m unittest discover -s tests -v
"""
import unittest

from test_shared_search import B


class BoardCleanTest(unittest.TestCase):
    def test_only_known_fields_types_and_words(self):
        evil = "<img src=x onerror=1>"
        got = B._board_clean([
            {"machine": "winbox", "user": "u", "state": "using", "source": "claim", "since": 1.5, "key": "k",
             "what": "印刷", "extra": evil},
            {"machine": "winbox", "user": "v", "state": evil, "source": evil, "ended_why": evil,
             "since": "soon", "ended_at": True, "what": "x" * 5000, "label": ["a"]},
            "not an entry", None,
            {"machine": "winbox", "state": "using"}, {"user": "u", "state": "using"},   # whose / which: dropped
        ])
        self.assertEqual(len(got), 2)
        ok, bad = got
        self.assertEqual((ok["source"], ok["state"], ok["since"], ok["what"]), ("claim", "using", 1.5, "印刷"))
        self.assertNotIn("extra", ok)
        self.assertEqual(bad["state"], "using")
        for k in ("source", "ended_why", "since", "ended_at", "label"):
            self.assertNotIn(k, bad)
        self.assertEqual(len(bad["what"]), B.BOARD_ENTRY_TEXT["what"])
        self.assertEqual(B._board_clean({"entries": "x"}), [])

    def test_the_real_words_pass(self):
        for why in ("stopped", "fell", "deleted", "released", "disconnected"):
            self.assertEqual(B._board_clean([{"user": "u", "machine": "m", "state": "ended", "ended_why": why}])[0]["ended_why"], why)
        for st in ("using", "idle", "asleep", "ended"):
            self.assertEqual(B._board_clean([{"user": "u", "machine": "m", "state": st}])[0]["state"], st)


if __name__ == "__main__":
    unittest.main()
