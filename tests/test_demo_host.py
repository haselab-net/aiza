"""The public demo's host side (docker/demo-host): the relay and the door, run
as they are, against stand-ins for the Claude API and the room. What the
security review of 2026-11-28 asked for (R1, R2, R3, D1, D2)."""
import hashlib, hmac, http.server, json, os, socket, subprocess, sys, tempfile, threading, time, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST_DIR = ROOT / "docker" / "demo-host"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def raw(port, data, read=True, timeout=10):
    s = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    s.sendall(data)
    out = b""
    if read:
        try:
            while (b := s.recv(65536)):
                out += b
        except socket.timeout:
            pass
    s.close()
    return out


def wait_port(port):
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("did not start")


class Upstream(http.server.BaseHTTPRequestHandler):
    """Stands in for api.anthropic.com: keeps what it got, answers with usage."""
    got = []
    delay = 0

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        Upstream.got.append((self.path, dict(self.headers), self.rfile.read(n)))
        time.sleep(Upstream.delay)
        b = json.dumps({"type": "message", "usage": {"input_tokens": 1000, "output_tokens": 100}}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def log_message(self, *a):
        pass


class RelayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        threading.Thread(target=cls.up.serve_forever, daemon=True).start()
        cls.d = tempfile.mkdtemp(prefix="relay-")
        cls.port = free_port()
        (Path(cls.d) / "anthropic.key").write_text("sk-real-key\n")
        (Path(cls.d) / "relay.secret").write_text("s3cret\n")
        (Path(cls.d) / "relay.json").write_text(json.dumps({
            "host": "127.0.0.1", "port": cls.port, "upstream": ["127.0.0.1", cls.up.server_port, False],
            "models": ["claude-sonnet-5-5"], "max_tokens": 32000, "usd_hold_per_request": 0.25,
            "usd_per_day": {"seat": 0.4, "room": 10, "total": 10}, "max_inflight_per_seat": 3}))
        env = dict(os.environ, CREDENTIALS_DIRECTORY=cls.d, STATE_DIRECTORY=cls.d)
        cls.p = subprocess.Popen([sys.executable, str(HOST_DIR / "aiza-demo-relay")], env=env,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_port(cls.port)
        cls.until = int(time.time()) + 3600

    @classmethod
    def tearDownClass(cls):
        cls.p.kill()
        cls.p.wait()
        cls.up.shutdown()

    def key(self, room="r1", user="demo1", until=None):
        until = until or self.until
        sig = hmac.new(b"s3cret", f"{room}.{user}.{until}".encode(), hashlib.sha256).hexdigest()[:32]
        return f"demo.{room}.{user}.{until}.{sig}"

    def post(self, body, target="/anthropic/v1/messages?beta=true", extra=b"", key=None):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        head = (f"POST {target} HTTP/1.1\r\nHost: x\r\nx-api-key: {key or self.key()}\r\n"
                f"content-type: application/json\r\nContent-Length: {len(b)}\r\n").encode() + extra + b"\r\n"
        return raw(self.port, head + b)

    def setUp(self):
        Upstream.got.clear()
        Upstream.delay = 0

    BODY = {"model": "claude-sonnet-5-5", "max_tokens": 128000, "messages": [{"role": "user", "content": "hi"}]}

    def status(self, out):
        return int(out.split(b" ", 2)[1])

    def test_passes_and_rewrites(self):
        out = self.post(self.BODY, extra=b"anthropic-beta: claude-code-20250219,files-api-2025-04-14\r\nuser-agent: claude-cli/x (external, sdk-py)\r\n")
        self.assertEqual(self.status(out), 200)
        path, hdr, body = Upstream.got[-1]
        self.assertEqual(path, "/v1/messages?beta=true")
        self.assertEqual(hdr["x-api-key"], "sk-real-key")
        self.assertEqual(hdr["anthropic-beta"], "claude-code-20250219")       # files-api dropped
        self.assertEqual(json.loads(body)["max_tokens"], 32000)

    def test_control_characters_in_the_head(self):
        for extra in (b"user-agent: a\nx-api-key: other\r\n", b"user-agent: a\rb\r\n", b"user-agent: a\x00\r\n"):
            out = self.post(self.BODY, extra=extra)
            self.assertEqual(self.status(out), 400, extra)
            self.assertIn(b"x-should-retry: false", out)
        out = self.post(self.BODY, target="/anthropic/v1/messages?beta=true\nGET /v1/files")
        self.assertEqual(self.status(out), 400)
        self.assertEqual(Upstream.got, [])

    def test_only_the_messages_api(self):
        for t in ("/anthropic/v1/files", "/anthropic/v1/messages/batches", "/anthropic/v1/messages?x=1", "/other"):
            self.assertEqual(self.status(self.post(self.BODY, target=t)), 403, t)
        self.assertEqual(Upstream.got, [])

    def test_body_is_checked(self):
        bad = [
            dict(self.BODY, tools=[{"type": "web_fetch_20250910", "name": "web_fetch"}]),
            dict(self.BODY, tools=[{"type": "web_search_20250305", "name": "web_search"}]),
            dict(self.BODY, mcp_servers=[{"type": "url", "url": "https://example.org/mcp", "name": "x"}]),
            dict(self.BODY, container="c1"),
            dict(self.BODY, model="claude-opus-5-5"),
            dict(self.BODY, messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "url", "url": "https://example.org/x?d=secret"}}]}]),
            dict(self.BODY, messages=[{"role": "user", "content": [
                {"type": "document", "source": {"type": "file", "file_id": "file_1"}}]}]),
        ]
        for b in bad:
            self.assertEqual(self.status(self.post(b)), 400, b)
        dup = b'{"model":"claude-opus-5-5","model":"claude-sonnet-5-5","max_tokens":1,"messages":[]}'
        self.assertEqual(self.status(self.post(dup)), 400)
        self.assertEqual(Upstream.got, [])
        ok = dict(self.BODY, tools=[{"name": "Bash", "description": "d", "input_schema": {"type": "object"}}])
        self.assertEqual(self.status(self.post(ok)), 200)

    def test_odd_bodies_are_refused_and_closed(self):
        # F1, F2 of the review: a lone surrogate, deep nesting, a max_tokens that is not an integer
        for b in (b'{"model":"claude-sonnet-5-5","max_tokens":10,"messages":[{"role":"user","content":"\\ud800"}]}',
                  b'{"model":"claude-sonnet-5-5","max_tokens":10,"messages":' + b"[" * 50000 + b"]" * 50000 + b"}",
                  json.dumps(dict(self.BODY, max_tokens=1e9)).encode(),
                  json.dumps(dict(self.BODY, max_tokens="100")).encode()):
            self.assertEqual(self.status(self.post(b)), 400, b[:80])
        self.assertEqual(Upstream.got, [])

    def test_seat_key(self):
        self.assertEqual(self.status(self.post(self.BODY, key=self.key(until=int(time.time()) - 1))), 401)
        k = self.key()
        self.assertEqual(self.status(self.post(self.BODY, key=k[:-1] + ("0" if k[-1] != "0" else "1"))), 401)

    def test_budget_counts_requests_in_flight(self):
        # seat budget 0.4, 0.25 set aside per request: the second at once is refused
        Upstream.delay = 1.5
        k = self.key(room="r2", user="demo2")
        res = {}
        t = threading.Thread(target=lambda: res.setdefault("a", self.post(self.BODY, key=k)))
        t.start()
        time.sleep(0.5)
        second = self.post(self.BODY, key=k)
        t.join()
        self.assertEqual(self.status(res["a"]), 200)
        self.assertEqual(self.status(second), 429)
        self.assertIn(b"x-should-retry: false", second)


class DoorTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp(prefix="door-")
        self.port = free_port()
        self.room_port = free_port()
        self.kicks = []
        kicks = self.kicks

        class Room(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                b = json.dumps({"user": self.headers.get("X-Demo-User"), "n": len(self.headers.get_all("X-Demo-User") or [])}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self):
                kicks.append(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                self.send_response(200)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass

        self.room = http.server.ThreadingHTTPServer(("127.0.0.1", self.room_port), Room)
        threading.Thread(target=self.room.serve_forever, daemon=True).start()
        h = lambda s: hashlib.sha256(s.encode()).hexdigest()
        now = int(time.time())
        self.owner, self.guest = "a" * 24, "b" * 24
        st = {"rooms": {"room1": {"label": "", "created": now, "ends": now + 3600, "last": now, "max_seats": 3,
                                  "port": self.room_port, "key": "00" * 32, "seats": {
            self.owner: {"user": "demo1", "role": "owner", "token": None, "cookie": h("ck"), "created": now, "claimed": now},
            self.guest: {"user": "demo2", "role": "guest", "token": h("tk"), "cookie": None, "created": now, "claimed": None}}}}}
        (Path(self.d) / "rooms.json").write_text(json.dumps(st))
        (Path(self.d) / "relay.secret").write_text("s\n")
        env = dict(os.environ, DOOR_STATE=self.d, DOOR_HOST="demo.example.org", DOOR_VM="127.0.0.1",
                   DOOR_PORT=str(self.port), CREDENTIALS_DIRECTORY=self.d)
        self.p = subprocess.Popen([sys.executable, str(HOST_DIR / "aiza-demo-door")], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wait_port(self.port)

    def tearDown(self):
        self.p.kill()
        self.p.wait()
        self.room.shutdown()

    def req(self, method, path, body=b"", hdrs=b""):
        head = f"{method} {path} HTTP/1.1\r\nHost: x\r\n".encode() + hdrs
        if method == "POST":
            head += f"Content-Length: {len(body)}\r\n".encode()
        return raw(self.port, head + b"\r\n" + body)

    def status(self, out):
        return int(out.split(b" ", 2)[1])

    def test_signed_hand_off(self):
        out = self.req("GET", f"/r/{self.owner}/work", hdrs=b"Cookie: aiza_demo_seat=ck\r\nX-Demo-User: demo3\r\n")
        self.assertEqual(self.status(out), 200)
        self.assertEqual(json.loads(out.split(b"\r\n\r\n", 1)[1]), {"user": "demo1", "n": 1})

    def test_bare_lf_or_cr_in_the_head(self):
        for h in (b"Cookie: aiza_demo_seat=ck\nX-Demo-User: demo3\r\n", b"Cookie: aiza_demo_seat=ck\rX: y\r\n", b"X: \x01\r\n"):
            self.assertEqual(self.status(self.req("GET", f"/r/{self.owner}/work", hdrs=h)), 400, h)

    def test_a_held_claim_does_not_bring_back_a_kicked_seat(self):
        # The guest's claim sends its head and holds the body; the owner kicks the
        # guest meanwhile; the late body must not bring the seat back.
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        b = json.dumps({"token": "tk"}).encode()
        s.sendall(f"POST /r/{self.guest}/_door/claim HTTP/1.1\r\nHost: x\r\nX-Door: 1\r\nContent-Length: {len(b)}\r\n\r\n".encode())
        time.sleep(0.3)
        kick = self.req("POST", f"/r/{self.owner}/_door/kick", json.dumps({"seat": self.guest}).encode(),
                        b"Cookie: aiza_demo_seat=ck\r\nX-Door: 1\r\n")
        self.assertEqual(self.status(kick), 200)
        s.sendall(b)
        out = b""
        while (x := s.recv(65536)):
            out += x
        s.close()
        self.assertIn(self.status(out), (403, 404))      # refused: the seat is gone
        st = json.loads((Path(self.d) / "rooms.json").read_text())
        self.assertNotIn(self.guest, st["rooms"]["room1"]["seats"])
        self.assertEqual(len(self.kicks), 1)

    def test_owner_only(self):
        self.assertEqual(self.status(self.req("POST", f"/r/{self.guest}/_door/invite", b"{}", b"X-Door: 1\r\n")), 403)
        self.assertEqual(self.status(self.req("POST", f"/r/{self.owner}/_door/invite", b"{}", b"Cookie: aiza_demo_seat=ck\r\n")), 403)
        out = self.req("POST", f"/r/{self.owner}/_door/invite", b"{}", b"Cookie: aiza_demo_seat=ck\r\nX-Door: 1\r\n")
        self.assertEqual(self.status(out), 200)
        self.assertIn(b"https://demo.example.org/r/", out)


if __name__ == "__main__":
    unittest.main()
