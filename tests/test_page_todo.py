"""The to-do list (✅, the deployment notes), in headless Chrome against the stand-in
backend: which group each session's state puts it in and what its entry
says; ✓ and its 元に戻す, 💤 (the three choices, a date typed, one that
cannot be read), ⏰; the handoffs (🔁) and their ✓; an entry opened marks
it seen; and what the page says when the server refuses.

    python3 -m unittest discover -s tests -v
"""
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import test_page_failures as F   # (not its class itself: unittest would run it here again)
from page_harness import T0
from page_run import STEPS, posted, run_page, steps_js
from test_page_flow import CHROME

Y, Y2, DUE, SN, DN, W = ("dddddddddd%02d" % i for i in range(6))


def sess(i, label, task, **kw):
    return dict({"id": i, "label": label, "alive": True, "created_ts": T0, "preset": "claude-tui",
                 "tmux_location": "container", "task": task}, **kw)


SESSIONS = {"sessions": [
    sess(Y, "あなた", {"state": "you", "ts": T0 - 60, "text": "見てください", "seen": False, "declared": True}, waiting=True),
    sess(Y2, "黙った", {"state": "you", "ts": T0 - 30, "declared": False}),
    sess(DUE, "期限", {"state": "snooze", "ts": T0 - 9000, "until": T0 - 3600, "text": "待った"}),
    sess(SN, "寝た", {"state": "snooze", "ts": T0 - 9000, "until": T0 + 86400, "text": "返事待ち"}, alive=False, stopped=True),
    sess(DN, "済んだ", {"state": "done", "ts": T0 - 120, "text": "終わり", "seen": False}, usage={"cost": 1.25, "tokens": 12000}),
    sess(W, "作業", {"state": "working", "ts": T0, "seen": True}),
]}
HANDOFFS = {"handoffs": [
    {"id": "h1", "from": W, "from_label": "作業", "to": Y, "to_label": "あなた", "head": "これを頼みます", "ts": T0 - 50, "to_state": "working"},
    {"id": "h2", "from": W, "from_label": "作業", "to": DN, "to_label": "済んだ", "head": "片付いた件", "ts": T0 - 40, "done_ts": T0 - 5},
    {"id": "h3", "from": W, "from_label": "作業", "to": "dddddddd99", "to_label": "消えた", "head": "", "ts": T0 - 30, "to_gone": True},
]}
BASE = {"GET /sessions": [{"every": True, "body": SESSIONS}], "GET /handoffs": [{"every": True, "body": HANDOFFS}]}
TASK = lambda sid, task: {f"POST /sessions/{sid}/task": [{"every": True, "body": {"ok": True, "task": task}}]}
REFUSED = lambda key: {key: [{"every": True, "status": 500, "body": {"error": "だめ"}}]}

HELPERS = r"""
  const entries = () => [...document.querySelectorAll('#todo-modal .item')].map((e) => [
    (e.querySelector('.who') || {}).textContent || '', (e.querySelector('.msg') || {}).textContent || '',
    (e.querySelector('.when') || {}).textContent || '', [...e.querySelectorAll('.btns button')].map((b) => b.textContent)]);
  const entry = (who) => [...document.querySelectorAll('#todo-modal .item')].find((e) => (e.querySelector('.who') || {}).textContent.includes(who));
  const press = (who, text) => { const e = entry(who); const b = e && [...e.querySelectorAll('.btns button')].find((x) => x.textContent === text);
    if (b) b.click(); else out.missing = text + " on " + who; };
  const toast = () => { const e = document.querySelector('.undo-toast span'); return e ? e.textContent : null; };
"""
OPEN = ("document.querySelector('#work-views a[data-view=ball]').click()", 1200)
ASK = "window.prompt = (m, d) => { (out.asked = out.asked || []).push(m); return %s; }; "

# name: (faults, [(js, wait ms)])
CASES = {
    "the groups": (BASE, [
        OPEN,
        ("out.groups = [...document.querySelectorAll('#todo-modal .group')].map((e) => e.textContent); out.entries = entries();"
         " out.badge = document.getElementById('todo-badge').textContent", 100),
    ]),
    "✓ and 元に戻す": ({**BASE, **TASK(Y, {"state": "done", "ts": T0, "by_hand": True})}, [
        OPEN, ("press('あなた', '✓')", 1200),
        ("out.toast = toast(); document.querySelector('.undo-toast button').click()", 1200),
        ("out.toast2 = toast()", 100),
    ]),
    "✓ on one done: seen": ({**BASE, **TASK(DN, {"state": "done", "ts": T0, "seen": True})}, [
        OPEN, ("press('済んだ', '✓')", 1200),
        ("out.toast = toast()", 100),
    ]),
    # The page's own popup (the deployment notes): the usual times as buttons, or a date and time.
    "💤: a choice, a date, unreadable, cancelled": ({**BASE, **TASK(Y2, {"state": "you", "ts": T0, "declared": False})}, [
        OPEN, ("window.__popManual = true; press('黙った', '💤')", 800),
        ("const P = (q) => document.querySelector('.aiza-pop-ask ' + q); " + "out.labels = [...document.querySelectorAll('.aiza-pop-ask .pop-choice')].map((b) => b.textContent);"
         " out.title = P('.pop-head span').textContent; document.querySelectorAll('.aiza-pop-ask .pop-choice')[1].click();"
         " P('.pop-ok').click()", 800),
        ("press('黙った', '💤')", 800),
        ("const P = (q) => document.querySelector('.aiza-pop-ask ' + q); " + "let y = new Date().getFullYear(); if (new Date(y, 11, 31, 18, 30) < new Date()) y++;"
         " const c = P('.pop-custom'); c.value = y + '-12-31T18:30'; c.dispatchEvent(new Event('input')); P('.pop-ok').click()", 800),
        ("press('黙った', '💤')", 800),
        ("const P = (q) => document.querySelector('.aiza-pop-ask ' + q); " + "const c = P('.pop-custom'); c.value = '2000-01-01T09:00'; c.dispatchEvent(new Event('input')); P('.pop-ok').click()", 800),
        ("press('黙った', '💤')", 800),
        ("const P = (q) => document.querySelector('.aiza-pop-ask ' + q); " + "P('.close').click()", 500),
        ("out.open = document.querySelectorAll('.aiza-pop').length", 100),
    ]),
    "⏰ on a snoozed one": ({**BASE, **TASK(SN, {"state": "you", "ts": T0})}, [
        OPEN, ("press('寝た', '⏰')", 1000),
    ]),
    "a task not saved": ({**BASE, **REFUSED(f"POST /sessions/{SN}/task")}, [
        OPEN, ("press('寝た', '⏰')", 1000),
    ]),
    "a handoff closed": (BASE, [
        OPEN, ("const e = entry('作業 → 済んだ'); e.querySelector('.btns button').click()", 1000),
    ]),
    "a handoff not closed": ({**BASE, **REFUSED("POST /handoffs/h1")}, [
        OPEN, ("const e = entry('作業 → あなた'); e.querySelector('.btns button').click()", 1000),
        ("out.still = !!entry('作業 → あなた')", 100),
    ]),
    "an entry opened: seen": ({**BASE, **TASK(Y, {"state": "you", "ts": T0, "seen": True})}, [
        OPEN, ("entry('あなた').querySelector('a.body').click()", 1500),
        ("out.hash = location.hash; out.todo = document.getElementById('todo-modal').classList.contains('visible') || document.body.classList.contains('todo-page')", 100),
    ]),
    "looked at again: seen": ({**BASE, **TASK(W, {"state": "working", "ts": T0, "seen": True})}, [
        OPEN, ("entry('作業').querySelector('a.body').click()", 1500),
        ("window.dispatchEvent(new Event('pointerdown')); document.dispatchEvent(new Event('visibilitychange'))", 800),
    ]),
    # 番ごと has no 一覧 | 木 of its own any more (the deployment notes 段5): 仕事's 🌳 木 is the tree.
    "the tree and back": (BASE, [
        OPEN, ("out.views = !!document.querySelector('#todo-modal .todo-views'); out.head = !!document.querySelector('#todo-modal .head');"
               " document.querySelector('#work-views a[data-view=tree]').click()", 1000),
        ("out.tree = !!document.querySelector('.wtree'); document.querySelector('#work-views a[data-view=ball]').click()", 800),
        ("out.entries = entries().length", 100),
    ]),
}


def probe(steps):
    return F.PROBE.replace(STEPS, HELPERS + "  const steps = " + steps_js(steps) + ";")


def run_case(faults, steps, static=None):
    return run_page(probe(steps), {"faults": faults}, 4000 + sum(w for _, w in steps), static=static)


def at9(days):
    d = datetime.now() + timedelta(days=days)
    return d.replace(hour=9, minute=0, second=0, microsecond=0).timestamp()


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageTodoTest(unittest.TestCase):
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

    def test_each_state_in_its_group(self):
        out = self.got("the groups")
        # ...then the work tree's items no session here holds (人と AI's, 段5): nobody's, folded.
        self.assertEqual(out["groups"], ["🙋 あなたの番 (2)", "⏰ 期限が来た寝かせ (1)", "⚙️ AI 作業中 (1)",
                                         "💤 待ち(寝かせ) (1)", "✓ 済み(未確認) (1)", "🔁 引き継ぎ中 (3)",
                                         "▸ ○ まだ誰も持っていない (1)"])
        rows = {e[0].replace("🛠️ ", ""): e for e in out["entries"]}
        self.assertEqual(rows["あなた"][1], "確認待ち — 見てください")
        self.assertEqual(rows["あなた"][3], ["✓", "💤"])
        self.assertEqual(rows["済んだ"][3], ["✓", "💤"])
        self.assertEqual(rows["黙った"][1], "止まりました(状態の申告なし)")
        self.assertIn("💤 ", rows["期限"][2])
        self.assertIn("止めてあります(開くと続きから)", rows["寝た"][2])
        self.assertEqual(rows["寝た"][3], ["✓", "⏰"])
        self.assertIn("≈", rows["済んだ"][2])
        self.assertIn("≈$1.25 · 12k tok", rows["済んだ"][2])
        self.assertEqual(rows["作業"][3], ["✓"])
        # the handoffs: the finished one first, then the newest
        hand = [e for e in out["entries"] if e[0].startswith("🔁")]
        self.assertEqual([e[0] for e in hand], ["🔁 作業 → 済んだ", "🔁 作業 → 消えた", "🔁 作業 → あなた"])
        self.assertTrue(hand[0][2].startswith("片付いた — 確かめて閉じてください"))
        self.assertTrue(hand[1][2].startswith("相手のセッションはもうありません"))
        self.assertTrue(hand[2][2].startswith("相手が作業中"))
        self.assertEqual(out["badge"], "3")   # you ×2 and the due one

    def test_check_and_undo_put_the_task_back(self):
        out = self.got("✓ and 元に戻す")
        sent = posted(out, f"POST /sessions/{Y}/task")
        self.assertEqual(sent[0], {"state": "done"})
        self.assertEqual(sent[1], {"restore": SESSIONS["sessions"][0]["task"]})
        self.assertEqual(out["toast"], "「あなた」を済みにしました")
        self.assertEqual(out["toast2"], "「あなた」を元に戻しました")

    def test_check_on_a_done_one_marks_it_seen(self):
        out = self.got("✓ on one done: seen")
        self.assertEqual(posted(out, f"POST /sessions/{DN}/task"), [{"seen": True}])
        self.assertEqual(out["toast"], "「済んだ」を確認済みにしました")

    def test_snooze_choices_a_date_and_one_unreadable(self):
        out = self.got("💤: a choice, a date, unreadable, cancelled")
        self.assertEqual(out["title"], "いつまで寝かせますか")
        self.assertTrue(out["labels"][0].startswith("明日"), out["labels"])
        sent = [b["until"] for b in posted(out, f"POST /sessions/{Y2}/task")]
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[0], at9(3))
        now = datetime.now()
        x = datetime(now.year, 12, 31, 18, 30)
        self.assertEqual(sent[1], (x if x >= now else x.replace(year=now.year + 1)).timestamp())
        self.assertEqual(out["alerts"], ["日付が読めませんでした"])   # a time gone by: said, not sent
        self.assertEqual(out["open"], 0)                              # ✕ closed it, nothing written to lose
        self.assertTrue(all(b["state"] == "snooze" for b in posted(out, f"POST /sessions/{Y2}/task")))

    def test_wake_a_snoozed_one(self):
        out = self.got("⏰ on a snoozed one")
        self.assertEqual(posted(out, f"POST /sessions/{SN}/task"), [{"state": "you"}])

    def test_a_task_not_saved_is_said(self):
        out = self.got("a task not saved")
        self.assertEqual(out["alerts"], ["だめ"])

    def test_a_handoff_closed(self):
        out = self.got("a handoff closed")
        self.assertEqual(len(posted(out, "POST /handoffs/h2")), 1)

    def test_a_handoff_not_closed_is_said_and_stays(self):
        out = self.got("a handoff not closed")
        self.assertEqual(out["alerts"], ["だめ"])
        self.assertTrue(out["still"])

    def test_an_entry_opened_is_marked_seen(self):
        out = self.got("an entry opened: seen")
        self.assertEqual(out["hash"], f"#{Y}")
        self.assertFalse(out["todo"])
        self.assertIn({"seen": True}, posted(out, f"POST /sessions/{Y}/task"))

    def test_the_page_coming_back_says_it_is_looked_at(self):
        out = self.got("looked at again: seen")
        self.assertEqual(posted(out, f"POST /sessions/{W}/task"), [{"seen": True}])

    def test_the_tree_and_back_to_the_list(self):
        out = self.got("the tree and back")
        self.assertFalse(out["views"])
        self.assertFalse(out["head"])
        self.assertTrue(out["tree"])
        self.assertEqual(out["entries"], 9)


if __name__ == "__main__":
    unittest.main()
