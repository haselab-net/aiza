"""The work tree's ⋯ panels, its drag and its people view, in headless
Chrome against the stand-in backend (the deployment notes): what the
user picks and types there goes to the store as the right request.
- 🧑‍🤝‍🧑 共有: who sees (self / lab) and who writes (chips, the name
  filter, Enter on one match); やめる sends nothing;
- ▶ セッションで作業: 新規 makes the session and ties the node to it,
  既存 picks one from the session list's folder tree;
- ＋ 子を足す by a title or from a GitHub repository (owner/name checked);
- ✏️ 名前を変える, ✓ 済みにする, 📁 the root's session folder;
- someone else's node: 🤛 引き取る, ✍ 書き込み可で共有, 💬 参照;
- ↕ 並べ替え: a row dragged before another or into one;
- 人と AI: each open leaf in the column of who holds it.

    python3 -m unittest discover -s tests -v
"""
import json
import re
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

from page_harness import NEW, T0, serve
from test_page_flow import CHROME

A, B, D = "n00000000000a", "n00000000000b", "n00000000000d"   # 親の仕事, 子の仕事 (under A), 共有の仕事 (v's)
E = "n00000000000e"   # one more root of mine (tree_extra)
EXTRA = [{"id": E, "parent": None, "title": "三つ目の仕事", "created_ts": T0}]   # after 親の仕事 (T0 - 100)
F1 = "f0000000001"
FOLDERS = {"folders": [{"id": F1, "name": "研究"}], "assign": {}}

# The page opened on the list; the to-do list's tree; then each step (JS run
# in the page) with the wait before the next. `out` (with the page's errors)
# is written into the page for the test to read.
PROBE = r"""
(function () {
  const out = {};
  window.__alerts = [];
  window.confirm = () => true; window.prompt = () => null; window.alert = (m) => window.__alerts.push(String(m));
  // A made-up pointer cannot be captured (no such pointer is down).
  Element.prototype.setPointerCapture = function () {};
  // The clipboard of a page nobody looks at waits for a permission forever.
  Object.defineProperty(navigator, "clipboard", { value: { writeText: async (s) => { window.__copied = s; } } });
  const q = (sel) => document.querySelector(sel);
  const menu = () => [...document.querySelectorAll(".tmenu")].find((m) => !m.hidden);
  const more = (id) => { const b = q(`.wtree [data-id="${id}"] button.tmore`); if (b) b.click(); else out.missing = "⋯ " + id; };
  const press = (root, text) => {
    const b = [...(root || document).querySelectorAll("button")].find((x) => x.textContent.includes(text) && !x.disabled);
    if (b) b.click(); else out.missing = (out.missing ? out.missing + "; " : "") + text;
  };
  const item = (text) => press(menu(), text);
  // A row of 仕事's list selected (its title tapped once): the top row's ＋ work on it.
  const sel = (id) => { const b = q(`.wtree [data-id="${id}"] .tmain`); if (b) b.click(); else out.missing = "row " + id; };
  const field = (root, i) => [...root.querySelectorAll("input:not([type=radio]), select")].filter((x) => !x.hidden && !x.closest("[hidden]"))[i || 0];
  const set = (el, v) => { el.value = v; el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); };
  const enter = (el) => el.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  const texts = (sel) => [...document.querySelectorAll(sel)].map((e) => e.textContent.trim());
  const ptr = (el, type, y) => el.dispatchEvent(new PointerEvent(type, { button: 0, pointerId: 7, clientY: y, clientX: 10, bubbles: true }));
  const mid = (id, f) => { const r = q(`.wtree .tnode[data-id="${id}"]`).getBoundingClientRect(); return r.top + r.height * f; };
  const steps = [
    // 仕事's tree (the deployment notes 段5): the work tree in the list's folders.
    [() => q("#work-views a[data-view=tree]").click(), 900],
    [() => {}, 900],
  ].concat(__STEPS__);
  let i = 0;
  function next() {
    if (i === steps.length) {
      out.alerts = window.__alerts;
      out.hash = location.hash;
      out.errors = (window.__aizaPageErrors || ["no checkPage"]).concat(window.__jsErrors || []);
      const pre = document.createElement("pre"); pre.id = "probe-out";
      pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
      return;
    }
    const [fn, wait] = steps[i++];
    try { fn(); } catch (e) { out.thrown = String(e) + " (step " + i + ")"; }
    setTimeout(next, wait);
  }
  setTimeout(next, 2500);
})();
"""

# name: [(js, wait ms)]
CASES = {
    "share": [
        (f"more('{A}')", 500), ("item('共有')", 500),
        ("const p = menu().querySelector('.tshare'); p.querySelector('input[value=lab]').click();"
         " out.none = p.querySelector('.tshare-chosen').textContent.trim();"
         " out.offered = [...p.querySelectorAll('.tshare-list .tchip')].map((b) => b.textContent)", 200),
        ("const s = menu().querySelector('.tshare-q'); set(s, 'zz');"
         " out.noMatch = menu().querySelector('.tshare-list').textContent.trim()", 200),
        ("const s = menu().querySelector('.tshare-q'); set(s, 'w'); enter(s)", 200),
        ("press(menu().querySelector('.tshare-list'), 'v(V)')", 200),
        ("out.chosen = [...menu().querySelectorAll('.tshare-chosen .tchip')].map((b) => b.textContent)", 100),
        ("press(menu().querySelector('.tshare-chosen'), 'v(V)')", 200),
        ("press(menu().querySelector('.tshare'), '保存')", 1500),
    ],
    "share, cancelled": [
        (f"more('{A}')", 500), ("item('共有')", 500),
        ("menu().querySelector('.tshare input[value=lab]').click(); press(menu().querySelector('.tshare'), 'やめる')", 1500),
        ("out.menu = !!menu()", 100),
    ],
    # ▶'s 新規 opens the start screen (the deployment notes 段3) with the item filled in.
    "work: a new session": [
        # select the item, then the top row's ＋ 🤖 AI (2026-11-27: no ▶ in the list's ⋯)
        (f"sel('{A}')", 300), ("q('#start-btn').click()", 800),
        ("out.places = [...q('#place').options].map((o) => o.value); out.title = q('#label').value;"
         " out.note = q('#start-note .what').textContent; set(q('#label'), 'T1'); q('#create-btn').click()", 2500),
    ],
    # 置く場所 (the deployment notes 段4): from ＋ セッション, an item of a tree.
    "the start screen's place: a tree item": [
        ("q('#start-btn').click()", 800),
        ("const p = q('#start-place'); out.options = [...p.options].map((o) => o.value);"
         f" p.value = 'n:{A}'; p.dispatchEvent(new Event('change'));"
         " out.label = q('#label').value; out.note = q('#start-note:not([hidden]) .what').textContent; q('#create-btn').click()", 2500),
    ],
    "work: a new session, not linked": [
        (f"sel('{A}')", 300), ("q('#start-btn').click()", 800),
        ("q('#start-link').checked = false; q('#create-btn').click()", 2500),
    ],
    "child by a title": [
        # ＋ 🌳 with the item selected: its ＋ 子を足す under the top row
        (f"sel('{A}')", 300), ("q('#new-tree-btn').click()", 500),
        ("const v = field(q('#child-slot'), 0); set(v, '小さな仕事'); enter(v)", 1500),
    ],
    "child from GitHub": [
        (f"sel('{A}')", 300), ("q('#new-tree-btn').click()", 500), ("press(q('#child-slot'), 'GitHub につなぐ')", 300),
        ("const p = q('#child-slot'); set(field(p, 0), 'not a repo'); press(p, '結びつける')", 300),
        ("out.note = [...q('#child-slot').querySelectorAll('.tpane span')].map((e) => e.textContent).join('|')", 100),
        ("const p = q('#child-slot'); set(field(p, 0), 'org/repo'); press(p, '結びつける')", 1500),
    ],
    "rename and done": [
        (f"more('{B}')", 500), ("item('名前を変える')", 500),
        ("const v = field(menu(), 0); set(v, '子の仕事'); enter(v); out.sameKept = !!menu(); set(v, '新しい名前'); enter(v)", 1500),
        (f"more('{B}')", 500), ("item('済みにする')", 1500),
    ],
    "the root's session folder": [
        (f"more('{A}')", 500), ("item('置くフォルダ')", 500),
        ("const p = menu(); out.choices = [...field(p, 0).options].map((o) => o.textContent);"
         " set(field(p, 0), '+new'); out.parents = [...field(p, 1).options].map((o) => o.textContent);"
         f" set(field(p, 1), '{F1}'); set(field(p, 2), '新しい箱'); press(p, '決める')", 1500),
        (f"more('{E}')", 500), ("item('置くフォルダ')", 500),
        (f"const p = menu(); set(field(p, 0), '{F1}'); press(p, '決める')", 1500),
    ],
    "someone else's: take over": [
        (f"sel('{D}')", 300), ("q('#start-btn').click()", 500),
        ("out.note = q('#start-note .what').textContent; q('#create-btn').click()", 1500),
    ],
    "someone else's: co-work": [
        (f"more('{D}')", 500), ("item('書き込み可で共有')", 1500),
    ],
    "someone else's: a reference": [
        (f"more('{D}')", 500), ("item('参照')", 500),
        ("const p = menu(); out.token = field(p, 0).value; press(p, 'コピーする')", 500),
        ("out.note = [...menu().querySelectorAll('span')].map((e) => e.textContent).join('|'); out.copied = window.__copied", 100),
    ],
    "drag": [
        ("q('#list-arrange-btn').click()", 500),   # ↕ at 仕事's tree's top (段4)
        ("out.grips = [...document.querySelectorAll('.wtree .tnode[data-id]')].filter((r) => r.querySelector('.tgrip')?.textContent === '⠿').map((r) => r.dataset.id)", 100),
        # 三つ目 onto the top of 親の仕事: before it, among the roots
        (f"const g = q('.wtree .tnode[data-id=\"{E}\"] .tgrip'); ptr(g, 'pointerdown', mid('{E}', 0.5));"
         f" ptr(g, 'pointermove', mid('{A}', 0.1)); out.mark = q('.wtree .tnode[data-id=\"{A}\"]').className; ptr(g, 'pointerup', mid('{A}', 0.1))", 1500),
        # 子の仕事 onto the middle of 三つ目: its child
        (f"const g = q('.wtree .tnode[data-id=\"{B}\"] .tgrip'); ptr(g, 'pointerdown', mid('{B}', 0.5));"
         f" ptr(g, 'pointermove', mid('{E}', 0.5)); ptr(g, 'pointerup', mid('{E}', 0.5))", 1500),
        # a tap on ⠿ (no move): nothing
        (f"const g = q('.wtree .tnode[data-id=\"{E}\"] .tgrip'); ptr(g, 'pointerdown', mid('{E}', 0.5)); ptr(g, 'pointerup', mid('{E}', 0.5))", 1500),
    ],
    # 人と AI is part of 🙋 番ごと now (the deployment notes 段5): the tree's open
    # items no session of mine holds, by whose turn; nobody's folded.
    # ↕: a tree in no folder dragged onto a folder row goes in that folder (2026-11-26, the user).
    "drag a tree into a folder": [
        ("q('#list-arrange-btn').click()", 500),
        (f"const g = q('.wtree .tnode[data-id=\"{E}\"] .tgrip'); const f = q('#sessions > .session-row[data-folder-id=\"{F1}\"]').getBoundingClientRect();"
         f" ptr(g, 'pointerdown', mid('{E}', 0.5)); ptr(g, 'pointermove', f.top + f.height / 2);"
         f" out.mark = q('#sessions > .session-row[data-folder-id=\"{F1}\"]').className; ptr(g, 'pointerup', f.top + f.height / 2)", 1500),
    ],
    "people": [
        ("q('#work-views a[data-view=ball]').click()", 900),
        ("out.groups = texts('#todo-modal .group.turns'); out.rows = texts('#todo-modal .tree .tnode .tmain');"
         " q('#todo-modal .group.turns.none').click()", 300),
        ("out.unfolded = texts('#todo-modal .tree .tnode .tmain').length", 100),
    ],
}


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageTreeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(zip(CASES, pool.map(cls.run_case, CASES.values())))

    @staticmethod
    def run_case(steps, static=None):
        """static: another copy of the page's files (a check that these
        tests notice it broken)."""
        js = "[" + ",".join(f"[() => {{ {s} }}, {w}]" for s, w in steps) + "]"
        srv = serve(PROBE.replace("__STEPS__", js), **({"static": static} if static else {}),
                    folders=FOLDERS, tree_extra=EXTRA)
        try:
            with tempfile.TemporaryDirectory() as prof:
                url = f"http://127.0.0.1:{srv.server_address[1]}/agents/"
                budget = 6000 + sum(w for _, w in steps)
                r = subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={prof}",
                                    f"--virtual-time-budget={budget}", "--window-size=420,900", "--dump-dom", url],
                                   capture_output=True, text=True, timeout=120)
        finally:
            srv.shutdown()
            srv.server_close()
        m = re.search(r'<pre id="probe-out">(.*?)</pre>', r.stdout, re.S)
        if not m:
            return {"unfinished": True, "log": srv.state["log"]}
        out = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
        out["log"] = srv.state["log"]
        out["folders"] = srv.state["folders"]
        return out

    def got(self, name):
        out = self.results[name]
        self.assertNotIn("unfinished", out, name)
        self.assertNotIn("thrown", out)
        self.assertNotIn("missing", out)
        self.assertEqual(out["errors"], [])
        return out

    @staticmethod
    def posted(out, path):
        return [b for m, p, b in out["log"] if m == "POST" and p == path]

    def tree_ops(self, out):
        return self.posted(out, "/tree")

    def test_share(self):
        out = self.got("share")
        self.assertEqual(out["none"], "まだいません")
        self.assertEqual(out["offered"], ["＋ v(V)", "＋ w(W)"])      # not the owner (me)
        self.assertEqual(out["noMatch"], "合う人がいません")
        self.assertEqual(out["chosen"], ["v(V) ×", "w(W) ×"])        # w by Enter, v by its chip
        self.assertEqual(self.tree_ops(out), [{"op": "update", "id": A, "visibility": "lab", "members": ["w"]}])

    def test_share_cancelled_sends_nothing(self):
        out = self.got("share, cancelled")
        self.assertEqual(self.tree_ops(out), [])
        self.assertFalse(out["menu"])

    def test_work_in_a_new_session(self):
        out = self.got("work: a new session")
        self.assertIn("dev", out["places"])
        self.assertIn("mail", out["places"])
        self.assertIn("ssh:winbox", out["places"])            # any place: the start screen's
        self.assertEqual(out["title"], "親の仕事")   # the item's title to start with
        self.assertIn("のセッションになります", out["note"])
        made = self.posted(out, "/sessions")
        self.assertEqual(len(made), 1)
        self.assertEqual({k: made[0][k] for k in ("preset", "label", "skip_permissions")},
                         {"preset": "claude-tui", "label": "T1", "skip_permissions": True})
        self.assertIn("「親の仕事」", made[0]["initial_message"])
        self.assertIn("指示を待ってください", made[0]["initial_message"])
        self.assertEqual(self.tree_ops(out), [{"op": "update", "id": A, "links": {"session": NEW["id"]}}])
        self.assertEqual(out["hash"], "#" + NEW["id"])

    def test_the_start_screens_place_is_a_tree_item(self):
        out = self.got("the start screen's place: a tree item")
        self.assertEqual(out["options"][0], "")                 # (in no folder)
        self.assertIn("n:" + A, out["options"])
        self.assertEqual(out["label"], "親の仕事")
        self.assertIn("のセッションになります", out["note"])
        made = self.posted(out, "/sessions")
        self.assertEqual(len(made), 1)
        self.assertIn("「親の仕事」", made[0]["initial_message"])
        self.assertEqual(self.tree_ops(out), [{"op": "update", "id": A, "links": {"session": NEW["id"]}}])

    def test_a_new_session_left_unlinked(self):
        out = self.got("work: a new session, not linked")
        made = self.posted(out, "/sessions")
        self.assertEqual(len(made), 1)
        self.assertNotIn("initial_message", made[0])
        self.assertEqual(self.tree_ops(out), [])

    def test_child_by_a_title(self):
        out = self.got("child by a title")
        self.assertEqual(self.tree_ops(out), [{"op": "add", "parent": A, "title": "小さな仕事", "visibility": "self"}])

    def test_child_from_github(self):
        out = self.got("child from GitHub")
        self.assertIn("owner/name の形で書いてください", out["note"])
        self.assertEqual(self.tree_ops(out), [{"op": "update", "id": A, "links": {"repo": "org/repo"}},
                                              {"op": "sync", "id": A}])

    def test_rename_and_done(self):
        out = self.got("rename and done")
        self.assertTrue(out["sameKept"])   # the same title: nothing sent, the panel stays
        self.assertEqual(self.tree_ops(out), [{"op": "update", "id": B, "title": "新しい名前"},
                                              {"op": "update", "id": B, "state": "done"}])

    def test_the_roots_session_folder(self):
        out = self.got("the root's session folder")
        self.assertIn("研究", out["choices"])
        self.assertIn("研究 の下に作る", out["parents"])
        ops = self.posted(out, "/folders/ops")
        self.assertEqual(len(ops), 2)
        put, root = ops[0]["ops"]
        self.assertEqual((put["op"], put["folder"]["name"], put["folder"]["parent"]), ("put", "新しい箱", F1))
        self.assertEqual(root, {"op": "tree_root", "node": A, "folder": put["folder"]["id"]})
        self.assertEqual(ops[1]["ops"], [{"op": "tree_root", "node": E, "folder": F1}])
        roots = {f["name"]: f["tree_roots"] for f in out["folders"]["folders"]}
        self.assertEqual(roots, {"研究": [E], "新しい箱": [A]})

    def test_take_over_someone_elses(self):
        out = self.got("someone else's: take over")
        self.assertIn("引き取ります", out["note"])
        ops = self.tree_ops(out)
        self.assertEqual([(o["op"], o["id"], o["preset"]) for o in ops], [("take", D, "claude-tui")])
        self.assertEqual(out["hash"], "#aaaaaaaaaa09")

    def test_co_work_in_someone_elses(self):
        out = self.got("someone else's: co-work")
        self.assertEqual([p for m, p, _ in out["log"] if m == "POST" and p.endswith("/join")],
                         ["/shared/v/sessions/cccccccccc01/join"])
        self.assertEqual(out["hash"], "#cccccccccc01")

    def test_a_reference_to_someone_elses(self):
        out = self.got("someone else's: a reference")
        self.assertTrue(out["token"].startswith("[AI座参照 s:v/cccccccccc01 "), out["token"])
        self.assertIn("参照をコピーしました", out["note"])
        self.assertEqual(out["copied"], out["token"])

    def test_drag(self):
        out = self.got("drag")
        self.assertEqual(out["grips"], [A, B, D, E])   # v's root too: only to put it in a folder of mine (段4)
        self.assertIn("drop-before", out["mark"])
        ops = self.tree_ops(out)
        self.assertEqual(len(ops), 2, ops)
        self.assertEqual((ops[0]["id"], "parent" in ops[0]), (E, False))
        self.assertEqual(ops[0]["order"], T0 - 100 - 1)              # just before 親の仕事 (made at T0 - 100)
        self.assertEqual((ops[1]["id"], ops[1]["parent"]), (B, E))

    def test_a_tree_dragged_into_a_folder(self):
        out = self.got("drag a tree into a folder")
        self.assertIn("drop-into", out["mark"])
        self.assertEqual(self.posted(out, "/folders/ops"), [{"ops": [{"op": "tree_root", "node": E, "folder": F1}]}])
        self.assertEqual(self.tree_ops(out), [])

    def test_people(self):
        out = self.got("people")
        # 子の仕事 is mine, but its session is in the list already (🙋 あなたの番): not again here.
        self.assertEqual(out["groups"], ["▸ ○ まだ誰も持っていない (2)"])
        self.assertEqual(out["rows"], [])                             # nobody's: folded
        self.assertEqual(out["unfolded"], 2)


if __name__ == "__main__":
    unittest.main()
