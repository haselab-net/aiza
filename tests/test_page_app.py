"""app.js's own parts, in headless Chrome against the stand-in backend: the
one-shot hashes a link from outside brings (#issue=, the deployment notes;
#desk&, the deployment notes; a session this list does not have) and the
extensions /config lists (ext/README.md): what each asks of the user and of
the server.

    python3 -m unittest discover -s tests -v
"""
import os
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import test_page_failures as F   # (not its class itself: unittest would run it here again)
from page_harness import ISSUE, STATIC
from page_run import STEPS, posted, run_page, steps_js
from test_page_failures import CHROME

S1 = F.S1
ISSUE_GET = "GET /issue?ref=" + quote("org/repo#1", safe="")
# What the page asks (confirm / prompt) is kept; the answers are given.
ASKS = ("window.__asked = []; window.confirm = (m) => { window.__asked.push(m); return window.__yes !== false; };"
        " window.prompt = (m, d) => { window.__asked.push(m + '|' + d); return window.__answers ? window.__answers.shift() : d; };")
GO = lambda h: f"location.hash = {h!r}"
NOTE = "out.note = document.querySelector('#start-note:not([hidden]) .what').textContent; "
SEEN = ("out.asked = window.__asked; out.page = window.__aizaPage(); out.at = window.__aizaSession(); out.hash = location.hash")
NEW_ISSUE = dict(ISSUE, sessions=[], state="OPEN", status="Ready", worker="w", assignees=["u"])
EXT = {"GET /config": [{"every": True, "body": {"ext": [{"name": "x", "js": ["a.js", "gone.js"], "css": ["a.css"]}]}}]}

# name: (faults, [(js, wait ms)], extra static files {path: text} or None)
CASES = {
    "#issue=: a session already on it opens": ({ISSUE_GET: [{"body": ISSUE}]}, [
        (ASKS + GO("#issue=" + quote("org/repo#1", safe="")), 1500),
        (SEEN, 100),
    ], None),
    # The start screen asks (the deployment notes 段3): what it shows, then 開始 or ✕.
    "#issue=: a new session in its worktree": ({ISSUE_GET: [{"body": NEW_ISSUE}]}, [
        (ASKS + GO("#issue=" + quote("org/repo#1", safe="")), 1500),
        (NOTE + "out.label = document.getElementById('label').value; document.getElementById('create-btn').click()", 1500),
        (SEEN, 100),
    ], None),
    "#issue=: closed, and declined": ({ISSUE_GET: [{"body": dict(NEW_ISSUE, state="CLOSED")}]}, [
        (ASKS + GO("#issue=" + quote("org/repo#1", safe="")), 1500),
        (NOTE + "document.querySelector('#start-modal .close').click()", 800),
        (SEEN, 100),
    ], None),
    "#issue=: not cloned": ({ISSUE_GET: [{"body": dict(NEW_ISSUE, cloned=False)}]}, [
        (ASKS + GO("#issue=" + quote("org/repo#1", safe="")), 1500),
        (SEEN, 100),
    ], None),
    "#issue=: cannot be read": ({ISSUE_GET: [{"status": 404, "body": {"error": "no such issue"}}]}, [
        (ASKS + GO("#issue=" + quote("org/repo#1", safe="")), 1500),
        (SEEN, 100),
    ], None),
    "#desk&: a report from the other host": ({"POST /desk/report": [{"body": {"ok": True}}]}, [
        (ASKS + "window.__answers = ['  動かない  ']; " + GO("#desk&t=" + quote("初めの文") + "&ref=h/u/k/s1&pos=3"), 1500),
        (SEEN, 100),
    ], None),
    "#desk&: a deploy request": ({"POST /desk/report": [{"body": {"ok": True, "desk_url": "#tree=n00000000000a"}}]}, [
        (ASKS + GO("#desk&t=x&ref=h/u/k/s1&c=" + quote('{"repo":"r","sha":"0123456789abcdef"}')), 1500),
        (SEEN, 100),
    ], None),
    "#desk&: nothing written, nothing sent": ({}, [
        (ASKS + "window.__answers = ['   ']; " + GO("#desk&t="), 1500),
        (SEEN, 100),
    ], None),
    "#desk&: refused": ({"POST /desk/report": [{"status": 500, "body": {"error": "down"}}]}, [
        (ASKS + GO("#desk&t=x"), 1500),
        (SEEN, 100),
    ], None),
    "#<id>: a session not in the list": ({}, [
        (ASKS + GO("#aaaaaaaaaaff"), 1500),
        (SEEN, 100),
    ], None),
    "extensions: loaded before the first paint, a missing one left out": (EXT, [
        ("out.ran = window.__extRan; out.rowsAtExt = window.__rowsAtExt; out.css = getComputedStyle(document.body).getPropertyValue('--ext-mark').trim();"
         " out.listed = document.querySelectorAll('#sessions > .session-row').length", 100),
    ], {"ext/x/a.js": "window.__extRan = (window.__extRan || 0) + 1;"
                  " window.__rowsAtExt = document.querySelectorAll('#sessions > .session-row').length;", "ext/x/a.css": "body { --ext-mark: on; }"}),
}


def run_case(faults, steps, extra=None, static=None):
    probe = F.PROBE.replace(STEPS, "  const steps = " + steps_js(steps) + ";")
    budget = 4000 + sum(w for _, w in steps)
    if not extra:
        return run_page(probe, {"faults": faults}, budget, static=static)
    with tempfile.TemporaryDirectory() as d:
        copy = os.path.join(d, "static")
        shutil.copytree(static or STATIC, copy)
        for rel, text in extra.items():
            os.makedirs(os.path.dirname(os.path.join(copy, rel)), exist_ok=True)
            with open(os.path.join(copy, rel), "w", encoding="utf-8") as fh:
                fh.write(text)
        return run_page(probe, {"faults": faults}, budget, static=copy)


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageAppTest(unittest.TestCase):
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

    def test_an_issue_with_a_session_opens_it(self):
        out = self.got("#issue=: a session already on it opens")
        self.assertEqual(out["asked"], ["この Issue のセッションがすでに動いています。開きますか？"])
        self.assertEqual((out["page"], out["at"]), ("chat", S1))
        self.assertEqual(posted(out, "POST /sessions"), [])

    def test_an_issue_starts_claude_in_its_worktree_after_asking(self):
        out = self.got("#issue=: a new session in its worktree")
        self.assertEqual(out["asked"], [])   # no confirm: the start screen
        asked = out["note"]
        self.assertTrue(asked.startswith("🔗 #1 t\nStatus: Ready / Worker: w / 担当: u"), asked)
        self.assertNotIn("⚠", asked)
        self.assertIn("~/sandhome/repo-wt/i1", asked)
        self.assertEqual(out["label"], "#1 t")
        sent = posted(out, "POST /sessions")
        self.assertEqual([(x["preset"], x["issue"], x["label"]) for x in sent], [("claude-tui", "org/repo#1", "#1 t")])
        self.assertEqual(out["page"], "chat")
        self.assertEqual(out["hash"], "#aaaaaaaaaa07")   # the new session (page_harness NEW)

    def test_a_closed_issue_says_so_and_no_is_no(self):
        out = self.got("#issue=: closed, and declined")
        self.assertIn("⚠ この Issue は閉じています", out["note"])
        self.assertEqual(posted(out, "POST /sessions"), [])
        self.assertEqual(out["page"], "list")
        self.assertEqual(out["hash"], "")    # one-shot: a reload does not offer it again

    def test_an_issue_not_cloned_is_said(self):
        out = self.got("#issue=: not cloned")
        self.assertEqual(out["alerts"], ["~/sandhome/repo がありません。先に clone してください"])
        self.assertEqual(posted(out, "POST /sessions"), [])

    def test_an_issue_that_cannot_be_read_is_said(self):
        out = self.got("#issue=: cannot be read")
        self.assertEqual(out["alerts"], ["Issue を読めませんでした: no such issue"])

    def test_a_desk_report_from_the_other_host(self):
        out = self.got("#desk&: a report from the other host")
        self.assertTrue(out["asked"][0].endswith("|初めの文"), out["asked"])     # what the other host wrote, to change
        self.assertEqual(posted(out, "POST /desk/report"), [{"text": "動かない", "ref": "h/u/k/s1", "pos": "3"}])
        self.assertEqual(out["alerts"], ["窓口に送りました。仕事の木の「AI座 の窓口」で進み具合が見えます。"])
        self.assertEqual(out["hash"], "")    # one-shot: a reload does not ask again

    def test_a_desk_deploy_request_goes_with_its_commit(self):
        out = self.got("#desk&: a deploy request")
        self.assertIn("配備の依頼: r のコミット 0123456789", out["asked"][0])
        self.assertEqual(posted(out, "POST /desk/report"),
                         [{"text": "x", "ref": "h/u/k/s1", "commit": '{"repo":"r","sha":"0123456789abcdef"}'}])
        self.assertEqual(out["alerts"], [])  # it went to the desk's page (its node in the tree) instead
        self.assertEqual(out["page"], "list")

    def test_a_blank_desk_report_sends_nothing(self):
        out = self.got("#desk&: nothing written, nothing sent")
        self.assertEqual(posted(out, "POST /desk/report"), [])

    def test_a_refused_desk_report_is_said(self):
        out = self.got("#desk&: refused")
        self.assertEqual(out["alerts"], ["窓口に送れませんでした: down"])

    def test_a_link_to_a_session_not_in_the_list_says_so(self):
        out = self.got("#<id>: a session not in the list")
        self.assertEqual(out["alerts"], ["このセッションは見られません(共有が外されたか、消されたか、もう一方のホストのものです)"])
        self.assertEqual((out["page"], out["hash"]), ("list", ""))

    def test_extensions_load_and_a_missing_file_is_left_out(self):
        out = self.got("extensions: loaded before the first paint, a missing one left out")
        self.assertEqual(out["ran"], 1)
        self.assertEqual(out["rowsAtExt"], 0)   # before the list was first drawn
        self.assertEqual(out["css"], "on")
        self.assertGreater(out["listed"], 0)
        asked = [p for m, p, _ in out["log"] if p.startswith("/config")]
        self.assertEqual(asked, ["/config"])


if __name__ == "__main__":
    unittest.main()
