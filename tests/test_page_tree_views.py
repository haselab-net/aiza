"""The work tree's rows and folds, in headless Chrome against the stand-in
backend (the deployment notes): what a row says (その他 and the state of
the session holding it, 訳/原文, an issue, a repository, a desk report, the
cost), the folds (済みの枝, 済みの引き継ぎ, 終了済み) and the bar's filters,
＋ 新しい仕事; the ⋯ items the other tree tests leave (↩ 引き取りを取り消す,
↻ GitHub から読み直す, 共有(根で設定), Email in ▶ セッションで作業), the
balloon closing on a scroll; 週のまとめ with entries; /agents/#tree=<id>.

    python3 -m unittest discover -s tests -v
"""
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_tree as TT
from page_harness import T0
from page_run import posted, run_page, steps_js
from test_page_flow import CHROME

A, B = TT.A, TT.B
R0, DR, FOL, TK = "n0000000000r0", "n0000000000d0", "n0000000000f0", "n0000000000t0"
K1, K2, K3, K4, K5, K6, K7 = ("n0000000000k%d" % i for i in range(1, 8))
S1 = "aaaaaaaaaa01"
EXTRA = [
    {"id": R0, "parent": None, "title": "整理の仕事", "created_ts": T0, "links": {"repo": "org/repo"}},
    {"id": K1, "parent": R0, "title": "済んだ枝", "state": "done", "created_ts": T0 + 1},
    {"id": K2, "parent": R0, "title": "渡した件", "state": "done", "created_ts": T0 + 2,
     "links": {"handoff": "h1", "session": S1}, "session_label": "s1", "session_owner": "u"},
    {"id": K3, "parent": R0, "title": "その他", "rest": True, "created_ts": T0 + 3, "links": {"session": S1}},
    {"id": K4, "parent": R0, "title": "開いた枝", "created_ts": T0 + 4, "tr": {"title": "Open branch", "ball": "訳の球"},
     "ball": {"kind": "ai", "text": "原の球", "since": T0}, "usage": {"cost": 0.5, "tokens": 100}, "links": {"session": "aaaaaaaaaa02"}},
    {"id": K5, "parent": R0, "title": "課題", "created_ts": T0 + 5, "links": {"issue": "org/repo#3"}},
    {"id": K6, "parent": R0, "title": "窓口", "created_ts": T0 + 6, "links": {"ref": "desk/u/1234/abc"},
     "report_pos": {"events": 5}},
    {"id": DR, "parent": None, "title": "終わった木", "state": "done", "created_ts": T0 + 7},
    {"id": FOL, "parent": A, "title": "合わせる枝", "follows": True, "created_ts": T0 + 8},
    {"id": TK, "parent": None, "title": "引き取った仕事", "created_ts": T0 + 9, "taken": {"by": "u", "state": "taken"}},
    {"id": K7, "parent": TK, "title": "その他", "rest": True, "created_ts": T0 + 10, "links": {"session": "aaaaaaaaaa77"}},
]
WEEK = {"since": T0 - 7 * 86400, "done": [{"id": K1, "title": "済んだ枝", "session": None, "owner": "u"}],
        "moving": [{"id": K4, "title": "開いた枝", "owner": "u", "ball": {"kind": "ai"}}],
        "stuck": [{"id": B, "title": "子の仕事", "owner": "u", "days": 5, "ball": {"kind": "person", "who": "u"}}],
        "pingpong": [{"id": K4, "title": "開いた枝", "owner": "u", "changes": 4}]}
TREE = "POST /tree"
ROWS = "out.rows = [...document.querySelectorAll('.wtree .tnode')].map((r) => r.querySelector('.tt, .tvis') ? " \
       "[...r.querySelectorAll('.tt, .tvis, .tstale, .ttr')].map((e) => e.textContent.trim()).join(' | ') : r.textContent.trim())"
# 仕事's tree's 出すもの (the deployment notes 段4)
BAR = "const bar = () => document.getElementById('tree-filter'); "
row = lambda i: f"q('.wtree .tnode[data-id=\"{i}\"]')"

# name: (faults, [(js, wait ms)])
CASES = {
    "the rows": ({}, [(ROWS + f"; out.issue = {row(K5)}.querySelector('a.tt').href; out.k4 = {row(K4)}.textContent", 100)]),
    "訳 and 原文": ({}, [
        (f"{row(K4)}.querySelector('.ttr').click()", 300),
        (f"out.orig = {row(K4)}.querySelector('.tt').textContent + ' | ' + {row(K4)}.querySelector('.ttr').textContent;"
         f" {row(K4)}.querySelector('.ttr').click()", 300),
        (f"out.back = {row(K4)}.querySelector('.tt').textContent", 100),
    ]),
    # A finished tree is in 🗄 アーカイブ (段4), not at the tree's end.
    "the folds": ({}, [
        ("q('.wtree .done-branches').click()", 300),
        (ROWS + "; q('.wtree .handoff-fold .tvis').click()", 300),
        ("out.hand = !!" + row(K2) + "; out.notHere = !" + row(DR) + "; q('#archive-toggle-btn').click()", 300),
        ("out.done = !!" + row(DR) + "; q('#archive-toggle-btn').click()", 300),
        ("out.folded = !" + row(DR), 100),
    ]),
    "a row's own open and close": ({}, [
        # the first tap selects it (the 選択中 bar), the next ones open and close it
        (f"{row(R0)}.querySelector('.tmain').click(); out.sel = {row(R0)}.classList.contains('tsel')", 300),
        (f"{row(R0)}.querySelector('.tmain').click()", 300),
        (f"out.closed = !{row(K4)}; {row(R0)}.querySelector('.tmain').click()", 300),
        (f"out.open = !!{row(K4)}; {row(R0)}.querySelector('.tog').click()", 300),
        (f"out.part = !!{row(K1)}; {row(R0)}.querySelector('.tog').click()", 300),
        (f"out.none = !{row(K4)}", 100),
    ]),
    "the filters": ({}, [
        ("press(bar(), 'あなたの番')", 300),
        ("out.you = [...document.querySelectorAll('.wtree .tnode[data-id]')].map((r) => r.dataset.id);"
         " press(bar(), '3日止まり')", 300),
        ("out.stale = [...document.querySelectorAll('.wtree .tnode[data-id]')].map((r) => r.dataset.id);"
         " press(bar(), '全部')", 300),
    ]),
    # ＋ 🌳 at 仕事's tree's top (段4).
    "＋ 新しい仕事": ({}, [
        ("q('#new-tree-btn').click()", 300),
        ("const v = q('#new-tree-title'); set(v, ' 新しい木 '); q('#new-tree-add').click(); out.cleared = v.value", 1000),
    ]),
    "⋯ 引き取りを取り消す": ({}, [
        (f"more('{TK}')", 500), ("item('引き取りを取り消す')", 500), ("press(menu().querySelector('div'), '取り消す')", 1000),
    ]),
    "⋯ GitHub から読み直す": ({TREE: [{"body": {"ok": True, "changed": 2}}]}, [
        (f"more('{R0}')", 500), ("item('GitHub から読み直す')", 1000),
        ("out.toast = (q('.undo-toast span') || {}).textContent", 100),
    ]),
    "⋯ GitHub から読み直す refused": ({TREE: [{"status": 500, "body": {"error": "だめ"}}]}, [
        (f"more('{R0}')", 500), ("item('GitHub から読み直す')", 1000),
    ]),
    "⋯ 共有(根で設定)": ({}, [
        (f"more('{FOL}')", 500), ("item('共有(根で設定)')", 500),
        ("out.note = [...menu().querySelectorAll('span')].map((e) => e.textContent).join('|'); out.panel = !!menu().querySelector('.tshare')", 100),
    ]),
    # The start screen's 何で × どこで (the deployment notes 段3): the Email box has no Codex here.
    "⋯ セッションで作業 in Email": ({}, [
        # select it, then the top row's ＋ 🤖 AI (no ▶ in the list's ⋯ any more, 2026-11-27)
        (f"{row(A)}.querySelector('.tmain').click()", 300), ("document.getElementById('start-btn').click()", 800),
        ("const k = q('#kind'); k.value = 'codex'; k.dispatchEvent(new Event('change'));"
         " out.mailWithCodex = q('#place option[value=mail]').disabled;"
         " k.value = 'claude'; k.dispatchEvent(new Event('change'));"
         " out.mailWithClaude = q('#place option[value=mail]').disabled", 100),
    ]),
    "the balloon closes on a scroll": ({}, [
        (f"more('{A}')", 500), ("out.open = !!menu(); document.dispatchEvent(new Event('scroll'))", 300),
        ("out.closed = !menu()", 100),
    ]),
    "週のまとめ": ({"GET /tree/week": [{"every": True, "body": WEEK}]}, [
        ("q('#work-views a[data-view=week]').click()", 1000),
        ("out.groups = texts('#todo-modal .group'); out.rows = texts('#todo-modal .tree .tnode')", 100),
    ]),
    # A link to a node: 仕事's tree, with the node in sight (段5).
    "#tree= a folded one, one not there": ({}, [
        ("q('#work-views a[data-view=ball]').click()", 500),
        (f"location.hash = '#tree={K2}'", 1500),
        (f"out.shown = !!{row(K2)}; out.view = window.__aizaTab(); location.hash = '#tree=n0000000000zz'", 1500),
    ]),
}


def probe(steps):
    return TT.PROBE.replace("  const steps = [", BAR + "\n  const steps = [").replace("__STEPS__", steps_js(steps))


def run_case(faults, steps, static=None):
    return run_page(probe(steps), {"faults": faults, "folders": TT.FOLDERS, "tree_extra": EXTRA},
                    6000 + sum(w for _, w in steps), static=static, height=1600)


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageTreeViewsTest(unittest.TestCase):
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

    def test_what_the_rows_say(self):
        out = self.got("the rows")
        self.assertEqual(out["rows"], [
            "親の仕事", "子の仕事 | 5 日止まっている", "合わせる枝", "共有の仕事 | v",
            # a repository, a translated title, an issue, a desk report, その他 with its session's state
            "整理の仕事 | GitHub org/repo", "Open branch | 訳", "課題", "窓口 | 📮 desk · u · 1234",
            "その他 — 「s1」の作業 | 動いている · 作業中",
            # the finished branches folded (済んだ枝 and the handoff)
            "✓ 済みの枝 2 件",
            "引き取った仕事", "その他(分ける前の作業の残り) | 担当のセッションはもうない"])   # the finished tree: in 🗄 アーカイブ (段4)
        self.assertEqual(out["issue"], "https://github.com/org/repo/issues/3")
        self.assertIn("訳の球", out["k4"])   # the ball translated too
        self.assertIn("≈$0.50", out["k4"])

    def test_translation_and_original(self):
        out = self.got("訳 and 原文")
        self.assertEqual(out["orig"], "開いた枝 | 原文")
        self.assertEqual(out["back"], "Open branch")

    def test_the_folds_open(self):
        out = self.got("the folds")
        self.assertIn("済んだ枝", out["rows"])
        self.assertIn("🔁 済みの引き継ぎ 1 件", out["rows"])
        self.assertTrue(out["hand"])
        self.assertTrue(out["notHere"])
        self.assertTrue(out["done"])
        self.assertTrue(out["folded"])

    def test_a_row_opens_and_closes_and_its_mark_cycles(self):
        out = self.got("a row's own open and close")
        self.assertEqual([out[k] for k in ("sel", "closed", "open", "part", "none")], [True, True, True, True, True])

    def test_the_filters(self):
        out = self.got("the filters")
        self.assertEqual(out["you"], [A, B])                     # 子の仕事's ball is mine
        self.assertEqual(out["stale"], [A, B])                   # ...for 5 days

    def test_a_new_job(self):
        out = self.got("＋ 新しい仕事")
        self.assertEqual(posted(out, TREE), [{"op": "add", "title": "新しい木"}])
        self.assertEqual(out["cleared"], "")

    def test_untake(self):
        out = self.got("⋯ 引き取りを取り消す")
        self.assertEqual(posted(out, TREE), [{"op": "untake", "id": TK}])

    def test_resync_from_github(self):
        out = self.got("⋯ GitHub から読み直す")
        self.assertEqual(posted(out, TREE), [{"op": "sync", "id": R0}])
        self.assertEqual(out["toast"], "2 件を直しました")

    def test_resync_refused_is_said(self):
        out = self.got("⋯ GitHub から読み直す refused")
        self.assertEqual(out["alerts"], ["だめ"])

    def test_a_branch_that_follows_its_root_shares_from_the_root(self):
        out = self.got("⋯ 共有(根で設定)")
        self.assertIn("「親の仕事」の設定です", out["note"])
        self.assertTrue(out["panel"])

    def test_work_in_email_without_codex_is_claude(self):
        out = self.got("⋯ セッションで作業 in Email")
        self.assertEqual((out["mailWithCodex"], out["mailWithClaude"]), (True, False))

    def test_the_balloon_closes_on_a_scroll(self):
        out = self.got("the balloon closes on a scroll")
        self.assertTrue(out["open"])
        self.assertTrue(out["closed"])

    def test_the_week(self):
        out = self.got("週のまとめ")
        self.assertEqual(out["groups"], ["✓ 済んだもの (1)", "⚙️ 動いたもの (1)", "⏳ 3日以上止まっているもの (1)",
                                         "🔁 ボールが行ったり来たりしたもの (1)"])
        self.assertEqual(out["rows"], ["済んだ枝🌳", "開いた枝🤖 AI🌳", "子の仕事5 日止まっている 🙋 あなた🌳", "開いた枝4 回渡った🌳"])

    def test_a_tree_link_opens_its_folds_and_one_not_there_is_said(self):
        out = self.got("#tree= a folded one, one not there")
        self.assertTrue(out["shown"])
        self.assertEqual(out["view"], "work/tree")
        self.assertEqual(out["alerts"], ["この枝は見られません(共有が外されたか、消されました)"])

if __name__ == "__main__":
    unittest.main()
