"""Read-only sharing and sharing with everyone (the deployment notes): a
reader gets the chat log, never the live screen or any action; a root shell
is only ever shared read-only; Email only with a named user (read-only or,
since 2026-11-25, co-working); everyone may co-work a devbox session only.

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

OWNER = B.getpass.getuser()
OTHER = "daemon" if OWNER != "daemon" else "bin"  # any real account but this one


class ShareReadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        stubs = {
            "session_roots": lambda: [self.root],
            # Always locked: `touch` says ok false, `status` unlocked false.
            "_unlockd_call": lambda verb, **fields: {"ok": verb == "status", "unlocked": False},
            "list_tmux_sessions": lambda: [],
            "list_host_tmux_sessions": lambda: [],
            "list_root_tmux_sessions": lambda: [],
            "ensure_watcher": lambda sid: None,
            "_load_links": lambda: {},
            "expire_links": lambda: None,
            "MAIL_PRESETS": {"mail-tui"},
        }
        self.saved = {name: getattr(B, name) for name in stubs}
        for name, value in stubs.items():
            setattr(B, name, value)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), B.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for name, value in self.saved.items():
            setattr(B, name, value)
        self.tmp.cleanup()

    def make(self, sid, preset, location, **extra):
        d = self.root / sid
        d.mkdir()
        meta = {"id": sid, "label": sid, "preset": preset, "tmux_location": location,
                "stopped": True, **extra}
        (d / "meta.json").write_text(json.dumps(meta))
        (d / "events.jsonl").write_text(json.dumps(
            {"type": "agent_output", "seq": 1, "ts": 1, "text": "log"}) + "\n")
        return sid

    def meta(self, sid):
        return json.loads((self.root / sid / "meta.json").read_text())

    def call(self, method, path, viewer=None, body=None):
        req = urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        if viewer is not None:
            req.add_header("X-Aiza-On-Behalf-Of", viewer)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    # -- share_mode --
    def test_modes(self):
        self.assertEqual(B.share_mode({"preset": "shell", "shared_with": ["bob"]}, "bob"), "write")
        self.assertEqual(B.share_mode({"preset": "shell", "shared_read": ["bob"]}, "bob"), "read")
        self.assertEqual(B.share_mode({"preset": "shell", "shared_read": ["*"]}, "anyone"), "read")
        self.assertIsNone(B.share_mode({"preset": "shell", "shared_read": ["bob"]}, "bobby"))
        self.assertIsNone(B.share_mode({"preset": "shell", "shared_read": "*"}, "bob"))
        # A root shell shared before 2026-10-15 as co-working is read-only now.
        self.assertEqual(B.share_mode({"preset": "root-shell", "shared_with": ["bob"]}, "bob"), "read")
        # Every pane that runs as root, the login ones too (2026-11-23).
        for p in ("root-shell", "claude-login-root", "codex-login-root"):
            m = {"preset": p, "tmux_location": "root", "shared_with": ["bob"]}
            self.assertEqual(B.share_mode(m, "bob"), "read", p)
        # Email: with a named user only -- never "*", even if meta says so;
        # co-working since 2026-11-25.
        self.assertEqual(B.share_mode({"preset": "mail-tui", "shared_read": ["bob"]}, "bob"), "read")
        self.assertIsNone(B.share_mode({"preset": "mail-tui", "shared_read": ["*"]}, "bob"))
        self.assertIsNone(B.share_mode({"preset": "mail-tui", "shared_read": ["bob"]}, "*"))
        self.assertEqual(B.share_mode({"preset": "mail-tui", "shared_with": ["bob"]}, "bob"), "write")
        self.assertIsNone(B.share_mode({"preset": "mail-tui", "shared_with": ["*"]}, "bob"))
        self.assertIsNone(B.share_mode({"preset": "mail-tui", "shared_with": ["bob"]}, "*"))
        self.assertEqual(B.share_mode({"preset": "mail-shell", "shared_with": ["bob"]}, "bob"), "read")
        # The box's Codex (launched in the box's shell) co-works like its Claude.
        self.assertEqual(B.share_mode({"preset": "mail-shell", "launch": "codex", "shared_with": ["bob"]}, "bob"), "write")
        self.assertIsNone(B.share_mode({"preset": "mail-shell", "launch": "codex", "shared_with": ["*"]}, "bob"))
        # Everyone co-works only a session in the owner's container.
        self.assertEqual(B.share_mode({"preset": "claude-tui", "shared_with": ["*"]}, "anyone"), "write")
        self.assertEqual(B.share_mode({"preset": "shell", "tmux_location": "container", "shared_with": ["*"]}, "x"), "write")
        for p, loc in (("host-shell", "host"), ("claude-tui", "host"), ("claude-tui", "ssh:box"), ("root-shell", "root")):
            m = {"preset": p, "tmux_location": loc, "shared_with": ["*"]}
            self.assertIsNone(B.share_mode(m, "anyone"), (p, loc))
        # A named collaborator still wins over everyone's read.
        self.assertEqual(B.share_mode({"preset": "shell", "shared_with": ["bob"], "shared_read": ["*"]}, "bob"), "write")

    # -- share_session --
    def test_share_rules(self):
        root = self.make("bbbb000000000001", "root-shell", "root")
        login_root = self.make("bbbb000000000009", "claude-login-root", "root")
        with self.assertRaises(ValueError):
            B.share_session(login_root, OTHER, mode="write")
        mail = self.make("bbbb000000000002", "mail-tui", "host")
        shell = self.make("bbbb000000000003", "shell", "container")
        with self.assertRaises(ValueError):
            B.share_session(root, OTHER, mode="write")
        with self.assertRaises(ValueError):
            B.share_session(mail, "*", mode="read")
        with self.assertRaises(ValueError):
            B.share_session(mail, "*", mode="write")
        B.share_session(mail, OTHER, mode="read")
        self.assertEqual(self.meta(mail)["shared_read"], [OTHER])
        B.share_session(mail, OTHER, mode="write")
        m = self.meta(mail)
        self.assertEqual((m["shared_read"], m["shared_with"]), ([], [OTHER]))
        host = self.make("bbbb00000000000a", "host-shell", "host")
        with self.assertRaises(ValueError):
            B.share_session(host, "*", mode="write")
        with self.assertRaises(ValueError):
            B.share_session(root, "*", mode="write")
        B.share_session(shell, "*", mode="write")
        self.assertEqual(self.meta(shell)["shared_with"], ["*"])
        B.unshare_session(shell, "*")
        with self.assertRaises(ValueError):
            B.share_session(shell, "*", mode="admin")
        with self.assertRaises(ValueError):
            B.share_session(shell, OWNER, mode="read")
        B.share_session(root, "*", mode="read")
        self.assertEqual(self.meta(root)["shared_read"], ["*"])
        # One mode per person: switching moves them between the lists.
        B.share_session(shell, OTHER, mode="write")
        B.share_session(shell, OTHER, mode="read")
        m = self.meta(shell)
        self.assertEqual((m["shared_read"], m["shared_with"]), ([OTHER], []))
        B.unshare_session(shell, OTHER)
        self.assertEqual(self.meta(shell)["shared_read"], [])

    # -- what a reader can reach --
    def test_reader_gets_root_log_without_window_but_nothing_else(self):
        sid = self.make("bbbb000000000004", "root-shell", "root", shared_read=["*"])
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page", "bob")[0], 200)
        self.assertEqual(self.call("GET", f"/sessions/{sid}/screen", "bob")[0], 403)
        for action in ("messages", "keys", "stop", "resize", "rename"):
            self.assertEqual(self.call("POST", f"/sessions/{sid}/{action}", "bob", {})[0], 403, action)
        status, body = self.call("GET", "/sessions", "bob")
        row = [s for s in body["sessions"] if s["id"] == sid][0]
        self.assertEqual(row["share_mode"], "read")
        self.assertEqual(row["label"], sid)  # not redacted: no window needed
        # The owner still needs their window.
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page")[0], 403)

    def test_collaborator_on_host_still_needs_window(self):
        sid = self.make("bbbb000000000005", "host-shell", "host", shared_with=["bob"])
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page", "bob")[0], 403)

    def test_everyone_share_reaches_strangers_read_only(self):
        sid = self.make("bbbb000000000006", "shell", "container", shared_read=["*"])
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page", "carol")[0], 200)
        self.assertEqual(self.call("POST", f"/sessions/{sid}/messages", "carol", {"text": "x"})[0], 403)
        hits = B.search_events("log", "carol")["hits"]
        self.assertEqual({h["session_id"] for h in hits}, {sid})

    def test_email_shared_read_with_a_named_user(self):
        sid = self.make("bbbb000000000008", "mail-tui", "host", shared_read=["bob"])
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page", "bob")[0], 200)
        self.assertEqual(self.call("GET", f"/sessions/{sid}/screen", "bob")[0], 403)
        for action in ("messages", "keys", "stop", "resize", "rename", "attach"):
            self.assertEqual(self.call("POST", f"/sessions/{sid}/{action}", "bob", {})[0], 403, action)
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page", "carol")[0], 404)
        status, body = self.call("GET", "/sessions", "carol")
        self.assertNotIn(sid, [s["id"] for s in body["sessions"]])
        status, body = self.call("GET", "/sessions", "bob")
        self.assertEqual([s["share_mode"] for s in body["sessions"] if s["id"] == sid], ["read"])
        self.assertEqual(self.call("POST", f"/sessions/{sid}/share", None, {"username": "*", "mode": "read"})[0], 400)

    def test_email_collaborator_needs_no_window_of_the_owners(self):
        # 2026-11-25: a named collaborator on an Email session acts without
        # the owner's passkey window (the stub keeps every window locked).
        sid = self.make("bbbb00000000000b", "mail-tui", "host", shared_with=["bob"])
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page", "bob")[0], 200)
        status, body = self.call("POST", f"/sessions/{sid}/rename", "bob", {"label": "renamed"})
        self.assertEqual(status, 200, body)
        status, body = self.call("GET", "/sessions", "bob")
        row = [s for s in body["sessions"] if s["id"] == sid][0]
        self.assertEqual((row["share_mode"], row["label"]), ("write", "renamed"))
        # Nobody else, and the owner still needs their own window.
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page", "carol")[0], 404)
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page")[0], 403)
        # A collaborator may attach a file; a reader may not.
        self.assertTrue(B._shared_post_path_allowed(["sessions", sid, "attach"]))
        # The answer to a card (the outward gate) is not a shared route.
        self.assertEqual(self.call("POST", f"/sessions/{sid}/ask", "bob", {})[0], 403)

    def test_email_codex_coworks_only_while_codex_runs(self):
        # 2026-11-25 ("codexも共有したい"): the box's Codex co-works, the
        # box's plain shell does not -- not even the one Codex leaves behind.
        cx = self.make("bbbb00000000000e", "mail-shell", "host", launch="codex")
        sh = self.make("bbbb00000000000f", "mail-shell", "host")
        with self.assertRaises(ValueError):
            B.share_session(sh, OTHER, mode="write")
        with self.assertRaises(ValueError):
            B.share_session(cx, "*", mode="write")
        B.share_session(cx, OTHER, mode="write")
        self.assertEqual(self.meta(cx)["shared_with"], [OTHER])
        self.assertTrue(B.share_waives_window(self.meta(cx), "write"))
        saved = B._codex_relay_active
        try:
            B._codex_relay_active = lambda sid, meta, sdir: False
            for action in ("messages", "keys", "attach"):
                status, body = self.call("POST", f"/sessions/{cx}/{action}", OTHER, {})
                self.assertEqual(status, 403, action)
                self.assertIn("Codex is not running", body.get("error", ""), action)
            self.assertEqual(self.call("POST", f"/sessions/{cx}/rename", OTHER, {"label": "x"})[0], 200)
            B._codex_relay_active = lambda sid, meta, sdir: True
            self.assertFalse(B._shared_codex_gone(["sessions", cx, "messages"]))
        finally:
            B._codex_relay_active = saved
        # Claude's box session is never asked about Codex.
        self.assertFalse(B._shared_codex_gone(["sessions", self.make("bbbb000000000010", "mail-tui", "host"), "keys"]))

    def test_share_waiver_covers_host_tier_only(self):
        B._REQ.share_waived = True
        try:
            B.require_unlock_if_outside_sandbox("host")          # no raise
            with self.assertRaises(B.UnlockRequired):
                B.require_unlock_if_outside_sandbox("root")
        finally:
            B._REQ.share_waived = False
        with self.assertRaises(B.UnlockRequired):
            B.require_unlock_if_outside_sandbox("host")

    def test_everyone_coworks_a_devbox_session(self):
        sid = self.make("bbbb00000000000c", "claude-tui", "container", shared_with=["*"])
        self.assertEqual(self.call("GET", f"/sessions/{sid}/events/page", "carol")[0], 200)
        status, body = self.call("POST", f"/sessions/{sid}/rename", "carol", {"label": "by carol"})
        self.assertEqual(status, 200, body)
        host = self.make("bbbb00000000000d", "host-shell", "host", shared_with=["*"])
        self.assertEqual(self.call("GET", f"/sessions/{host}/events/page", "carol")[0], 404)
        status, meta = self.call("POST", f"/sessions/{host}/share", None, {"username": "*", "mode": "write"})
        self.assertEqual(status, 400, meta)

    def test_share_route_takes_mode(self):
        sid = self.make("bbbb000000000007", "shell", "container")
        status, meta = self.call("POST", f"/sessions/{sid}/share", None, {"username": "*", "mode": "read"})
        self.assertEqual((status, meta.get("shared_read")), (200, ["*"]))
        self.assertEqual(self.call("POST", f"/sessions/{sid}/share", "bob", {"username": "*", "mode": "read"})[0], 403)


if __name__ == "__main__":
    unittest.main()
