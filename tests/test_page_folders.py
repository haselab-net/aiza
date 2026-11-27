"""The session list's own buttons, in headless Chrome against the stand-in
backend (the deployment notes, the deployment notes, the deployment notes):
a folder's ✏️ (name, 作業フォルダ), ＋ (a session there, a folder inside),
🗄 and its undo, 🗑; a session row's ✏️ 🗄 🗑 and the archive's 📤;
Ctrl+Z; the patrol bar's ✏️ and 🗑; the tmux sessions' 接続; the locked
rows' 🔓 -- what each sends and what the page says when it is refused.

    python3 -m unittest discover -s tests -v
"""
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_failures as F   # (not its class itself: unittest would run it here again)
import test_page_list as L
from page_run import STEPS, posted, run_page, steps_js
from test_page_flow import CHROME

S0, S1, S2, S5, S9 = "aaaaaaaaaa00", "aaaaaaaaaa01", "aaaaaaaaaa02", "aaaaaaaaaa05", "aaaaaaaaaa09"
# L.FOLDERS and an empty one (空, fe): only that has 🗑
FOLDERS = {"folders": L.FOLDERS["folders"] + [{"id": "fe", "name": "空"}], "assign": L.FOLDERS["assign"]}
FS = {"folders": FOLDERS}
OPS = "POST /folders/ops"

HELPERS = L.HELPERS + r"""
  // A session's and a folder's buttons are in its ⋯ (the deployment notes 段4), its mark first.
  const btn = (k, text) => { const b = [...row(k).querySelectorAll(':scope > button, :scope > .row-acts > button')]
      .find((x) => x.textContent === text || (x.firstChild && x.firstChild.nodeType === 3 && x.firstChild.textContent === text));
    if (b) b.click(); else out.missing = text + " on " + k; };
  // A folder's ⋯ opened (more), then an item of it by its words (pickMenu).
  const more = (k) => { const b = row(k).querySelector(':scope > .row-more'); if (b) b.click(); else out.missing = "⋯ on " + k; };
  const menuWords = () => [...document.querySelectorAll('.row-acts:not([hidden]) > button span')].map((x) => x.textContent);
  const pickMenu = (text) => { const b = [...document.querySelectorAll('.row-acts:not([hidden]) > button')].find((x) => x.querySelector('span').textContent === text);
    if (b) b.click(); else out.missing = "menu " + text; };
  const toast = () => { const e = document.querySelector('.undo-toast span'); return e ? e.textContent : null; };
  const ctrlZ = () => document.body.dispatchEvent(new KeyboardEvent('keydown', { key: 'z', ctrlKey: true, bubbles: true }));
  const label = (k) => row(k).querySelector('.label').textContent.trim();
"""
ASK = "window.prompt = (m, d) => { (out.asked = out.asked || []).push(d); return %s; }; "
SAY = "window.confirm = (m) => { (out.said = out.said || []).push(m); return %s; }; "
REFUSED = lambda key: {key: [{"status": 500, "body": {"error": "だめ"}}]}

# name: (stand-in settings, [(js, wait ms)])
CASES = {
    "folder: rename": (FS, [
        (ASK % "' 研究 '" + "more('fa')", 200), ("out.menu = menuWords(); pickMenu('名前を変更')", 800),
        ("out.label = label('fa')", 100),
    ]),
    "folder: the same name or none": (FS, [
        (ASK % "'仕事'" + "more('fa')", 200), ("pickMenu('名前を変更')", 500),
        (ASK % "null" + "more('fa')", 200), ("pickMenu('名前を変更')", 500),
    ]),
    "folder: 作業フォルダ, a session there": (FS, [
        (ASK % "'~/proj/a/'" + "more('fa')", 200), ("pickMenu('作業ディレクトリを設定')", 800),
        ("out.wd = row('fa').querySelector('.workdir').textContent; out.title = row('fa').title; row('fa').querySelector('.ficon').click()", 300),
        # select it, then the top row's ＋ 🤖 AI (the folder's own ＋ went, 2026-11-27)
        ("row('fb').click()", 200), ("document.getElementById('start-btn').click()", 300),
        ("const b = document.getElementById('nsb-folder'); out.bar = b.hidden ? null : b.querySelector('span').textContent;"
         " document.getElementById('create-btn').click()", 1500),
    ]),
    "folder: 作業フォルダ with .., cancelled, the bar's ✕": (FS, [
        (ASK % "'a/../b'" + "more('fa')", 200), ("pickMenu('作業ディレクトリを設定')", 500),
        (ASK % "null" + "more('fa')", 200), ("pickMenu('作業ディレクトリを設定')", 500),
        ("row('fe').click()", 200), ("document.getElementById('start-btn').click()", 300),
        ("const b = document.getElementById('nsb-folder'); out.bar = b.querySelector('span').textContent; b.querySelector('button').click()", 200),
        ("out.after = document.getElementById('nsb-folder').hidden", 100),
    ]),
    "folder: a folder inside": (FS, [
        ("row('fe').click()", 200), ("document.getElementById('new-folder-btn').click()", 200),
        ("document.getElementById('new-folder-name').value = '中'; document.getElementById('new-folder-add').click()", 800),
        ("out.rows = rows()", 100),
    ]),
    "folder: delete the empty one": (FS, [
        ("out.trash = [...document.querySelectorAll('#sessions > .folder-row')].filter((r) => [...r.querySelectorAll(':scope > .row-acts > button')]"
         ".some((b) => b.firstChild.textContent === '🗑')).map((r) => r.dataset.folderId); " + SAY % "true" + "btn('fe', '🗑')", 800),
        ("out.rows = rows()", 100),
    ]),
    "folder: delete declined": (FS, [
        (SAY % "false" + "btn('fe', '🗑')", 800),
        ("out.rows = rows()", 100),
    ]),
    "folder: 🗄 and 元に戻す": (FS, [
        ("btn('fa', '🗄')", 800),
        ("out.toast = toast(); out.rows = rows(); document.querySelector('.undo-toast button').click()", 800),
        ("out.toast2 = toast(); out.rows2 = rows()", 100),
    ]),
    "folder: 🗄 and Ctrl+Z": (FS, [
        ("btn('fe', '🗄')", 800),
        ("ctrlZ()", 800),
        ("out.toast = toast(); out.rows = rows()", 100),
    ]),
    "Ctrl+Z, nothing to undo": (FS, [
        ("ctrlZ()", 300),
        ("out.toast = toast()", 100),
    ]),
    "folder: not saved": (dict(FS, faults=REFUSED(OPS)), [
        (ASK % "'研究'" + "more('fa')", 200), ("pickMenu('名前を変更')", 1000),
        ("out.label = label('fa')", 100),
    ]),
    "folder: resume, one refused": (dict(FS, faults=REFUSED("POST /sessions")), [
        ("row('fc').querySelector('.dot.resumable').click()", 1500),
    ]),
    "session: rename": ({}, [
        (ASK % "' 新しい名前 '" + f"btn('{S1}', '✏️')", 1000),
    ]),
    "session: rename cancelled or the same": ({}, [
        (ASK % "null" + f"btn('{S1}', '✏️')", 500),
        (ASK % "'s1'" + f"btn('{S1}', '✏️')", 500),
    ]),
    "session: rename refused": ({"faults": REFUSED(f"POST /sessions/{S1}/rename")}, [
        (ASK % "'x'" + f"btn('{S1}', '✏️')", 1000),
    ]),
    "session: delete, declined": ({}, [
        (SAY % "false" + f"btn('{S1}', '🗑')", 600),
        (SAY % "true" + f"btn('{S1}', '🗑')", 1000),
    ]),
    "session: 🗄 and Ctrl+Z": ({}, [
        (f"btn('{S0}', '🗄')", 1000),
        ("out.toast = toast(); ctrlZ()", 1000),
        ("out.toast2 = toast()", 100),
    ]),
    "session: 🗄 refused": ({"faults": REFUSED(f"POST /sessions/{S0}/archive")}, [
        (f"btn('{S0}', '🗄')", 1000),
        ("out.toast = toast()", 100),
    ]),
    # The ended one is shown with 止まったセッションも (the deployment notes 段4: hidden by default).
    "session dots: resume the ended one, stop a running one": ({}, [
        ("document.getElementById('show-stopped').click()", 300),
        (SAY % "true" + f"row('{S1}').querySelector('.dot.stoppable').click()", 1500),
        ("out.stopHash = location.hash; " + SAY % "true" + f"row('{S5}').querySelector('.dot.resumable').click()", 1500),
        ("out.hash = location.hash", 100),
    ]),
    "the archive: 📤 refused, 🗑": ({"faults": REFUSED(f"POST /sessions/{S9}/unarchive")}, [
        ("document.getElementById('archive-toggle-btn').click()", 500),
        (f"document.querySelector('#archived-list [data-session-id={S9}] .archive-btn').click()", 1000),
        (SAY % "true" + f"document.querySelector('#archived-list [data-session-id={S9}] .delete-btn').click()", 1000),
    ]),
    "patrol: ✏️ the open one": ({}, [
        (f"row('{S1}').click()", 1500),
        (ASK % "'巡回で'" + "document.getElementById('patrol-rename').click()", 1500),
        ("out.title = document.getElementById('chat-label').textContent", 100),
    ]),
    "patrol: 🗑 refused": ({"faults": REFUSED(f"POST /sessions/{S1}/delete")}, [
        (f"row('{S1}').click()", 1500),
        ("document.getElementById('patrol-delete').click()", 1500),
        ("out.hash = location.hash", 100),
    ]),
    "patrol: the title opens and closes the bar": ({}, [
        (f"row('{S1}').click()", 1500),
        ("out.open = !document.getElementById('patrol-bar').hidden; document.getElementById('chat-label').click()", 200),
        ("out.closed = document.getElementById('patrol-bar').hidden; document.getElementById('chat-label').click()", 200),
        ("out.again = !document.getElementById('patrol-bar').hidden", 100),
    ]),
    "tmux: 接続": ({}, [
        ("out.rows = [...document.querySelectorAll('#tmux-sessions .tmux-row')].map((r) => r.textContent);"
         " document.querySelector('#tmux-sessions button').click()", 1500),
        ("out.hash = location.hash", 100),
    ]),
    "tmux: 接続 refused": ({"faults": REFUSED("POST /sessions/adopt")}, [
        ("document.querySelector('#tmux-sessions button').click()", 1500),
        ("out.hash = location.hash", 100),
    ]),
    "locked rows: 🔓 refused": ({"faults": {"POST /unlock/begin-assertion": [{"every": True, "status": 500, "body": {"error": "鍵なし"}}]}}, [
        ("const b = document.getElementById('tree-tools').previousElementSibling.querySelector('button');"
         " window.__alerts.length = 0; b.click()", 1500),
    ]),
}


def probe(steps):
    return F.PROBE.replace(STEPS, HELPERS + "  const steps = " + steps_js(steps) + ";")


def run_case(settings, steps, static=None):
    return run_page(probe(steps), settings, 4000 + sum(w for _, w in steps), static=static)


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageFoldersTest(unittest.TestCase):
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

    def folder(self, out, fid):
        return next((f for f in out["folders"]["folders"] if f["id"] == fid), None)

    def test_folder_rename(self):
        out = self.got("folder: rename")
        self.assertEqual(out["menu"], ["名前を変更", "作業ディレクトリを設定", "フォルダごと共有…", "アーカイブへ移動"])
        self.assertEqual(out["asked"], ["仕事"])
        self.assertEqual(posted(out, OPS), [{"ops": [{"op": "put", "folder": {"id": "fa", "name": "研究"}}]}])
        self.assertEqual(out["label"], "📁▶ 研究")
        self.assertEqual(out["alerts"], [])

    def test_folder_rename_to_the_same_or_cancelled_sends_nothing(self):
        out = self.got("folder: the same name or none")
        self.assertEqual(posted(out, OPS), [])

    def test_folder_workdir_and_a_session_started_there(self):
        out = self.got("folder: 作業フォルダ, a session there")
        self.assertEqual(posted(out, OPS), [{"ops": [{"op": "put", "folder": {"id": "fa", "workdir": "proj/a"}}]}])
        self.assertEqual(out["wd"], "~/proj/a")
        self.assertEqual(out["title"], "作業ディレクトリ ~/proj/a")
        # 下 has none of its own: its parent's
        self.assertEqual(out["bar"], "📁 下 · 作業ディレクトリ ~/proj/a")
        made = posted(out, "POST /sessions")
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0]["folder"], "fb")
        self.assertNotIn("cwd", made[0])   # the backend picks it from the folder

    def test_folder_workdir_refuses_dotdot_and_cancel_sends_nothing(self):
        out = self.got("folder: 作業フォルダ with .., cancelled, the bar's ✕")
        self.assertEqual(posted(out, OPS), [])
        self.assertEqual(out["alerts"], ["「..」は使えません"])
        self.assertEqual(out["bar"], "📁 空")
        self.assertTrue(out["after"])

    def test_a_folder_inside_another(self):
        out = self.got("folder: a folder inside")
        ops = posted(out, OPS)
        self.assertEqual(len(ops), 1)
        f = ops[0]["ops"][0]["folder"]
        self.assertEqual((f["name"], f["parent"]), ("中", "fe"))
        # the parent opened to show it
        self.assertEqual(out["rows"][out["rows"].index("📁fe") + 1], "📁" + f["id"])

    def test_only_an_empty_folder_can_be_deleted(self):
        out = self.got("folder: delete the empty one")
        self.assertEqual(out["trash"], ["fe"])
        self.assertEqual(out["said"], ["フォルダ「空」を消しますか?"])
        self.assertEqual(posted(out, OPS), [{"ops": [{"op": "delete", "id": "fe"}]}])
        self.assertNotIn("📁fe", out["rows"])
        self.assertIsNone(self.folder(out, "fe"))

    def test_delete_declined_sends_nothing(self):
        out = self.got("folder: delete declined")
        self.assertEqual(posted(out, OPS), [])
        self.assertIn("📁fe", out["rows"])

    def test_folder_archive_and_undo(self):
        out = self.got("folder: 🗄 and 元に戻す")
        self.assertEqual(posted(out, OPS), [{"ops": [{"op": "put", "folder": {"id": "fa", "archived": True}}]},
                                            {"ops": [{"op": "put", "folder": {"id": "fa", "archived": False}}]}])
        self.assertEqual(out["toast"], "フォルダ「仕事」をアーカイブしました")
        self.assertNotIn("📁fa", out["rows"])
        self.assertEqual(out["toast2"], "フォルダ「仕事」をアーカイブから戻しました")
        self.assertIn("📁fa", out["rows2"])

    def test_folder_archive_undone_by_ctrl_z(self):
        out = self.got("folder: 🗄 and Ctrl+Z")
        self.assertEqual([o["ops"][0]["folder"].get("archived") for o in posted(out, OPS)], [True, False])
        self.assertEqual(out["toast"], "フォルダ「空」をアーカイブから戻しました")
        self.assertIn("📁fe", out["rows"])

    def test_ctrl_z_with_nothing_to_undo_says_so(self):
        out = self.got("Ctrl+Z, nothing to undo")
        self.assertEqual(out["toast"], "元に戻すアーカイブはありません")

    def test_folders_not_saved_are_said_and_read_again(self):
        out = self.got("folder: not saved")
        self.assertEqual(out["alerts"], ["フォルダを保存できませんでした: だめ"])
        # read again from the server: the name it has
        self.assertGreaterEqual(sum(1 for m, p, _ in out["log"] if (m, p) == ("GET", "/folders")), 2)
        self.assertEqual(out["label"], "📁▶ 仕事")

    def test_folder_resume_refused_is_said(self):
        out = self.got("folder: resume, one refused")
        self.assertEqual(out["alerts"], ["再開できなかったもの:\nended: だめ"])
        # what the stop stopped is cleared all the same
        self.assertEqual(posted(out, OPS), [{"ops": [{"op": "put", "folder": {"id": "fc", "last_stopped": []}}]}])

    def test_session_rename(self):
        out = self.got("session: rename")
        self.assertEqual(out["asked"], ["s1"])
        self.assertEqual(posted(out, f"POST /sessions/{S1}/rename"), [{"label": "新しい名前"}])

    def test_session_rename_cancelled_or_the_same_sends_nothing(self):
        out = self.got("session: rename cancelled or the same")
        self.assertEqual(posted(out, f"POST /sessions/{S1}/rename"), [])

    def test_session_rename_refused_is_said(self):
        out = self.got("session: rename refused")
        self.assertEqual(out["alerts"], ["名前を変更できませんでした: だめ"])

    def test_session_delete_asks_first(self):
        out = self.got("session: delete, declined")
        self.assertEqual(len(out["said"]), 2)
        self.assertIn("「s1」の会話ログを削除します", out["said"][0])
        self.assertEqual(len(posted(out, f"POST /sessions/{S1}/delete")), 1)

    def test_session_archive_undone_by_ctrl_z(self):
        out = self.got("session: 🗄 and Ctrl+Z")
        self.assertEqual(len(posted(out, f"POST /sessions/{S0}/archive")), 1)
        self.assertEqual(out["toast"], "「s0」をアーカイブしました")
        self.assertEqual(len(posted(out, f"POST /sessions/{S0}/unarchive")), 1)
        self.assertEqual(out["toast2"], "「s0」をアーカイブから戻しました")

    def test_session_archive_refused_is_said_and_offers_no_undo(self):
        out = self.got("session: 🗄 refused")
        self.assertEqual(out["alerts"], ["アーカイブできませんでした: だめ"])
        self.assertIsNone(out["toast"])

    def test_a_rows_dot_resumes_or_stops_it(self):
        out = self.got("session dots: resume the ended one, stop a running one")
        self.assertEqual(len(out["said"]), 2)
        made = posted(out, "POST /sessions")
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].get("resume"), "c0ffee")
        self.assertEqual(len(posted(out, f"POST /sessions/{S1}/stop")), 1)
        self.assertEqual(out["stopHash"], "")   # stopping did not open it
        self.assertEqual(out["hash"], "#aaaaaaaaaa07")   # the resumed one opens

    def test_archived_restore_refused_and_delete(self):
        out = self.got("the archive: 📤 refused, 🗑")
        self.assertEqual(out["alerts"], ["元に戻せませんでした: だめ"])
        self.assertEqual(len(posted(out, f"POST /sessions/{S9}/delete")), 1)

    def test_patrol_rename_changes_the_title_too(self):
        out = self.got("patrol: ✏️ the open one")
        self.assertEqual(posted(out, f"POST /sessions/{S1}/rename"), [{"label": "巡回で"}])
        self.assertTrue(out["title"].endswith("巡回で"), out["title"])

    def test_patrol_delete_refused_stays(self):
        out = self.got("patrol: 🗑 refused")
        self.assertEqual(out["alerts"], ["削除できませんでした: だめ"])
        self.assertEqual(out["hash"], f"#{S1}")

    def test_the_chat_title_opens_and_closes_the_patrol_bar(self):
        out = self.got("patrol: the title opens and closes the bar")
        self.assertEqual((out["open"], out["closed"], out["again"]), (True, True, True))

    def test_tmux_adopt_opens_it(self):
        out = self.got("tmux: 接続")
        self.assertEqual(out["rows"], ["work (container)接続"])
        body = posted(out, "POST /sessions/adopt")
        self.assertEqual(len(body), 1)
        self.assertEqual((body[0]["tmux_name"], body[0]["location"], body[0]["label"]), ("work", "container", "work"))
        self.assertGreater(body[0]["cols"], 0)
        self.assertEqual(out["hash"], "#aaaaaaaaaa06")

    def test_tmux_adopt_refused_is_said(self):
        out = self.got("tmux: 接続 refused")
        self.assertEqual(out["alerts"], ["接続に失敗しました: だめ"])
        self.assertEqual(out["hash"], "")

    def test_locked_rows_unlock_refused_is_said(self):
        out = self.got("locked rows: 🔓 refused")
        self.assertEqual(len(out["alerts"]), 1)
        self.assertIn("鍵なし", out["alerts"][0])


if __name__ == "__main__":
    unittest.main()
