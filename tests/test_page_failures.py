"""What the page does when something on the way fails, in headless Chrome
against the stand-in backend (the deployment notes). The page flows
(test_page_flow.py) check its moves between pages; these check the
branches that do not move it, where a mistake loses what the user typed or
leaves a chat that silently stops updating:
- sending: the text goes as typed; a failed send puts it back in the box
  (before what was typed meanwhile) and says so; a send that needs the
  passkey asks for it and sends the same text once more;
- a chat's live events: each is drawn once (the stream may send one again),
  a stream that ended is reopened from the last event received, a history
  that could not be read is replayed from the start, and a passkey window
  that closed under the stream says so and stops reopening.

    python3 -m unittest discover -s tests -v
"""
import json
import re
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from page_harness import EVENTS, T0, serve
from test_page_flow import CHROME

S0 = "aaaaaaaaaa00"
PAGE = f"GET /sessions/{S0}/events/page"
STREAM = f"GET /sessions/{S0}/events"
SEND = f"POST /sessions/{S0}/messages"
S1 = "aaaaaaaaaa01"
OPENED_S1 = f"GET /sessions/{S1}/events/page?limit=50"
KEYS = f"POST /sessions/{S0}/keys"
ATTACH = f"POST /sessions/{S0}/attach"
UNLOCK = {"status": 403, "body": {"error": "unlock", "unlock_required": True, "tier": "host"}}

# The probe: the page opened on s0's chat, then each step (JS run in the
# page) with the wait before the next; `out` (with the page's errors) is
# written into the page for the test to read.
PROBE = r"""
(function () {
  const out = {};
  window.__alerts = [];
  window.confirm = () => true; window.prompt = () => "1"; window.alert = (m) => window.__alerts.push(String(m));
  document.hasFocus = () => true;
  try { Object.defineProperty(navigator.credentials, "get", { value: async () => ({ toJSON: () => ({ id: "fake" }) }) }); } catch (e) {}
  const box = () => document.getElementById("text");
  const type = (s) => { box().value = s; box().dispatchEvent(new Event("input", { bubbles: true })); };
  const sendBtn = () => document.getElementById("send-btn");
  const bubbles = (sel) => [...document.querySelectorAll("#messages " + sel)].map((e) => e.textContent.trim());
  const historyTop = () => { const el = document.querySelector("#messages .history-top"); return el ? el.textContent : ""; };
  const tap = (sel, text) => { const el = [...document.querySelectorAll(sel)].find((x) => x.textContent === text); if (el) el.click(); else out.missing = sel + "|" + text; };
  const pick = (name) => {
    const input = document.getElementById("attach-file-input");
    const dt = new DataTransfer(); dt.items.add(new File(["x"], name, { type: "text/plain" }));
    input.files = dt.files; input.dispatchEvent(new Event("change"));
  };
  const scrollTop = () => { const m = document.getElementById("messages"); m.scrollTop = 0; m.dispatchEvent(new Event("scroll")); };
  const steps = __STEPS__;
  let i = 0;
  function next() {
    if (i === steps.length) {
      out.alerts = window.__alerts;
      out.errors = (window.__aizaPageErrors || ["no checkPage"]).concat(window.__jsErrors || []);
      const pre = document.createElement("pre"); pre.id = "probe-out";
      pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
      return;
    }
    const [fn, wait] = steps[i++];
    try { fn(); } catch (e) { out.thrown = String(e); }
    setTimeout(next, wait);
  }
  setTimeout(next, 2500);
})();
"""


def ev(seq, text, kind="agent_output"):
    return {"seq": seq, "ts": T0 + seq, "type": kind, "text": text}


# name: (faults, [(js, wait ms)], budget ms)
CASES = {
    "send": ({}, [
        ("type('hello')", 300),
        ("sendBtn().click()", 1500),
        ("out.box = box().value", 100),
    ]),
    "send fails, the text comes back before what was typed since": ({SEND: [{"status": 502, "body": {"error": "bad gateway"}}]}, [
        ("type('hello')", 300),
        # typed while the send is on its way (the box is cleared at once)
        ("sendBtn().click(); out.cleared = box().value; type('next')", 3000),
        ("out.box = box().value", 100),
        ("sendBtn().click()", 1500),
        ("out.after = box().value", 100),
    ]),
    "send asks for the passkey, then sends the same text": ({SEND: [UNLOCK]}, [
        ("type('hello')", 300),
        ("sendBtn().click()", 3000),
        ("out.box = box().value", 100),
    ]),
    "live events: each once, a stream that ended reopens from the last": ({STREAM: [
        {"sse": [ev(2, "二つ目"), ev(1, "needle", "user_message"), ev(3, "三つ目")]},
        {"status": 502},
        {"sse": [ev(3, "三つ目"), ev(4, "四つ目")]},
    ]}, [
        ("", 9000),
        ("out.agent = bubbles('.bubble.agent'); out.user = bubbles('.bubble.user')", 100),
    ]),
    "history unreadable: the stream replays from the start": ({PAGE: [{"status": 500, "body": {"error": "x"}}], STREAM: [
        {"sse": [ev(1, "needle", "user_message"), ev(2, "二つ目")]},
    ]}, [
        ("", 1500),
        ("out.agent = bubbles('.bubble.agent'); out.user = bubbles('.bubble.user')", 100),
    ]),
    "the passkey window closes under the stream": ({STREAM: [{"status": 403, "body": UNLOCK["body"]}],
                                                    PAGE: [{"body": {"events": EVENTS, "has_more": False}}, UNLOCK]}, [
        ("", 8000),
        ("out.top = document.getElementById('messages').textContent.includes('パスキーの解錠が切れました')", 100),
    ]),
    "keys: the armed modifiers go with the next key only": ({}, [
        ("tap('#key-modrow button.mod', 'Ctrl'); tap('#key-modrow button.mod', '⇧')", 300),
        ("tap('#key-grid button', 'a')", 600),
        ("tap('#key-modrow button', '↑')", 600),
        ("tap('#key-grid button.chord', 'x s')", 1200),
    ]),
    "keys: one that needs the passkey is sent again after it": ({KEYS: [UNLOCK]}, [
        ("tap('#key-modrow button', 'Esc')", 3000),
    ]),
    "attach: the file's path goes into the box": ({ATTACH: [{"status": 201, "body": {"path": "/inbox/a.txt"}}]}, [
        ("type('abc')", 300),
        ("pick('a.txt')", 1500),
        ("out.box = box().value", 100),
    ]),
    "attach fails: said, the box as it was": ({ATTACH: [{"status": 413, "body": {"error": "attachment too large"}}]}, [
        ("type('abc')", 300),
        ("pick('a.txt')", 1500),
        ("out.box = box().value", 100),
    ]),
    "older history: a failed page is tried again by scrolling": ({PAGE + "?limit=50": [
        {"body": {"events": [ev(50, "五十"), ev(51, "五十一")], "has_more": True}}], PAGE + "?before=50&limit=50": [
        {"status": 500, "body": {"error": "x"}},
        {"body": {"events": [ev(48, "四十八"), ev(49, "四十九")], "has_more": False}},
    ]}, [
        ("", 300),
        ("out.top0 = historyTop()", 100),
        ("scrollTop()", 1200),
        ("out.top1 = historyTop(); out.agent1 = bubbles('.bubble.agent')", 100),
        ("scrollTop()", 1200),
        ("out.top2 = historyTop(); out.agent2 = bubbles('.bubble.agent')", 100),
    ]),
    # Late answers (the deployment notes): the user moved on before the answer came.
    "late: a send that fails after moving to another session": ({SEND: [
        {"after": OPENED_S1, "status": 502, "body": {"error": "bad gateway"}}]}, [
        ("type('hello')", 300),
        (f"sendBtn().click(); window.aizaExt.app.openSessionById('{S1}')", 2500),
        ("out.inS1 = box().value; out.at = window.__aizaSession()", 100),
        (f"window.aizaExt.app.openSessionById('{S0}')", 2500),
        ("out.inS0 = box().value", 100),
    ]),
    "late: an attach answered after moving to another session": ({ATTACH: [
        {"after": OPENED_S1, "status": 201, "body": {"path": "/inbox/a.txt"}}]}, [
        (f"pick('a.txt'); window.aizaExt.app.openSessionById('{S1}')", 2500),
        ("out.inS1 = box().value", 100),
        (f"window.aizaExt.app.openSessionById('{S0}')", 2500),
        ("out.inS0 = box().value", 100),
    ]),
    "late: a stop answered after moving to another session": ({f"POST /sessions/{S0}/stop": [
        {"after": OPENED_S1, "body": {"ok": True}}]}, [
        (f"document.getElementById('chat-dot').click(); window.aizaExt.app.openSessionById('{S1}')", 2500),
        ("out.page = window.__aizaPage(); out.at = window.__aizaSession()", 100),
    ]),
    "late: an older search answered after a newer one": ({
        "GET /search?q=old": [{"after": "GET /search?q=new", "body": {
            "hits": [{"session_id": S1, "seq": 1, "ts": T0, "type": "user_message", "label": "s1", "preset": "claude-tui",
                      "archived": False, "snippet": "old hit"}], "locked": 0, "truncated": False}}],
        "GET /search?q=new": [{"body": {
            "hits": [{"session_id": S1, "seq": 1, "ts": T0, "type": "user_message", "label": "s1", "preset": "claude-tui",
                      "archived": False, "snippet": "new hit"}], "locked": 0, "truncated": False}}],
    }, [
        ("location.hash = ''", 1500),
        ("document.getElementById('search-toggle-btn').click()", 500),
        ("const i = document.getElementById('search-input'), f = document.getElementById('search-form');"
         " i.value = 'old'; f.requestSubmit(); i.value = 'new'; f.requestSubmit()", 2000),
        ("out.hits = [...document.querySelectorAll('.search-hit-row .snippet')].map((e) => e.textContent)", 100),
    ]),
}


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageFailureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(zip(CASES, pool.map(lambda kv: cls.run_case(*kv[1]), CASES.items())))

    @staticmethod
    def run_case(faults, steps, static=None):
        """static: another copy of the page's files (a check that these
        tests notice it broken)."""
        js = "[" + ",".join(f"[() => {{ {s} }}, {w}]" for s, w in steps) + "]"
        srv = serve(PROBE.replace("__STEPS__", js), **({"static": static} if static else {}), faults=faults)
        try:
            with tempfile.TemporaryDirectory() as prof:
                url = f"http://127.0.0.1:{srv.server_address[1]}/agents/#{S0}"
                budget = 4000 + sum(w for _, w in steps)
                r = subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={prof}",
                                    f"--virtual-time-budget={budget}", "--window-size=420,800", "--dump-dom", url],
                                   capture_output=True, text=True, timeout=120)
        finally:
            srv.shutdown()
            srv.server_close()
        m = re.search(r'<pre id="probe-out">(.*?)</pre>', r.stdout, re.S)
        if not m:
            return {"unfinished": True, "log": srv.state["log"]}
        out = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
        out["log"] = srv.state["log"]
        return out

    def got(self, name):
        out = self.results[name]
        self.assertNotIn("unfinished", out, name)
        self.assertNotIn("thrown", out)
        self.assertEqual(out["errors"], [])
        return out

    @staticmethod
    def sent(out):
        return [b for m, p, b in out["log"] if m == "POST" and p == f"/sessions/{S0}/messages"]

    @staticmethod
    def streams(out):
        return [p.split("since=")[1] for m, p, _ in out["log"] if m == "GET" and p.startswith(f"/sessions/{S0}/events?")]

    def test_send(self):
        out = self.got("send")
        self.assertEqual(self.sent(out), [{"text": "hello", "submit": False, "typed": True}])
        self.assertEqual(out["box"], "")
        self.assertEqual(out["alerts"], [])

    def test_a_list_still_locked_after_the_passkey_does_not_ask_again_and_again(self):
        # The stand-in's list keeps a locked row after a passkey that worked:
        # the page asked again at once, without end (197 times in one run).
        out = self.got("send")
        self.assertLessEqual(sum(1 for _, p, _ in out["log"] if p == "/unlock/begin-assertion"), 3)

    def test_a_failed_send_gives_the_text_back(self):
        out = self.got("send fails, the text comes back before what was typed since")
        self.assertEqual(out["cleared"], "")
        self.assertEqual(out["box"], "hello\nnext")
        self.assertEqual(len(out["alerts"]), 1)
        self.assertIn("送信に失敗しました", out["alerts"][0])
        # sent again from the box: both, as one message
        self.assertEqual([b["text"] for b in self.sent(out)], ["hello", "hello\nnext"])
        self.assertEqual(out["after"], "")

    def test_a_send_that_needs_the_passkey_is_sent_again_after_it(self):
        out = self.got("send asks for the passkey, then sends the same text")
        self.assertEqual([b["text"] for b in self.sent(out)], ["hello", "hello"])
        paths = [p for m, p, _ in out["log"] if m == "POST"]
        self.assertLess(paths.index("/unlock/finish-assertion"), len(paths) - 1 - paths[::-1].index(f"/sessions/{S0}/messages"))
        self.assertEqual(out["box"], "")
        self.assertEqual(out["alerts"], [])

    def test_live_events_drawn_once_and_the_stream_reopened_from_the_last(self):
        out = self.got("live events: each once, a stream that ended reopens from the last")
        self.assertEqual(out["agent"], ["二つ目", "三つ目", "四つ目"])
        self.assertEqual(out["user"], ["needle"])
        # from the history's last; the browser's own retry keeps its since;
        # after the error, from the last event received
        since = self.streams(out)
        self.assertEqual(since[:3], ["1", "1", "3"])

    def test_an_unreadable_history_is_replayed_from_the_start(self):
        out = self.got("history unreadable: the stream replays from the start")
        self.assertEqual(self.streams(out)[0], "0")
        self.assertEqual(out["user"], ["needle"])
        self.assertEqual(out["agent"], ["二つ目"])

    def test_a_closed_passkey_window_stops_the_stream(self):
        out = self.got("the passkey window closes under the stream")
        self.assertTrue(out["top"])
        self.assertEqual(len(self.streams(out)), 1)

    def keys(self, out):
        return [b for m, p, b in out["log"] if m == "POST" and p == f"/sessions/{S0}/keys"]

    def test_armed_modifiers_go_with_the_next_key_only(self):
        out = self.got("keys: the armed modifiers go with the next key only")
        self.assertNotIn("missing", out)
        self.assertEqual(self.keys(out), [
            {"key": "a", "ctrl": True, "alt": False, "shift": True},
            {"key": "Up", "ctrl": False, "alt": False, "shift": False},
            # a chord: Ctrl+x, then Ctrl+s
            {"key": "x", "ctrl": True, "alt": False, "shift": False},
            {"key": "s", "ctrl": True, "alt": False, "shift": False}])

    def test_a_key_that_needs_the_passkey_is_sent_again(self):
        out = self.got("keys: one that needs the passkey is sent again after it")
        self.assertNotIn("missing", out)
        self.assertEqual([b["key"] for b in self.keys(out)], ["Escape", "Escape"])
        self.assertIn("/unlock/finish-assertion", [p for m, p, _ in out["log"] if m == "POST"])

    def test_an_attached_files_path_goes_into_the_box(self):
        out = self.got("attach: the file's path goes into the box")
        self.assertEqual(out["box"], "abc /inbox/a.txt ")
        sent = [b for m, p, b in out["log"] if m == "POST" and p == f"/sessions/{S0}/attach"]
        self.assertEqual([(b["filename"], b["data_base64"]) for b in sent], [("a.txt", "eA==")])
        self.assertEqual(out["alerts"], [])

    def test_a_failed_attach_says_so_and_leaves_the_box(self):
        out = self.got("attach fails: said, the box as it was")
        self.assertEqual(out["box"], "abc")
        self.assertEqual(len(out["alerts"]), 1)
        self.assertIn("attachment too large", out["alerts"][0])

    def test_older_history_tried_again_after_a_failure(self):
        out = self.got("older history: a failed page is tried again by scrolling")
        self.assertEqual(out["top0"], "")
        self.assertIn("読み込みに失敗しました", out["top1"])
        self.assertEqual(out["agent1"], ["五十", "五十一"])
        self.assertEqual(out["agent2"], ["四十八", "四十九", "五十", "五十一"])
        self.assertEqual(out["top2"], "ここが会話の最初です")
        older = [p for m, p, _ in out["log"] if "/events/page?before=" in p]
        self.assertEqual([p.split("before=")[1].split("&")[0] for p in older], ["50", "50"])

    def test_a_late_failed_send_keeps_the_text_for_its_own_session(self):
        out = self.got("late: a send that fails after moving to another session")
        self.assertEqual(out["at"], S1)
        self.assertEqual(out["inS1"], "")        # not where the next send would go to s1
        self.assertEqual(len(out["alerts"]), 1)
        self.assertIn("「s0」への送信に失敗しました", out["alerts"][0])
        self.assertEqual(out["inS0"], "hello")    # back when s0 is opened again

    def test_a_late_attach_keeps_the_path_for_its_own_session(self):
        out = self.got("late: an attach answered after moving to another session")
        self.assertEqual(out["inS1"], "")
        self.assertEqual(out["inS0"], "/inbox/a.txt ")

    def test_a_newer_search_wins_over_a_slower_older_one(self):
        out = self.got("late: an older search answered after a newer one")
        self.assertEqual(out["hits"], ["new hit"])

    def test_a_late_stop_does_not_close_the_session_moved_to(self):
        out = self.got("late: a stop answered after moving to another session")
        self.assertIn(f"/sessions/{S0}/stop", [p for m, p, _ in out["log"] if m == "POST"])
        self.assertEqual((out["page"], out["at"]), ("chat", S1))


if __name__ == "__main__":
    unittest.main()
