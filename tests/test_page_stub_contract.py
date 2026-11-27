"""The stand-in backend of the page tests (tests/page_harness.py) against the
real one (the deployment notes): the same kinds of things asked of the real
aiza-backend (and the real work tree store), and the answers' shapes compared.

A page test is only as good as the stand-in's answers. When the stand-in
leaves out a field the real backend always sends, the page may break in the
test though not for real (2026-11-23: no partner_label stopped the list); when
it sends one the real backend never does, or with another type, the page may
pass in the test and break for real. Both fail here, so the stand-in is fixed
-- or the gap is listed below with why it may stay.

Only names and types are compared, never values.

    python3 -m unittest discover -s tests -v
"""
import json
import os
import re
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import page_harness as H
from page_sources import sources
from test_shared_search import B
from test_tree_store import load as load_tree_store

APP = "\n".join(sources().values())
# Names the page's scripts read as a field somewhere (x.name, x?.name, x["name"]).
READ = set(re.findall(r"\??\.([A-Za-z_]\w*)", APP)) | set(re.findall(r"\[\"([A-Za-z_]\w*)\"\]", APP))

# A field the real backend sends and the stand-in leaves out, though app.js
# reads that name: "<what>.<field>": why it may stay out.
MAY_LACK = {
}
# A field the stand-in sends that the real backend did not send here:
# "<what>.<field>": why it may stay.
MAY_ADD = {
}


def kind(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "str"
    if isinstance(v, list):
        return "list"
    return "dict"


def fields(objs):
    """name -> set of kinds, over a list of dicts."""
    out = {}
    for o in objs:
        for k, v in o.items():
            out.setdefault(k, set()).add(kind(v))
    return out


class Gaps:
    def __init__(self):
        self.lack, self.add, self.type = [], [], []

    def compare(self, what, stub_objs, real_objs, nested=()):
        """stub_objs/real_objs: the dicts of one kind; nested: fields whose
        value is a dict (or a list of dicts) compared the same way."""
        s, r = fields(stub_objs), fields(real_objs)
        if not stub_objs or not real_objs:
            self.lack.append(f"{what}: no example (stand-in {len(stub_objs)}, real {len(real_objs)})")
            return
        for k in sorted(set(r) - set(s)):
            if k in READ and f"{what}.{k}" not in MAY_LACK:
                self.lack.append(f"{what}.{k}")
        for k in sorted(set(s) - set(r)):
            if f"{what}.{k}" not in MAY_ADD:
                self.add.append(f"{what}.{k}")
        for k in sorted(set(s) & set(r)):
            sk, rk = s[k] - {"null"}, r[k] - {"null"}
            if sk and rk and not sk <= rk:
                self.type.append(f"{what}.{k}: stand-in {sorted(sk)}, real {sorted(rk)}")
        for k in nested:
            sub = lambda objs: [x for o in objs for v in [o.get(k)] for x in (v if isinstance(v, list) else [v])
                                if isinstance(x, dict)]
            self.compare(f"{what}.{k}", sub(stub_objs), sub(real_objs))


class StubContractTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root / "sessions"
        self.root.mkdir()
        self.st = {"rev": 1, "gated": 0}
        # both states of the stand-in (before and after /__bump)
        stand_in = H.sessions(self.st) + [H.LOGIN, H.NEW, H.MAILED, H.ADOPTED]
        self.stand_in_more = H.sessions({"rev": 0, "gated": 0})
        alive = {"container": set(), "host": set()}
        computed = {"alive", "link", "locked", "task", "waiting", "group"}
        for m in stand_in:
            d = self.root / m["id"]
            d.mkdir(exist_ok=True)
            meta = {k: v for k, v in m.items() if k not in computed}
            if not m.get("alive"):
                meta["stopped"] = True
            (d / "meta.json").write_text(json.dumps(meta))
            if m.get("task"):
                (d / "task.json").write_text(json.dumps(m["task"]))
            (d / "events.jsonl").write_text(json.dumps({"seq": 1, "ts": H.T0, "type": "user_message",
                                                        "text": "a needle here"}) + "\n")
            if m.get("alive"):
                alive[m.get("tmux_location", "container")].add(m["id"])
        self.stand_in = stand_in
        links = {"L1": {"members": ["aaaaaaaaaa00", "aaaaaaaaaa01"], "expires_ts": H.T0 + 3600, "created_ts": H.T0}}
        # the work tree store, asked in process as user "u"
        self.tree_dir = root / "tree"
        self.tree_dir.mkdir()
        S = load_tree_store(str(self.tree_dir))
        S.in_lab = lambda u: u in ("u", "v")
        S.notify_members = lambda *a: None

        def tree_call(req):
            res = S.handle("u", req)
            if not res.get("ok"):
                raise ValueError(res.get("error"))
            return res
        a = S.handle("u", {"op": "add", "title": "親の仕事"})["node"]
        S.handle("u", {"op": "add", "title": "子の仕事", "parent": a["id"], "links": {"session": "aaaaaaaaaa00"},
                       "ball": {"kind": "person", "who": "u"}})
        S.handle("u", {"op": "add", "title": "新しい子", "parent": a["id"],
                       "ball": {"kind": "sleep", "until": H.T0 + 86400, "text": "待ち"}})
        shared = S.handle("v", {"op": "add", "title": "共有の仕事", "visibility": "lab", "links": {"session": "cccccccccc01"}})["node"]
        # its Discord channel (the deployment notes), as aiza-discord-tree writes it
        with open(S.DISCORD_LINKS, "w") as f:
            json.dump({shared["id"]: "https://discord.com/channels/900000000000000001/800000000000000001"}, f)
        self.S = S
        stubs = {
            "session_roots": lambda: [self.root],
            "_unlockd_call": lambda verb, **kw: {"ok": True, "unlocked": False},
            "list_tmux_sessions": lambda: sorted(alive["container"]) + ["work"],
            "list_host_tmux_sessions": lambda: sorted(alive["host"]),
            "list_root_tmux_sessions": lambda: [],
            "ensure_watcher": lambda sid: None,
            "_load_links": lambda: json.loads(json.dumps(links)),
            "expire_links": lambda: None,
            "add_issue_statuses": lambda sessions: None,
            "tree_call": tree_call,
            "tree_lab_users": lambda: [{"user": "u", "name": "U"}, {"user": "v", "name": "V"}, {"user": "w", "name": "W"}],
            "viewer_lang": lambda: "ja",
            "reachable_ssh_machines": lambda asleep: ["winbox"],
            "SSH_MACHINES": {"winbox": {"drives": True}},
            "BOARD_DIR": root / "board",
            "BOARD_PATH": root / "board" / "board.json",
            "BOARD_LOCK_PATH": root / "board" / "board.lock",
            "BOARD_IS_MAIN": True,
            "_board_feeds": lambda: {},
        }
        (root / "board").mkdir()
        (root / "board" / "board.json").write_text(json.dumps({"entries": [
            {"machine": "winbox", "user": "u", "session_id": "aaaaaaaaaa01", "label": "s1", "state": "using",
             "source": "auto", "since": H.T0, "key": "k1", "last_ts": H.T0}]}))
        self.saved = {k: getattr(B, k) for k in stubs if hasattr(B, k)}
        for k, v in stubs.items():
            setattr(B, k, v)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), B.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.server.server_port}{path}") as r:
            return json.load(r)

    def gaps(self):
        g = Gaps()
        real = self.get("/sessions")
        g.compare("/sessions", [{"sessions": []}], [real])
        g.compare("session", self.stand_in + self.stand_in_more, real["sessions"], nested=("link", "task"))
        g.compare("session.link.members", [x for m in self.stand_in for x in (m.get("link") or {}).get("members", [])],
                  [x for m in real["sessions"] for x in (m.get("link") or {}).get("members", [])])
        tree = self.get("/tree")
        stand_trees = [H.tree(self.st), H.tree({"rev": 0, "gated": 0})]
        g.compare("/tree", stand_trees, [tree])
        g.compare("tree node", [n for t in stand_trees for n in t["nodes"]], tree["nodes"], nested=("ball",))
        search = self.get("/search?q=needle")
        g.compare("/search", [H.SEARCH], [search])
        g.compare("search hit", H.SEARCH["hits"], search["hits"])
        g.compare("/capabilities", [H.CAPS], [self.get("/capabilities")], nested=("unlock", "mailbox"))
        board = self.get("/board")
        g.compare("/board", [H.BOARD], [board])
        g.compare("board entry", H.BOARD["entries"], board["entries"])
        g.compare("/tree/week", [H.GETS["/tree/week"]], [self.get("/tree/week")])
        g.compare("/handoffs", [H.GETS["/handoffs"]], [self.get("/handoffs")])
        g.compare("/config", [H.GETS["/config"]], [self.get("/config")])
        g.compare("/codex-auth place", [H.NO_CODEX], [B._codex_status_result(1, "Not logged in", "")])
        g.compare("/tmux-sessions", [{"sessions": [{"name": "work", "location": "container"}]}],
                  [self.get("/tmux-sessions")], nested=("sessions",))
        return g

    def test_stand_in_answers_like_the_real_backend(self):
        g = self.gaps()
        self.assertEqual(g.lack, [], "the real backend sends these (app.js reads them); the stand-in does not")
        self.assertEqual(g.add, [], "the stand-in sends these; the real backend did not")
        self.assertEqual(g.type, [], "of another type in the stand-in")


if __name__ == "__main__":
    unittest.main()
