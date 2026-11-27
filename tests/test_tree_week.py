"""The weekly summary of the work tree (the plan's stage 3).

    python3 -m unittest discover -s tests -v
"""
import time
import unittest

from test_shared_search import B

NOW = 1_800_000_000


class WeekTest(unittest.TestCase):
    def setUp(self):
        self.nodes = [
            {"id": "n1", "parent": None, "title": "親", "state": "open", "ball": None},
            {"id": "n2", "parent": "n1", "title": "止まり", "state": "open", "ball": {"kind": "person", "who": "u", "since": NOW - 5 * 86400}},
            {"id": "n3", "parent": "n1", "title": "済み", "state": "done", "ball": None},
            {"id": "n4", "parent": "n1", "title": "往復", "state": "open", "ball": {"kind": "ai", "since": NOW - 3600}},
        ]
        flips = [{"kind": "ai"}, {"kind": "person", "who": "u"}, {"kind": "ai"}, {"kind": "person", "who": "u"}, {"kind": "ai"}]
        self.hist = ([{"ts": NOW - 86400, "id": "n3", "op": "update", "changes": {"state": "done"}}]
                     + [{"ts": NOW - 1000 + i, "id": "n4", "op": "ball", "changes": {"ball": b}} for i, b in enumerate(flips)])
        self.saved = B.tree_call
        B.tree_call = lambda req: {"nodes": self.nodes} if req["op"] == "list" else {"history": self.hist}

    def tearDown(self):
        B.tree_call = self.saved

    def test_week(self):
        w = B.tree_week(NOW)
        self.assertEqual([x["id"] for x in w["done"]], ["n3"])
        self.assertEqual([x["id"] for x in w["moving"]], ["n4"])
        self.assertEqual([(x["id"], x["days"]) for x in w["stuck"]], [("n2", 5)])   # the parent is not a leaf
        self.assertEqual([(x["id"], x["changes"]) for x in w["pingpong"]], [("n4", 4)])


if __name__ == "__main__":
    unittest.main()
