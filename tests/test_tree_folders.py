"""The work tree's ▶ starts a session in the session folder of its tree:
one chosen on the root (📁), else guessed from where the tree's sessions are.

    python3 -m unittest discover -s tests -v
"""
import tempfile
import unittest
from pathlib import Path

from test_shared_search import B


def node(i, parent=None, session=None, owner="me", **kw):
    return dict({"id": i, "parent": parent, "title": i, "owner": owner,
                 "links": {"session": session} if session else {}}, **kw)


class TreeFoldersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = B.STATE_DIR
        B.STATE_DIR = Path(self.tmp.name) / "state"
        B.apply_folder_ops([
            {"op": "put", "folder": {"id": "fres", "name": "Research"}},
            {"op": "put", "folder": {"id": "fpc", "name": "WebApp", "parent": "fres", "workdir": "webapp"}},
            {"op": "put", "folder": {"id": "fsp", "name": "Robot", "parent": "fres"}},
            {"op": "put", "folder": {"id": "fold", "name": "Old", "archived": True}},
            {"op": "assign", "session": "aaaaaaaaaa01", "folder": "fpc"},
            {"op": "assign", "session": "aaaaaaaaaa02", "folder": "fsp"},
            {"op": "assign", "session": "aaaaaaaaaa03", "folder": "fold"},
        ])

    def tearDown(self):
        B.STATE_DIR = self.saved
        self.tmp.cleanup()

    def folders(self, nodes):
        return {n["id"]: (n.get("folder") or {}).get("id") for n in B.tree_folders(nodes, "me")}

    def test_guess_from_the_nearest_session(self):
        nodes = [node("n000000000001"), node("n000000000002", "n000000000001"),
                 node("n000000000003", "n000000000002", "aaaaaaaaaa02"),
                 node("n000000000004", "n000000000003"), node("n000000000005", "n000000000001", "aaaaaaaaaa01"),
                 node("n000000000006", "n000000000002")]
        f = self.folders(nodes)
        self.assertEqual(f["n000000000004"], "fsp")          # its parent's session
        self.assertEqual(f["n000000000005"], "fpc")          # its own
        # No session on the way up: the tree's most common folder (a tie here, any of the two).
        self.assertIn(f["n000000000006"], ("fpc", "fsp"))
        self.assertEqual(nodes[3]["folder"]["how"], "guess")
        self.assertEqual(nodes[3]["folder"]["path"], "Research / Robot")

    def test_rest_counts_and_others_sessions_and_archived_do_not(self):
        nodes = [node("n000000000001"), node("n000000000002", "n000000000001", "aaaaaaaaaa01", rest=True),
                 node("n000000000003", "n000000000001"),
                 node("n000000000011"), node("n000000000012", "n000000000011", "aaaaaaaaaa02", owner="bob"),
                 node("n000000000021"), node("n000000000022", "n000000000021", "aaaaaaaaaa03")]
        f = self.folders(nodes)
        self.assertEqual(f["n000000000001"], "fpc")          # through its その他
        self.assertIsNone(f["n000000000012"])                # bob's session, not mine
        self.assertIsNone(f["n000000000022"])                # in an archived folder

    def test_chosen_on_the_root_wins(self):
        B.apply_folder_ops([{"op": "tree_root", "node": "n000000000001", "folder": "fsp"}])
        nodes = [node("n000000000001"), node("n000000000002", "n000000000001", "aaaaaaaaaa01")]
        f = self.folders(nodes)
        self.assertEqual(f, {"n000000000001": "fsp", "n000000000002": "fsp"})
        self.assertEqual(nodes[1]["folder"]["how"], "set")
        # Choosing another moves it; "" goes back to guessing.
        B.apply_folder_ops([{"op": "tree_root", "node": "n000000000001", "folder": "fpc"}])
        doc = B.load_folders()
        self.assertEqual([f["id"] for f in doc["folders"] if "n000000000001" in f["tree_roots"]], ["fpc"])
        B.apply_folder_ops([{"op": "tree_root", "node": "n000000000001", "folder": ""}])
        self.assertFalse(any(f["tree_roots"] for f in B.load_folders()["folders"]))
        with self.assertRaises(ValueError):
            B.apply_folder_ops([{"op": "tree_root", "node": "n000000000001", "folder": "nope"}])
        with self.assertRaises(ValueError):
            B.apply_folder_ops([{"op": "tree_root", "node": "x", "folder": "fpc"}])

    def test_chosen_archived_folder_holds_a_finished_tree(self):
        # A finished tree dragged onto an archived folder (the deployment notes, 2026-11-26): chosen, so it holds;
        # a guess never lands in an archived folder.
        B.apply_folder_ops([{"op": "tree_root", "node": "n000000000031", "folder": "fold"}])
        f = self.folders([node("n000000000031", state="done"), node("n000000000032", session="aaaaaaaaaa03")])
        self.assertEqual(f["n000000000031"], "fold")
        self.assertIsNone(f["n000000000032"])

    def test_new_folder_and_choice_in_one_write(self):
        B.apply_folder_ops([{"op": "put", "folder": {"id": "fnew", "name": "VGent", "parent": "fres"}},
                            {"op": "tree_root", "node": "n000000000009", "folder": "fnew"}])
        nodes = [node("n000000000009")]
        self.assertEqual(self.folders(nodes)["n000000000009"], "fnew")
        self.assertEqual(nodes[0]["folder"]["path"], "Research / VGent")


    def test_a_session_misfiled_against_its_place_does_not_vouch(self):
        # 2026-11-22: another project's session running in /root/work/cad, filed by
        # mistake in WebApp (作業ディレクトリ webapp), sent a CAD task there.
        B.apply_folder_ops([
            {"op": "put", "folder": {"id": "fcad", "name": "CAD", "workdir": "work/cad"}},
            {"op": "assign", "session": "aaaaaaaaaa04", "folder": "fpc"},
            {"op": "assign", "session": "aaaaaaaaaa05", "folder": "fpc"},
            {"op": "assign", "session": "aaaaaaaaaa06", "folder": "fpc"},
            {"op": "assign", "session": "aaaaaaaaaa07", "folder": "fsp"},
        ])
        metas = {"aaaaaaaaaa04": {"preset": "root-shell", "cwd": "/root/work/cad"},       # place says CAD
                 "aaaaaaaaaa05": {"preset": "root-shell", "cwd": "/root/elsewhere"},     # no folder's place
                 "aaaaaaaaaa06": {"preset": "root-shell", "claude_cwd": "/root/webapp/x"},  # agrees
                 "aaaaaaaaaa07": {"preset": "root-shell", "cwd": "/root/work/cad"}}       # Robot names no place
        saved = B.load_meta
        B.load_meta = lambda sid: metas.get(sid)
        try:
            nodes = [node("n000000000001"), node("n000000000002", "n000000000001", "aaaaaaaaaa04", rest=True),
                     node("n000000000003", "n000000000001"),
                     node("n000000000011"), node("n000000000012", "n000000000011", "aaaaaaaaaa05"),
                     node("n000000000013", "n000000000012"),
                     node("n000000000021"), node("n000000000022", "n000000000021", "aaaaaaaaaa06"),
                     node("n000000000031"), node("n000000000032", "n000000000031", "aaaaaaaaaa07")]
            f = self.folders(nodes)
        finally:
            B.load_meta = saved
        self.assertEqual(f["n000000000003"], "fcad")      # by its place, not where it was filed
        self.assertIsNone(f["n000000000013"])            # contradicts and no place matches: no guess
        self.assertEqual(f["n000000000022"], "fpc")      # under the folder's place: trusted
        self.assertEqual(f["n000000000032"], "fsp")      # the folder names no place: trusted

if __name__ == "__main__":
    unittest.main()
