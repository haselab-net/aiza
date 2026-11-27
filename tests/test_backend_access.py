"""Who may do what to a session, at the backend's HTTP layer (the deployment notes,
the deployment notes): the owner (no X-Aiza-On-Behalf-Of, which only aiza-gateway
and the owner's own processes can send) does everything; a co-worker
(shared_with) reads and acts (send, keys, stop) but never deletes, shares,
archives or creates; a reader (shared_read, an Email session's named reader,
a root session's) only reads; anyone else finds no such session -- the same
answer as for an id that does not exist. What a request would do is
recorded by stand-ins, so a refused one is seen to have done nothing.

    python3 -m unittest discover -s tests -v
"""
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from test_shared_search import B

CO, READ, NONE_, MAIL, ROOT_S = "bbbb000000000001", "bbbb000000000002", "bbbb000000000003", "bbbb000000000004", "bbbb000000000005"
MISSING = "bbbb0000000000ff"


class AccessTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.done = []
        self.make(CO, preset="shell", shared_with=["bob"])
        self.make(READ, preset="shell", shared_read=["bob"])
        self.make(NONE_, preset="shell")
        self.make(MAIL, preset="mail-shell", location="host", shared_read=["bob"], shared_with=["bob"])   # the box's shell: never co-worked
        self.make(ROOT_S, preset="claude-login-root", location="root", shared_with=["bob"])
        rec = lambda name: (lambda *a, **k: self.done.append((name, a[0] if a else None)))
        stubs = {
            "session_roots": lambda: [self.root],
            "_meta_fits_root": lambda sdir, meta: True,
            "_unlockd_call": lambda verb, **f: {"ok": True, "unlocked": True, "tier": "root", "expires_at": 9e9},
            "list_tmux_sessions": lambda: [], "list_host_tmux_sessions": lambda: [], "list_root_tmux_sessions": lambda: [],
            "ensure_watcher": lambda sid: None, "_load_links": lambda: {}, "expire_links": lambda: None,
            "send_message": rec("send"), "send_key": lambda name, loc, key, **k: self.done.append(("key", name)),
            "stop_session": rec("stop"), "delete_session": rec("delete"),
            "archive_session": rec("archive"), "share_session": rec("share"),
        }
        self.saved = {n: getattr(B, n) for n in stubs if hasattr(B, n)}
        for n, fn in stubs.items():
            setattr(B, n, fn)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), B.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for n, fn in self.saved.items():
            setattr(B, n, fn)
        self.tmp.cleanup()

    def make(self, sid, preset, location="container", **share):
        d = self.root / sid
        d.mkdir()
        meta = {"id": sid, "label": sid, "preset": preset, "tmux_location": location, "tmux_name": sid, **share}
        (d / "meta.json").write_text(json.dumps(meta))
        (d / "events.jsonl").write_text(json.dumps({"type": "user_message", "seq": 1, "ts": 1, "text": "hi"}) + "\n")

    def req(self, method, path, who=None, body=None):
        url = f"http://127.0.0.1:{self.server.server_port}{path}"
        data = json.dumps(body or {}).encode() if method == "POST" else None
        r = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
        if who is not None:
            r.add_header("X-Aiza-On-Behalf-Of", who)
        try:
            with urllib.request.urlopen(r, timeout=10) as resp:
                return resp.status
        except urllib.error.HTTPError as e:
            return e.code

    def read(self, sid, who):
        return self.req("GET", f"/sessions/{sid}/events/page?limit=5", who)

    def act(self, sid, who):
        """(status of send, keys, stop) and what they did."""
        self.done.clear()
        got = (self.req("POST", f"/sessions/{sid}/messages", who, {"text": "x"}),
               self.req("POST", f"/sessions/{sid}/keys", who, {"key": "Enter"}),
               self.req("POST", f"/sessions/{sid}/stop", who))
        return got, list(self.done)

    def test_the_owner_reads_and_acts_on_every_session(self):
        for sid in (CO, READ, NONE_):
            self.assertEqual(self.read(sid, None), 200, sid)
            got, done = self.act(sid, None)
            self.assertEqual(got, (202, 200, 200), sid)     # a message is taken (202)
            self.assertEqual([d[0] for d in done], ["send", "key", "stop"], sid)

    def test_a_coworker_reads_and_acts(self):
        self.assertEqual(self.read(CO, "bob"), 200)
        got, done = self.act(CO, "bob")
        self.assertEqual(got, (202, 200, 200))
        self.assertEqual([d[0] for d in done], ["send", "key", "stop"])

    def test_a_reader_only_reads(self):
        for sid in (READ, MAIL, ROOT_S):     # the Email box's shell: only read; root: shared_with means read
            self.assertEqual(self.read(sid, "bob"), 200, sid)
            got, done = self.act(sid, "bob")
            self.assertEqual(got, (403, 403, 403), sid)
            self.assertEqual(done, [], sid)

    def test_anyone_else_finds_no_such_session(self):
        for who in ("carol", "bo", "bobby", "Bob", "*"):
            for sid in (CO, READ, NONE_, MAIL, ROOT_S):
                self.assertEqual(self.read(sid, who), 404, (who, sid))
        self.assertEqual(self.read(MISSING, "carol"), 404)          # the same as a session that is not there
        self.assertIn(self.read("../../etc", "carol"), (403, 404))
        self.assertEqual(self.done, [])

    def test_what_sharing_never_includes(self):
        for path in (f"/sessions/{CO}/delete", f"/sessions/{CO}/share", f"/sessions/{CO}/unshare",
                     f"/sessions/{CO}/archive", f"/sessions/{CO}/to-mailbox", "/sessions", "/push/subscribe",
                     "/folders/ops", "/chrome/kill", "/claude-auth/login"):   # attach: a collaborator's since 2026-11-25
            self.assertEqual(self.req("POST", path, "bob", {"scope": "container"}), 403, path)
        for path in ("/capabilities", "/prefs", "/folders", f"/sessions/{CO}/share-info", "/tree"):
            self.assertIn(self.req("GET", path, "bob"), (403, 404), path)
        self.assertEqual(self.done, [])

    def test_the_owner_deletes(self):
        self.assertEqual(self.req("POST", f"/sessions/{NONE_}/delete"), 200)
        self.assertEqual(self.done, [("delete", NONE_)])


if __name__ == "__main__":
    unittest.main()
