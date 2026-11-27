"""The page's scripts share one global scope (the deployment notes); these
are the rules that keep that manageable, checked with a parser
(tests/page_scopes.js, acorn in tests/vendor):
- what runs while a file loads uses no name of a file loaded after it (it
  would stop the page);
- a top-level variable is assigned only in the file that declares it: who
  may change a piece of state is then read from one file. FOREIGN_WRITES are
  the ones not yet moved; the list only shrinks (a new one fails, and so does
  one that is gone but still listed);
- reading another file's name: the base (BASE_READS: page.js's helpers for
  building the page, api.js's calls, chat.js's entry for the open session)
  from anywhere, anything else only as listed in tests/page_reads.txt, a
  list that also only shrinks: a file's own element or state is declared in
  the file that uses it.

    python3 -m unittest discover -s tests -v
"""
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")

# (the file that assigns, the name, the file that declares it)
FOREIGN_WRITES = set()
# What any file may read of another (the deployment notes): page.js's
# helpers for building the page (html, PH, ui, escapeHtml), api.js's calls to
# the backend (api, withUnlockRetry, sessionPath) and chat.js's one entry for
# the open session (chatNow). Every other read of another file's name is
# listed in tests/page_reads.txt, a list that only shrinks.
BASE_READS = {("page.js", "html"), ("page.js", "PH"), ("page.js", "ui"), ("page.js", "escapeHtml"),
              ("api.js", "api"), ("api.js", "withUnlockRetry"), ("api.js", "sessionPath"), ("chat.js", "chatNow")}


def scopes():
    """(load order, page_scopes.js's answer) for the page's own scripts."""
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    order = re.findall(r'<script src="/agents/([a-z0-9-]+\.js)"', html)
    files = [[n, (ROOT / "static" / n).read_text(encoding="utf-8")] for n in order]
    r = subprocess.run([NODE, str(ROOT / "tests" / "page_scopes.js")], input=json.dumps(files),
                       capture_output=True, text=True, timeout=60, check=True)
    return order, json.loads(r.stdout)


@unittest.skipUnless(NODE, "node is needed to parse the page's scripts")
class PageScopesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.order, cls.got = scopes()

    def test_the_page_scripts_are_all_read(self):
        self.assertEqual(self.order[-1], "app.js")
        self.assertIn("lastSessions", self.got["declared"]["list.js"])

    def test_nothing_run_at_load_uses_a_later_files_name(self):
        pos = {n: i for i, n in enumerate(self.order)}
        late = sorted({(u["file"], u["line"], u["name"], u["owner"]) for u in self.got["uses"]
                       if u["load"] and pos[u["owner"]] > pos[u["file"]]})
        self.assertEqual(late, [])

    def test_a_variable_is_assigned_only_where_it_is_declared(self):
        writes = {(u["file"], u["name"], u["owner"]) for u in self.got["uses"] if u["write"]}
        self.assertEqual(sorted(writes - FOREIGN_WRITES), [], "new: declare it in the file that changes it, or change it through its file")
        self.assertEqual(sorted(FOREIGN_WRITES - writes), [], "moved: take it out of FOREIGN_WRITES")

    def test_reads_of_another_files_names_are_the_base_or_listed(self):
        reads = {(u["file"], u["owner"], u["name"]) for u in self.got["uses"]
                 if not u["write"] and (u["owner"], u["name"]) not in BASE_READS}
        listed = {tuple(line.split()) for line in (ROOT / "tests" / "page_reads.txt").read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#")}
        self.assertEqual(sorted(reads - listed), [], "new: read it through the base or the owner's entry, or list it in tests/page_reads.txt")
        self.assertEqual(sorted(listed - reads), [], "gone: take it off tests/page_reads.txt")
        self.assertEqual(sorted(r for r in listed if (r[1], r[2]) in BASE_READS), [], "the base needs no listing")

    def test_the_parser_sees_a_write_and_a_load_time_use(self):
        # the checker itself, on a two-file page
        files = [["a.js", "let x = 1; function f() { let y; y = 2; }"],
                 ["b.js", "x = 2; function g(x) { x = 3; } const z = x; function h() { x++; }"]]
        r = subprocess.run([NODE, str(ROOT / "tests" / "page_scopes.js")], input=json.dumps(files),
                           capture_output=True, text=True, timeout=60, check=True)
        uses = sorted((u["file"], u["name"], u["write"], u["load"]) for u in json.loads(r.stdout)["uses"])
        self.assertEqual(uses, [("b.js", "x", False, True), ("b.js", "x", True, False), ("b.js", "x", True, True)])


if __name__ == "__main__":
    unittest.main()
