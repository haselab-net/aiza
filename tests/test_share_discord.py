"""A Discord DM when a session is shared with someone new (the deployment notes):
the backend only asks root's helper (sudo), in the background; the helper
checks the share, reads the roster and sends.

    python3 -m unittest discover -s tests -v
"""
import importlib.machinery
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_shared_search import B

ROOT = Path(__file__).resolve().parents[1]


def load_helper():
    loader = importlib.machinery.SourceFileLoader("aiza_discord_dm", str(ROOT / "bin" / "aiza-discord-dm"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    mod.DOMAIN = ".example.org"   # the links' domain, not this host's
    return mod


class BackendAsksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.metas = {"aaaaaaaaaa01": {"id": "aaaaaaaaaa01", "preset": "claude-tui", "label": "x"}}
        self.saved = (B.load_meta, B.save_meta, B.notify_share_discord)
        B.load_meta = lambda sid: self.metas.get(sid)
        B.save_meta = lambda sid, m: self.metas.__setitem__(sid, m)
        self.asked = []
        B.notify_share_discord = lambda sid, user: self.asked.append((sid, user))

    def tearDown(self):
        B.load_meta, B.save_meta, B.notify_share_discord = self.saved
        self.tmp.cleanup()

    def test_only_a_new_person_is_told(self):
        me = os.environ.get("USER") or "alice"
        other = "root" if me != "root" else "daemon"
        B.share_session("aaaaaaaaaa01", other, "write")
        B.share_session("aaaaaaaaaa01", other, "write")       # again: nothing new
        B.share_session("aaaaaaaaaa01", other, "read")        # mode change: not new
        B.share_session("aaaaaaaaaa01", B.SHARE_EVERYONE, "read")
        self.assertEqual(self.asked, [("aaaaaaaaaa01", other)])

    def test_every_new_share_leaves_the_gateway_a_hint(self):
        # A share made by the backend itself (the desk, the work tree) must
        # also put the owner in the viewer's list, or the link opens nothing.
        hints = []
        saved = B._peer_call
        B._peer_call = lambda req, timeout=30: (hints.append(req), {"ok": True})[1]
        try:
            me = os.environ.get("USER") or "alice"
            other = "root" if me != "root" else "daemon"
            B.share_session("aaaaaaaaaa01", other, "read")
            B.share_session("aaaaaaaaaa01", other, "write")    # mode change: no new hint
            B.share_session("aaaaaaaaaa01", B.SHARE_EVERYONE, "read")
        finally:
            B._peer_call = saved
        self.assertEqual(hints, [{"op": "share_hint", "viewer": other}, {"op": "share_hint", "viewer": "*"}])

    def test_no_gateway_is_not_in_the_way(self):
        me = os.environ.get("USER") or "alice"
        other = "root" if me != "root" else "daemon"
        B.share_session("aaaaaaaaaa01", other, "read")    # PEER_SOCK points nowhere in tests
        self.assertIn(other, self.metas["aaaaaaaaaa01"]["shared_read"])


class HelperTest(unittest.TestCase):
    def setUp(self):
        self.H = load_helper()
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.H.ROSTER = d / "members.md"
        self.H.ROSTER.write_text(
            "# 名簿\n\n| 名前 | 学年 | 入学 | aiza | gs.example.org | Discord 名 | Discord ID |\n"
            "|---|---|---|---|---|---|---|\n"
            "| 山田 太郎 | M1 | 2026-04 | `yamada` | yamada@gs.example.org | taro | 123456789012345678 |\n"
            "| 佐藤 | D2 | 2024-04 | `sato` | sato@gs.example.org | sato_ | |\n", encoding="utf-8")
        self.H.APPROVED = d / "discord-ids.json"   # root approved yamada's ID
        self.H.APPROVED.write_text('{"yamada": "123456789012345678"}')
        self.H.STATE = d / "state"
        self.H.LOG = d / "log"
        self.H.TOKEN_FILE = d / "token"
        self.H.TOKEN_FILE.write_text("tok\n")
        self.meta = {"label": "論文 @everyone の直し", "shared_with": ["yamada"], "shared_read": ["sato"]}
        self.H.session_meta = lambda user, sid: self.meta
        self.sent = []
        self.H.call = lambda token, method, path, body: (self.sent.append((path, body)), {"id": "999"})[1]

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_roster_id_counts_only_once_root_approved_it(self):
        # the roster is the lab's to write: a row giving yamada another ID
        # (someone's own) does not move yamada's DMs and channels there
        self.H.ROSTER.write_text(self.H.ROSTER.read_text().replace("123456789012345678", "999999999999999999")
                                 .replace("| sato_ | |", "| sato_ | 888888888888888888 |"))
        r = self.H.roster()
        self.assertEqual((r["yamada"]["discord_id"], r["yamada"]["pending"]), ("123456789012345678", True))
        self.assertEqual((r["sato"]["discord_id"], r["sato"]["pending"]), ("", True))
        self.H.discord_name = lambda did: {"888888888888888888": "sato_ / 佐藤"}.get(did, "")
        with mock.patch("os.geteuid", return_value=0), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(self.H.main(["x", "ids"]), 0)
        self.assertEqual(out.getvalue(),
                         "sato\tpending: new in the roster\t888888888888888888\tDiscord: sato_ / 佐藤\troster: sato_\n"
                         "yamada\tpending: changed in the roster\t999999999999999999\tDiscord: ?\troster: taro\n")
        with mock.patch("os.geteuid", return_value=0), mock.patch("sys.stdout", new_callable=io.StringIO), \
                mock.patch("sys.stderr", new_callable=io.StringIO):
            # the ID must be the one root saw, and still the roster's
            self.assertEqual(self.H.main(["x", "approve", "sato", "777777777777777777"]), 1)
            self.assertEqual(self.H.main(["x", "approve", "sato", "888888888888888888"]), 0)
            self.assertEqual(self.H.main(["x", "revoke", "yamada"]), 0)
        logged = self.H.LOG.read_text()
        self.assertIn("approve ...8888", logged)
        self.assertNotIn("888888888888888888", logged)
        r = self.H.roster()
        self.assertEqual((r["sato"]["discord_id"], r["yamada"]["discord_id"]), ("888888888888888888", ""))
        self.assertEqual(oct(self.H.APPROVED.stat().st_mode & 0o777), "0o600")

    def test_a_sessions_meta_is_read_without_following_links(self):
        H = load_helper()
        home = Path(self.tmp.name) / "home"
        other = Path(self.tmp.name) / "other"
        (home / ".aiza-state" / "sessions" / "aaaaaaaaaa01").mkdir(parents=True)
        (home / ".aiza-state" / "sessions" / "aaaaaaaaaa01" / "meta.json").write_text('{"label": "mine"}')
        (other / "aaaaaaaaaa02").mkdir(parents=True)
        (other / "aaaaaaaaaa02" / "meta.json").write_text('{"label": "someone else"}')
        (home / ".aiza-state" / "sessions" / "aaaaaaaaaa02").symlink_to(other / "aaaaaaaaaa02")
        (home / "sandhome").symlink_to(other)
        pw = type("pw", (), {"pw_dir": str(home), "pw_uid": os.getuid()})
        with mock.patch.object(H.pwd, "getpwnam", return_value=pw):
            self.assertEqual(H.session_meta("yamada", "aaaaaaaaaa01"), {"label": "mine"})
            self.assertIsNone(H.session_meta("yamada", "aaaaaaaaaa02"))
        pw.pw_uid = os.getuid() + 1   # a file not the user's own
        with mock.patch.object(H.pwd, "getpwnam", return_value=pw):
            self.assertIsNone(H.session_meta("yamada", "aaaaaaaaaa01"))

    def test_names_for_roots_terminal_lose_control_characters(self):
        self.assertEqual(self.H.printable("a\x1b[2Jb\u202ec\u200bd"), "a[2Jbcd")

    def test_approving_is_roots_alone(self):
        with mock.patch("os.geteuid", return_value=1000), mock.patch("sys.stderr", new_callable=io.StringIO):
            self.assertEqual(self.H.main(["x", "approve", "sato"]), 2)

    def run_as(self, sender, *args):
        with mock.patch.object(self.H.os, "geteuid", return_value=0), \
                mock.patch.dict(self.H.os.environ, {"SUDO_USER": sender}):
            return self.H.main(["aiza-discord-dm", *args])

    def test_roster_rows(self):
        r = self.H.roster()
        self.assertEqual(r["yamada"]["discord_id"], "123456789012345678")
        self.assertEqual(r["sato"]["discord_id"], "")

    def test_sends_with_the_sessions_own_title(self):
        self.assertEqual(self.run_as("sato", "share", "yamada", "aaaaaaaaaa01"), 0)
        self.assertEqual(self.sent[0], ("/users/@me/channels", {"recipient_id": "123456789012345678"}))
        text = self.sent[1][1]["content"]
        self.assertIn("佐藤 さんが", text)
        self.assertIn("論文 @​everyone の直し", text)               # no mention
        self.assertIn("(共同作業)", text)
        self.assertTrue(text.rstrip().endswith("/agents/#aaaaaaaaaa01"))
        self.assertEqual(self.sent[1][1]["allowed_mentions"], {"parse": []})

    def test_not_shared_or_no_id_sends_nothing(self):
        self.assertEqual(self.run_as("sato", "share", "nobody", "aaaaaaaaaa01"), 1)   # not in the session
        self.assertEqual(self.run_as("yamada", "share", "sato", "aaaaaaaaaa01"), 0)   # no Discord ID
        self.assertEqual(self.sent, [])
        log = [json.loads(l)["result"] for l in self.H.LOG.read_text().splitlines()]
        self.assertEqual(log, ["not-shared", "no-discord-id"])
        self.assertNotIn("論文", self.H.LOG.read_text())                           # no title in the log

    def test_a_few_per_hour(self):
        for _ in range(self.H.PER_HOUR):
            self.assertEqual(self.run_as("sato", "share", "yamada", "aaaaaaaaaa01"), 0)
        self.assertEqual(self.run_as("sato", "share", "yamada", "aaaaaaaaaa01"), 1)

    def test_bad_arguments(self):
        self.assertEqual(self.run_as("sato", "share", "yamada", "../x"), 2)
        self.assertEqual(self.run_as("root", "share", "yamada", "aaaaaaaaaa01"), 2)


class TreeAndPeerTest(HelperTest):
    """The work tree's notice (root's store calls the helper)."""
    def setUp(self):
        super().setUp()
        self.H.TREE_NODES = Path(self.tmp.name) / "nodes.json"
        self.H.TREE_NODES.write_text(json.dumps({"n0123456789ab": {
            "id": "n0123456789ab", "owner": "sato", "members": ["yamada"], "title": "装置 @here の改造"}}))

    def tree(self, *args, env=None):
        with mock.patch.object(self.H.os, "geteuid", return_value=0), \
                mock.patch.dict(self.H.os.environ, env or {}, clear=True):
            return self.H.main(["aiza-discord-dm", "tree", *args])

    def test_tree_notice_with_link(self):
        self.assertEqual(self.tree("sato", "yamada", "n0123456789ab"), 0)
        text = self.sent[1][1]["content"]
        self.assertIn("佐藤 さんが、仕事の木の「装置 @\u200bhere の改造」", text)
        self.assertTrue(text.rstrip().endswith("/agents/#tree=n0123456789ab"))

    def test_tree_only_owner_to_named_member_and_not_via_sudo(self):
        self.assertEqual(self.tree("yamada", "sato", "n0123456789ab"), 1)        # not the owner
        self.assertEqual(self.tree("sato", "nobody", "n0123456789ab"), 1)        # not named
        self.assertEqual(self.tree("sato", "yamada", "nffffffffffff"), 1)        # no such node
        self.assertEqual(self.tree("sato", "yamada", "../x"), 2)
        self.assertEqual(self.tree("sato", "yamada", "n0123456789ab", env={"SUDO_USER": "sato"}), 2)
        self.assertEqual(self.sent, [])


class RelayTest(HelperTest):
    """the deployment notes: a host without the roster spools the notice;
    the host with it pulls and sends."""
    def setUp(self):
        super().setUp()
        d = Path(self.tmp.name)
        self.H.RELAY_PEERS = d / "peers"
        self.H.RELAY_PEERS.write_text("other\n")
        self.H.SPOOL = d / "spool"

    def test_spool_then_pull(self):
        roster = self.H.ROSTER
        self.H.ROSTER = Path(self.tmp.name) / "missing.md"
        self.H.ring = lambda *a: True
        self.assertEqual(self.run_as("sato", "share", "yamada", "aaaaaaaaaa01"), 0)
        self.assertEqual(self.sent, [])
        self.assertEqual(len(list(self.H.SPOOL.glob("*.json"))), 1)
        out = io.StringIO()
        with mock.patch.object(self.H.sys, "stdout", out):
            self.assertEqual(self.H.spool_take(), 0)
        self.assertEqual(list(self.H.SPOOL.glob("*.json")), [])
        self.H.ROSTER = roster
        with mock.patch.object(self.H.subprocess, "run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=out.getvalue())
            self.assertEqual(self.H.pull_peers(), 0)
        self.assertEqual(run.call_args[0][0][-2], "other")
        text = self.sent[1][1]["content"]
        self.assertIn("佐藤 さんが、セッション「論文 @\u200beveryone の直し」", text)
        self.assertIn("(共同作業)", text)
        self.assertTrue(text.rstrip().endswith("https://other.example.org/agents/#aaaaaaaaaa01"))

    def test_spool_rings_without_content(self):
        self.H.ROSTER = Path(self.tmp.name) / "missing.md"
        self.H.DOORBELL_URL = Path(self.tmp.name) / "bell"
        self.H.DOORBELL_URL.write_text("https://host1.example/aiza-doorbell/discord\n")
        with mock.patch.object(self.H.urllib.request, "urlopen") as op:
            op.return_value.__enter__.return_value.status = 204
            self.assertEqual(self.run_as("sato", "share", "yamada", "aaaaaaaaaa01"), 0)
        self.assertEqual(op.call_count, 1)
        req = op.call_args[0][0]
        self.assertEqual((req.full_url, req.get_method(), req.data), ("https://host1.example/aiza-doorbell/discord", "POST", b""))

    def test_ring_tries_again_then_logs(self):
        self.H.DOORBELL_URL = Path(self.tmp.name) / "bell"
        self.H.DOORBELL_URL.write_text("https://host1.example/aiza-doorbell/discord\n")
        self.H.RING_TRIES = (0, 0, 0)
        with mock.patch.object(self.H.urllib.request, "urlopen", side_effect=OSError("down")) as op:
            self.assertFalse(self.H.ring("sato", "yamada"))
        self.assertEqual(op.call_count, 3)
        self.assertEqual(json.loads(self.H.LOG.read_text().splitlines()[-1])["result"], "ring-failed:OSError")

    def test_doorbell_answers_and_pulls(self):
        import socket as so
        a, b = so.socketpair()
        srv = mock.Mock()
        srv.accept.side_effect = [(a, None)] + [so.timeout()] * 1000
        self.H.DOORBELL_IDLE = 0
        pulls = []
        self.H.pull_peers = lambda: pulls.append(1) or 0
        b.sendall(b"POST / HTTP/1.1\r\n\r\n")
        with mock.patch.object(self.H.socket, "socket", return_value=srv):
            self.assertEqual(self.H.doorbell(), 0)
        self.assertTrue(b.recv(100).startswith(b"HTTP/1.1 204"))
        self.assertEqual(pulls, [1])
        b.close()

    def test_pulled_lines_are_checked_again(self):
        good = {"from": "sato", "to": "yamada", "sid": "aaaaaaaaaa01", "title": "x", "mode": "閲覧"}
        for bad in (dict(good, mode="x"), dict(good, sid="../x"), dict(good, **{"from": "root"}), ["x"]):
            self.assertEqual(self.H.relay_one("other", bad), 2)
        self.assertEqual(self.sent, [])

    def test_only_root_and_not_through_members_sudo(self):
        with mock.patch.object(self.H.os, "geteuid", return_value=1000):
            self.assertEqual(self.H.main(["aiza-discord-dm", "spool-take"]), 2)


class SayTest(HelperTest):
    """the deployment notes: a DM from a container, through the socket unit."""

    def test_mention_and_names(self):
        r = self.H.say("sato", {"to": ["taro"], "text": "@yamada さん、pc-01 の Office が直りました @everyone"})
        self.assertEqual(r, {"ok": True, "sent": ["yamada"], "failed": {}})
        body = self.sent[1][1]
        self.assertTrue(body["content"].startswith("<@123456789012345678> 山田 太郎 さんへ — 佐藤 さんより(AI座)\n"))
        self.assertIn("<@123456789012345678> さん、", body["content"])
        self.assertEqual(body["allowed_mentions"], {"parse": [], "users": ["123456789012345678"]})

    def test_by_roster_name_and_unknowns(self):
        r = self.H.say("nobody", {"to": ["山田 太郎", "sato", "ghost"], "text": "x"})
        self.assertEqual(r["sent"], ["yamada"])
        self.assertEqual(sorted(r["failed"]), ["ghost", "sato"])
        self.assertIn("nobody さんより", self.sent[1][1]["content"])
        self.assertFalse(r["ok"])

    def test_bad_requests_and_list(self):
        self.assertFalse(self.H.say("sato", {"to": [], "text": "x"})["ok"])
        self.assertFalse(self.H.say("sato", {"to": ["yamada"] * 6, "text": "x"})["ok"])
        self.assertFalse(self.H.say("sato", {"to": ["yamada"], "text": "  "})["ok"])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.H.say("sato", {"list": True})["members"],
                         [{"aiza": "yamada", "name": "山田 太郎", "discord": "taro"}])

    def test_rate_limit(self):
        for _ in range(self.H.PER_HOUR):
            self.H.say("sato", {"to": ["yamada"], "text": "x"})
        r = self.H.say("sato", {"to": ["yamada"], "text": "x"})
        self.assertEqual(r["failed"], {"yamada": "too many messages this hour"})

    def test_channel_post(self):
        def call(token, method, path, body):
            self.sent.append((method, path, body))
            if path == "/users/@me/guilds":
                return [{"id": "1"}]
            if path == "/guilds/1/channels":
                return [{"id": "77", "name": "random", "type": 0}, {"id": "78", "name": "voice", "type": 2}]
            return {"id": "999"}
        self.H.call = call
        r = self.H.say("sato", {"channel": "#random", "to": ["yamada"], "text": "@taro 見て @here"})
        self.assertEqual(r, {"ok": True, "sent": ["#random"], "failed": {}})
        method, path, body = self.sent[-1]
        self.assertEqual(path, "/channels/77/messages")
        self.assertTrue(body["content"].startswith("<@123456789012345678> 山田 太郎 さんへ — 佐藤 さんより(AI座)\n"))
        self.assertEqual(body["allowed_mentions"], {"parse": [], "users": ["123456789012345678"]})
        self.assertFalse(self.H.say("sato", {"channel": "voice", "text": "x"})["ok"])
        self.assertFalse(self.H.say("sato", {"channel": "random", "to": ["sato"], "text": "x"})["ok"])


if __name__ == "__main__":
    unittest.main()
