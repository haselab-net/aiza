"""aiza-usage-collect (the deployment notes): what counts as a person's message, the
weekly buckets, tokens as they grow, and where a session sits in the tree.

    python3 -m unittest discover -s tests -v
"""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    loader = importlib.machinery.SourceFileLoader("aiza_usage_collect", str(ROOT / "bin" / "aiza-usage-collect"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("aiza_usage_collect", loader))
    loader.exec_module(mod)
    return mod


class UsageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.U = load()
        self.U.MAILBOX_CONFIG = str(self.home / "no-mailbox.json")
        self.lab = {"alice", "bob"}
        self.t0 = time.mktime((2026, 11, 18, 15, 0, 0, 0, 0, -1))   # a Wednesday

    def tearDown(self):
        self.tmp.cleanup()

    def session(self, sid, events, usage=None, store=("sandhome", ".aiza")):
        d = self.home.joinpath(*store, sid)
        d.mkdir(parents=True, exist_ok=True)
        (d / "meta.json").write_text(json.dumps({"id": sid, "created_ts": self.t0}))
        with open(d / "events.jsonl", "a") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")
        if usage is not None:
            (d / "usage.json").write_text(json.dumps({"by_model": {"claude-opus-5-5": usage}}))
        return d

    def scan(self, state):
        prev = {k.split("/", 1)[1]: v for k, v in (state.get("sessions") or {}).items() if k.startswith("alice/")}
        rows = self.U.scan_user("alice", str(self.home), prev, self.lab)
        self.U.merge(state, "alice", rows, self.lab, "2026-11-23")
        state.setdefault("since", 1.0)
        return state

    def counts(self, state, k):
        out = {}
        for key, c in state["counts"].items():
            if k in c:
                week, who, _owner, _sid = key.split("|")
                out[(week, who)] = out.get((week, who), 0) + c[k]
        return out

    def test_whose_messages(self):
        um = lambda **kw: dict({"type": "user_message", "text": "x", "ts": self.t0}, **kw)
        self.session("aaaaaaaaaa01", [um(), um(), um(**{"from": "bob"}), um(**{"from": "🔗 other"}),
                                      um(**{"from": "⏰ AI座"}), um(moved_from="aaaaaaaaaa09"),
                                      {"type": "agent_output", "text": "y", "ts": self.t0},
                                      um(ts=self.t0 + 7 * 86400)])
        st = self.scan({})
        self.assertEqual(self.counts(st, "msgs"), {("2026-11-16", "alice"): 2, ("2026-11-16", "bob"): 1,
                                                    ("2026-11-23", "alice"): 1})
        self.assertEqual(self.counts(st, "sessions"), {("2026-11-16", "alice"): 1})
        # Read again: nothing twice; a new line once.
        self.session("aaaaaaaaaa01", [um()])
        st = self.scan(st)
        self.assertEqual(self.counts(st, "msgs")[("2026-11-16", "alice")], 3)
        self.assertEqual(self.counts(st, "sessions"), {("2026-11-16", "alice"): 1})

    def test_tokens_as_they_grow(self):
        d = self.session("aaaaaaaaaa02", [], usage={"input": 1000, "output": 100})
        st = self.scan({})
        self.assertEqual(self.counts(st, "tokens"), {("before", "alice"): 1100})
        (d / "usage.json").write_text(json.dumps({"by_model": {"claude-opus-5-5": {"input": 1500, "output": 200}}}))
        self.session("aaaaaaaaaa03", [], usage={"input": 10, "output": 0}, store=(".aiza-state", "sessions"))
        st = self.scan(st)
        self.assertEqual(self.counts(st, "tokens"), {("before", "alice"): 1100, ("2026-11-23", "alice"): 610})
        self.assertGreater(self.counts(st, "cost")[("2026-11-23", "alice")], 0)

    def test_links_are_not_followed(self):
        real = self.session("aaaaaaaaaa04", [{"type": "user_message", "text": "x", "ts": self.t0}])
        other = self.home / "sandhome" / ".aiza" / "aaaaaaaaaa05"
        other.mkdir()
        (other / "meta.json").symlink_to(real / "meta.json")
        rows = self.U.scan_user("alice", str(self.home), {}, self.lab)
        self.assertEqual([r["sid"] for r in rows], ["aaaaaaaaaa04"])

    def test_tree_places(self):
        p = self.home / "nodes.json"
        p.write_text(json.dumps({"nodes": {
            "n000000000001": {"id": "n000000000001", "visibility": "lab", "owner": "alice", "links": {"session": "aaaaaaaaaa01"}},
            "n000000000002": {"id": "n000000000002", "visibility": "self", "owner": "bob", "links": {"session": "aaaaaaaaaa02"}},
            "n000000000003": {"id": "n000000000003", "visibility": "lab", "owner": "alice", "session_owner": "bob",
                              "links": {"session": "aaaaaaaaaa03"}}}}))
        self.U.TREE_NODES = str(p)
        self.assertEqual(self.U.tree_places(), {("alice", "aaaaaaaaaa01"): "n000000000001",
                                                ("bob", "aaaaaaaaaa02"): "private",
                                                ("bob", "aaaaaaaaaa03"): "n000000000003"})

    def test_week_is_monday(self):
        self.assertEqual(self.U.week_of(self.t0), "2026-11-16")
        self.assertEqual(self.U.week_of(time.mktime((2026, 11, 22, 23, 59, 0, 0, 0, -1))), "2026-11-16")
        self.assertEqual(self.U.week_of(time.mktime((2026, 11, 23, 0, 1, 0, 0, 0, -1))), "2026-11-23")


if __name__ == "__main__":
    unittest.main()
