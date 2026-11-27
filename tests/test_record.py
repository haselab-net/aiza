"""The session record (the deployment notes, stage 1): what a Claude session did,
read from its conversation log into a file of aiza's own; for an Email
session only references and keyed hashes on the host.

    python3 -m unittest test_record -v
"""
import importlib.machinery
import importlib.util
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B

CHECK = Path(__file__).resolve().parent.parent / "bin" / "aiza-record-check"
_loader = importlib.machinery.SourceFileLoader("aiza_record_check_under_test", str(CHECK))
C = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(C)

CONV = "11111111-2222-3333-4444-555555555555"
CONV2 = "66666666-2222-3333-4444-555555555555"


def lines():
    return [
        {"type": "user", "uuid": "u1", "message": {"role": "user", "content": "please list the files"}},
        {"type": "assistant", "uuid": "a1", "message": {
            "id": "msg_1", "model": "claude-opus-5-5",
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100,
                      "cache_creation_input_tokens": 7},
            "content": [{"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "assistant", "uuid": "a1b", "message": {
            "id": "msg_1", "model": "claude-opus-5-5",
            "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 100,
                      "cache_creation_input_tokens": 7},
            "content": [{"type": "text", "text": "running"}]}},
        {"type": "user", "uuid": "r1", "message": {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": "x" * (B.RECORD_CUT + 10)}]}},
        {"type": "user", "uuid": "c1", "message": {"role": "user", "content": "<command-name>/clear</command-name>"}},
        {"type": "user", "uuid": "m1", "isMeta": True, "message": {"role": "user", "content": "meta"}},
    ]


class RecordTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.state, self.box = t / "state", t / "box"
        self.proj = t / "proj"
        for d in (self.state, self.box, self.proj):
            d.mkdir()
        self.meta = {"id": "abcdef012345", "preset": "claude-tui", "tmux_location": "container", "record": 1}
        self.saved = {n: getattr(B, n) for n in ("RECORD_DIR", "MAIL_RECORD_DIR", "STATE_DIR", "load_meta",
                                                   "_record_ensure_thread", "sandbox_roots", "MAIL_TREE_PRESETS")}
        B.STATE_DIR = self.state
        B.RECORD_DIR = self.state / "records"
        B.MAIL_RECORD_DIR = self.box / ".aiza-records"
        B.MAIL_TREE_PRESETS = {"mail-tui", "mail-shell"}
        B.load_meta = lambda sid: dict(self.meta)
        B._record_ensure_thread = lambda sid: None
        B.sandbox_roots = lambda: [self.box]
        B._conv_pending.clear()

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(B, n, v)
        self.tmp.cleanup()

    def write_log(self, name, objs, mode="w"):
        path = self.proj / f"{name}.jsonl"
        with open(path, mode) as f:
            for o in objs:
                f.write(json.dumps(o) + "\n")
        return path

    def records(self, rdir):
        return [json.loads(l) for l in (rdir / "record.jsonl").read_text().splitlines()]

    def test_devbox_record_and_check(self):
        path = self.write_log(CONV, lines())
        B.record_follow("abcdef012345", path)
        self.assertTrue(B.record_pump("abcdef012345"))
        rdir = B.RECORD_DIR / "abcdef012345"
        self.assertEqual(stat.S_IMODE(os.stat(rdir).st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(os.stat(rdir / "record.jsonl").st_mode), 0o600)
        recs = self.records(rdir)
        kinds = [r["k"] for r in recs]
        self.assertEqual(kinds, ["conv", "user", "usage", "tool_use", "tool_result", "upto"])
        res = [r for r in recs if r["k"] == "tool_result"][0]
        self.assertEqual((res["cut"], res["len"], len(res["content"])), (True, B.RECORD_CUT + 10, B.RECORD_CUT))
        self.assertEqual(recs[-1]["line"], 6)
        # Nothing new: nothing read; more lines: only those.
        self.assertFalse(B.record_pump("abcdef012345"))
        self.write_log(CONV, [{"type": "user", "uuid": "u2", "message": {"content": "thanks"}}], mode="a")
        self.assertTrue(B.record_pump("abcdef012345"))
        self.assertEqual([r["k"] for r in self.records(rdir)][-2:], ["user", "upto"])
        got, spans = C.from_record(rdir)
        want = C.from_logs(rdir, spans)
        for k in C.KINDS:
            self.assertEqual(got[k], want[k], k)
        self.assertEqual(C.by_model(got["msg"]), C.by_model(want["msg"]))
        self.assertEqual(len(got["user"]), 2)

    def test_half_written_line_waits(self):
        path = self.write_log(CONV, lines()[:1])
        with open(path, "a") as f:
            f.write('{"type": "user", "uuid": "u9", "mess')
        B.record_follow("abcdef012345", path)
        B.record_pump("abcdef012345")
        self.assertEqual(self.records(B.RECORD_DIR / "abcdef012345")[-1]["line"], 1)

    def test_continued_copy_is_not_counted_twice(self):
        p1 = self.write_log(CONV, lines())
        B.record_follow("abcdef012345", p1)
        B.record_pump("abcdef012345")
        p2 = self.write_log(CONV2, lines() + [{"type": "user", "uuid": "u3", "message": {"content": "next"}}])
        B._conv_pending["abcdef012345"] = {"id": CONV2, "source": "continued", "size": None}
        B.record_follow("abcdef012345", p2)
        B.record_pump("abcdef012345")
        recs = self.records(B.RECORD_DIR / "abcdef012345")
        self.assertEqual(sum(r["k"] == "tool_use" for r in recs), 1)
        self.assertEqual([r["why"] for r in recs if r["k"] == "conv"], ["start", "continued"])
        got, spans = C.from_record(B.RECORD_DIR / "abcdef012345")
        self.assertEqual(got["user"], C.from_logs(B.RECORD_DIR / "abcdef012345", spans)["user"])

    def test_resumed_conversation_starts_at_its_end(self):
        path = self.write_log(CONV, lines())
        self.meta["resumed_from"] = CONV
        B.record_follow("abcdef012345", path)
        B.record_pump("abcdef012345")
        recs = self.records(B.RECORD_DIR / "abcdef012345")
        self.assertEqual([(r["k"], r["line"], r["why"]) for r in recs], [("conv", 7, "resume")])

    def test_mail_session_keeps_content_in_the_box(self):
        self.meta.update(preset="mail-tui", tmux_location="host")
        path = self.write_log(CONV, lines())
        B.record_follow("abcdef012345", path)
        B.record_pump("abcdef012345")
        inside = self.records(B.MAIL_RECORD_DIR / "abcdef012345")
        self.assertIn("tool_use", [r["k"] for r in inside])
        key = B.MAIL_RECORD_DIR / "ref.key"
        self.assertEqual(stat.S_IMODE(os.stat(key).st_mode), 0o600)
        host = B.RECORD_DIR / "abcdef012345"
        self.assertEqual(sorted(p.name for p in host.iterdir()), ["ref.jsonl"])
        text = (host / "ref.jsonl").read_text()
        for word in ("Bash", "ls", "please", "claude-opus", '"len"', "xxxx", "name", "input", "content"):
            self.assertNotIn(word, text, word)
        self.assertNotIn(key.read_bytes().hex(), text)
        refs = [json.loads(l) for l in text.splitlines()]
        self.assertEqual([r["k"] for r in refs], [r["k"] for r in inside])
        self.assertTrue(all(len(r["h"]) == 64 for r in refs if r["k"] not in ("conv", "upto")))
        self.assertNotIn("byte", text)

    def test_not_recorded(self):
        path = self.write_log(CONV, lines())
        for meta in ({"record": 1, "tmux_location": "ssh:box"}, {"record": 1, "launch": "codex"}, {"preset": "claude-tui"}):
            self.assertFalse(B.record_wanted(meta), meta)
        self.meta.pop("record")
        B.record_follow("abcdef012345", path)
        self.assertFalse((B.RECORD_DIR / "abcdef012345").exists())

    def test_subagent_logs_are_copied_as_they_are(self):
        path = self.write_log(CONV, lines()[:1])
        sub = self.proj / CONV / "subagents"
        sub.mkdir(parents=True)
        raw = b'{"type": "user", "isSidechain": true}\n{"partial'
        (sub / "agent-a1.jsonl").write_bytes(raw)
        B.record_follow("abcdef012345", path)
        B.record_pump("abcdef012345")
        copy = B.RECORD_DIR / "abcdef012345" / "subagents" / CONV / "agent-a1.jsonl"
        self.assertEqual(copy.read_bytes(), raw.split(b"\n")[0] + b"\n")
        rec = [r for r in self.records(B.RECORD_DIR / "abcdef012345") if r["k"] == "subagent"]
        self.assertEqual((rec[0]["from_line"], rec[0]["lines"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
