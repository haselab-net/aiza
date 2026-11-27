"""A tree item's start (the deployment notes 段3): what treeStartCtx gives the
start screen, run with a minimal API stub. Which presets the box offers is
the start screen's (test_page_form, test_page_tree_views); here: the issue
only for Claude in the devbox, the item linked (or a child made), the short
first message."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

TREE = (Path(__file__).resolve().parents[1] / "static" / "tree.js").read_text()


@unittest.skipUnless(shutil.which("node"), "node is needed for browser function tests")
class MailboxUITest(unittest.TestCase):
    def run_js(self, source):
        result = subprocess.run(["node", "-e", source], text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_launch_matrix_preserves_tree_link_and_claude_issue_only(self):
        function = TREE.split("function treeStartCtx(", 1)[1].split("\n// 🤛 Someone's item", 1)[0]
        result = self.run_js('''
            let held = false, calls = [];
            const folderDoc = { folders: [] };
            const treeData = { nodes: [{ id: "up", title: "parent" }] };
            const treeHeldBy = () => held;
            const t = (k, v) => k + JSON.stringify(v || {});
            const alert = e => {throw Error(e)};
            const api = async (path, options) => { calls.push({path, body: JSON.parse(options.body)}); return {}; };
            function treeStartCtx(''' + function + '''
            (async () => {
                const node = {id: "node", parent: "up", title: "title", visibility: "self", links: {issue: "org/repo#1"}};
                const results = [];
                for (const [h, preset] of [[false, "claude-tui"], [false, "mail-tui"], [false, "codex-tui"],
                                          [false, "codex-mail"], [true, "codex-tui"]]) {
                    held = h; calls = [];
                    const ctx = treeStartCtx(node), body = {preset, label: ""};
                    ctx.prepare(body);
                    await ctx.after({id: "new-session"});
                    results.push({body, calls, title: ctx.title});
                }
                console.log(JSON.stringify(results));
            })();
        ''')
        self.assertEqual(result[0]["body"]["issue"], "org/repo#1")      # Claude in the devbox: the issue's own session
        for r in result[1:]:
            self.assertNotIn("issue", r["body"])
        for r in result:
            self.assertEqual(r["title"], "title")
            self.assertEqual(r["body"]["label"], "title")               # empty: the item's title
            self.assertIn("parent / title", r["body"]["initial_message"])
        for r in result[:4]:
            self.assertEqual(r["calls"][0]["body"]["op"], "update")
            self.assertEqual(r["calls"][0]["body"]["links"]["session"], "new-session")
        self.assertEqual(result[4]["calls"][0]["body"]["op"], "add")   # held already: a child
        self.assertEqual(result[4]["calls"][0]["body"]["parent"], "node")


if __name__ == "__main__":
    unittest.main()
