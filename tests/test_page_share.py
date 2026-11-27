"""A session's ⋯ pane and a folder's sharing (the deployment notes,
the deployment notes, the deployment notes), in headless Chrome against the
stand-in backend: 💾 the log saved under the server's file name (or its
own), a session shared with me offering only that; 共有する / 解除 and
their refusals; the linked sessions' → and ✂; a folder shared with
everyone or one person, co-working only with a person, and taken back.

    python3 -m unittest discover -s tests -v
"""
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_failures as F   # (not its class itself: unittest would run it here again)
import test_page_folders as P
import test_page_list as L
from page_harness import T0, sessions
from page_run import STEPS, posted, run_page, steps_js
from test_page_flow import CHROME

S0, S1, S2, SH = "aaaaaaaaaa00", "aaaaaaaaaa01", "aaaaaaaaaa02", "cccccccccc01"
OPS = "POST /folders/ops"
SHARE, UNSHARE = f"POST /sessions/{S2}/share", f"POST /sessions/{S2}/unshare"
DOWNLOAD = f"GET /sessions/{S2}/download"
REFUSED = lambda key: {key: [{"every": True, "status": 500, "body": {"error": "だめ"}}]}
# s0's link with a member this list does not have (a session of the other host's)
GONE = sessions({"rev": 0})
GONE[0]["link"] = dict(GONE[0]["link"], members=[{"id": "aaaaaaaaaa77", "label": "向こう", "stopped": True}])

HELPERS = P.HELPERS + r"""
  const pane = () => document.getElementById('share-pane');
  const paneButtons = () => [...pane().querySelectorAll('button')].filter((b) => !b.closest('[hidden]')).map((b) => b.textContent);
  const paneTap = (text) => { const b = [...pane().querySelectorAll('button')].find((x) => x.textContent === text);
    if (b) b.click(); else out.missing = "pane " + text; };
  const shareRows = (root) => [...root.querySelectorAll('.share-row span, .share-empty')].map((e) => e.textContent);
  const catchDownload = () => { const c = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function () { if (this.download) out.download = this.download; else c.call(this); }; };
  const fs = () => document.querySelector('#folder-share .box');
  const fsSet = (sel, v) => { const e = fs().querySelector(sel); e.value = v; e.dispatchEvent(new Event('change')); };
"""
OPEN = lambda sid: (f"row('{sid}').click()", 1500)
PANE = ("document.getElementById('share-btn').click()", 500)
FOLDER_SHARE = [("more('fa')", 200), ("pickMenu('フォルダごと共有…')", 300)]

# name: (stand-in settings, [(js, wait ms)])
CASES = {
    "💾 under the server's name": ({"faults": {DOWNLOAD: [{"body": {"x": 1}}]}}, [
        OPEN(S2), PANE, ("out.buttons = paneButtons(); catchDownload(); paneTap('💾 会話ログを保存')", 800),
    ]),
    "💾 refused": ({"faults": {DOWNLOAD: [{"status": 404, "body": {}}]}}, [
        OPEN(S2), PANE, ("paneTap('💾 会話ログを保存')", 800),
    ]),
    "shared with me: only 💾": ({"faults": {f"GET /shared/v/sessions/{SH}/download": [{"body": {}}]}}, [
        ("document.getElementById('shared-toggle-btn').click()", 300),
        ("document.querySelector('#shared-list .shared-folder').click()", 300),
        (f"document.querySelector('#shared-list [data-session-id={SH}]').click()", 1500),
        PANE, ("out.buttons = paneButtons(); catchDownload(); paneTap('💾 会話ログを保存')", 800),
    ]),
    "共有する and 解除": ({"faults": {SHARE: [{"body": {"shared_with": [], "shared_read": ["*"]}}],
                                     UNSHARE: [{"body": {"shared_with": [], "shared_read": []}}]}}, [
        OPEN(S2), PANE, ("out.before = shareRows(pane()); document.getElementById('share-add-btn').click()", 800),
        ("out.rows = shareRows(pane()); out.colored = document.getElementById('share-btn').classList.contains('shared');"
         " pane().querySelector('.unshare-btn').click()", 800),
        ("out.after = shareRows(pane())", 100),
    ]),
    "共有する: a person, co-working": ({"faults": {SHARE: [{"body": {"shared_with": ["bob"], "shared_read": []}}]}}, [
        OPEN(S2), PANE,
        ("const t = document.getElementById('share-target'); t.value = 'user'; t.dispatchEvent(new Event('change'));"
         " out.writeOk = !document.querySelector('#share-mode option[value=write]').disabled;"
         " document.getElementById('share-username').value = ' bob '; document.getElementById('share-mode').value = 'write';"
         " document.getElementById('share-add-btn').click()", 800),
        ("out.rows = shareRows(pane())", 100),
    ]),
    "共有する and 解除 refused": ({"faults": {**REFUSED(SHARE), UNSHARE: [{"status": 500, "body": {"error": "いや"}}]}}, [
        OPEN(S2), PANE, ("document.getElementById('share-add-btn').click()", 800),
        # a row to take off: the pane drawn again with one
        ("currentSharedRead = ['*']; document.getElementById('share-btn').click(); document.getElementById('share-btn').click()", 300),
        ("pane().querySelector('.unshare-btn').click()", 800),
    ]),
    "linked: → the other, ✂": ({"faults": {"POST /sessions/unlink": [{"every": True, "body": {"ok": True}}]}}, [
        OPEN(S0), PANE, ("out.buttons = paneButtons(); out.head = pane().querySelector('.share-links-head').textContent;"
                         " window.confirm = (m) => { out.asked = m; return true; }; paneTap('✂ 連携から外す')", 1000),
        ("out.hash = location.hash; paneTap('→ s1')", 1500),
        ("out.hash2 = location.hash; out.paneOpen = pane().classList.contains('visible')", 100),
    ]),
    "linked: → one not here": ({"faults": {"GET /sessions": [{"every": True, "body": {"sessions": GONE}}]}}, [
        OPEN(S0), PANE, ("paneTap('→ 向こう (停止中)')", 1500),
        ("out.hash = location.hash", 100),
    ]),
    "linked: ＋ another": ({}, [
        OPEN(S0), PANE, ("paneTap('＋ ほかのセッションを加える')", 800),
        ("out.hash = location.hash; out.banner = document.getElementById('link-armed-banner').classList.contains('visible')", 100),
    ]),
    "folder: shared with everyone, then a person co-working, taken back": ({"folders": L.FOLDERS}, [
        *FOLDER_SHARE,
        ("out.shown = !document.getElementById('folder-share').hidden; out.title = fs().querySelector('h3').textContent;"
         " out.before = shareRows(fs()); fs().querySelector('.add').click()", 800),
        ("out.everyone = shareRows(fs()); fsSet('.target', 'user');"
         " out.userShown = !fs().querySelector('.username').hidden; out.writeOk = !fs().querySelector('.mode option[value=write]').disabled;"
         " fs().querySelector('.username').value = 'bob'; fsSet('.mode', 'write'); fs().querySelector('.add').click()", 800),
        ("out.both = shareRows(fs()); out.badge = !!row('fa').querySelector('.meta[title]');"
         " [...fs().querySelectorAll('.share-row')].find((r) => r.dataset.user === '*').querySelector('.unshare-btn').click()", 800),
        ("out.left = shareRows(fs()); fsSet('.target', 'user'); fsSet('.mode', 'write'); fsSet('.target', '*');"
         " out.reset = [fs().querySelector('.username').hidden, fs().querySelector('.mode').value]; fs().querySelector('.close').click()", 300),
        ("out.closed = document.getElementById('folder-share').hidden", 100),
    ]),
    "folder: a person's name empty, the backdrop": ({"folders": L.FOLDERS}, [
        *FOLDER_SHARE,
        ("fsSet('.target', 'user'); fs().querySelector('.username').value = '  '; fs().querySelector('.add').click()", 500),
        ("const el = document.getElementById('folder-share'); el.dispatchEvent(new MouseEvent('click', { bubbles: true }))", 200),
        ("out.closed = document.getElementById('folder-share').hidden", 100),
    ]),
}


def probe(steps):
    return F.PROBE.replace(STEPS, HELPERS + "  const steps = " + steps_js(steps) + ";")


def run_case(settings, steps, static=None):
    return run_page(probe(steps), settings, 4000 + sum(w for _, w in steps), static=static)


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageShareTest(unittest.TestCase):
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

    def test_the_log_saved_under_its_own_name_when_the_server_gives_none(self):
        out = self.got("💾 under the server's name")
        self.assertIn("💾 会話ログを保存", out["buttons"])
        self.assertIn("共有する", out["buttons"])
        self.assertEqual(out["download"], f"aiza-{S2}.txt")
        self.assertEqual(out["alerts"], [])

    def test_the_log_not_saved_is_said(self):
        out = self.got("💾 refused")
        self.assertEqual(out["alerts"], ["ダウンロードに失敗しました: 404"])

    def test_a_session_shared_with_me_offers_only_the_log(self):
        out = self.got("shared with me: only 💾")
        self.assertEqual(out["buttons"], ["💾 会話ログを保存"])
        self.assertEqual(out["download"], f"aiza-{SH}.txt")
        self.assertEqual(len(posted(out, f"GET /shared/v/sessions/{SH}/download")), 1)

    def test_share_with_everyone_and_take_it_back(self):
        out = self.got("共有する and 解除")
        self.assertEqual(out["before"], ["まだ誰とも共有していません"])
        self.assertEqual(posted(out, SHARE), [{"username": "*", "mode": "read"}])
        self.assertEqual(out["rows"], ["全員 · 閲覧のみ"])
        self.assertTrue(out["colored"])
        self.assertEqual(posted(out, UNSHARE), [{"username": "*"}])
        self.assertEqual(out["after"], ["まだ誰とも共有していません"])

    def test_share_with_a_person_co_working(self):
        out = self.got("共有する: a person, co-working")
        self.assertTrue(out["writeOk"])
        self.assertEqual(posted(out, SHARE), [{"username": "bob", "mode": "write"}])
        self.assertEqual(out["rows"], ["bob · 共同作業"])

    def test_share_and_unshare_refused_are_said(self):
        out = self.got("共有する and 解除 refused")
        self.assertEqual(out["alerts"], ["共有に失敗しました: だめ", "共有解除に失敗しました: いや"])

    def test_linked_unlink_and_go_to_the_other(self):
        out = self.got("linked: → the other, ✂")
        self.assertIn("→ s1", out["buttons"])
        self.assertIn("＋ ほかのセッションを加える", out["buttons"])
        self.assertTrue(out["head"].startswith("🔗 連携中"), out["head"])
        self.assertIn("s1", out["asked"])
        self.assertEqual(len(posted(out, "POST /sessions/unlink")), 1)
        self.assertEqual(out["hash"], f"#{S0}")
        self.assertEqual(out["hash2"], f"#{S1}")
        self.assertFalse(out["paneOpen"])

    def test_linked_one_not_here_is_said(self):
        out = self.got("linked: → one not here")
        self.assertEqual(len(out["alerts"]), 1)
        self.assertIn("このセッションは見られません", out["alerts"][0])
        self.assertEqual(out["hash"], f"#{S0}")

    def test_linked_add_another_goes_to_the_list_armed(self):
        out = self.got("linked: ＋ another")
        self.assertEqual(out["hash"], "")
        self.assertTrue(out["banner"])

    def test_folder_sharing(self):
        out = self.got("folder: shared with everyone, then a person co-working, taken back")
        self.assertTrue(out["shown"])
        self.assertEqual(out["title"], "🧑‍🤝‍🧑 フォルダ「仕事」を共有")
        self.assertEqual(out["before"], ["まだ誰とも共有していません"])
        self.assertEqual(out["everyone"], ["全員 · 閲覧のみ"])
        self.assertTrue(out["userShown"])
        self.assertTrue(out["writeOk"])
        self.assertEqual(out["both"], ["全員 · 閲覧のみ", "bob · 共同作業"])
        self.assertTrue(out["badge"])
        self.assertEqual(out["left"], ["bob · 共同作業"])
        self.assertEqual(out["reset"], [True, "read"])
        self.assertTrue(out["closed"])
        self.assertEqual([o["ops"] for o in posted(out, OPS)], [
            [{"op": "share", "id": "fa", "username": "*", "mode": "read"}],
            [{"op": "share", "id": "fa", "username": "bob", "mode": "write"}],
            [{"op": "unshare", "id": "fa", "username": "*"}]])
        fa = next(f for f in out["folders"]["folders"] if f["id"] == "fa")
        self.assertEqual((fa["shared_with"], fa["shared_read"]), (["bob"], []))

    def test_folder_share_with_no_name_sends_nothing_and_the_backdrop_closes(self):
        out = self.got("folder: a person's name empty, the backdrop")
        self.assertEqual(posted(out, OPS), [])
        self.assertTrue(out["closed"])


if __name__ == "__main__":
    unittest.main()
