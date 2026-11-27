"""A new member's first steps in the app, in headless Chrome against the
stand-in backend: what nobody tries again once their own account is set up,
and the first impression of AI座 --
- the first list (no sessions, no folders, no tree) and its first session;
- Claude Code not logged in yet: the settings' login, and a first Claude
  session that opens the login first (the deployment notes);
- the first Email session (the deployment notes: the passkey asked on 開始).
The pages outside the app a new member meets (the passkey registration, the
Email box's) are tested with the extensions that serve them (ext/<name>/tests).

    python3 -m unittest discover -s tests -v
"""
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_failures as F   # (not its class itself: unittest would run it here again)
from page_harness import CAPS, LOGIN, MAILED, T0
from page_run import STEPS, posted, run_page, steps_js
from test_page_failures import CHROME

EVERY = lambda body: [{"every": True, "body": body}]

# A new account: nothing of its own yet.
NEW = {"GET /sessions": EVERY({"sessions": []}), "GET /shared-with-me": EVERY({"sessions": []}),
       "GET /tree": EVERY({"user": "u", "nodes": [], "tr_pending": 0, "lang": "ja", "lab_users": [{"user": "u", "name": "U"}]})}
LOGIN_ID = LOGIN["id"]
LOGIN_PAGE = f"GET /sessions/{LOGIN_ID}/events/page"
SAID = "Claude Code にまだログインしていないので、先にログインの画面を開きました。"
START = "document.getElementById('create-btn').click()"
PLACE = lambda v: f"const p = document.getElementById('place'); p.value = '{v}'; p.dispatchEvent(new Event('change'))"
UNLOCK = {"status": 403, "body": {"error": "unlock", "unlock_required": True, "tier": "host"}}

# name: (faults, [(js, wait ms)])
MAIN = {
    "the first list": (NEW, [
        ("", 300),
        # ＋ 🤖 AI opens the start form (in the top row's panel, the deployment notes): the form is in sight there.
        ("out.hint = [...document.querySelectorAll('#sessions > .list-empty')].map((e) => e.textContent);"
         " document.getElementById('start-btn').click()", 400),
        ("out.rows = document.querySelectorAll('#sessions > .session-row').length;"
         " out.create = !!document.getElementById('create-btn') && document.getElementById('create-btn').offsetParent !== null;"
         " out.kind = document.getElementById('kind').value; out.place = document.getElementById('place').value;"
         "", 100),
        (START, 1500),
        ("out.page = window.__aizaPage(); out.at = window.__aizaSession()", 100),
    ]),
    "settings: not logged in, then the login": ({**NEW, LOGIN_PAGE: EVERY({"events": [], "has_more": False})}, [
        ("location.hash = '#auth'", 1000),
        ("out.status = [...document.querySelectorAll('#auth-rows .auth-status-text')].map((e) => e.textContent);"
         " document.querySelector('#auth-rows .auth-login[data-scope=container]').click()", 1500),
        ("out.page = window.__aizaPage(); out.at = window.__aizaSession()", 100),
    ]),
    "the login ends: a tap goes back": ({**NEW, LOGIN_PAGE: EVERY({"events": [
        {"seq": 1, "ts": T0, "type": "session_ended"}], "has_more": False})}, [
        ("location.hash = '#auth'", 1000),
        ("document.querySelector('#auth-rows .auth-login[data-scope=container]').click()", 1500),
        ("out.said = [...document.querySelectorAll('#messages .bubble.system')].map((e) => e.textContent);"
         " out.composer = getComputedStyle(document.getElementById('composer')).display;"
         " document.getElementById('messages').click()", 800),
        ("out.page = window.__aizaPage()", 100),
    ]),
    "a first Claude session opens the login first": ({**NEW, "POST /sessions": [{"body": dict(LOGIN, login_first="claude")}],
                                                      LOGIN_PAGE: EVERY({"events": [
                                                          {"seq": 1, "ts": T0, "type": "system", "text": SAID + "ログインが済んだら、もう一度セッションを作ってください。"}],
                                                          "has_more": False})}, [
        (START, 1500),
        ("out.page = window.__aizaPage(); out.at = window.__aizaSession();"
         " out.said = [...document.querySelectorAll('#messages .bubble.system')].map((e) => e.textContent)", 100),
    ]),
    "a first Email session asks for the passkey on 開始": ({**NEW, "GET /capabilities": EVERY(dict(CAPS, mailbox={"label": "Email", "codex": False})),
                                                         "POST /sessions": [UNLOCK, {"body": MAILED}]}, [
        (PLACE("mail"), 300),
        ("out.preset = document.getElementById('preset').value; " + START, 3000),
        ("out.page = window.__aizaPage(); out.at = window.__aizaSession()", 100),
    ]),
}

def run_main(faults, steps):
    probe = F.PROBE.replace(STEPS, "  const steps = " + steps_js(steps) + ";")
    return run_page(probe, {"faults": faults}, 4000 + sum(w for _, w in steps))



@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class FirstUseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(zip(MAIN, pool.map(lambda v: run_main(*v), MAIN.values())))

    def got(self, name):
        out = self.results[name]
        self.assertNotIn("unfinished", out, name)
        self.assertNotIn("thrown", out)
        self.assertNotIn("missing", out)
        self.assertEqual(out["errors"], [])
        return out

    def test_the_first_list_and_its_first_session(self):
        out = self.got("the first list")
        self.assertEqual(out["rows"], 0)
        # what to do first is said where the list would be
        self.assertEqual(out["hint"], ["まだセッションがありません。上の「＋ 🤖 AI」を押し、AI(Claude など)と場所を選んで「開始」を押すと始まります。"])
        self.assertTrue(out["create"])                       # the new-session form is in sight
        self.assertEqual((out["kind"], out["place"]), ("claude", "dev"))
        self.assertEqual(posted(out, "POST /sessions")[0]["preset"], "claude-tui")
        self.assertEqual((out["page"], out["at"]), ("chat", "aaaaaaaaaa07"))
        self.assertEqual(out["alerts"], [])

    def test_settings_say_not_logged_in_and_open_the_login(self):
        out = self.got("settings: not logged in, then the login")
        self.assertEqual(out["status"][:2], ["未ログイン", "未ログイン"])   # Claude: devbox, this host
        self.assertEqual(posted(out, "POST /claude-auth/login"), [{"scope": "container"}])
        self.assertEqual((out["page"], out["at"]), ("chat", LOGIN_ID))

    def test_a_finished_login_says_a_tap_goes_back(self):
        out = self.got("the login ends: a tap goes back")
        self.assertEqual(out["said"], ["セッションは終了しました\n画面のどこかをタップすると戻ります"])
        self.assertEqual(out["composer"], "none")
        self.assertEqual(out["page"], "auth")

    def test_a_first_claude_session_opens_the_login_and_says_why(self):
        out = self.got("a first Claude session opens the login first")
        self.assertEqual((out["page"], out["at"]), ("chat", LOGIN_ID))
        self.assertEqual(len(out["said"]), 1)
        self.assertTrue(out["said"][0].startswith(SAID))
        self.assertEqual(out["alerts"], [])

    def test_a_first_email_session_asks_for_the_passkey_and_starts(self):
        out = self.got("a first Email session asks for the passkey on 開始")
        self.assertEqual(out["preset"], "mail-tui")
        made = posted(out, "POST /sessions")
        self.assertEqual(len(made), 2)                       # refused, then again after the passkey
        self.assertEqual(made[0], made[1])
        paths = [p for m, p, _ in out["log"] if m == "POST"]
        self.assertLess(paths.index("/sessions"), paths.index("/unlock/finish-assertion"))
        self.assertEqual((out["page"], out["at"]), ("chat", MAILED["id"]))
        self.assertEqual(out["alerts"], [])


if __name__ == "__main__":
    unittest.main()
