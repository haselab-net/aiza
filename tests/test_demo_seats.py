"""A demo room's seats (the deployment notes): the page's base is "/r/<seat>" when
it is opened under one, "" otherwise, and this browser's storage is the
seat's own -- two seats in two tabs of one browser do not see each other's
settings (i18n.js, the first script the page runs).

    python3 -m unittest discover -s tests -v
"""
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")
SEAT_A, SEAT_B = "a" * 24, "b" * 24

RUN = r"""
const store = new Map(JSON.parse(process.argv[3]));
const real = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)),
               removeItem: (k) => store.delete(k), key: (i) => [...store.keys()][i] ?? null, get length() { return store.size; } };
global.window = global;
Object.defineProperty(global, "localStorage", { value: real, configurable: true, writable: true });
global.location = { pathname: process.argv[2] };
global.document = { documentElement: {} };
require(process.argv[1]);
localStorage.setItem("aiza-x", "1");
console.log(JSON.stringify({ base: window.aizaBase, seen: localStorage.getItem("aiza-y"), n: localStorage.length,
                             store: [...store.entries()] }));
"""


@unittest.skipUnless(NODE, "node is needed")
class DemoSeatsTest(unittest.TestCase):
    def run_at(self, path, store=()):
        r = subprocess.run([NODE, "-e", RUN, str(ROOT / "static" / "i18n.js"), path, json.dumps(list(store))],
                           capture_output=True, text=True, timeout=30, check=True)
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_deployment_has_no_base_and_the_shared_storage(self):
        out = self.run_at("/work", [("aiza-y", "shared")])
        self.assertEqual(out["base"], "")
        self.assertEqual(out["seen"], "shared")
        self.assertIn(["aiza-x", "1"], out["store"])

    def test_a_seat_has_its_base_and_storage_of_its_own(self):
        out = self.run_at(f"/r/{SEAT_A}/work", [("aiza-y", "shared"), (f"seat:{SEAT_B}:aiza-y", "b's")])
        self.assertEqual(out["base"], f"/r/{SEAT_A}")
        self.assertIsNone(out["seen"])                  # neither the shared one nor the other seat's
        self.assertEqual(out["n"], 1)                   # only its own key counts
        self.assertIn([f"seat:{SEAT_A}:aiza-x", "1"], out["store"])
        self.assertNotIn(["aiza-x", "1"], out["store"])

    def test_not_a_seat_path(self):
        for path in ("/r/short/work", f"/r/{SEAT_A.upper()}/work", f"/x/r/{SEAT_A}/work", f"/r/{SEAT_A}"):
            self.assertEqual(self.run_at(path)["base"], "", path)


import hashlib
import hmac
import http.client
import os as _os
import tempfile
import threading
import time
from http.server import ThreadingHTTPServer

from test_gateway_login import load_gateway

G = load_gateway()
KEY = "ab" * 32
ROOM = "room00000001"


def signed(method, target, seat=SEAT_A, user="demo1", role="owner", room=ROOM, exp=None, key=KEY):
    exp = str(int(time.time()) + 60 if exp is None else exp)
    msg = "\n".join([room, seat, user, role, exp, method, target]).encode()
    return {"X-Demo-Room": room, "X-Demo-Seat": seat, "X-Demo-User": user, "X-Demo-Role": role, "X-Demo-Exp": exp,
            "X-Demo-Sig": hmac.new(bytes.fromhex(key), msg, hashlib.sha256).hexdigest()}


class DemoGateTest(unittest.TestCase):
    """The gateway in a demo room: only what the door signed gets in."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        keyf = Path(self.tmp.name) / "demo_room_key"
        keyf.write_text(KEY + "\n")
        self.saved = (G.DEMO_ROOM_KEY_FILE, G._demo_key, _os.environ.get("AIZA_DEMO_ROOM"), _os.environ.get("AIZA_DEMO_SEATS"))
        G.DEMO_ROOM_KEY_FILE, G._demo_key = keyf, None
        _os.environ["AIZA_DEMO_ROOM"], _os.environ["AIZA_DEMO_SEATS"] = ROOM, "8"

    def tearDown(self):
        G.DEMO_ROOM_KEY_FILE, G._demo_key = self.saved[0], self.saved[1]
        for k, v in (("AIZA_DEMO_ROOM", self.saved[2]), ("AIZA_DEMO_SEATS", self.saved[3])):
            if v is None:
                _os.environ.pop(k, None)
            else:
                _os.environ[k] = v
        self.tmp.cleanup()

    def check(self, method, target, h):
        return G.demo_check(method, target, h)

    def test_a_signed_seat_is_its_user_with_the_prefix_taken_off(self):
        t = f"/r/{SEAT_A}/agents/api/sessions?x=1"
        d = self.check("GET", t, signed("GET", t))
        self.assertEqual((d["user"], d["role"], d["base"], d["path"]), ("demo1", "owner", f"/r/{SEAT_A}", "/agents/api/sessions?x=1"))
        self.assertEqual(self.check("GET", f"/r/{SEAT_A}/", signed("GET", f"/r/{SEAT_A}/"))["path"], "/")

    def test_what_is_refused(self):
        t = f"/r/{SEAT_A}/work"
        bad = {
            "no headers": {},
            "another method": signed("POST", t),
            "another target": signed("GET", f"/r/{SEAT_A}/settings"),
            "another seat's target": signed("GET", f"/r/{SEAT_B}/work"),
            "stale": signed("GET", t, exp=int(time.time()) - 1),
            "too far ahead": signed("GET", t, exp=int(time.time()) + 600),
            "another room": signed("GET", t, room="room00000002"),
            "another key": signed("GET", t, key="cd" * 32),
            "beyond the seats": signed("GET", t, user="demo9"),
            "not a demo user": signed("GET", t, user="root"),
            "a role that is not": signed("GET", t, role="admin"),
            "the door's role on a seat": signed("GET", t, role="door"),
        }
        for name, h in bad.items():
            self.assertIsNone(self.check("GET", t, h), name)
        h = signed("GET", t)
        h["X-Demo-User"] = "demo2"            # changed after signing
        self.assertIsNone(self.check("GET", t, h))

    def test_the_door_itself_only_on_its_own_paths(self):
        h = signed("POST", "/_room/kick", seat="-", user="demo3", role="door")
        self.assertEqual(self.check("POST", "/_room/kick", h)["role"], "door")
        h = signed("GET", f"/r/{SEAT_A}/work", seat="-", role="door")
        self.assertIsNone(self.check("GET", f"/r/{SEAT_A}/work", h))

    def test_through_the_gateway(self):
        static = Path(self.tmp.name) / "static"
        static.mkdir()
        (static / "manifest.json").write_text('{"start_url": "/work", "scope": "/", "icons": [{"src": "/agents/icons/a.png"}]}')
        saved = G.STATIC_DIR
        G.STATIC_DIR = static
        srv = ThreadingHTTPServer(("127.0.0.1", 0), G.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            def get(target, headers):
                c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
                c.request("GET", target, headers=headers)
                r = c.getresponse()
                out = r.status, r.read()
                c.close()
                return out
            t = f"/r/{SEAT_A}/agents/manifest.json"
            self.assertEqual(get(t, {})[0], 403)                        # not through the door
            status, body = get(t, signed("GET", t))
            self.assertEqual(status, 200)
            m = json.loads(body)
            self.assertEqual((m["start_url"], m["scope"], m["icons"][0]["src"]),
                             (f"/r/{SEAT_A}/work", f"/r/{SEAT_A}/", f"/r/{SEAT_A}/agents/icons/a.png"))
        finally:
            srv.shutdown()
            srv.server_close()
            G.STATIC_DIR = saved


class DeploymentUnchangedTest(unittest.TestCase):
    def test_without_the_room_key_nothing_is_checked(self):
        saved = (G.DEMO_ROOM_KEY_FILE, G._demo_key)
        G.DEMO_ROOM_KEY_FILE, G._demo_key = Path("/nonexistent/demo_room_key"), None
        try:
            self.assertIsNone(G.demo_room_key())
            self.assertIsNone(G.demo_check("GET", f"/r/{SEAT_A}/work", signed("GET", f"/r/{SEAT_A}/work")))
        finally:
            G.DEMO_ROOM_KEY_FILE, G._demo_key = saved


from test_shared_search import B


class DemoRoomBackendTest(unittest.TestCase):
    """In a demo room the backend starts only the demo's AI (the deployment notes)."""

    def setUp(self):
        self.saved = B.DEMO_ROOM
        B.DEMO_ROOM = ROOM

    def tearDown(self):
        B.DEMO_ROOM = self.saved

    def test_nothing_else_is_started(self):
        for preset in ("shell", "claude-tui", "codex-tui", "host-shell", "root-shell", "claude-login", "mail-tui"):
            with self.assertRaises(ValueError, msg=preset):
                B.create_session(preset, "x")
        with self.assertRaises(ValueError):
            B.adopt_session("x", "container", "x")

    def test_a_deployment_is_not_a_demo(self):
        B.DEMO_ROOM = ""
        with self.assertRaises(ValueError) as e:
            B.create_session("agent", "x")
        self.assertIn("only in the demo", str(e.exception))
        with self.assertRaises(ValueError) as e:
            B.create_session("no-such-preset", "x")
        self.assertIn("unknown preset", str(e.exception))


import base64
import socketserver
from http.server import BaseHTTPRequestHandler


class _HtmlBackend(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    """A stand-in backend answering every request with an HTML file a session made."""
    daemon_threads = True

    def __init__(self, path):
        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def address_string(self):
                return "backend"

            def do_GET(self):
                out = b"<script>parent.document.cookie</script>"
                kind = self.path.split("t=", 1)[1].replace("%2F", "/") if "t=" in self.path else "text/html"
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
        super().__init__(path, H)


class PageGuardTest(DemoGateTest):
    """What a page may load (CSP, inline scripts by hash), and what a session
    made (HTML/SVG/XML) never being a page of the site (the deployment notes C)."""

    def serve(self):
        static = Path(self.tmp.name) / "static"
        static.mkdir(exist_ok=True)
        (static / "outbox-browse.html").write_text("<!doctype html><script>var a=1;</script><script src=\"/agents/x.js\"></script>")
        backend = _HtmlBackend(str(Path(self.tmp.name) / "be.sock"))
        threading.Thread(target=backend.serve_forever, daemon=True).start()
        saved = (G.STATIC_DIR, G.backend_socket_path_for)
        G.STATIC_DIR, G.backend_socket_path_for = static, (lambda user: backend.server_address)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), G.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self._port = srv.server_address[1]

        def done():
            srv.shutdown(); srv.server_close(); backend.shutdown(); backend.server_close()
            G.STATIC_DIR, G.backend_socket_path_for = saved
        self.addCleanup(done)

        def get(target, headers):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            c.request("GET", target, headers=headers)
            r = c.getresponse()
            out = r.status, {k.lower(): v for k, v in r.getheaders()}, r.read()
            c.close()
            return out
        return get

    def test_a_page_in_a_seat_has_the_policy_enforced_with_its_inline_scripts_hashes(self):
        get = self.serve()
        t = f"/r/{SEAT_A}/agents/outbox-browse.html"
        status, h, body = get(t, signed("GET", t))
        self.assertEqual(status, 200)
        csp = h["content-security-policy"]
        want = "'sha256-" + base64.b64encode(bytes.fromhex(hashlib.sha256(b"var a=1;").hexdigest())).decode() + "'"
        self.assertIn(f"script-src 'self' {want};", csp)
        for part in ("default-src 'self'", "object-src 'none'", "base-uri 'none'", "frame-ancestors 'self'"):
            self.assertIn(part, csp)
        self.assertNotIn("unsafe-inline';", csp.split("script-src")[1].split(";")[0])
        self.assertEqual(h["x-content-type-options"], "nosniff")
        self.assertIn(f'src="/r/{SEAT_A}/agents/x.js"', body.decode())

    def test_html_a_session_made_only_downloads_sandboxed_in_a_seat(self):
        get = self.serve()
        t = f"/r/{SEAT_A}/agents/api/sessions/0123456789ab/files/x.html"
        status, h, body = get(t, signed("GET", t))
        self.assertEqual(status, 200)
        self.assertEqual(h["content-security-policy"], "sandbox")
        self.assertEqual(h["content-disposition"], "attachment")
        self.assertEqual(h["x-content-type-options"], "nosniff")

    def test_on_a_deployment_the_page_policy_is_report_only(self):
        self.assertIn("script-src 'self' 'sha256-", G.page_csp(b"<script>x</script>"))
        self.assertEqual(G.page_csp(b"<p>no script</p>").split("script-src ")[1].split(";")[0], "'self'")
        self.assertTrue(G.ACTIVE_CONTENT_RE.match("image/svg+xml"))
        self.assertTrue(G.ACTIVE_CONTENT_RE.match("text/html; charset=utf-8"))
        self.assertFalse(G.ACTIVE_CONTENT_RE.match("application/json"))


class RoomDoorTest(PageGuardTest):
    """The room's own part (the deployment notes D): who a seat is, and the door
    sending someone out."""

    def test_every_answer_is_never_sniffed_and_sends_no_referer(self):
        # The audit's L1 (2026-11-28): a page, JSON, the backend's answer passed
        # through, an error, a refusal -- all of them, whichever route wrote it.
        get = self.serve()
        page = f"/r/{SEAT_A}/agents/outbox-browse.html"
        room = f"/r/{SEAT_A}/agents/demo/room"
        made = f"/r/{SEAT_A}/agents/api/sessions/0123456789ab/files/x.json?t=application%2Fjson"
        lost = f"/r/{SEAT_A}/agents/no-such-thing"
        for t, headers in ((page, signed("GET", page)), (room, signed("GET", room)), (made, signed("GET", made)),
                           (lost, signed("GET", lost)), (page, {})):
            status, h, _ = get(t, headers)
            self.assertEqual(h.get("x-content-type-options"), "nosniff", (t, status))
            self.assertEqual(h.get("referrer-policy"), "no-referrer", (t, status))

    def test_the_owner_is_shown_the_doors_page_and_a_guest_is_not(self):
        get = self.serve()
        t = f"/r/{SEAT_A}/agents/demo/room"
        status, _, body = get(t, signed("GET", t))
        self.assertEqual((status, json.loads(body)["door"]), (200, f"/r/{SEAT_A}/_door/"))
        status, _, body = get(t, signed("GET", t, user="demo2", role="guest"))
        self.assertEqual((json.loads(body)["role"], json.loads(body)["door"]), ("guest", None))

    def test_the_door_sends_someone_out(self):
        kick = Path(self.tmp.name) / "kick"
        kick.mkdir()
        saved = G.DEMO_KICK_DIR
        G.DEMO_KICK_DIR = str(kick)
        self.addCleanup(lambda: setattr(G, "DEMO_KICK_DIR", saved))
        get = self.serve()

        def post(body, **kw):
            h = signed("POST", "/_room/kick", seat="-", role="door", **kw)
            h["Content-Type"] = "application/json"
            srv_port = self._port
            c = http.client.HTTPConnection("127.0.0.1", srv_port, timeout=10)
            c.request("POST", "/_room/kick", body=json.dumps(body), headers=h)
            r = c.getresponse()
            out = r.status
            r.read()
            c.close()
            return out
        self.assertEqual(post({"user": "demo3"}, user="demo3"), 200)
        self.assertTrue((kick / "demo3").exists())
        self.assertEqual(post({"user": "demo4"}, user="demo3"), 400)   # not the one signed for
        self.assertFalse((kick / "demo4").exists())
        status, _, _ = get("/_room/kick", signed("GET", "/_room/kick", seat="-", role="door"))
        self.assertEqual(status, 404)                                  # the door reads nothing


class AuditFixesTest(PageGuardTest):
    """The demo's audit (2026-11-28): G1, a file a session made never loads as
    a script or style of the site; D2, a door header said twice is refused."""

    def test_in_a_seat_only_set_types_open_in_the_page(self):
        get = self.serve()
        for kind, want in (("text/javascript", "application/octet-stream"), ("application/javascript", "application/octet-stream"),
                           ("text/css", "application/octet-stream"), ("application/wasm", "application/octet-stream"),
                           ("text/plain", "application/octet-stream"), ("application/pdf", "application/octet-stream"),
                           ("image/png", "image/png"), ("audio/mpeg", "audio/mpeg"),
                           ("application/json", "application/json"), ("text/event-stream", "text/event-stream")):
            t = f"/r/{SEAT_A}/agents/api/sessions/0123456789ab/files/x?t={kind.replace('/', '%2F')}"
            status, h, _ = get(t, signed("GET", t))
            self.assertEqual((status, h["content-type"]), (200, want), kind)
            self.assertEqual(h.get("content-disposition"),
                             "attachment; filename*=UTF-8''x" if want == "application/octet-stream" else None, kind)

    def test_a_door_header_said_twice_is_refused(self):
        self.serve()
        t = f"/r/{SEAT_A}/work"
        h = signed("GET", t)
        c = http.client.HTTPConnection("127.0.0.1", self._port, timeout=10)
        c.putrequest("GET", t)
        for k, v in h.items():
            c.putheader(k, v)
        c.putheader("X-Demo-User", "demo2")          # a second one
        c.endheaders()
        r = c.getresponse()
        r.read()
        c.close()
        self.assertEqual(r.status, 403)


class AttachmentNameTest(PageGuardTest):
    """A file sent as an attachment in a seat keeps its name, safely (RFC 6266)."""

    def test_the_name_goes_with_it(self):
        get = self.serve()
        for name, want in (("x.js", "x.js"), ("%E3%83%A1%E3%83%A2.css", "%E3%83%A1%E3%83%A2.css"),
                           ("a%22b%0D%0Ac%5C.js", "abc.js")):
            t = f"/r/{SEAT_A}/agents/api/sessions/0123456789ab/files/{name}?t=text%2Fjavascript"
            status, h, _ = get(t, signed("GET", t))
            self.assertEqual((status, h["content-disposition"]), (200, f"attachment; filename*=UTF-8''{want}"), name)
        self.assertEqual(G.demo_attachment("attachment; filename*=UTF-8''%E5%90%8D.txt", "/x/y"),
                         "attachment; filename*=UTF-8''%E5%90%8D.txt")
        self.assertEqual(G.demo_attachment(None, "/sessions/x/files/"), "attachment")
