"""The session list's folders, its drag and its archive, in headless Chrome
against the stand-in backend (the deployment notes, the deployment notes):
what the page shows and what it saves (POST /folders/ops, /session-order),
checked in the stand-in's state.

    python3 -m unittest discover -s tests -v
"""
import json
import re
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_failures as F   # (not its class itself: unittest would run it here again)
from page_harness import serve
from test_page_failures import CHROME

S0, S1, S2, S5 = "aaaaaaaaaa00", "aaaaaaaaaa01", "aaaaaaaaaa02", "aaaaaaaaaa05"
# s0 is 子の仕事's session (page_harness): in the tree, under its item. A session among the list's rows:
SB = "bbbbbbbbbb01"
# 仕事 holds s1 and the folder 下 (which holds s2); 止めた holds the ended
# s5 that its last stop stopped; 古い is archived, with the archived s9.
FOLDERS = {"folders": [{"id": "fa", "name": "仕事"}, {"id": "fb", "name": "下", "parent": "fa"},
                       {"id": "fc", "name": "止めた", "last_stopped": [S5]},
                       {"id": "fd", "name": "古い", "archived": True}],
           "assign": {S1: "fa", S2: "fb", S5: "fc", "aaaaaaaaaa09": "fd"}}

# In the page: the rows of the list, and a drag of a row's ⠿ handle to the
# middle of another row (pointer events; the capture is a stand-in).
HELPERS = r"""
  const rows = () => [...document.querySelectorAll("#sessions > .session-row")].map((r) =>
    r.dataset.folderId ? "📁" + r.dataset.folderId : r.dataset.sessionId);
  // A session's row wherever it is (an item's session is in its tree, the deployment notes).
  const row = (k) => document.querySelector(k.startsWith("f") ? `#sessions > [data-folder-id=${k}]` : `#sessions [data-session-id=${k}]`);
  const drag = (from, to, where) => {
    Element.prototype.setPointerCapture = () => {};
    const h = row(from).querySelector(".drag-handle");
    const a = h.getBoundingClientRect(), b = row(to).getBoundingClientRect();
    const y = where === "below" ? b.bottom + 2 : b.top + b.height / 2;
    const ev = (type, cy) => h.dispatchEvent(new PointerEvent(type, { pointerId: 7, button: 0, clientX: a.left + 2, clientY: cy, bubbles: true }));
    ev("pointerdown", a.top + 2); ev("pointermove", (a.top + y) / 2); ev("pointermove", y); ev("pointerup", y);
  };
"""

# name: (folders, [(js, wait ms)])
CASES = {
    "folders open and close": (FOLDERS, [
        ("out.closed = rows(); out.count = row('fa').querySelector('.meta').textContent", 100),
        ("row('fa').querySelector('.ficon').click()", 300),
        ("out.open = rows(); row('fb').querySelector('.ficon').click()", 300),
        ("out.deeper = rows(); row('fa').querySelector('.ficon').click()", 300),
        ("out.again = rows()", 100),
    ]),
    "stop a folder: everything running in it": (FOLDERS, [
        ("row('fa').querySelector('.dot.stoppable').click()", 1500),
    ]),
    "resume a folder: what its last stop stopped": (FOLDERS, [
        ("row('fc').querySelector('.dot.resumable').click()", 1500),
    ]),
    "a new folder": (FOLDERS, [
        ("document.getElementById('new-folder-btn').click(); document.getElementById('new-folder-name').value = '1';"
         " document.getElementById('new-folder-add').click()", 1000),
        ("out.rows = rows(); out.panel = document.getElementById('tool-panel').hidden", 100),
    ]),
    # The top row's forms, one at a time in #tool-panel (the deployment notes).
    "the top row's forms": (FOLDERS, [
        ("const shown = () => ['new-tree-row', 'new-folder-row', 'arrange-row', 'start-modal']"
         ".filter((id) => !document.getElementById(id).hidden && !document.getElementById('tool-panel').hidden);"
         " window.shown = shown; out.steps = [];"
         " document.getElementById('new-folder-btn').click(); out.steps.push(shown());"
         " document.getElementById('new-tree-btn').click(); out.steps.push(shown());"
         " document.getElementById('new-tree-btn').click(); out.steps.push(shown());"
         " document.getElementById('list-arrange-btn').click(); out.steps.push(shown().concat(document.body.classList.contains('list-arrange') ? ['arranging'] : []));"
         " document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));"
         " out.steps.push(shown().concat(document.body.classList.contains('list-arrange') ? ['arranging'] : []));"
         " document.getElementById('start-btn').click(); out.steps.push(shown());"
         " out.inPanel = !!document.querySelector('#tool-panel #start-modal');"
         " document.getElementById('start-btn').click(); out.steps.push(shown());", 300),
    ]),
    "drag a session into a folder": (FOLDERS, [
        ("document.getElementById('list-arrange-btn').click()", 300),
        (f"drag('{SB}', 'fa')", 1000),
        ("out.rows = rows(); row('fa').querySelector('.ficon').click()", 300),
        ("out.open = rows()", 100),
    ]),
    "drag a session below another": (FOLDERS, [
        ("document.getElementById('list-arrange-btn').click()", 300),
        (f"out.before = rows(); drag('{SB}', 'aaaaaaaaaa0c', 'below')", 1000),
        ("out.rows = rows()", 100),
    ]),
    "drag a folder into another": (FOLDERS, [
        ("document.getElementById('list-arrange-btn').click()", 300),
        ("drag('fc', 'fa')", 1000),
        ("out.rows = rows(); row('fa').querySelector('.ficon').click()", 300),
        ("out.open = rows()", 100),
    ]),
    "no drag while the order is locked": (FOLDERS, [
        (f"drag('{SB}', 'fa')", 1000),
        ("out.rows = rows()", 100),
    ]),
    # 仕事's tree, its top (the deployment notes 段4).
    "stopped sessions hidden, then shown": (None, [
        (f"out.hidden = !row('{S5}'); out.before = rows(); document.getElementById('show-stopped').click()", 300),
        (f"out.shown = !!row('{S5}')", 100),
    ]),
    "your turn only": (None, [
        ("out.before = rows(); document.querySelector('#tree-filter [data-f=you]').click()", 300),
        ("out.rows = rows(); out.on = document.querySelector('#tree-filter .on').dataset.f", 100),
    ]),
    "a new tree": (None, [
        ("document.getElementById('new-tree-btn').click()", 200),
        ("document.getElementById('new-tree-title').value = '新しい木'; document.getElementById('new-tree-add').click()", 800),
    ]),
    "a row's ⋯": (None, [
        (f"out.closed = row('{S0}').querySelector('.row-acts').hidden; row('{S0}').querySelector('.row-more').click()", 200),
        (f"const m = row('{S0}').querySelector('.row-acts'); out.open = !m.hidden;"
         " out.items = [...m.querySelectorAll('button')].map((b) => b.className.split(' ')[0]); document.body.click()", 200),
        (f"out.after = row('{S0}').querySelector('.row-acts').hidden; out.height = row('{S0}').getBoundingClientRect().height;"
         f" out.more = row('{S0}').querySelector('.row-more').getBoundingClientRect().width;"
         # s0 is 子の仕事's: in the tree under the item, not in the list's own rows (2026-11-26)
         f" out.inTree = !!document.querySelector('.wtree .tsession [data-session-id=\"{S0}\"]');"
         f" out.inList = !!document.querySelector('#sessions > [data-session-id=\"{S0}\"]')", 100),
    ]),
    # A session dragged onto a tree's item goes under it (2026-11-26, the user).
    "drag a session onto a tree item": (None, [
        ("", 800),
        ("document.getElementById('list-arrange-btn').click()", 300),
        ("Element.prototype.setPointerCapture = () => {};"
         f" const h = row('{SB}').querySelector('.drag-handle'), a = h.getBoundingClientRect();"
         " const t = document.querySelector('.wtree .tnode[data-id=\"n00000000000a\"]').getBoundingClientRect(), y = t.top + t.height / 2;"
         " const ev = (type, cy) => h.dispatchEvent(new PointerEvent(type, { pointerId: 7, button: 0, clientX: a.left + 2, clientY: cy, bubbles: true }));"
         " ev('pointerdown', a.top + 2); ev('pointermove', (a.top + y) / 2); ev('pointermove', y);"
         " out.mark = document.querySelector('.wtree .tnode[data-id=\"n00000000000a\"]').className;"
         # held still over the item, it stays marked (it blinked: the rows' shift moved the item away, 2026-11-27)
         " out.marks = []; for (let i = 0; i < 4; i++) { ev('pointermove', y); out.marks.push(document.querySelector('.wtree .tnode[data-id=\"n00000000000a\"]').classList.contains('drop-into')); }"
         " ev('pointerup', y)", 1500),
    ]),
    # The same, up onto the root of a tree in the session's own folder: the
    # rows shift while dragging, and the tree's box with them -- its items
    # came under the pointer and went away again by turns (2026-11-27, the
    # user: 点滅して落とせません).
    "drag a session up onto a tree in its folder": (
        {"folders": [{"id": "fa", "name": "仕事"}], "assign": {SB: "fa", S1: "fa"}}, [
        ("", 800),
        ("for (const r of document.querySelectorAll('#sessions > .session-row[data-folder-id] .ficon')) r.click()", 500),
        ("document.getElementById('list-arrange-btn').click()", 300),
        ("Element.prototype.setPointerCapture = () => {};"
         f" const h = row('{SB}').querySelector('.drag-handle'), a = h.getBoundingClientRect();"
         " const node = () => document.querySelector('.wtree .tnode[data-id=\"n00000000000e\"]');"
         " const box = node().closest('.wtree'), bb = box.getBoundingClientRect(), t = node().getBoundingClientRect(), y = t.top + t.height / 2;"
         " const ev = (type, cy) => h.dispatchEvent(new PointerEvent(type, { pointerId: 7, button: 0, clientX: a.left + 2, clientY: cy, bubbles: true }));"
         " ev('pointerdown', a.top + 2); out.shifted = [];"
         " for (let cy = a.top; cy > y; cy -= 5) { ev('pointermove', cy); if (cy > bb.top && cy < bb.bottom && box.style.transform) out.shifted.push(Math.round(cy)); }"
         " out.marks = []; for (let i = 0; i < 4; i++) { ev('pointermove', y); out.marks.push(node().classList.contains('drop-into')); }"
         " ev('pointerup', y)", 1500),
    ], [{"id": "n00000000000e", "title": "箱の仕事", "folder": {"id": "fa", "how": "set", "path": "仕事"}},
        {"id": "n00000000000f", "parent": "n00000000000e", "title": "箱の子"}]),
    "search from the toolbar": (None, [
        ("const b = document.getElementById('tree-search'); b.value = 'needle';"
         " b.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))", 800),
        ("out.hits = document.querySelectorAll('.search-hit-row').length", 100),
    ]),
    "the archive: an archived folder, back with 📤": (FOLDERS, [
        ("document.getElementById('archive-toggle-btn').click()", 500),
        ("const r = document.querySelector('#archived-list [data-folder-id=fd]'); out.shown = !!r; r.click()", 500),
        ("out.inside = [...document.querySelectorAll('#archived-list .session-row')].map((e) => e.dataset.sessionId || e.dataset.folderId);"
         " document.querySelector('#archived-list [data-folder-id=fd] .archive-btn').click()", 1000),
        ("out.rows = rows()", 100),
    ]),
}


def run_case(folders, steps, tree_extra=None):
    js = "[" + ",".join(f"[() => {{ {s} }}, {w}]" for s, w in steps) + "]"
    probe = F.PROBE.replace("  const steps = __STEPS__;", HELPERS + "  const steps = " + js + ";")
    srv = serve(probe, folders=folders, tree_extra=tree_extra)
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
    out["log"], out["state"] = srv.state["log"], srv.state
    return out


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageListTest(unittest.TestCase):
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
    def ops(out):
        return [op for m, p, b in out["log"] if m == "POST" and p == "/folders/ops" for op in b["ops"]]

    @staticmethod
    def folder(out, fid):
        return next((f for f in out["state"]["folders"]["folders"] if f["id"] == fid), None)

    def test_folders_open_and_close(self):
        out = self.got("folders open and close")
        self.assertEqual(out["closed"][:3], ["📁fa", "📁fc", SB])   # s0: in the tree
        self.assertNotIn(S1, out["closed"])
        self.assertEqual(out["count"], "2")   # s1 and, in 下, s2
        self.assertEqual(out["open"][:3], ["📁fa", "📁fb", S1])
        self.assertEqual(out["deeper"][:4], ["📁fa", "📁fb", S2, S1])
        self.assertEqual(out["again"], out["closed"])

    def test_stopping_a_folder_stops_what_runs_in_it_and_keeps_the_list(self):
        out = self.got("stop a folder: everything running in it")
        stopped = sorted(p.split("/")[2] for m, p, _ in out["log"] if m == "POST" and p.endswith("/stop"))
        self.assertEqual(stopped, [S1, S2])
        self.assertEqual(sorted(self.folder(out, "fa")["last_stopped"]), [S1, S2])

    def test_resuming_a_folder_resumes_what_its_last_stop_stopped(self):
        out = self.got("resume a folder: what its last stop stopped")
        made = [b for m, p, b in out["log"] if m == "POST" and p == "/sessions"]
        self.assertEqual(len(made), 1)
        self.assertEqual(made[0].get("resume"), "c0ffee")
        self.assertEqual(self.folder(out, "fc")["last_stopped"], [])

    def test_a_new_folder(self):
        out = self.got("a new folder")
        new = [f for f in out["state"]["folders"]["folders"] if f["id"] not in ("fa", "fb", "fc", "fd")]
        self.assertEqual([(f["name"], f["parent"]) for f in new], [("1", None)])
        self.assertIn("📁" + new[0]["id"], out["rows"])
        self.assertTrue(out["panel"])   # the row closed

    def test_the_top_rows_forms(self):
        out = self.got("the top row's forms")
        self.assertEqual(out["steps"], [["new-folder-row"], ["new-tree-row"], [], ["arrange-row", "arranging"], [],
                                        ["start-modal"], []])
        self.assertTrue(out["inPanel"])

    def test_dragging_a_session_into_a_folder(self):
        out = self.got("drag a session into a folder")
        self.assertEqual(out["state"]["folders"]["assign"].get(SB), "fa")
        self.assertNotIn(SB, out["rows"])
        self.assertIn(SB, out["open"])

    def test_dragging_a_session_below_another_saves_the_order(self):
        out = self.got("drag a session below another")
        order = out["state"]["order"]
        self.assertLess(order.index("aaaaaaaaaa0c"), order.index(SB))
        top = [x for x in out["rows"] if not x.startswith("📁")]
        self.assertLess(top.index("aaaaaaaaaa0c"), top.index(SB))
        self.assertEqual(self.ops(out), [])   # still in no folder

    def test_dragging_a_folder_into_another(self):
        out = self.got("drag a folder into another")
        self.assertEqual(self.folder(out, "fc")["parent"], "fa")
        self.assertNotIn("📁fc", out["rows"])
        self.assertIn("📁fc", out["open"])

    def test_no_drag_while_the_order_is_locked(self):
        out = self.got("no drag while the order is locked")
        self.assertEqual(self.ops(out), [])
        self.assertEqual(out["state"]["order"], [])

    def test_an_archived_folder_shows_in_the_archive_and_comes_back(self):
        out = self.got("the archive: an archived folder, back with 📤")
        self.assertTrue(out["shown"])
        self.assertIn("aaaaaaaaaa09", out["inside"])
        self.assertFalse(self.folder(out, "fd")["archived"])
        self.assertIn("📁fd", out["rows"])




class TreeTopTest(unittest.TestCase):
    """仕事's tree, its top (the deployment notes 段4): what to show, ＋ 🌳, 🔍."""
    @classmethod
    def setUpClass(cls):
        names = ["stopped sessions hidden, then shown", "your turn only", "a new tree", "search from the toolbar", "a row's ⋯",
                 "drag a session onto a tree item", "drag a session up onto a tree in its folder"]
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.out = dict(zip(names, pool.map(lambda n: run_case(*CASES[n]), names)))

    def test_stopped_sessions_hidden_until_asked(self):
        out = self.out["stopped sessions hidden, then shown"]
        self.assertTrue(out["hidden"])
        self.assertTrue(out["shown"])

    def test_your_turn_only(self):
        out = self.out["your turn only"]
        self.assertEqual(out["on"], "you")
        self.assertLess(len(out["rows"]), len(out["before"]))
        self.assertTrue(set(out["rows"]) <= set(out["before"]))

    def test_a_new_tree(self):
        out = self.out["a new tree"]
        self.assertIn({"op": "add", "title": "新しい木"}, [b for m, p, b in out["log"] if m == "POST" and p == "/tree"])

    def test_a_rows_actions_are_in_its_menu(self):
        out = self.out["a row's ⋯"]
        self.assertEqual((out["closed"], out["open"], out["after"]), (True, True, True))
        self.assertEqual(out["items"], ["edit-btn", "link-btn", "archive-btn", "delete-btn"])
        self.assertGreaterEqual(out["height"], 64)
        self.assertGreaterEqual(out["more"], 44)
        self.assertEqual((out["inTree"], out["inList"]), (True, False))

    def test_a_session_dragged_onto_a_tree_item(self):
        out = self.out["drag a session onto a tree item"]
        self.assertIn("drop-into", out["mark"])
        self.assertEqual(out["marks"], [True] * 4)

    def test_a_session_dragged_up_onto_a_tree_in_its_folder(self):
        out = self.out["drag a session up onto a tree in its folder"]
        self.assertEqual(out["shifted"], [])               # over the tree's box, nothing moves under the pointer
        self.assertEqual(out["marks"], [True] * 4)
        ops = [b for m, p, b in out["log"] if m == "POST" and p == "/tree"]
        self.assertEqual(len(ops), 1, ops)
        self.assertEqual((ops[0].get("links") or {}).get("session"), SB, ops[0])
        ops = [b for m, p, b in out["log"] if m == "POST" and p == "/tree"]
        self.assertEqual(len(ops), 1)
        # s0 has an item of its own already (子の仕事): that item moves under 親の仕事 (▶'s 既存 does the same)
        self.assertTrue((ops[0].get("links") or {}).get("session") == SB, ops[0])
        self.assertFalse([b for m, p, b in out["log"] if m == "POST" and p in ("/session-order", "/folders/ops")])

    def test_search_from_the_toolbar(self):
        out = self.out["search from the toolbar"]
        self.assertTrue(any(m == "GET" and p.startswith("/search") and "needle" in p for m, p, b in out["log"]))
        self.assertGreater(out["hits"], 0)


if __name__ == "__main__":
    unittest.main()
