"""aiza-discord-tree (the deployment notes): a channel for each shared root of
the work tree, a thread for each branch under it -- against a stand-in
Discord that records what was asked.

    python3 -m unittest discover -s tests -v
"""
import importlib.machinery
import importlib.util
import unittest
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load():
    loader = importlib.machinery.SourceFileLoader("aiza_discord_tree", str(ROOT / "bin" / "aiza-discord-tree"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("aiza_discord_tree", loader))
    loader.exec_module(mod)
    return mod


T = load()
GUILD, BOT = "900000000000000001", "900000000000000002"
PEOPLE = {
    "alice": {"name": "A", "discord_id": "100000000000000001"},
    "bob": {"name": "B", "discord_id": "100000000000000002"},
    "carol": {"name": "C", "discord_id": "100000000000000003"},
    "dave": {"name": "D", "discord_id": ""},
}
LAB = {"alice", "bob", "carol", "dave"}


class FakeDiscord:
    def __init__(self):
        self.calls = []
        self.channels = {}
        self.n = 0
        self.broken = {}   # channel id -> the HTTP error it answers

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/users/@me/guilds":
            return [{"id": GUILD}]
        if path == "/users/@me":
            return {"id": BOT}
        if method == "POST" and (path.endswith("/channels") or path.endswith("/threads")):
            self.n += 1
            cid = str(800000000000000000 + self.n)
            self.channels[cid] = dict(body, parent=path)
            return {"id": cid}
        cid = path.split("/")[2] if path.startswith("/channels/") else None
        if cid in self.broken:
            raise urllib.error.HTTPError(path, self.broken[cid], "broken", {}, None)
        if method == "PATCH":
            self.channels[cid].update(body)
            return {}
        if method == "GET" and cid:
            return self.channels[cid]
        return {}


def node(nid, title, parent=None, owner="alice", vis="self", members=(), state="open", order=0):
    return {"id": nid, "title": title, "parent": parent, "owner": owner, "visibility": vis,
            "members": list(members), "state": state, "order": order}


def tree(*ns):
    return {n["id"]: n for n in ns}


class DiscordTreeTest(unittest.TestCase):
    def run_sync(self, nodes, state=None):
        api = FakeDiscord() if not hasattr(self, "api") else self.api
        self.api = api
        state = {} if state is None else state
        did, failed = T.sync(api, state, T.want(nodes, PEOPLE, lambda u: u in LAB))
        self.assertEqual(failed, [])
        return state, did

    def seen_by(self, overwrites):
        return sorted(o["id"] for o in overwrites if o["type"] == 1 and o["id"] != BOT)

    def test_only_shared_roots_get_a_channel_seen_by_who_sees_the_root(self):
        nodes = tree(node("n1", "mine alone"),
                     node("n2", "with bob", members=["bob"]),
                     node("n3", "the lab", vis="lab", owner="bob"),
                     node("n21", "a branch", parent="n2"))
        state, _ = self.run_sync(nodes)
        self.assertEqual(sorted(state["roots"]), ["n2", "n3"])
        ch2 = self.api.channels[state["roots"]["n2"]["channel"]]
        self.assertEqual(self.seen_by(ch2["permission_overwrites"]), ["100000000000000001", "100000000000000002"])
        everyone = [o for o in ch2["permission_overwrites"] if o["id"] == GUILD][0]
        self.assertEqual(int(everyone["deny"]) & T.VIEW, T.VIEW)
        ch3 = self.api.channels[state["roots"]["n3"]["channel"]]
        # the lab: everyone with a Discord ID (dave has none)
        self.assertEqual(len(self.seen_by(ch3["permission_overwrites"])), 3)
        self.assertIn("#tree=n2", ch2["topic"])
        self.assertEqual(ch2["parent_id"], state["categories"]["tree"])
        # a thread for the branch, with a link back
        self.assertIn("n21", state["roots"]["n2"]["threads"])
        msgs = [b for m, p, b in self.api.calls if p.endswith("/messages")]
        self.assertTrue(any("#tree=n21" in b["content"] for b in msgs))
        self.assertTrue(all(b["allowed_mentions"] == {"parse": []} for b in msgs))

    def test_a_second_run_with_nothing_changed_does_nothing(self):
        nodes = tree(node("n2", "with bob", members=["bob"]), node("n21", "a branch", parent="n2"))
        state, _ = self.run_sync(nodes)
        _, did = self.run_sync(nodes, state)
        self.assertEqual(did, [])

    def test_titles_members_and_done_follow(self):
        nodes = tree(node("n2", "with bob", members=["bob"]), node("n21", "a branch", parent="n2"))
        state, _ = self.run_sync(nodes)
        cid = state["roots"]["n2"]["channel"]
        tid = state["roots"]["n2"]["threads"]["n21"]["thread"]
        nodes["n2"]["title"] = "renamed"
        nodes["n2"]["members"] = ["bob", "carol"]
        nodes["n21"]["state"] = "done"
        self.run_sync(nodes, state)
        self.assertEqual(self.api.channels[cid]["name"], "renamed")
        self.assertEqual(len(self.seen_by(self.api.channels[cid]["permission_overwrites"])), 3)
        self.assertTrue(self.api.channels[tid]["archived"])
        # opened again
        nodes["n21"]["state"] = "open"
        self.run_sync(nodes, state)
        self.assertFalse(self.api.channels[tid]["archived"])
        # the root done: over, its threads closed
        nodes["n2"]["state"] = "done"
        self.run_sync(nodes, state)
        self.assertEqual(self.api.channels[cid]["parent_id"], state["categories"]["over"])
        self.assertTrue(self.api.channels[tid]["archived"])

    def test_an_archived_thread_is_opened_to_rename_and_archived_again(self):
        nodes = tree(node("n2", "r", members=["bob"]), node("n21", "b", parent="n2", state="done"))
        state, _ = self.run_sync(nodes)
        tid = state["roots"]["n2"]["threads"]["n21"]["thread"]
        nodes["n21"]["title"] = "b2"
        self.run_sync(nodes, state)
        patches = [b for m, p, b in self.api.calls if m == "PATCH" and p == f"/channels/{tid}"]
        self.assertEqual(patches[-2:], [{"archived": False, "name": "b2"}, {"archived": True}])

    def test_no_longer_shared_goes_over_and_only_the_owner_sees_it(self):
        nodes = tree(node("n2", "with bob", members=["bob"]))
        state, _ = self.run_sync(nodes)
        cid = state["roots"]["n2"]["channel"]
        nodes["n2"]["members"] = []
        self.run_sync(nodes, state)
        ch = self.api.channels[cid]
        self.assertEqual(ch["parent_id"], state["categories"]["over"])
        self.assertEqual(self.seen_by(ch["permission_overwrites"]), ["100000000000000001"])
        # shared again: back, seen again
        nodes["n2"]["members"] = ["bob"]
        self.run_sync(nodes, state)
        self.assertEqual(ch["parent_id"], state["categories"]["tree"])
        self.assertEqual(len(self.seen_by(ch["permission_overwrites"])), 2)
        # nothing is ever deleted
        self.assertFalse([c for c in self.api.calls if c[0] == "DELETE"])

    def test_a_branch_moved_away_is_archived(self):
        nodes = tree(node("n2", "r", members=["bob"]), node("n21", "b", parent="n2"), node("n3", "other"))
        state, _ = self.run_sync(nodes)
        tid = state["roots"]["n2"]["threads"]["n21"]["thread"]
        nodes["n21"]["parent"] = "n3"
        self.run_sync(nodes, state)
        self.assertTrue(self.api.channels[tid]["archived"])

    def test_dry_run_asks_nothing_that_changes(self):
        nodes = tree(node("n2", "r", members=["bob"]), node("n21", "b", parent="n2"))
        api = FakeDiscord()
        state = {}
        did, _ = T.sync(api, state, T.want(nodes, PEOPLE, lambda u: u in LAB), dry=True)
        self.assertTrue(did)
        self.assertEqual({m for m, _, _ in api.calls}, {"GET"})

    def test_links_name_open_roots_and_their_threads(self):
        nodes = tree(node("n2", "r", members=["bob"]), node("n21", "b", parent="n2"))
        state, _ = self.run_sync(nodes)
        links = T.links(state)
        self.assertEqual(sorted(links), ["n2", "n21"])
        self.assertTrue(links["n2"].startswith(f"https://discord.com/channels/{GUILD}/"))
        nodes["n2"]["members"] = []
        self.run_sync(nodes, state)
        self.assertEqual(T.links(state), {})

    def test_a_failing_root_does_not_stop_the_others_and_narrowing_comes_first(self):
        nodes = tree(node("n2", "a", members=["bob"]), node("n3", "b", members=["bob", "carol"]))
        state, _ = self.run_sync(nodes)
        c2, c3 = state["roots"]["n2"]["channel"], state["roots"]["n3"]["channel"]
        self.api.broken[c2] = 403
        nodes["n2"]["title"] = "a2"
        nodes["n3"]["members"] = ["bob"]   # carol out
        did, failed = T.sync(self.api, state, T.want(nodes, PEOPLE, lambda u: u in LAB))
        self.assertEqual(failed, ["n2"])
        self.assertEqual(self.seen_by(self.api.channels[c3]["permission_overwrites"]),
                         ["100000000000000001", "100000000000000002"])
        self.assertEqual(did[0], "channel n3 narrow")

    def test_a_channel_deleted_on_discord_is_made_again(self):
        nodes = tree(node("n2", "a", members=["bob"]))
        state, _ = self.run_sync(nodes)
        old = state["roots"]["n2"]["channel"]
        self.api.broken[old] = 404
        nodes["n2"]["title"] = "a2"
        _, failed = T.sync(self.api, state, T.want(nodes, PEOPLE, lambda u: u in LAB))
        self.assertEqual(failed, ["n2"])
        self.assertNotIn("n2", state["roots"])
        state, _ = self.run_sync(nodes, state)
        self.assertNotEqual(state["roots"]["n2"]["channel"], old)

    def test_check_puts_back_overwrites_changed_by_hand(self):
        nodes = tree(node("n2", "a", members=["bob"]))
        state, _ = self.run_sync(nodes)
        cid = state["roots"]["n2"]["channel"]
        self.api.channels[cid]["permission_overwrites"].append(
            {"id": "100000000000000003", "type": 1, "allow": str(T.MEMBER), "deny": "0"})
        _, did = self.run_sync(nodes, state)
        self.assertEqual(did, [])   # without check: not seen
        did, _ = T.sync(self.api, state, T.want(nodes, PEOPLE, lambda u: u in LAB), check=True)
        self.assertEqual(did, ["channel n2 overwrites"])
        self.assertEqual(len(self.seen_by(self.api.channels[cid]["permission_overwrites"])), 2)
        did, _ = T.sync(self.api, state, T.want(nodes, PEOPLE, lambda u: u in LAB), check=True)
        self.assertEqual(did, [])

    def test_a_branch_moved_away_is_no_longer_linked(self):
        nodes = tree(node("n2", "r", members=["bob"]), node("n21", "b", parent="n2"), node("n3", "other"))
        state, _ = self.run_sync(nodes)
        nodes["n21"]["parent"] = "n3"
        self.run_sync(nodes, state)
        self.assertEqual(sorted(T.links(state)), ["n2"])
        nodes["n21"]["parent"] = "n2"   # back: linked again
        self.run_sync(nodes, state)
        self.assertEqual(sorted(T.links(state)), ["n2", "n21"])


if __name__ == "__main__":
    unittest.main()
