"""The new-session form's pickers (the deployment notes, the deployment notes)
and what /capabilities adds to it, in headless Chrome against the stand-in
backend: which folder each tap asks for (GET /workdirs), what a new folder
posts, what a listing that fails falls back to, which programs and places
the form offers, and the label a resumed conversation brings.

    python3 -m unittest discover -s tests -v
"""
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_links as K
from page_harness import CAPS, T0
from test_page_failures import CHROME

W = "GET /workdirs?scope="
EVERY = lambda body: [{"every": True, "body": body}]
SHELL = "const k = document.getElementById('kind'); k.value = 'shell'; k.dispatchEvent(new Event('change'))"
HOST = "const p = document.getElementById('place'); p.value = 'host'; p.dispatchEvent(new Event('change'))"
PICK = lambda sel, v: f"const c = document.getElementById('{sel}'); c.value = '{v}'; c.dispatchEvent(new Event('change'))"
STATE = lambda pre: (f"out.{pre}crumb = document.getElementById('shell-cwd-crumb').textContent;"
                     f" out.{pre}up = document.getElementById('shell-cwd-up').disabled;"
                     f" out.{pre}kids = [...document.getElementById('shell-cwd-child').options].map((o) => o.textContent);"
                     f" out.{pre}off = document.getElementById('shell-cwd-child').disabled")
ROOT_MAIL = dict(CAPS, root_shell=True, mailbox={"label": "Email", "codex": False})

# name: (faults, [(js, wait ms)])
CASES = {
    # A public demo's room (the deployment notes): only the AI the demo offers.
    "demo: only the AI": ({"GET /capabilities": EVERY(dict(CAPS, demo=True, presets=["agent"], root_shell=True,
                                                          mailbox={"label": "Email", "codex": False}))}, [
        ("out.kinds = [...document.getElementById('kind').options].map((o) => o.value);"
         " out.places = [...document.getElementById('place').options].map((o) => o.value);"
         " out.presets = [...document.getElementById('preset').options].map((o) => o.value);"
         " out.loginsHidden = document.getElementById('auth-rows').closest('.set-card').hidden;"
         " out.machines = [...document.getElementById('machine-select').options].map((o) => o.value)", 100),
    ]),
    "shell on devbox: down, up": ({W + "sandhome&dir=": EVERY({"dir": "", "subdirs": ["a", "b"]}),
                                   W + "sandhome&dir=a": EVERY({"dir": "a", "subdirs": []})}, [
        (SHELL, 600),
        (STATE("top_") + "; " + PICK("shell-cwd-child", "a"), 600),
        (STATE("a_") + "; document.getElementById('shell-cwd-up').click()", 600),
        (STATE("back_"), 100),
    ]),
    "shell on the host: absolute paths": ({W + "host&dir=": EVERY({"dir": "/home/u", "subdirs": ["x"]}),
                                           W + "host&dir=%2Fhome%2Fu%2Fx": EVERY({"dir": "/home/u/x", "subdirs": []}),
                                           W + "host&dir=%2Fhome%2Fu": EVERY({"dir": "/home/u", "subdirs": ["x"]}),
                                           W + "host&dir=%2Fhome": EVERY({"dir": "/home", "subdirs": ["u"]}),
                                           W + "host&dir=%2F": EVERY({"dir": "/", "subdirs": ["home"]})}, [
        (SHELL + "; " + HOST, 600),
        (STATE("top_") + "; " + PICK("shell-cwd-child", "x"), 600),
        (STATE("x_") + "; document.getElementById('shell-cwd-up').click()", 600),
        ("document.getElementById('shell-cwd-up').click()", 600),
        ("document.getElementById('shell-cwd-up').click()", 600),
        (STATE("root_"), 100),
    ]),
    "a folder that cannot be read: back to the default": ({W + "sandhome&dir=": EVERY({"dir": "", "subdirs": ["gone"]}),
                                                           W + "sandhome&dir=gone": [{"status": 404, "body": {"error": "no"}}]}, [
        (SHELL, 600),
        (PICK("shell-cwd-child", "gone"), 800),
        (STATE(""), 100),
    ]),
    "not even the default: said in the picker": ({W + "sandhome&dir=": [{"every": True, "status": 500, "body": {"error": "x"}}]}, [
        (SHELL, 800),
        (STATE(""), 100),
    ]),
    "＋ in the shell picker": ({W + "sandhome&dir=": EVERY({"dir": "", "subdirs": []}),
                               W + "sandhome&dir=%E6%96%B0": EVERY({"dir": "新", "subdirs": []}),
                               "POST /workdirs": EVERY({"dir": "新"})}, [
        (SHELL, 600),
        ("window.prompt = () => ' 新 '; document.getElementById('shell-cwd-new').click()", 800),
        (STATE(""), 100),
    ]),
    "＋ in Claude's picker, refused": ({"POST /workdirs": [{"status": 409, "body": {"error": "exists"}}]}, [
        ("window.prompt = () => '新'; document.getElementById('cwd-new').click()", 800),
    ]),
    "＋ with no name: nothing": ({}, [
        ("window.prompt = () => '  '; document.getElementById('cwd-new').click(); document.getElementById('shell-cwd-new').click()", 600),
    ]),
    "capabilities: root and Email": ({"GET /capabilities": EVERY(ROOT_MAIL)}, [
        ("", 300),
        ("out.places = [...document.getElementById('place').options].map((o) => [o.value, o.disabled]);"
         " out.presets = [...document.getElementById('preset').options].map((o) => o.value);"
         " const k = document.getElementById('kind'); k.value = 'codex'; k.dispatchEvent(new Event('change'))", 300),
        ("out.codexPlaces = [...document.getElementById('place').options].map((o) => [o.value, o.disabled]);"
         " out.skipDev = document.getElementById('skip-row').hidden;"
         " const p = document.getElementById('place'); p.value = 'root'; p.dispatchEvent(new Event('change'))", 300),
        ("out.preset = document.getElementById('preset').value; out.skipRoot = document.getElementById('skip-row').hidden", 100),
    ]),
    "resume: the conversation's name as the label": ({"GET /claude-conversations?scope=sandhome&cwd=": EVERY({"conversations": [
        {"id": "c1" * 8, "mtime": T0, "aiza_label": "前の名前", "summary": "要約"},
        {"id": "c2" * 8, "mtime": T0 - 60, "summary": ""}]})}, [
        ("", 300),
        ("out.options = [...document.getElementById('resume').options].map((o) => o.textContent.replace(/^.*?(\\[|\\()/, '$1'));"
         + PICK("resume", "c1" * 8), 100),
        ("out.label1 = document.getElementById('label').value; " + PICK("resume", "c2" * 8), 100),
        ("out.label2 = document.getElementById('label').value; document.getElementById('label').value = '自分の名前'; "
         + PICK("resume", "c1" * 8), 100),
        ("out.label3 = document.getElementById('label').value", 100),
    ]),
}


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageFormTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(zip(CASES, pool.map(lambda v: K.run_case(*v), CASES.values())))

    def got(self, name):
        out = self.results[name]
        self.assertNotIn("unfinished", out, name)
        self.assertNotIn("thrown", out)
        self.assertNotIn("missing", out)
        self.assertEqual(out["errors"], [])
        return out

    @staticmethod
    def asked(out, scope):
        return [p.split("dir=")[1] for m, p, _ in out["log"] if m == "GET" and p.startswith(f"/workdirs?scope={scope}&")]

    def test_the_shell_picker_on_devbox(self):
        out = self.got("shell on devbox: down, up")
        self.assertEqual((out["top_crumb"], out["top_up"]), ("sandhome", True))
        self.assertEqual(out["top_kids"], ["サブディレクトリを開く…", "a", "b"])
        self.assertEqual((out["a_crumb"], out["a_up"], out["a_kids"], out["a_off"]), ("sandhome/a", False, ["(サブディレクトリなし)"], True))
        self.assertEqual(out["back_crumb"], "sandhome")
        self.assertEqual(self.asked(out, "sandhome")[-2:], ["a", ""])

    def test_the_shell_picker_on_the_host_walks_absolute_paths(self):
        out = self.got("shell on the host: absolute paths")
        self.assertEqual((out["top_crumb"], out["top_up"]), ("/home/u", False))
        self.assertEqual(out["x_crumb"], "/home/u/x")
        self.assertEqual(self.asked(out, "host"), ["", "%2Fhome%2Fu%2Fx", "%2Fhome%2Fu", "%2Fhome", "%2F"])
        self.assertEqual((out["root_crumb"], out["root_up"]), ("/", True))   # nothing above /

    def test_a_folder_that_cannot_be_read_goes_back_to_the_default(self):
        out = self.got("a folder that cannot be read: back to the default")
        self.assertEqual(self.asked(out, "sandhome")[-2:], ["gone", ""])
        self.assertEqual(out["crumb"], "sandhome")
        self.assertEqual(out["kids"], ["サブディレクトリを開く…", "gone"])

    def test_no_default_folder_is_said_in_the_picker(self):
        out = self.got("not even the default: said in the picker")
        self.assertEqual((out["crumb"], out["up"], out["kids"], out["off"]), ("", True, ["(一覧を取得できません)"], True))

    def test_a_new_folder_in_the_shell_picker(self):
        out = self.got("＋ in the shell picker")
        posts = [b for m, p, b in out["log"] if m == "POST" and p == "/workdirs"]
        self.assertEqual(posts, [{"scope": "sandhome", "dir": "", "name": "新"}])
        self.assertEqual(out["crumb"], "sandhome/新")

    def test_a_refused_new_folder_is_said(self):
        out = self.got("＋ in Claude's picker, refused")
        posts = [b for m, p, b in out["log"] if m == "POST" and p == "/workdirs"]
        self.assertEqual(posts, [{"scope": "sandhome", "dir": "", "name": "新"}])
        self.assertEqual(out["alerts"], ["ディレクトリを作れませんでした: exists"])

    def test_a_new_folder_with_no_name_posts_nothing(self):
        out = self.got("＋ with no name: nothing")
        self.assertEqual([p for m, p, _ in out["log"] if m == "POST" and p == "/workdirs"], [])

    def test_root_and_email_from_the_capabilities(self):
        out = self.got("capabilities: root and Email")
        # Email first; the ssh machines after this host's places (the deployment notes 段3)
        self.assertEqual([v for v, _ in out["places"]], ["mail", "dev", "host", "root", "ssh:winbox"])
        for p in ("root-shell", "claude-root", "codex-root", "mail-tui", "mail-shell"):
            self.assertIn(p, out["presets"])
        self.assertNotIn("codex-mail", out["presets"])                  # Email's Codex not ready
        self.assertEqual(dict(out["codexPlaces"])["mail"], True)        # so not offered
        self.assertEqual(out["preset"], "codex-root")
        self.assertFalse(out["skipDev"])     # devbox's Codex: the checkbox
        self.assertTrue(out["skipRoot"])     # root's: none (2026-11-24, the user: root は Skip 無し)

    def test_a_resumed_conversation_brings_its_name_unless_one_was_typed(self):
        out = self.got("resume: the conversation's name as the label")
        self.assertEqual(out["options"][1:], ["[前の名前] 要約", "(c2c2c2c2)"])
        self.assertEqual(out["label1"], "前の名前")
        self.assertEqual(out["label2"], "")         # its own name went with it
        self.assertEqual(out["label3"], "自分の名前")

    def test_a_demo_room_offers_only_its_ai(self):
        out = self.got("demo: only the AI")
        self.assertEqual((out["kinds"], out["places"], out["presets"]), (["agent"], ["dev"], ["agent"]))
        self.assertTrue(out["loginsHidden"])
        self.assertEqual(out["machines"], ["local", "auth"])   # no ssh machines, no Email, no root


if __name__ == "__main__":
    unittest.main()
