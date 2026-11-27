"""aiza-session: a session reads another it was pointed at (plan stage 14).

    python3 -m unittest discover -s tests -v
"""
import getpass
import json
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B


class SessionRefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.me = getpass.getuser()
        self.metas = {}
        self.peer = {"sessions": [], "events": {}}
        self.peer_calls = []
        self.saved = {k: getattr(B, k) for k in ("load_meta", "session_dir", "_peer_call", "MAIL_TREE_PRESETS",
                                                 "SREF_SUMMARIES", "subprocess")}
        B.load_meta = lambda sid: self.metas.get(sid)
        B.session_dir = lambda sid: self.root / sid
        B.MAIL_TREE_PRESETS = {"mail-tui", "mail-shell"}
        B.SREF_SUMMARIES = self.root / "summaries.json"

        def peer(req, timeout=30):
            self.peer_calls.append(req)
            if req["op"] == "list":
                return {"ok": True, "sessions": self.peer["sessions"]}
            return {"ok": True, "events": self.peer["events"].get((req["owner"], req["session"]), [])}
        B._peer_call = peer

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        self.tmp.cleanup()

    def own(self, sid, preset="claude-tui", label="解析", events=()):
        self.metas[sid] = {"id": sid, "preset": preset, "label": label}
        (self.root / sid).mkdir(exist_ok=True)
        (self.root / sid / "events.jsonl").write_text(
            "".join(json.dumps(dict(e, seq=i + 1)) + "\n" for i, e in enumerate(events)))

    def ask(self, ref, asker_preset="claude-tui", **kw):
        self.metas["aaaaaaaaaa00"] = {"id": "aaaaaaaaaa00", "preset": asker_preset}
        return B.session_ref_from_session("aaaaaaaaaa00", dict({"ref": ref}, **kw))

    def test_tail_of_own_session(self):
        self.own("aaaaaaaaaa01", events=[{"type": "user_message", "text": "図を直して"},
                                         {"type": "tool", "text": "Edit: fig.py"},
                                         {"type": "agent_output", "text": "直しました"}])
        status, text = self.ask("aaaaaaaaaa01", mode="tail")
        self.assertEqual(status, "ok")
        self.assertIn("[利用者] 図を直して", text)
        self.assertIn("[AI] 直しました", text)

    def test_grep(self):
        self.own("aaaaaaaaaa01", events=[{"type": "agent_output", "text": "branch i12 に push"},
                                         {"type": "agent_output", "text": "別の話"}])
        status, text = self.ask("aaaaaaaaaa01", mode="grep", q="push")
        self.assertIn("i12", text)
        self.assertNotIn("別の話", text)

    def test_someone_elses_via_gateway(self):
        self.peer["sessions"] = [{"id": "bbbbbbbbbb01", "owner": "bob", "label": "bob の解析", "preset": "claude-tui"}]
        self.peer["events"][("bob", "bbbbbbbbbb01")] = [{"type": "agent_output", "text": "結果は表 2", "seq": 1}]
        status, text = self.ask("bob/bbbbbbbbbb01", mode="tail")
        self.assertEqual(status, "ok")
        self.assertIn("結果は表 2", text)
        self.assertEqual(self.peer_calls[-1], {"op": "events", "owner": "bob", "session": "bbbbbbbbbb01", "limit": 500})

    def test_not_shared_is_refused(self):
        status, text = self.ask("bob/bbbbbbbbbb01", mode="tail")
        self.assertEqual(status, "error")

    def test_mail_rules(self):
        self.own("aaaaaaaaaa02", preset="mail-tui", events=[{"type": "agent_output", "text": "x"}])
        self.assertEqual(self.ask("aaaaaaaaaa02", mode="tail")[0], "error")          # from outside the box
        self.assertEqual(self.ask("aaaaaaaaaa02", asker_preset="mail-tui", mode="tail")[0], "ok")
        self.assertEqual(self.ask("aaaaaaaaaa02", asker_preset="mail-tui")[0], "error")  # no summary
        self.peer["sessions"] = [{"id": "bbbbbbbbbb02", "owner": "bob", "preset": "mail-tui"}]
        self.assertEqual(self.ask("bob/bbbbbbbbbb02", asker_preset="mail-tui", mode="tail")[0], "error")

    def test_summary_is_made_once(self):
        runs = []

        class R:
            returncode, stdout = 0, "目的: 図の修正"

        class SP:
            TimeoutExpired = TimeoutError

            @staticmethod
            def run(cmd, **kw):
                runs.append((cmd, kw["input"]))
                return R()
        B.subprocess = SP
        self.own("aaaaaaaaaa01", events=[{"type": "user_message", "text": "図を直して"}])
        self.assertIn("目的: 図の修正", self.ask("aaaaaaaaaa01")[1])
        self.assertIn("前に作ったもの", self.ask("aaaaaaaaaa01")[1])
        self.assertEqual(len(runs), 1)
        self.assertIn("--tools", runs[0][0])
        self.assertIn("図を直して", runs[0][1])

    def test_bad_ref(self):
        self.assertEqual(self.ask("../x")[0], "error")


class GatewayPeerTest(unittest.TestCase):
    """The gateway's peer socket: read-only, always on the caller's behalf."""

    def setUp(self):
        from test_gateway_login import G
        self.G = G
        self.calls = []
        self.saved = (G.backend_request, G.backend_socket_path_for, G.shared_sessions_for)

        class Resp:
            status = 200

            @staticmethod
            def read():
                return json.dumps({"events": [{"type": "agent_output", "text": "x"}]}).encode()

        class Conn:
            @staticmethod
            def close():
                pass

        def req(sock, method, path, body=None, headers=None, timeout=60):
            self.calls.append((sock, method, path, headers))
            return Conn(), Resp()
        G.backend_request = req
        G.backend_socket_path_for = lambda u: f"/run/{u}.sock"
        G.shared_sessions_for = lambda u: [{"id": "s", "owner": "bob"}]

    def tearDown(self):
        self.G.backend_request, self.G.backend_socket_path_for, self.G.shared_sessions_for = self.saved

    def test_events_on_behalf_of_caller(self):
        r = self.G.peer_handle("alice", {"op": "events", "owner": "bob", "session": "bbbbbbbbbb01", "limit": 9999})
        self.assertTrue(r["ok"])
        sock, method, path, headers = self.calls[0]
        self.assertEqual((sock, method), ("/run/bob.sock", "GET"))
        self.assertEqual(path, "/sessions/bbbbbbbbbb01/events/page?limit=500")
        self.assertEqual(headers["X-Aiza-On-Behalf-Of"], "alice")

    def test_rejects_bad_and_writes(self):
        for req in ({"op": "events", "owner": "bob", "session": "../x"},
                    {"op": "events", "owner": "Bob;", "session": "bbbbbbbbbb01"},
                    {"op": "events", "owner": "alice", "session": "bbbbbbbbbb01"},
                    {"op": "send", "owner": "bob", "session": "bbbbbbbbbb01"}):
            self.assertFalse(self.G.peer_handle("alice", req)["ok"], req)
        self.assertEqual(self.calls, [])

    def test_list(self):
        self.assertEqual(self.G.peer_handle("alice", {"op": "list"})["sessions"], [{"id": "s", "owner": "bob"}])

    def test_share_hint_names_the_caller_as_owner(self):
        added = []
        saved = self.G._add_share_hint
        self.G._add_share_hint = lambda owner, viewer: added.append((owner, viewer))
        try:
            self.assertTrue(self.G.peer_handle("alice", {"op": "share_hint", "viewer": "bob"})["ok"])
            self.assertTrue(self.G.peer_handle("alice", {"op": "share_hint", "viewer": "*"})["ok"])
            for bad in ("alice", "Bob;", "", None, ["bob"]):
                self.assertFalse(self.G.peer_handle("alice", {"op": "share_hint", "viewer": bad})["ok"], bad)
        finally:
            self.G._add_share_hint = saved
        self.assertEqual(added, [("alice", "bob"), ("alice", "*")])


if __name__ == "__main__":
    unittest.main()
