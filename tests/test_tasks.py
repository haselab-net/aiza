"""The to-do list (the deployment notes, 2026-11-07): Claude's 「状態:」 line read from
the Stop hook's input; only what needs the user pushes; a session archived
right after its Stop stays quiet; 寝かせ comes back when its date comes.

    python3 -m unittest discover -s tests -v
"""
import datetime
import json
import tempfile
import time
import unittest
from pathlib import Path

from test_shared_search import B


def ts(y, mo, d, h=0, mi=0):
    return datetime.datetime(y, mo, d, h, mi).timestamp()


class ParseTest(unittest.TestCase):
    NOW = ts(2026, 11, 7, 15, 0)

    def p(self, text):
        return B.parse_task_line(text, self.NOW)

    def test_states(self):
        self.assertEqual(self.p("本文\n\n状態: 要判断 — 返信案AかBか"), {"state": "you", "text": "返信案AかBか"})
        self.assertEqual(self.p("状態：済み：図を直した"), {"state": "done", "text": "図を直した"})
        self.assertEqual(self.p("**状態:** 済み — 太字でも"), {"state": "done", "text": "太字でも"})

    def test_none(self):
        self.assertIsNone(self.p("ただの返事です"))
        self.assertIsNone(self.p("状態: 要判断 — 古い\nあ\nい\nう"))  # only the last lines count
        self.assertIsNone(self.p(""))

    def test_snooze_dates(self):
        r = self.p("状態: 寝かせ 11/12 15:30 — Bさんの返事待ち")
        self.assertEqual(r, {"state": "snooze", "until": ts(2026, 11, 12, 15, 30), "text": "Bさんの返事待ち"})
        self.assertEqual(self.p("状態: 寝かせ 11/12 — x")["until"], ts(2026, 11, 12, 9, 0))
        self.assertEqual(self.p("状態: 寝かせ 1/5 — 年明け")["until"], ts(2027, 1, 5, 9, 0))
        self.assertEqual(self.p("状態: 寝かせ — 日付なし")["until"], ts(2026, 11, 8, 9, 0))
        self.assertEqual(self.p("状態: 寝かせ 13/40 — 変な日付")["until"], ts(2026, 11, 8, 9, 0))

    def test_text_capped(self):
        self.assertEqual(len(self.p("状態: 要判断 — " + "あ" * 200)["text"]), B.TASK_TEXT_MAX)


class TaskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.pushes = []
        self.timers = []
        self.saved = {n: getattr(B, n) for n in ("session_dir", "iter_session_dirs", "send_push_notification",
                                                 "stop_session", "TASK_DECIDE_DELAY",
                                                 "_session_busy_in_background", "TASK_PUSH_DELAY",
                                                 "send_push_payload")}
        self.busy = set()
        B._session_busy_in_background = lambda sid, meta, now: sid in self.busy
        B.session_dir = lambda sid: self.root / sid
        B.iter_session_dirs = lambda: sorted(p for p in self.root.iterdir() if p.is_dir())
        B.send_push_notification = lambda sid, msg: self.pushes.append((sid, msg))
        self.stopped = []
        B.stop_session = lambda sid: self.stopped.append(sid)
        B.TASK_DECIDE_DELAY = 0.01
        B.TASK_PUSH_DELAY = 0.01
        self.payloads = []
        B.send_push_payload = lambda payload: self.payloads.append(payload)
        B._task_pushed.clear()
        B._task_recent.clear()

    def tearDown(self):
        for n, v in self.saved.items():
            setattr(B, n, v)
        self.tmp.cleanup()

    def sess(self, sid, **kw):
        d = self.root / sid
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"id": sid, "label": "L-" + sid, **kw}))
        return d

    def stop(self, sid, text):
        B.task_hook(sid, {"hook_event_name": "Stop", "last_assistant_message": text})
        time.sleep(0.15)

    def test_decision_pushes_done_does_not(self):
        self.sess("a1")
        self.stop("a1", "結果です\n状態: 要判断 — どちらで送るか")
        self.assertEqual(self.pushes, [("a1", "要判断: どちらで送るか")])
        self.assertEqual(B.load_task("a1")["state"], "you")
        self.stop("a1", "直しました\n状態: 済み — 図の修正")
        self.assertEqual(len(self.pushes), 1)
        t = B.load_task("a1")
        self.assertEqual((t["state"], t["text"], t["seen"]), ("done", "図の修正", False))

    def test_undeclared_stop_pushes_without_content(self):
        self.sess("a2")
        self.stop("a2", "秘密の本文")
        self.assertEqual(self.pushes, [("a2", "止まりました(状態の申告なし)")])
        self.assertEqual(B.load_task("a2")["declared"], False)

    def test_same_stop_from_both_routes_once(self):
        self.sess("a3")
        B.task_hook("a3", {"hook_event_name": "Stop", "last_assistant_message": "状態: 要判断 — x"})
        self.stop("a3", "状態: 要判断 — x")
        self.assertEqual(len(self.pushes), 1)

    def test_archived_right_after_stop_is_quiet(self):
        d = self.sess("a4")
        (d / B.ARCHIVE_ON_EXIT).write_text("")
        self.stop("a4", "状態: 済み — 既決にした")
        self.stop("a4", "状態: 要判断 — 送信の確認")
        self.assertEqual(self.pushes, [])
        self.assertEqual(B.load_task("a4")["seen"], True)

    def test_user_reply_wins_over_late_decision(self):
        self.sess("a5")
        B.task_hook("a5", {"hook_event_name": "Stop", "last_assistant_message": "状態: 要判断 — x"})
        B.task_user_sent("a5")
        time.sleep(0.15)
        self.assertEqual(B.load_task("a5")["state"], "working")
        self.assertEqual(self.pushes, [])

    def test_notifications(self):
        self.sess("a6")
        B.task_hook("a6", {"hook_event_name": "Notification", "notification_type": "idle_prompt",
                           "message": "Claude is waiting for your input"})
        self.assertEqual(self.pushes, [])
        B.task_hook("a6", {"hook_event_name": "Notification", "notification_type": "permission_prompt",
                           "message": "Claude needs your permission to use Bash"})
        time.sleep(0.1)
        self.assertEqual(self.pushes, [("a6", "Claude needs your permission to use Bash")])
        self.assertEqual(B.load_task("a6")["state"], "you")

    def test_push_waits_and_skips_a_turn_already_looked_at(self):
        # the deployment notes: nothing at once; seen within the wait, nothing at all.
        B.TASK_PUSH_DELAY = 0.3
        self.sess("p1")
        self.sess("p2")
        B.task_hook("p1", {"hook_event_name": "Stop", "last_assistant_message": "状態: 要判断 — x"})
        B.task_hook("p2", {"hook_event_name": "Stop", "last_assistant_message": "状態: 要判断 — y"})
        time.sleep(0.1)
        self.assertEqual(self.pushes, [])
        B.task_update("p1", {"seen": True})
        time.sleep(0.4)
        self.assertEqual(self.pushes, [("p2", "要判断: y")])
        self.assertEqual(self.payloads, [])

    def test_push_taken_back_once_the_turn_moves_or_is_seen(self):
        B.send_push_notification = lambda sid, msg: (self.pushes.append((sid, msg)), True)[1]
        for sid in ("r1", "r2", "r3"):
            self.sess(sid)
            B.task_hook(sid, {"hook_event_name": "Stop", "last_assistant_message": f"状態: 要判断 — {sid}"})
        time.sleep(0.15)
        self.assertEqual(len(self.pushes), 3)
        B.task_update("r1", {"seen": True})     # looked at on another device
        B.task_user_sent("r2")                  # answered
        time.sleep(0.05)
        self.assertEqual(sorted(p["close"] for p in self.payloads), ["r1", "r2"])
        B.task_user_sent("r1")                  # taken back once only
        time.sleep(0.05)
        self.assertEqual(len(self.payloads), 2)

    def test_snooze_fires_once_and_stops_devbox_session(self):
        self.sess("b1", tmux_location="container", preset="claude-tui")
        self.sess("b2", tmux_location="host", preset="claude-tui")
        self.sess("b3", tmux_location="container", preset="claude-tui")
        now = time.time()
        B.save_task("b1", {"state": "snooze", "until": now - 5, "ts": now - 7200, "text": "期限"})
        B.save_task("b2", {"state": "snooze", "until": now + 86400, "ts": now - 7200, "text": "ホスト"})
        B.save_task("b3", {"state": "snooze", "until": now + 86400, "ts": now - 7200, "text": "devbox"})
        B._task_check_once()
        B._task_check_once()
        self.assertEqual(self.pushes, [("b1", "寝かせの期限: 期限")])
        self.assertEqual(self.stopped, ["b3"])  # not the host one (passkey), not the due one
        self.assertTrue(B.load_task("b3")["auto_stopped"])

    def test_snooze_date_wakes_the_session_itself(self):
        # 2026-11-22, the user: 自分でタイマーを仕掛けるやつは危ない…クーロンで
        # 起こすように. A 寝かせ the agent wrote: aiza resumes it if stopped and
        # tells it; no push (its reply's state line decides). Set by hand, a
        # root shell, or one that cannot be told: the old push.
        names = ("_wake_for_talkto", "send_message", "_wait_prompt", "task_user_sent")
        saved = {n: getattr(B, n) for n in names}
        self.addCleanup(lambda: [setattr(B, n, v) for n, v in saved.items()])
        sent, woke = [], []
        B._wake_for_talkto = lambda sid, meta: woke.append(sid) or "n" + sid
        B._wait_prompt = lambda sid: True
        B.task_user_sent = lambda sid: None
        def send(sid, text, submit=True, from_user=None):
            if sid == "w5":
                raise B.UnlockRequired("closed", tier="host")
            sent.append((sid, from_user, text))
        B.send_message = send
        self.sess("w1", tmux_location="container", preset="claude-tui")
        self.sess("w2", tmux_location="container", preset="claude-tui", stopped=True)
        self.sess("w3", tmux_location="container", preset="claude-tui")
        self.sess("w4", tmux_location="root", preset="root-shell")
        self.sess("w5", tmux_location="container", preset="claude-tui")  # sending fails
        now = time.time()
        for sid in ("w1", "w2", "w4", "w5"):
            B.save_task(sid, {"state": "snooze", "until": now - 5, "ts": now - 7200, "text": "返事", "declared": True})
        B.save_task("w3", {"state": "snooze", "until": now - 5, "ts": now - 7200, "text": "手で", "by_hand": True})
        B._task_check_once()
        time.sleep(0.3)
        B._task_check_once()
        time.sleep(0.3)
        self.assertEqual(woke, ["w2"])
        self.assertEqual(sorted(s for s, _, _ in sent), ["nw2", "w1"])
        self.assertTrue(all(f == "⏰ AI座" and "「返事」" in t for _, f, t in sent))
        self.assertEqual(sorted(self.pushes), [("w3", "寝かせの期限: 手で"), ("w4", "寝かせの期限: 返事"),
                                               ("w5", "寝かせの期限: 返事")])

    def test_done_stops_devbox_session_soon(self):
        # 2026-11-18, the user: "済になったらセッションを停止するわけには行きませんか？",
        # then "30分待つ必要が無い" -- at the next check once a minute has passed,
        # but not while something still runs under it ("２は見るように").
        self.sess("d1", tmux_location="container", preset="claude-tui")
        self.sess("d2", tmux_location="container", preset="claude-tui")
        self.sess("d3", tmux_location="host", preset="claude-tui")
        self.sess("d4", tmux_location="container", preset="claude-tui")
        self.sess("d5", tmux_location="container", preset="claude-tui")
        now = time.time()
        B.save_task("d1", {"state": "done", "ts": now - 90, "text": "済んだ"})
        B.save_task("d2", {"state": "done", "ts": now - 10, "text": "済んだばかり"})
        B.save_task("d3", {"state": "done", "ts": now - 7200, "text": "ホスト"})
        B.save_task("d4", {"state": "done", "ts": now - 7200, "text": "裏で動いている"})
        B.save_task("d5", {"state": "snooze", "until": now + 86400, "ts": now - 90, "text": "寝かせは30分"})
        self.busy.add("d4")
        B._task_check_once()
        B._task_check_once()
        self.assertEqual(self.stopped, ["d1"])
        self.busy.clear()
        B._task_check_once()
        self.assertEqual(self.stopped, ["d1", "d4"])
        self.assertEqual(self.pushes, [])
        self.assertTrue(B.load_task("d1")["auto_stopped"])

    def test_update_by_hand(self):
        self.sess("c1")
        now = time.time()
        self.assertEqual(B.task_update("c1", {"state": "snooze", "until": now + 3600})["until"], now + 3600)
        with self.assertRaises(ValueError):
            B.task_update("c1", {"state": "snooze", "until": now - 10})
        with self.assertRaises(ValueError):
            B.task_update("c1", {"state": "bogus"})
        self.assertEqual(B.task_update("c1", {"state": "done"})["state"], "done")
        B.save_task("c1", dict(B.load_task("c1"), seen=False))
        self.assertTrue(B.task_update("c1", {"seen": True})["seen"])
        self.assertIsNone(B.task_update("c1", {"state": None}))
        self.assertIsNone(B.load_task("c1"))

    def test_restore_after_check(self):
        # The list's 8-second "元に戻す" after ✓ puts the task back as it was.
        self.sess("c2")
        old = {"state": "you", "text": "見て", "ts": 123.0, "declared": True, "seen": False, "prompt": True}
        B.save_task("c2", dict(old))
        B.task_update("c2", {"state": "done"})
        self.assertEqual(B.task_update("c2", {"restore": dict(old, junk="x")}), old)
        self.assertEqual(B.load_task("c2"), old)
        self.assertIsNone(B.task_update("c2", {"restore": None}))
        with self.assertRaises(ValueError):
            B.task_update("c2", {"restore": {"state": "bogus"}})

    def test_new_turn_in_log_means_working(self):
        # 済み, then a turn typed anywhere (terminal, talkto, the box): working.
        self.sess("c3")
        B.save_task("c3", {"state": "done", "text": "直した", "ts": 1000.0, "declared": True, "seen": True})
        def line(content, t="2026-11-10T12:00:00.000Z", **kw):
            return json.dumps(dict({"type": "user", "timestamp": t, "message": {"role": "user", "content": content}}, **kw)).encode() + b"\n"
        for skip in (line([{"type": "tool_result", "content": "x"}]), line("<command-name>/clear</command-name>"),
                     line("要約", isCompactSummary=True), line("x", isMeta=True)):
            B._split_assistant_text_events(skip, "c3")
            self.assertEqual(B.load_task("c3")["state"], "done")
        B._split_assistant_text_events(line("続きをお願い"), "c3")
        self.assertEqual(B.load_task("c3")["state"], "working")
        # An older turn (a log read from the start) changes nothing.
        B.save_task("c3", {"state": "done", "text": "", "ts": 2e9, "seen": True})
        B._split_assistant_text_events(line([{"type": "text", "text": "昔の"}]), "c3")
        self.assertEqual(B.load_task("c3")["state"], "done")

    def test_queued_message_moves_after_the_reply(self):
        # Sent while Claude was still answering: written again after that answer.
        self.sess("c4")
        B._pending_user.pop("c4", None)
        B._last_agent_seq.pop("c4", None)
        def line(kind, content, t="2026-11-11T06:05:38.000Z"):
            return json.dumps({"type": kind, "timestamp": t, "message": {"role": kind, "content": content}}).encode() + b"\n"
        sent = {"seq": 10, "ts": 1.0, "type": "user_message", "text": "#9 から:\n  GPU を起こして", "from": "🔗 x"}
        B._note_pending_user("c4", sent)
        buf = (line("assistant", [{"type": "text", "text": "つながりました"}])
               + line("user", '<pasted_content id="1">\n#9 から:\nGPU を起こして\n</pasted_content>'))
        _, events = B._split_assistant_text_events(buf, "c4")
        self.assertEqual([e["type"] for e in events], ["agent_output", "user_message"])
        self.assertEqual(events[1]["moved_from"], 10)
        self.assertEqual(events[1]["from"], "🔗 x")
        self.assertNotIn("seq", events[1])
        # Taken at once (nothing from Claude in between): left where it is.
        B._note_pending_user("c4", dict(sent, seq=20))
        _, events = B._split_assistant_text_events(line("user", "#9 から: GPU を起こして"), "c4")
        self.assertEqual(events, [])
        self.assertEqual(B._pending_user["c4"], [])

    def test_queued_message_taken_mid_turn(self):
        # Handed into the running turn: only the queue line's "remove" shows it.
        self.sess("c5")
        B._pending_user.pop("c5", None)
        B._last_agent_seq["c5"] = 30
        B._note_pending_user("c5", {"seq": 25, "ts": 1.0, "type": "user_message", "text": "人が判断する段階を入れられますか？"})
        q = json.dumps({"type": "queue-operation", "operation": "remove", "timestamp": "2026-11-11T07:59:59.799Z",
                        "content": "人が判断する段階を入れられますか？"}).encode() + b"\n"
        _, events = B._split_assistant_text_events(q, "c5")
        self.assertEqual([(e["type"], e.get("moved_from")) for e in events], [("user_message", 25)])
        self.assertEqual(B._pending_user["c5"], [])
        # "enqueue" is not taking it.
        B._note_pending_user("c5", {"seq": 40, "ts": 1.0, "type": "user_message", "text": "次"})
        B._split_assistant_text_events(json.dumps({"type": "queue-operation", "operation": "enqueue", "content": "次"}).encode() + b"\n", "c5")
        self.assertEqual(len(B._pending_user["c5"]), 1)

    def test_taken_upto(self):
        # Told to a page whose stream (re)opens: up to just before the oldest still waiting.
        self.sess("c6")
        B._pending_user.pop("c6", None)
        with B._seq_lock:
            B._next_seq["c6"] = 51
        self.assertEqual(B._taken_upto("c6"), 50)
        B._note_pending_user("c6", {"seq": 42, "ts": time.time(), "type": "user_message", "text": "a"})
        B._note_pending_user("c6", {"seq": 45, "ts": time.time(), "type": "user_message", "text": "b"})
        self.assertEqual(B._taken_upto("c6"), 41)
        # Taken in place: pushed with "taken", never "seq" (a seq is dropped as a duplicate).
        got = []
        orig = B.push_ephemeral
        B.push_ephemeral = lambda sid, ev: got.append(ev)
        try:
            B._split_assistant_text_events(json.dumps({"type": "user", "timestamp": "2026-11-12T00:00:00.000Z",
                                                       "message": {"role": "user", "content": "a"}}).encode() + b"\n", "c6")
        finally:
            B.push_ephemeral = orig
        self.assertEqual(got, [{"type": "user_taken", "taken": 42}])
        self.assertEqual(B._taken_upto("c6"), 44)

    def test_talkto_line(self):
        line = json.dumps({"task": {"hook_event_name": "Stop", "last_assistant_message": "x"}}).encode()
        self.assertEqual(B._parse_talkto_lines([line]),
                         [(None, ("task", {"hook_event_name": "Stop", "last_assistant_message": "x"}))])


if __name__ == "__main__":
    unittest.main()
