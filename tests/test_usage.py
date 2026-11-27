"""Usage per session (the plan's stage 3): token counts from Claude Code's own
log, once per message id, and the estimate at API list prices.

    python3 -m unittest discover -s tests -v
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from test_shared_search import B


def line(mid, model="claude-opus-5-5", **u):
    usage = {"input_tokens": 10, "output_tokens": 1000, "cache_read_input_tokens": 100000,
             "cache_creation_input_tokens": 2000, "cache_creation": {"ephemeral_1h_input_tokens": 2000, "ephemeral_5m_input_tokens": 0}}
    usage.update(u)
    return {"type": "assistant", "message": {"id": mid, "model": model, "usage": usage, "content": [{"type": "text", "text": "x"}]}}


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = B.session_dir
        B.session_dir = lambda sid: self.root / sid
        (self.root / "aaaaaaaaaa01").mkdir()

    def tearDown(self):
        B.session_dir = self.saved
        self.tmp.cleanup()

    def test_once_per_message(self):
        for _ in range(3):                       # one message, written as three lines
            B.usage_note("aaaaaaaaaa01", line("msg_1"))
        B.usage_note("aaaaaaaaaa01", line("msg_2"))
        s = B.usage_summary("aaaaaaaaaa01")
        self.assertEqual(s["output"], 2000)
        # 2 x (10*4 + 1000*20 + 100000*0.2 + 2000*4*2) / 1e6
        self.assertAlmostEqual(s["cost"], 2 * (40 + 20000 + 20000 + 16000) / 1e6, places=4)

    def test_through_the_transcript_reader(self):
        buf = "\n".join(json.dumps(line(f"msg_{i}")) for i in range(2)).encode() + b"\n"
        B._split_assistant_text_events(buf, "aaaaaaaaaa01")
        self.assertEqual(B.usage_summary("aaaaaaaaaa01")["output"], 2000)

    def test_unknown_model_counts_tokens_only(self):
        B.usage_note("aaaaaaaaaa01", line("m", model="something-else"))
        s = B.usage_summary("aaaaaaaaaa01")
        self.assertIsNone(s["cost"])
        self.assertGreater(s["tokens"], 0)

    def test_dated_and_1m_names(self):
        self.assertEqual(B._usage_price("claude-opus-5-5[1m]"), B.USAGE_PRICES["claude-opus-5-5"])
        self.assertEqual(B._usage_price("claude-haiku-4-5-20251001"), B.USAGE_PRICES["claude-haiku-4-5"])

    def test_bad_lines(self):
        for obj in ({}, {"message": {}}, {"message": {"id": 3, "usage": {}}}, line("x", output_tokens=-5, input_tokens=True)):
            B.usage_note("aaaaaaaaaa01", obj)
        s = B.usage_summary("aaaaaaaaaa01")
        self.assertEqual(s["output"], 0)

    def test_backfill(self):
        t = self.root / "conv.jsonl"
        t.write_text("\n".join(json.dumps(line(f"m{i}")) for i in range(3)) + "\n")
        B.usage_backfill("aaaaaaaaaa01", t)
        for _ in range(50):
            s = B.usage_summary("aaaaaaaaaa01")
            if s and s["output"] == 3000:
                break
            time.sleep(0.05)
        self.assertEqual(B.usage_summary("aaaaaaaaaa01")["output"], 3000)


if __name__ == "__main__":
    unittest.main()
