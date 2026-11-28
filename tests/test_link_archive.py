"""An archived session leaves its talkto link (the deployment notes,
2026-11-27, the user: "セッションをアーカイブしたらそのセッションは外れるようにして").
Restoring it does not rejoin; links that already hold an archived session
are cleaned up by expire_links.

    python3 -m unittest discover -s tests -v
"""
import tempfile
import unittest
from unittest import mock

from test_link_groups import A, B2, C, LinkGroupTest
from test_shared_search import B


class LinkArchiveTest(unittest.TestCase):
    setUp, tearDown, meta, had_a_turn = LinkGroupTest.setUp, LinkGroupTest.tearDown, LinkGroupTest.meta, LinkGroupTest.had_a_turn

    def _members(self):
        return [rec["members"] for rec in B._load_links().values()]

    def test_archive_leaves_group(self):
        B.create_link(A, B2, forever=True)
        B.create_link(C, A)
        B.archive_session(C, True)
        self.assertEqual(self._members(), [[A, B2]])
        self.assertTrue(any(sid == A and "アーカイブ" in ev.get("text", "") for sid, ev in self.events))
        B.archive_session(C, False)  # restoring does not rejoin
        self.assertEqual(self._members(), [[A, B2]])

    def test_archive_of_pair_ends_link(self):
        B.create_link(A, B2, forever=True)
        B.archive_session(B2, True)
        self.assertEqual(self._members(), [])
        self.assertEqual(B.link_list_from_session(A)[0], "no_link")

    def test_old_archived_member_swept(self):
        B.create_link(A, B2, forever=True)
        B.create_link(C, A)
        self.meta(B2, archived=True)  # archived before this change / by archive-on-exit
        B.expire_links()
        self.assertEqual(self._members(), [[A, C]])

    def test_archive_leaves_its_team_linked_or_not(self):
        # 🤝 協力 (the deployment notes): an archived helper with no link left
        # (2026-11-27, the user: 協力のアイコンだけ残りました) leaves its team,
        # before the archive answers (the page refreshes right after).
        calls = []
        with tempfile.NamedTemporaryFile() as sock, \
                mock.patch.object(B, "TREE_SOCK", sock.name), \
                mock.patch.object(B, "tree_call", lambda req: calls.append(req) or {"ok": True}):
            B.archive_session(C, True)
            self.assertEqual(calls, [{"op": "team_left", "session": C}])
            B.archive_session(C, True)       # already archived: nothing again
            B.archive_session(C, False)      # restoring does not rejoin
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
