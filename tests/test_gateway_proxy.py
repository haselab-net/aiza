"""What the gateway passes to a backend (the deployment notes, the deployment notes): only a
logged-in caller gets through; one's own API goes to one's own backend with
no "on behalf of"; a shared session's API goes to the owner's backend with
the caller as X-Aiza-On-Behalf-Of, and only the routes a shared session
allows (others are refused before any backend is reached); the caller's own
X-Aiza-* headers never pass; the per-browser unlock key is the login's.

    python3 -m unittest discover -s tests -v
"""
import getpass
import http.client
import json
import os
import socketserver
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from test_gateway_login import load_gateway
from test_gateway_session import Clock

G = load_gateway()
ME = getpass.getuser()
OTHER = "someone"          # a stand-in account name the test maps to its own backend


class FakeBackend(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path, seen):
        self.seen = seen

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def address_string(self):
                return "backend"

            def handle_one(self):
                if "/events?" in self.path:
                    # The chat's SSE stream, as aiza-backend sends it (no
                    # Content-Length, ends by closing), from a backend that
                    # then stops -- a restart or a deploy.
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "keep-alive")
                    self.end_headers()
                    self.wfile.write(b'data: {"seq": 1}\n\n')
                    self.wfile.flush()
                    self.close_connection = True
                    return
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n) if n else b""
                seen.append((self.server.name, self.command, self.path,
                             {k: v for k, v in self.headers.items() if k.lower().startswith("x-aiza")}, body))
                out = json.dumps({"ok": True}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)
            do_GET = do_POST = handle_one
        super().__init__(path, H)


class ProxyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / "secret").write_bytes(b"s" * 32)
        names = ("COOKIE_SECRET_FILE", "SESSION_STORE_PATH", "SESSION_STORE_LOCK_PATH", "time", "backend_socket_path_for")
        self.saved = {k: getattr(G, k) for k in names}
        G.COOKIE_SECRET_FILE = str(d / "secret")
        G.SESSION_STORE_PATH = d / "sessions.json"
        G.SESSION_STORE_LOCK_PATH = d / ".lock"
        self.clock = G.time = Clock()
        self.seen = []
        self.backends = {}
        for user in (ME, OTHER):
            b = FakeBackend(str(d / f"{user}.sock"), self.seen)
            b.name = user
            threading.Thread(target=b.serve_forever, daemon=True).start()
            self.backends[user] = b

        def sock_for(user):
            if user not in self.backends:
                raise KeyError(user)
            return self.backends[user].server_address
        G.backend_socket_path_for = sock_for
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), G.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        cookie, _ = G.make_session_cookie(ME)
        self.cookie = cookie
        self.chain = G.check_and_rotate_session(cookie)[3]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for b in self.backends.values():
            b.shutdown()
            b.server_close()
        G._backend_pool_clear() if hasattr(G, "_backend_pool_clear") else None
        for k, v in self.saved.items():
            setattr(G, k, v)
        self.tmp.cleanup()

    def req(self, method, path, headers=None, body=None, cookie=True):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        h = dict(headers or {})
        if cookie:
            h["Cookie"] = f"{G.SESSION_COOKIE}={self.cookie}"
        if body is not None:
            h["Content-Type"] = "application/json"
        c.request(method, G.BASE_PATH + path, body=body, headers=h)
        r = c.getresponse()
        data = r.read()
        out = (r.status, [v for k, v in r.getheaders() if k.lower() == "set-cookie"], data)
        c.close()
        return out

    def test_a_stream_the_backend_ends_ends_for_the_phone_too(self):
        # 2026-11-25 (user report "書き込んだあと、チャット欄になかなか出ない"):
        # the backend restarted under an open chat; the gateway saw its
        # stream end but kept the phone's connection open, so the page
        # never noticed, never reopened it, and showed nothing new. The
        # stream must end for the phone as soon as it ends for the gateway.
        # Sent as nginx sends it (HTTP/1.1, Connection: close).
        import socket
        s = socket.create_connection(("127.0.0.1", self.server.server_port), timeout=5)
        s.sendall((f"GET {G.BASE_PATH}/api/sessions/aaaaaaaaaa00/events?since=0 HTTP/1.1\r\n"
                   f"Host: localhost\r\nConnection: close\r\n"
                   f"Cookie: {G.SESSION_COOKIE}={self.cookie}\r\n\r\n").encode())
        got = b""
        try:
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                got += chunk
        except socket.timeout:
            self.fail("the gateway kept the phone's stream open after the backend ended it")
        finally:
            s.close()
        self.assertTrue(got.startswith(b"HTTP/1.1 200"), got[:80])
        self.assertIn(b'data: {"seq": 1}', got)
        self.assertNotIn(b"keep-alive", got.split(b"\r\n\r\n", 1)[0].lower())

    def test_not_logged_in_reaches_no_backend(self):
        status, _, _ = self.req("GET", "/api/sessions", cookie=False)
        self.assertEqual(status, 401)
        status, _, _ = self.req("GET", f"/api/shared/{OTHER}/sessions", cookie=False)
        self.assertEqual(status, 401)
        self.assertEqual(self.seen, [])

    def test_ones_own_api_goes_to_ones_own_backend(self):
        status, _, _ = self.req("GET", "/api/sessions?x=1")
        self.assertEqual(status, 200)
        [(who, method, path, xh, _)] = self.seen
        self.assertEqual((who, method, path), (ME, "GET", "/sessions?x=1"))
        self.assertNotIn("X-Aiza-On-Behalf-Of", xh)
        self.assertEqual(xh.get("X-Aiza-Unlock-Key"), G.unlock_key_for(self.chain))

    def test_the_callers_own_aiza_headers_never_pass(self):
        forged = {"X-Aiza-On-Behalf-Of": "root", "X-Aiza-Unlock-Key": "k" * 40, "X-Aiza-User": "root"}
        self.req("POST", "/api/sessions/aaaaaaaaaa00/messages", headers=forged, body=b'{"text":"x"}')
        self.req("GET", f"/api/shared/{OTHER}/sessions", headers=forged)
        [(_, _, _, own, body), (_, _, _, shared, _)] = self.seen
        self.assertEqual(body, b'{"text":"x"}')
        self.assertEqual(own, {"X-Aiza-Unlock-Key": G.unlock_key_for(self.chain)})
        self.assertEqual(shared, {"X-Aiza-On-Behalf-Of": ME, "X-Aiza-Unlock-Key": G.unlock_key_for(self.chain)})

    def test_a_shared_session_goes_to_the_owners_backend_on_behalf_of_the_caller(self):
        for method, path in (("GET", "/sessions"), ("GET", "/sessions/aaaaaaaaaa00/events/page"),
                             ("GET", "/sessions/aaaaaaaaaa00/files/a.png"), ("POST", "/sessions/aaaaaaaaaa00/messages"),
                             ("POST", "/sessions/aaaaaaaaaa00/join")):
            self.seen.clear()
            status, _, _ = self.req(method, f"/api/shared/{OTHER}{path}", body=b"{}" if method == "POST" else None)
            self.assertEqual(status, 200, path)
            [(who, m, p, xh, _)] = self.seen
            self.assertEqual((who, m, p, xh.get("X-Aiza-On-Behalf-Of")), (OTHER, method, path, ME), path)

    def test_what_a_shared_session_does_not_allow_reaches_no_backend(self):
        for method, path in (("POST", "/sessions"), ("POST", "/push/subscribe"), ("GET", "/capabilities"),
                             ("POST", "/sessions/aaaaaaaaaa00/delete"), ("POST", "/sessions/aaaaaaaaaa00/share"),
                             ("GET", "/sessions/../capabilities"), ("GET", "/sessions/aaaaaaaaaa00/files/a/b"),
                             ("POST", "/chrome/kill"), ("GET", "/prefs")):
            status, _, _ = self.req(method, f"/api/shared/{OTHER}{path}", body=b"{}" if method == "POST" else None)
            self.assertEqual(status, 403, path)
        self.assertEqual(self.seen, [])

    def test_no_such_owner(self):
        status, _, _ = self.req("GET", "/api/shared/no-such-user-xyz/sessions")
        self.assertEqual(status, 404)
        self.assertEqual(self.seen, [])

    def test_a_system_account_has_no_backend(self):
        G.backend_socket_path_for = self.saved["backend_socket_path_for"]
        for user in ("root", "daemon"):
            status, _, _ = self.req("GET", f"/api/shared/{user}/sessions")
            self.assertEqual(status, 404, user)
        self.assertEqual(self.seen, [])

    def test_a_cookie_due_for_rotation_comes_back_renewed(self):
        self.clock.now += G.SESSION_ROTATE_INTERVAL
        status, cookies, _ = self.req("GET", "/api/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(len(cookies), 1)
        self.assertTrue(cookies[0].startswith(G.SESSION_COOKIE + "="))


if __name__ == "__main__":
    unittest.main()
