"""The tabs' addresses (the deployment notes, 2026-11-25): the gateway answers
/work (and its views), /inbox and /settings with the page, sends the old
/todo to /work/ball, and lets the service worker take the whole site.

    python3 -m unittest discover -s tests -v
"""
import http.client
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from test_gateway_login import load_gateway

G = load_gateway()


class TabRoutesTest(unittest.TestCase):
    def setUp(self):
        self.static = Path(tempfile.mkdtemp(prefix="aiza-test-tabs-"))
        for name, text in (("login.html", "LOGIN"), ("index.html", "INDEX"), ("sw.js", "// sw")):
            (self.static / name).write_text(text)
        self.saved = G.STATIC_DIR
        G.STATIC_DIR = self.static
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), G.Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        G.STATIC_DIR = self.saved

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        c.request("GET", path, headers={"Sec-Fetch-Mode": "navigate"})
        r = c.getresponse()
        body = r.read()
        headers = {k.lower(): v for k, v in r.getheaders()}
        c.close()
        return r.status, headers, body

    def test_each_tab_is_the_page(self):
        # Not logged in here: the login page, as /agents/ answers.
        for path in ("/work", "/work/", "/work/ball", "/work/week", "/work/usage", "/inbox", "/settings"):
            status, _, body = self.get(path)
            self.assertEqual((status, body), (200, b"LOGIN"), path)

    def test_other_paths_are_not_the_page(self):
        for path in ("/work/other", "/workshop", "/settingsx"):
            status, _, body = self.get(path)
            self.assertNotEqual(body, b"LOGIN", path)

    def test_the_old_todo_goes_to_ball(self):
        for path in ("/todo", "/agents/todo"):
            status, headers, _ = self.get(path)
            self.assertEqual(status, 302, path)
            self.assertTrue(headers["location"].endswith("/work/ball"), headers["location"])

    def test_the_service_worker_may_take_the_whole_site(self):
        status, headers, _ = self.get(f"{G.BASE_PATH}/sw.js")
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("service-worker-allowed"), "/")


if __name__ == "__main__":
    unittest.main()
