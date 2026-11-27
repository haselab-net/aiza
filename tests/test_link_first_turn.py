"""A session link's notice to a Claude/Codex session nothing has been sent to
yet (the deployment notes): held back and put before its first real turn,
not sent as a turn of its own. 2026-11-24 a new root Claude whose first
input was that notice alone (no task in it) made up a user's request and
repeated itself for an hour (the user: 空回りの直しをお願い).

    python3 -m unittest discover -s tests -v
"""
import json
import unittest

import test_link_groups as G
from test_link_groups import A, B2, C, D
from test_shared_search import B

NOTICE = "[AI座 セッション連携]"


class LinkFirstTurnTest(unittest.TestCase):
    # the same stand-ins as the link tests (not their tests: unittest would run them here again)
    meta, had_a_turn, fresh, tearDown = G.LinkGroupTest.meta, G.LinkGroupTest.had_a_turn, G.LinkGroupTest.fresh, G.LinkGroupTest.tearDown

    def setUp(self):
        G.LinkGroupTest.setUp(self)
        self.real_send = self.saved["send_message"]
        self.typed = []
        saved = {n: getattr(B, n) for n in ("tmux_exec_text", "tmux_exec", "require_unlock_if_outside_sandbox",
                                            "_start_stuck_input_check", "_note_pending_user", "_codex_takes_paste")}
        self.addCleanup(lambda: [setattr(B, n, v) for n, v in saved.items()])
        ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        B.tmux_exec_text = lambda loc, args, text: (self.typed.append(text), ok)[1]
        B.tmux_exec = lambda loc, args: ok
        B.require_unlock_if_outside_sandbox = lambda loc: None
        B._start_stuck_input_check = lambda *a: None
        B._note_pending_user = lambda *a: None
        B._codex_takes_paste = lambda sid, meta: False

    def send(self, sid, text, submit=True):
        """What aiza's send does to the pane (the real send_message)."""
        self.typed.clear()
        self.real_send(sid, text, submit=submit)
        return self.typed[0] if self.typed else None

    def links(self):
        return json.loads(B.LINKS_PATH.read_text())

    def test_a_fresh_session_is_not_sent_a_turn_of_its_own(self):
        self.fresh(C, preset="root-shell", launch="claude", tmux_location="root")
        B.create_link(A, C, forever=True)
        self.assertEqual([s for s, _ in self.sent], [A])              # the other one is told now
        self.assertIn("`talkto`", self.sent[0][1])
        rec = next(iter(self.links().values()))
        self.assertEqual(rec["unprimed"], [C])
        self.assertTrue(any(s == C and "つなぎました" in ev["text"] for s, ev in self.events))   # the chat says so

    def test_its_first_turn_carries_the_notice_once(self):
        self.fresh(C)
        B.create_link(A, C, forever=True)
        first = self.send(C, "6〜8 をお願いします")
        self.assertTrue(first.startswith(NOTICE), first)
        self.assertIn("`talkto`", first)
        self.assertTrue(first.endswith("\n\n6〜8 をお願いします"))
        self.assertEqual([ev["text"] for s, ev in self.events if s == C and ev["type"] == "user_message"], [first])
        self.assertEqual(self.send(C, "次"), "次")                      # once
        self.assertNotIn("unprimed", next(iter(self.links().values())))

    def test_a_talkto_is_a_first_turn_too(self):
        # the case of 2026-11-24: the request came by talkto, 20 minutes later
        self.fresh(C, preset="root-shell", launch="claude", tmux_location="root")
        B.create_link(A, C, forever=True)
        B.send_message = self.real_send
        status, _ = B._relay_to_partner(A, B.TalktoText("はじめまして"))
        self.assertEqual(status, "delivered")
        self.assertTrue(self.typed[0].startswith(NOTICE))
        self.assertTrue(self.typed[0].endswith("\n\nはじめまして"))

    def test_commands_and_unsent_text_do_not_take_it(self):
        self.fresh(C)
        B.create_link(A, C, forever=True)
        self.assertEqual(self.send(C, "/model"), "/model")
        self.assertEqual(self.send(C, "下書き", submit=False), "下書き")
        self.assertTrue(self.send(C, "本題").startswith(NOTICE))

    def test_a_shell_and_a_session_with_turns_are_told_now(self):
        self.fresh(C, preset="shell")                                 # no Claude/Codex in it
        self.fresh(D, preset="codex-tui")
        B.create_link(A, B2, forever=True)                            # both have had turns
        self.assertEqual(sorted(s for s, _ in self.sent), [A, B2])
        self.sent.clear()
        B.create_link(C, A)
        self.assertEqual(sorted(s for s, _ in self.sent), [C])        # those already there get no turn (2026-11-25)
        self.sent.clear()
        B.create_link(D, A)                                           # a fresh Codex joins
        self.assertEqual(self.sent, [])
        self.assertEqual(next(iter(self.links().values()))["unprimed"], [D])

    def test_one_holding_it_back_is_not_told_of_newcomers_and_hears_everyone(self):
        self.fresh(C)
        B.create_link(A, C)
        self.sent.clear()
        B.create_link(B2, A)                                          # B2 joins
        self.assertEqual(sorted(s for s, _ in self.sent), [B2])       # not A, not C
        first = self.send(C, "x")
        self.assertTrue(first.startswith("[AI座 セッション連携] 他のAIと`talkto`コマンドで通信できます。"), first)

    def test_kept_when_resumed_under_a_new_id(self):
        self.fresh(C)
        B.create_link(A, C)
        new = "aaaaaaaaaaa9"
        (self.root / new).mkdir()
        self.fresh(new, label="devbox")
        B.link_replace_member(C, new)
        self.assertEqual(next(iter(self.links().values()))["unprimed"], [new])
        self.assertIsNone(B.link_resumed_note(new))                   # nothing to tell on resume itself
        self.assertTrue(self.send(new, "x").startswith(NOTICE))

    def test_a_session_left_unlinked_is_sent_nothing_extra(self):
        self.fresh(C)
        B.create_link(A, C)
        B.break_link(C)
        self.assertEqual(self.send(C, "x"), "x")


if __name__ == "__main__":
    unittest.main()
