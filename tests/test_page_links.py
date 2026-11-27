"""The list's 🔗 (セッション連携, the deployment notes) and the Windows machines'
blackboard writes (the deployment notes), in headless Chrome against the
stand-in backend: what each tap asks of the server (POST /sessions/link,
/sessions/unlink, /board) and what the page says.

    python3 -m unittest discover -s tests -v
"""
import json
import re
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_failures as F   # (not its class itself: unittest would run it here again)
import test_page_list as L
from page_harness import BOARD, T0, serve
from test_page_failures import CHROME

S0, S2, GATED = "aaaaaaaaaa00", "aaaaaaaaaa02", "aaaaaaaaaa0c"   # s0 is linked with s1 (page_harness)
LINK, UNLINK = "POST /sessions/link", "POST /sessions/unlink"
OK = {LINK: [{"every": True, "body": {"ok": True}}], UNLINK: [{"every": True, "body": {"ok": True}}]}
tap = lambda sid: f"row('{sid}').querySelector('.link-btn').click()"
BANNER = "out.banner = document.getElementById('link-armed-banner').classList.contains('visible');" \
         " out.text = document.getElementById('link-armed-text').textContent;" \
         " out.armed = [...document.querySelectorAll('.link-btn.armed')].map((b) => b.closest('.session-row').dataset.sessionId)"
# the blackboard after a write: my own hand-written line on winbox
CLAIMED = dict(BOARD, entries=BOARD["entries"] + [{"machine": "winbox", "user": "u", "state": "using", "source": "claim",
                                                   "what": "印刷", "since": T0, "key": "k2"}])

# name: (faults, [(js, wait ms)])
CASES = {
    "arm, the bar, cancel": (OK, [
        (tap(S2), 600),
        (BANNER, 100),
        ("document.getElementById('link-armed-cancel').click()", 600),
        ("out.after = document.getElementById('link-armed-banner').classList.contains('visible')", 100),
    ]),
    "tap the armed one again": (OK, [
        (tap(S2), 600),
        (tap(S2), 600),
        (BANNER, 100),
    ]),
    "two not linked: the minutes asked": (OK, [
        ("window.prompt = (m, d) => { out.asked = d; return '15'; }; " + tap(S2), 600),
        (tap(GATED), 800),
        (BANNER, 100),
    ]),
    "0 minutes: never ends": (OK, [
        ("window.prompt = () => '0'; " + tap(S2), 600),
        (tap(GATED), 800),
    ]),
    "blank: the server's default": (OK, [
        ("window.prompt = () => ''; " + tap(S2), 600),
        (tap(GATED), 800),
    ]),
    "not a number: said, nothing sent": (OK, [
        ("window.prompt = () => 'abc'; " + tap(S2), 600),
        (tap(GATED), 800),
    ]),
    "the minutes cancelled": (OK, [
        ("window.prompt = () => null; " + tap(S2), 600),
        (tap(GATED), 800),
    ]),
    "join a link": (OK, [
        (tap(S2), 600),
        ("window.confirm = (m) => { out.asked = m; return true; }; " + tap(S0), 800),
    ]),
    "unlink": (OK, [
        ("window.confirm = (m) => { out.asked = m; return true; }; " + tap(S0), 800),
    ]),
    "unlink declined": (OK, [
        ("window.confirm = () => false; " + tap(S0), 800),
    ]),
    "link refused": ({LINK: [{"status": 409, "body": {"error": "もう連携中"}}]}, [
        ("window.prompt = () => '15'; " + tap(S2), 600),
        (tap(GATED), 800),
    ]),
    "the blackboard: write, change, take off": ({"POST /board": [{"every": True, "body": CLAIMED}]}, [
        ("document.getElementById('machine-btn').click()", 800),
        ("window.prompt = (m, d) => { (out.asked = out.asked || []).push(d); return '印刷'; };"
         " document.querySelector('#board-modal .use').click()", 800),
        ("out.lines = [...document.querySelectorAll('#board-modal .entry .what')].map((e) => e.textContent);"
         " const mine = [...document.querySelectorAll('#board-modal .entry')].find((e) => e.textContent.includes('印刷'));"
         " out.buttons = [...mine.querySelectorAll('button')].map((b) => b.textContent); mine.querySelector('button').click()", 800),
        ("const mine = [...document.querySelectorAll('#board-modal .entry')].find((e) => e.textContent.includes('印刷'));"
         " [...mine.querySelectorAll('button')].find((b) => b.textContent === '解除').click()", 800),
    ]),
    "the blackboard: a write refused": ({"POST /board": [{"status": 500, "body": {"error": "x"}}]}, [
        ("document.getElementById('machine-btn').click()", 800),
        ("window.prompt = () => '印刷'; document.querySelector('#board-modal .use').click()", 800),
    ]),
}


def run_case(faults, steps, static=None):
    """static: another copy of the page's files (a check that these tests
    notice it broken)."""
    js = "[" + ",".join(f"[() => {{ {s} }}, {w}]" for s, w in steps) + "]"
    probe = F.PROBE.replace("  const steps = __STEPS__;", L.HELPERS + "  const steps = " + js + ";")
    srv = serve(probe, faults=faults, **({"static": static} if static else {}))
    try:
        with tempfile.TemporaryDirectory() as prof:
            r = subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={prof}",
                                f"--virtual-time-budget={4000 + sum(w for _, w in steps)}", "--window-size=420,1400",
                                "--dump-dom", f"http://127.0.0.1:{srv.server_address[1]}/agents/"],
                               capture_output=True, text=True, timeout=120)
    finally:
        srv.shutdown()
        srv.server_close()
    m = re.search(r'<pre id="probe-out">(.*?)</pre>', r.stdout, re.S)
    out = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")) \
        if m else {"unfinished": True}
    out["log"] = srv.state["log"]
    return out


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageLinksTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(zip(CASES, pool.map(lambda v: run_case(*v), CASES.values())))

    def got(self, name):
        out = self.results[name]
        self.assertNotIn("unfinished", out, name)
        self.assertNotIn("thrown", out)
        self.assertNotIn("missing", out)
        self.assertEqual(out["errors"], [])
        return out

    @staticmethod
    def posted(out, what):
        method, path = what.split(" ")
        return [b for m, p, b in out["log"] if m == method and p == path]

    def test_arming_shows_the_bar_and_cancel_takes_it_off(self):
        out = self.got("arm, the bar, cancel")
        self.assertTrue(out["banner"])
        self.assertIn("s2", out["text"])
        self.assertEqual(out["armed"], [S2])
        self.assertFalse(out["after"])
        self.assertEqual(self.posted(out, LINK), [])

    def test_tapping_the_armed_one_again_disarms(self):
        out = self.got("tap the armed one again")
        self.assertFalse(out["banner"])
        self.assertEqual(out["armed"], [])

    def test_two_not_linked_are_linked_for_the_minutes_given(self):
        out = self.got("two not linked: the minutes asked")
        self.assertEqual(out["asked"], "240")    # neither is root: 4 hours suggested
        self.assertEqual(self.posted(out, LINK), [{"a": S2, "b": GATED, "duration_minutes": 15}])
        self.assertFalse(out["banner"])

    def test_zero_minutes_is_a_link_that_never_ends(self):
        out = self.got("0 minutes: never ends")
        self.assertEqual(self.posted(out, LINK), [{"a": S2, "b": GATED, "forever": True}])

    def test_blank_leaves_the_time_to_the_server(self):
        out = self.got("blank: the server's default")
        self.assertEqual(self.posted(out, LINK), [{"a": S2, "b": GATED}])

    def test_not_a_number_is_said_and_nothing_sent(self):
        out = self.got("not a number: said, nothing sent")
        self.assertEqual(self.posted(out, LINK), [])
        self.assertEqual(out["alerts"], ["分数は正の数で入力してください"])

    def test_cancelling_the_minutes_sends_nothing(self):
        out = self.got("the minutes cancelled")
        self.assertEqual(self.posted(out, LINK), [])
        self.assertEqual(out["alerts"], [])

    def test_joining_a_link(self):
        out = self.got("join a link")
        self.assertIn("「s2」を「s0・s1」の連携に加えます", out["asked"])
        self.assertEqual(self.posted(out, LINK), [{"a": S2, "b": S0}])   # no time asked: the link keeps its own

    def test_unlinking(self):
        out = self.got("unlink")
        self.assertIn("「s0」と「s1」の連携を切断します", out["asked"])
        self.assertEqual(self.posted(out, UNLINK), [{"session_id": S0}])

    def test_unlink_declined_sends_nothing(self):
        out = self.got("unlink declined")
        self.assertEqual(self.posted(out, UNLINK), [])

    def test_a_refused_link_is_said(self):
        out = self.got("link refused")
        self.assertEqual(len(self.posted(out, LINK)), 1)
        self.assertEqual(out["alerts"], ["連携できませんでした: もう連携中"])

    def test_the_blackboard_write_change_and_take_off(self):
        out = self.got("the blackboard: write, change, take off")
        self.assertEqual(out["asked"][:2], ["", "印刷"])   # a new line starts empty; a change starts from the line
        self.assertIn("印刷", out["lines"])
        self.assertEqual(out["buttons"], ["✏️", "解除"])
        self.assertEqual(self.posted(out, "POST /board"), [
            {"op": "claim", "machine": "winbox", "what": "印刷"},
            {"op": "note", "key": "k2", "what": "印刷"},
            {"op": "release", "key": "k2"},
        ])

    def test_a_refused_blackboard_write_is_said(self):
        out = self.got("the blackboard: a write refused")
        self.assertEqual(len(out["alerts"]), 1)
        self.assertIn("黒板を書き換えられませんでした", out["alerts"][0])


if __name__ == "__main__":
    unittest.main()
