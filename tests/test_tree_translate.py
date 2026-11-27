"""The work tree in the viewer's language (plan stage 13).

    python3 -m unittest discover -s tests -v
"""
import json
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B


class TranslateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.asked = []
        self.saved = (B.TR_FILE, B._tr_ask, B.threading.Thread)
        B.TR_FILE = Path(self.tmp.name) / "tr.json"

        def ask(lang, texts):
            self.asked.append((lang, list(texts)))
            return {t: f"<{lang}>{t}" for t in texts}
        B._tr_ask = ask

        class Now:                       # run the background batch at once
            def __init__(self, target, daemon=None, args=()):
                self.target, self.args = target, args

            def start(self):
                self.target(*self.args)
        B.threading.Thread = Now
        B._tr_pending.clear()
        B._tr_running.clear()

    def tearDown(self):
        B.TR_FILE, B._tr_ask, B.threading.Thread = self.saved
        self.tmp.cleanup()

    def nodes(self):
        return [{"id": "n1", "owner": "me", "visibility": "lab", "title": "図の作成",
                 "ball": {"kind": "person", "text": "寝かせ 11/18"}},
                {"id": "n2", "owner": "me", "visibility": "self", "title": "私の用事"},
                {"id": "n3", "owner": "bob", "visibility": "lab", "title": "Fix the motor mount"}]

    def test_language_guess(self):
        self.assertTrue(B._needs_tr("図の作成", "en"))
        self.assertFalse(B._needs_tr("Fix the motor", "en"))
        self.assertTrue(B._needs_tr("Fix the motor", "ja"))
        self.assertFalse(B._needs_tr("図の作成", "ja"))
        self.assertTrue(B._needs_tr("図の作成", "zh-CN"))       # kana: Japanese
        self.assertFalse(B._needs_tr("电机", "zh-CN"))

    def test_shared_only_and_remembered(self):
        first = self.nodes()
        missing = B.tree_translate(first, "me", lang="en")
        self.assertEqual(missing, 2)                              # n1's title and status line, not n2
        self.assertEqual(sorted(self.asked[0][1]), ["図の作成", "寝かせ 11/18"])
        again = self.nodes()
        self.assertEqual(B.tree_translate(again, "me", lang="en"), 0)
        self.assertEqual(again[0]["tr"], {"title": "<en>図の作成", "ball": "<en>寝かせ 11/18"})
        self.assertNotIn("tr", again[1])
        self.assertNotIn("tr", again[2])                          # already English
        self.assertEqual(len(self.asked), 1)
        self.assertEqual(json.loads(B.TR_FILE.read_text())["en"]["図の作成"], "<en>図の作成")

    def test_other_direction(self):
        ns = self.nodes()
        B.tree_translate(ns, "me", lang="ja")
        self.assertEqual(self.asked, [("ja", ["Fix the motor mount"])])


if __name__ == "__main__":
    unittest.main()
