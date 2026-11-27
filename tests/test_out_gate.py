"""Outward actions from the Email box, one card each (the deployment notes,
2026-11-20): aiza reads what `aiza-out` prepared in the box, checks its
hash, shows a card it writes itself, keeps the answer on the host bound to
that hash, and lets it run once. Only fake data.

    python3 -m unittest discover -s tests -v
"""
import email.message
import email.policy
import hashlib
import http.server
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from test_shared_search import B

HERE = Path(__file__).resolve().parent
HOOK = HERE.parent / "bin" / "aiza-gate-hook"
OUT = HERE.parent / "bin" / "aiza-out"
S = "aaaaaaaaaa01"


def write_action(root, oid, action, eml=None):
    d = Path(root) / ".out" / oid
    d.mkdir(parents=True)
    if eml is not None:
        (d / "message.eml").write_bytes(eml)
        action = dict(action, eml="message.eml", eml_sha256=hashlib.sha256(eml).hexdigest())
    raw = json.dumps(dict({"v": 1}, **action), ensure_ascii=False).encode()
    (d / "action.json").write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def mail_bytes(to="tanaka@example.ac.jp, 佐藤 <sato@example.ac.jp>", subject="日程", body="本文です\n二行目", att=None):
    m = email.message.EmailMessage(policy=email.policy.default)
    m["To"], m["Subject"] = to, subject
    m.set_content(body)
    if att:
        m.add_attachment(att, maintype="application", subtype="pdf", filename="資料.pdf")
    return m.as_bytes()


class OutGateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.events, self.told, self.tasks, self.closed = [], [], [], []
        names = ("GATE_DIR", "load_meta", "MAILBOX", "MAIL_PRESETS", "MAIL_TREE_PRESETS", "append_event",
                 "set_task", "send_push_notification", "_out_tell", "ask_close", "sandbox_roots", "ASK_ANSWERS_DIR")
        self.saved = {k: getattr(B, k) for k in names}
        B.GATE_DIR = self.root / "gate"
        B.ASK_ANSWERS_DIR = self.root / "ask-answers"
        B.MAILBOX = {"dir": self.root / "box"}
        (self.root / "box").mkdir()
        B.sandbox_roots = lambda: [self.root / "box"]
        B.MAIL_PRESETS, B.MAIL_TREE_PRESETS = {"mail-tui"}, {"mail-tui", "mail-shell"}
        self.metas = {S: {"preset": "mail-tui"}, "aaaaaaaaaa02": {"preset": "mail-tui"}, "bbbbbbbbbb01": {"preset": "claude-tui"}}
        B.load_meta = lambda sid: self.metas.get(sid)
        B.append_event = lambda sid, ev: self.events.append((sid, ev)) or ev
        B.set_task = lambda sid, task: self.tasks.append((sid, task))
        B.send_push_notification = lambda sid, msg: None
        B._out_tell = lambda sid, text: self.told.append((sid, text))
        B.ask_close = lambda sid, ask, how, text=None: self.closed.append((sid, ask, how, text))
        B._out_mem.clear()
        with B._ask_lock:
            B._ask_open.clear()

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        B._out_mem.clear()
        self.tmp.cleanup()

    def gate(self, op, oid, h=None, sid=S, **kw):
        return B.gate_request(sid, dict({"op": op, "id": oid, "hash": h}, **kw))

    def card(self, oid, h):
        r = self.gate("out-card", oid, h)
        self.assertTrue(r["ok"], r)
        return r["card"]

    def test_mail_card_shows_everything_and_runs_once_after_allow(self):
        eml = mail_bytes(att=b"%PDF-1.4 fake")
        h = write_action(self.root / "box", "o000000000001", {"kind": "mail", "thread": ""}, eml)
        ask = self.card("o000000000001", h)
        ev = self.events[-1][1]
        self.assertEqual((ev["type"], ev["tool"], ev["gate_out"], ev["ask_id"]), ("ask", "メールの送信", "o000000000001", ask))
        self.assertIn("宛先 2 件: tanaka@example.ac.jp, sato@example.ac.jp (佐藤)", ev["summary"])
        self.assertIn("件名: 日程", ev["summary"])
        self.assertIn("資料.pdf(13 バイト)", ev["summary"])
        self.assertNotIn("本文です", ev["summary"])                                  # the text is on the page
        self.assertEqual(self.tasks[-1][1]["state"], "you")
        # not before the answer
        self.assertFalse(self.gate("out-check", "o000000000001", h)["ok"])
        page = B.out_page(S, "o000000000001")
        self.assertEqual(page["mail"]["text"], "本文です\n二行目\n")
        self.assertEqual(page["mail"]["to"], ["tanaka@example.ac.jp", "sato@example.ac.jp (佐藤)"])
        self.assertEqual(B.out_attachment(S, "o000000000001", 0), ("資料.pdf", b"%PDF-1.4 fake"))
        self.assertEqual(B.out_answer(S, "o000000000001", True), "許可")
        self.assertIn("aiza-out run o000000000001", self.told[-1][1])
        with self.assertRaises(LookupError):
            B.out_answer(S, "o000000000001", False)                                  # one answer
        self.assertFalse(self.gate("out-check", "o000000000001", "f" * 64)["ok"])  # another hash
        self.assertTrue(self.gate("out-check", "o000000000001", h)["ok"])
        self.assertFalse(self.gate("out-check", "o000000000001", h)["ok"])        # once
        self.assertTrue(self.gate("out-done", "o000000000001", h, ok=True)["ok"])
        self.assertIn("実行しました", self.events[-1][1]["text"])
        rec = json.loads((B.GATE_DIR / f"{S}.json").read_text())
        self.assertNotIn("本文", json.dumps(rec, ensure_ascii=False))                # the host keeps no content
        self.assertEqual(oct((B.GATE_DIR / f"{S}.json").stat().st_mode & 0o777), "0o600")

    def test_deny_and_cancel(self):
        h = write_action(self.root / "box", "o000000000002", {"kind": "slack", "channel_url": "https://app.slack.com/client/T1/C1", "channel": "#x", "text": "こんにちは"})
        self.card("o000000000002", h)
        self.assertEqual(B.out_answer(S, "o000000000002", False), "拒否")
        self.assertIn("許可しませんでした", self.told[-1][1])
        self.assertFalse(self.gate("out-check", "o000000000002", h)["ok"])
        h3 = write_action(self.root / "box", "o000000000003", {"kind": "discord", "channel_url": "https://discord.com/channels/1/2", "text": "hi"})
        self.card("o000000000003", h3)
        self.assertTrue(self.gate("out-cancel", "o000000000003")["ok"])
        self.assertEqual(self.closed[-1][2], "gone")
        with self.assertRaises(LookupError):
            B.out_answer(S, "o000000000003", True)

    def test_changed_after_the_card_is_not_shown_or_run(self):
        eml = mail_bytes()
        h = write_action(self.root / "box", "o000000000004", {"kind": "mail", "thread": ""}, eml)
        self.card("o000000000004", h)
        B._out_mem.clear()                                                          # as after a restart
        (self.root / "box" / ".out" / "o000000000004" / "message.eml").write_bytes(mail_bytes(to="evil@example.com"))
        page = B.out_page(S, "o000000000004")
        self.assertIn("違う", page["error"])
        self.assertNotIn("mail", page)
        # after a restart, unchanged: read again and shown
        (self.root / "box" / ".out" / "o000000000004" / "message.eml").write_bytes(eml)
        self.assertEqual(B.out_page(S, "o000000000004")["mail"]["subject"], "日程")

    def post_with_file(self, oid, data=b"%PDF-1.4 fake", name="申請書 v2.pdf"):
        d = self.root / "box" / ".out" / oid / "att" / "0"
        d.mkdir(parents=True)
        (d / name).write_bytes(data)
        att = {"name": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "file": f"att/0/{name}"}
        raw = json.dumps({"v": 1, "kind": "discord", "channel_url": "https://discord.com/channels/1/2", "text": "確認をお願いします", "attachments": [att]}, ensure_ascii=False).encode()
        (self.root / "box" / ".out" / oid / "action.json").write_bytes(raw)
        return hashlib.sha256(raw).hexdigest(), d / name

    def test_post_with_attachment_card_page_and_file(self):
        h, f = self.post_with_file("o000000000021")
        self.card("o000000000021", h)
        self.assertIn("添付: 申請書 v2.pdf(13 バイト)", self.events[-1][1]["summary"])
        page = B.out_page(S, "o000000000021")
        self.assertEqual(page["action"]["attachments"][0]["name"], "申請書 v2.pdf")
        self.assertEqual(B.out_attachment(S, "o000000000021", 0), ("申請書 v2.pdf", b"%PDF-1.4 fake"))
        with self.assertRaises(LookupError):
            B.out_attachment(S, "o000000000021", 1)
        # the file changed after the card: not shown, the page says so
        B._out_mem.clear()
        f.write_bytes(b"%PDF-1.4 evil!")
        self.assertIn("添付 申請書 v2.pdf がカードのときと違う", B.out_page(S, "o000000000021")["error"])

    def test_post_attachment_shapes(self):
        for i, bad in enumerate([{"file": "att/0/../../x"}, {"name": "../x", "file": "att/0/../x"}, {"size": -1}, {"sha256": "x"}, {"size": 26 * 1024 * 1024}]):
            att = dict({"name": "a.pdf", "size": 1, "sha256": "a" * 64, "file": "att/0/a.pdf"}, **bad)
            oid = f"o00000000003{i}"
            h = write_action(self.root / "box", oid, {"kind": "discord", "channel_url": "https://discord.com/channels/1/2", "text": "t", "attachments": [att]})
            self.assertIn("形が違う", self.gate("out-card", oid, h)["why"], bad)
        h, _f = self.post_with_file("o000000000039")
        (self.root / "box" / ".out" / "o000000000039" / "att" / "0" / "申請書 v2.pdf").unlink()
        self.assertFalse(self.gate("out-card", "o000000000039", h)["ok"])                   # the file is gone

    def test_slack_thread_reply_on_the_card_and_its_shape(self):
        h = write_action(self.root / "box", "o000000000041", {"kind": "slack", "channel_url": "https://ws.slack.com/archives/C0TESTCHAN1", "channel": "#c", "thread_ts": "1700000000.000100", "text": "t"})
        self.card("o000000000041", h)
        self.assertIn("スレッド 1700000000.000100 への返信", self.events[-1][1]["summary"])
        self.assertEqual(B.out_page(S, "o000000000041")["action"]["thread_ts"], "1700000000.000100")
        for i, (k, ts) in enumerate([("slack", "1700000000"), ("slack", "x.000100"), ("slack", 1700000000.000100), ("discord", "1700000000.000100")]):
            url = "https://ws.slack.com/archives/C1" if k == "slack" else "https://discord.com/channels/1/2"
            h = write_action(self.root / "box", f"o00000000004{i + 2}", {"kind": k, "channel_url": url, "thread_ts": ts, "text": "t"})
            self.assertIn("形が違う", self.gate("out-card", f"o00000000004{i + 2}", h)["why"], (k, ts))

    def test_refuses_bad_shapes_and_places(self):
        self.assertFalse(self.gate("out-card", "o000000000005", "a" * 64)["ok"])            # nothing there
        h = write_action(self.root / "box", "o000000000005", {"kind": "slack", "channel_url": "https://evil.example/x", "text": "t"})
        self.assertIn("形が違う", self.gate("out-card", "o000000000005", h)["why"])
        h = write_action(self.root / "box", "o000000000006", {"kind": "form", "url": "http://x.example/", "fields": [{"selector": "#a", "value": "v"}], "submit": "#s"})
        self.assertFalse(self.gate("out-card", "o000000000006", h)["ok"])                   # not https
        h = write_action(self.root / "box", "o000000000007", {"kind": "calendar"})
        self.assertFalse(self.gate("out-card", "o000000000007", h)["ok"])
        self.assertFalse(self.gate("out-card", "../x", h)["ok"])
        h = write_action(self.root / "box", "o000000000008", {"kind": "discord", "channel_url": "https://discord.com/channels/1/2", "text": "t"})
        self.assertFalse(self.gate("out-card", "o000000000008", h, sid="bbbbbbbbbb01")["ok"])  # not an Email session
        self.assertFalse(self.gate("out-card", "o000000000008", "0" * 64)["ok"])             # another hash
        # a link out of the box is not followed
        d = self.root / "box" / ".out" / "o000000000009"
        d.mkdir()
        (self.root / "secret.json").write_text("{}")
        (d / "action.json").symlink_to(self.root / "secret.json")
        self.assertFalse(self.gate("out-card", "o000000000009", hashlib.sha256(b"{}").hexdigest())["ok"])
        self.assertEqual([e for _s, e in self.events if e.get("type") == "ask"], [])

    def test_one_card_per_id_and_a_few_per_ten_minutes(self):
        n = B.OUT_CARDS_PER_10MIN
        ids = [f"o{0x100 + i:012x}" for i in range(n + 1)]
        hs = [write_action(self.root / "box", oid, {"kind": "discord", "channel_url": "https://discord.com/channels/1/2", "text": str(i)}) for i, oid in enumerate(ids)]
        self.card(ids[0], hs[0])
        self.assertFalse(self.gate("out-card", ids[0], hs[0])["ok"])
        for i in range(1, n):
            self.card(ids[i], hs[i])
        self.assertIn("多すぎる", self.gate("out-card", ids[n], hs[n])["why"])

    def test_answer_is_bound_to_the_host_record_not_the_event(self):
        h = write_action(self.root / "box", "o000000000011", {"kind": "discord", "channel_url": "https://discord.com/channels/1/2", "text": "t"})
        self.card("o000000000011", h)
        ev = dict(self.events[-1][1], gate_out="o000000000011")
        with B._ask_lock:
            B._ask_open[S] = {ev["ask_id"]: ev}
        saved = B._ask_write_status
        B._ask_write_status = lambda *a: None
        try:
            self.assertEqual(B.ask_answer(S, {"ask_id": ev["ask_id"], "answer": {"behavior": "allow"},
                                         "card_hash": B._ask_hash(B._ask_host_card(S, ev["ask_id"]))}), "許可")
        finally:
            B._ask_write_status = saved
        self.assertTrue(self.gate("out-check", "o000000000011", h)["ok"])

    def test_the_card_on_the_page_is_the_hosts_after_a_restart(self):
        # 漏洩対策 N1: the box rewrites its card's line in events.jsonl; the
        # page still shows (and the answer is for) the card aiza made.
        h = write_action(self.root / "box", "o000000000031", {"kind": "discord", "channel_url": "https://discord.com/channels/1/2", "text": "t"})
        ask = self.card("o000000000031", h)
        made = self.events[-1][1]
        with B._ask_lock:
            B._ask_open.clear()
        forged = dict(made, summary="無害な文")
        shown = B._ask_for_page(S, forged)
        self.assertEqual((shown["summary"], shown["gate_out"]), (made["summary"], "o000000000031"))
        saved, saved_write = B._ask_find, B._ask_write_status
        B._ask_find = lambda sid, a: forged if a == ask else None
        B._ask_write_status = lambda *a: None
        try:
            with self.assertRaises(ValueError):
                B.ask_answer(S, {"ask_id": ask, "answer": {"behavior": "allow"},
                                 "card_hash": B._ask_hash({k: v for k, v in forged.items() if k not in B._ASK_EVENT_KEYS})})
            self.assertEqual(B.ask_answer(S, {"ask_id": ask, "answer": {"behavior": "allow"},
                                              "card_hash": shown["card_hash"]}), "許可")
        finally:
            B._ask_find, B._ask_write_status = saved, saved_write
        self.assertTrue(self.gate("out-check", "o000000000031", h)["ok"])

    def test_cards_stay_open_when_the_turn_ends_or_a_prompt_comes(self):
        hs = [write_action(self.root / "box", f"o00000000020{i}", {"kind": "discord", "channel_url": "https://discord.com/channels/1/2", "text": str(i)}) for i in range(3)]
        asks = [self.card(f"o00000000020{i}", hs[i]) for i in range(3)]
        with B._ask_lock:
            B._ask_open[S]["ask-plain"] = {"type": "ask", "ask_id": "ask-plain", "tool": "Bash"}
        self.assertEqual(sorted(B._ask_open_closable(S)), ["ask-plain"])
        self.assertEqual(B.out_answer(S, "o000000000200", True), "許可")
        with B._ask_lock:
            self.assertTrue(all(a in B._ask_open[S] for a in asks[1:]))

    def test_old_ways_are_refused(self):
        for op in ("preview", "check", "card", None):
            r = B.gate_request(S, {"op": op, "draft": {}})
            self.assertFalse(r["ok"])
            self.assertIn("aiza-out", r["why"])


def load_hook():
    loader = importlib.machinery.SourceFileLoader("gate_hook_under_test", str(HOOK))
    m = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    loader.exec_module(m)
    return m


class GateHookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.environ.get("HOME")
        os.environ["HOME"] = self.tmp.name
        self.h = load_hook()

    def tearDown(self):
        os.environ["HOME"] = self.home
        self.tmp.cleanup()

    def bash(self, cmd):
        return self.h.decide({"tool_name": "Bash", "tool_input": {"command": cmd}})

    def test_the_ways_around_the_card_are_refused(self):
        for cmd in ("~/gmail.py send r123 --yes", "python3 ~/gmail.py send r1", "~/gmail.py trash 18a0000000000001",
                    "cd x && ~/gmail.py trash 18a0000000000001 18a0000000000002"):
            out = self.bash(cmd)
            self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny", cmd)
            self.assertIn("aiza-out", out["hookSpecificOutput"]["permissionDecisionReason"])
        self.assertEqual(self.h.decide({"tool_name": "mcp__claude_ai_Gmail__send_message", "tool_input": {}})
                         ["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.h.decide({"tool_name": "mcp__claude_ai_Gmail__trash_thread", "tool_input": {}})
                         ["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_others_pass(self):
        for cmd in ("~/gmail.py trash 18a0000000000001 --undo", "~/gmail.py draft --to a@b --subject x",
                    "aiza-out mail --to a@b --subject x --body-file b.txt", "aiza-out run o000000000001",
                    "talkto <<'EOF'\ngmail.py send r1 --yes\nEOF"):
            self.assertIsNone(self.bash(cmd), cmd)
        self.assertIsNone(self.h.decide({"tool_name": "mcp__claude_ai_Gmail__create_draft", "tool_input": {}}))


class FakeAiza:
    """The box's gate listener, answering from a dict."""
    def __init__(self, answers):
        self.got, outer = [], self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.got.append(body)
                data = json.dumps(answers.get(body.get("op"), {"ok": False, "why": "no"})).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}/gate"

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


class AizaOutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "s" / S).mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_out(self, aiza, *args):
        env = dict(os.environ, HOME=str(self.root), AIZA_GATE_URL=aiza.url, AIZA_TALKTO=str(self.root / "s" / S / "talkto"),
                   AIZA_OUT_DIR=str(self.root / ".out"), AIZA_OUT_GMAIL="/bin/false", CDP_PORT="9")
        return subprocess.run(["node", str(OUT), *args], env=env, capture_output=True, text=True, timeout=60)

    def test_prepare_asks_for_a_card_with_the_hash_of_what_it_wrote(self):
        aiza = FakeAiza({"out-card": {"ok": True, "card": "ask-1"}})
        try:
            (self.root / "t.txt").write_text("こんにちは\n二行目")
            r = self.run_out(aiza, "discord", "--channel-url", "https://discord.com/channels/1/2", "--channel", "#test", "--text-file", str(self.root / "t.txt"))
            self.assertEqual(r.returncode, 0, r.stderr)
            [card] = aiza.got
            self.assertEqual((card["op"], card["session"]), ("out-card", S))
            raw = (self.root / ".out" / card["id"] / "action.json").read_bytes()
            self.assertEqual(card["hash"], hashlib.sha256(raw).hexdigest())
            a = json.loads(raw)
            self.assertEqual((a["kind"], a["text"], a["channel"]), ("discord", "こんにちは\n二行目", "#test"))
            self.assertIn(f"aiza-out run {card['id']}", r.stdout)
        finally:
            aiza.close()

    def test_run_does_nothing_without_the_gate_s_yes(self):
        aiza = FakeAiza({"out-card": {"ok": True}, "out-check": {"ok": False, "why": "本人が許可していない", "final": True}})
        try:
            (self.root / "t.txt").write_text("x")
            self.run_out(aiza, "slack", "--channel-url", "https://app.slack.com/client/T1/C1", "--text-file", str(self.root / "t.txt"))
            oid = aiza.got[0]["id"]
            r = self.run_out(aiza, "run", oid)
            self.assertEqual(r.returncode, 1)
            self.assertIn("本人が許可していない", r.stderr)
            self.assertEqual([g["op"] for g in aiza.got], ["out-card", "out-check"])        # no out-done: nothing ran
        finally:
            aiza.close()

    def test_attach_copies_the_file_binds_it_and_run_checks_it(self):
        aiza = FakeAiza({"out-card": {"ok": True}, "out-check": {"ok": False, "why": "本人が許可していない", "final": True}})
        try:
            (self.root / "t.txt").write_text("確認をお願いします")
            (self.root / "申請書.pdf").write_bytes(b"%PDF-1.4 x")
            r = self.run_out(aiza, "discord", "--channel-url", "https://discord.com/channels/1/2", "--text-file", str(self.root / "t.txt"),
                             "--attach", str(self.root / "申請書.pdf"))
            self.assertEqual(r.returncode, 0, r.stderr)
            oid = aiza.got[0]["id"]
            d = self.root / ".out" / oid
            a = json.loads((d / "action.json").read_bytes())
            self.assertEqual(a["attachments"], [{"name": "申請書.pdf", "size": 10, "sha256": hashlib.sha256(b"%PDF-1.4 x").hexdigest(), "file": "att/0/申請書.pdf"}])
            self.assertEqual((d / "att" / "0" / "申請書.pdf").read_bytes(), b"%PDF-1.4 x")
            B.out_validate(a)                                                                # the shape aiza takes
            (self.root / "申請書.pdf").write_bytes(b"changed")                               # the original may change: the copy is sent
            (d / "att" / "0" / "申請書.pdf").write_bytes(b"%PDF-1.4 y")                     # the copy changed: not run, not even asked
            r = self.run_out(aiza, "run", oid)
            self.assertEqual(r.returncode, 1)
            self.assertIn("カードのときと違う", r.stderr)
            self.assertEqual([g["op"] for g in aiza.got], ["out-card"])
            # a missing file or too many: nothing prepared
            r = self.run_out(aiza, "discord", "--channel-url", "https://discord.com/channels/1/2", "--text-file", str(self.root / "t.txt"), "--attach", str(self.root / "none.pdf"))
            self.assertEqual(r.returncode, 2)
            self.assertEqual(len(list((self.root / ".out").iterdir())), 1)
        finally:
            aiza.close()

    def test_slack_thread_from_the_option_or_the_url(self):
        aiza = FakeAiza({"out-card": {"ok": True}})
        try:
            (self.root / "t.txt").write_text("x")
            t = str(self.root / "t.txt")
            ok = [(["--channel-url", "https://ws.slack.com/archives/C0TESTCHAN1", "--thread-ts", "1700000000.000100"], "1700000000.000100"),
                  (["--channel-url", "https://ws.slack.com/archives/C0TESTCHAN1/p1700000090000200?thread_ts=1700000000.000100&cid=C0TESTCHAN1"], "1700000000.000100"),
                  (["--channel-url", "https://ws.slack.com/archives/C0TESTCHAN1/p1700000000000100"], "1700000000.000100"),
                  (["--channel-url", "https://app.slack.com/client/E01/C0TESTCHAN1/thread/C0TESTCHAN1-1700000000.000100"], "1700000000.000100"),
                  (["--channel-url", "https://ws.slack.com/archives/C0TESTCHAN1"], None)]
            for args, ts in ok:
                r = self.run_out(aiza, "slack", *args, "--text-file", t)
                self.assertEqual(r.returncode, 0, r.stderr)
                a = json.loads((self.root / ".out" / aiza.got[-1]["id"] / "action.json").read_bytes())
                self.assertEqual(a.get("thread_ts"), ts, args)
                self.assertEqual(a["channel_url"], args[1])
                B.out_validate(a)
            n = len(aiza.got)
            for kind, args in [("slack", ["--channel-url", "https://ws.slack.com/archives/C1/p1700000000000100", "--thread-ts", "1700000000.000001"]),
                               ("slack", ["--channel-url", "https://ws.slack.com/archives/C1", "--thread-ts", "1700000000"]),
                               ("slack", ["--channel-url", "https://app.slack.com/client/T1", "--thread-ts", "1700000000.000100"]),
                               ("discord", ["--channel-url", "https://discord.com/channels/1/2", "--thread-ts", "1700000000.000100"])]:
                r = self.run_out(aiza, kind, *args, "--text-file", t)
                self.assertEqual(r.returncode, 2, (args, r.stderr))
            self.assertEqual(len(aiza.got), n)                                               # nothing prepared
        finally:
            aiza.close()

    def test_card_refused_is_an_error(self):
        aiza = FakeAiza({"out-card": {"ok": False, "why": "カードが多すぎる"}})
        try:
            (self.root / "t.txt").write_text("x")
            r = self.run_out(aiza, "discord", "--channel-url", "https://discord.com/channels/1/2", "--text-file", str(self.root / "t.txt"))
            self.assertEqual(r.returncode, 1)
            self.assertIn("カードが多すぎる", r.stderr)
        finally:
            aiza.close()


if __name__ == "__main__":
    unittest.main()
