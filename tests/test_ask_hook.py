"""Questions and permission prompts answered from the page: aiza-ask-hook and
the backend's ask_hook / ask_answer / ask_close.

    python3 -m unittest discover -s tests -v
"""
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_shared_search import B

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "bin" / "aiza-ask-hook"
CONV = "0e000000-0000-4000-8000-000000000000"


def load_hook():
    loader = importlib.machinery.SourceFileLoader("aiza_ask_hook", str(HOOK))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("aiza_ask_hook", loader))
    loader.exec_module(mod)
    return mod


H = load_hook()

QUESTION = {"questions": [{"question": "Tea or coffee?", "header": "Drink", "multiSelect": False,
                           "options": [{"label": "Tea", "description": "hot"}, {"label": "Coffee"}]}]}

def page_answer(sid, body):
    """ask_answer as the page calls it: with the hash of the card it was
    given (_ask_for_page), when aiza holds the card."""
    card = B._ask_host_card(sid, body.get("ask_id"))
    if card is not None and "card_hash" not in body:
        body = dict(body, card_hash=B._ask_hash(card))
    return B.ask_answer(sid, body)



class BackendAskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sid = "aaaaaaaaaa01"
        (self.root / self.sid).mkdir()
        (self.root / self.sid / "meta.json").write_text(json.dumps({"id": self.sid, "claude_session_id": CONV}))
        self.pushes, self.tasks = [], []
        self.saved = {k: getattr(B, k) for k in ("session_dir", "send_push_notification", "set_task", "_ask_open",
                                                 "ASK_ORDER_WAIT", "_task_push_later", "ASK_ANSWERS_DIR", "_ask_seen")}
        B._ask_seen = {}
        B.ASK_ANSWERS_DIR = self.root / "ask-answers"
        B.ASK_ORDER_WAIT = 0.2
        B.session_dir = lambda sid: self.root / sid
        B.send_push_notification = lambda sid, msg: self.pushes.append(msg)
        B._task_push_later = lambda sid, msg, ts: self.pushes.append(msg)   # its wait: test_tasks
        B.set_task = lambda sid, task, **kw: self.tasks.append(task["state"])
        B._ask_open = {}
        B._next_seq.pop(self.sid, None)
        self.talkto = str(self.root / self.sid / B.TALKTO_FILENAME)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        B._next_seq.pop(self.sid, None)
        self.tmp.cleanup()

    def events(self):
        p = self.root / self.sid / "events.jsonl"
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def status(self):
        p = self.root / self.sid / B.TALKTO_STATUS_FILENAME
        return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []

    def ask(self, kind="question", **extra):
        body = {"kind": kind, "tool": "AskUserQuestion" if kind == "question" else "Bash",
                "terminal": True, "session_id": CONV, "pane": True}
        body.update(QUESTION if kind == "question" else {"summary": "rm -rf build", "can_session": True})
        body.update(extra)
        B.ask_hook(self.sid, self.talkto, "ask-1", body)
        return body

    def test_card_follows_the_reply_text(self):
        # The hook came before the tailer had shown the text above the
        # question: the card waits for the tool line, so it lands below.
        import threading
        B.ASK_ORDER_WAIT = 3.0

        def tailer():
            time.sleep(0.4)
            B.append_event(self.sid, {"type": "agent_output", "text": "説明"})
            B.append_event(self.sid, {"type": "tool", "text": "AskUserQuestion"})
        th = threading.Thread(target=tailer)
        th.start()
        self.ask()
        th.join()
        self.assertEqual([e["type"] for e in self.events()], ["agent_output", "tool", "ask"])

    def test_parse_lines(self):
        lines = [json.dumps({"id": "ask-1", "ask": {"kind": "question"}}).encode(),
                 json.dumps({"ask_done": "ask-1", "how": "terminal"}).encode(),
                 json.dumps({"id": "../bad", "ask": {}}).encode()]
        got = B._parse_talkto_lines(lines)
        self.assertEqual([(i, k) for i, (k, _) in got], [("ask-1", "ask"), (None, "ask_done")])

    def test_question_shown_listed_and_notified(self):
        self.ask()
        [ev] = self.events()
        self.assertEqual((ev["type"], ev["ask_id"], ev["questions"][0]["options"][1]["label"]), ("ask", "ask-1", "Coffee"))
        self.assertEqual(self.tasks, ["you"])
        self.assertEqual(self.pushes, ["質問: Drink"])

    def test_answer_goes_back_to_the_hook(self):
        self.ask()
        text = page_answer(self.sid, {"ask_id": "ask-1", "answer": {"answers": {"Tea or coffee?": "Coffee"}}})
        self.assertEqual(text, "Coffee")
        [st] = self.status()
        self.assertEqual((st["id"], st["status"], st["answer"]), ("ask-1", "answer", {"answers": {"Tea or coffee?": "Coffee"}}))
        self.assertEqual([e["type"] for e in self.events()], ["ask", "ask_done"])
        self.assertEqual(self.tasks, ["you", "working"])
        with self.assertRaises(LookupError):
            page_answer(self.sid, {"ask_id": "ask-1", "answer": {"terminal": True}})

    def test_outside_the_sandbox_the_answer_needs_the_unlock_window(self):
        # A root session's hook drops an answer while its window is closed:
        # the page is told to unlock first, and nothing is answered meanwhile.
        self.ask()
        (self.root / self.sid / "meta.json").write_text(json.dumps(
            {"id": self.sid, "claude_session_id": CONV, "preset": "root-shell", "tmux_location": "root"}))
        self.assertEqual(B.session_unlock_location(B.load_meta(self.sid)), "root")
        seen = []

        def closed(location):
            seen.append(location)
            raise B.UnlockRequired("解錠してください", "root")
        orig = B.require_unlock_if_outside_sandbox
        B.require_unlock_if_outside_sandbox = closed
        try:
            with self.assertRaises(B.UnlockRequired):
                page_answer(self.sid, {"ask_id": "ask-1", "answer": {"answers": {"Tea or coffee?": "Coffee"}}})
            self.assertEqual((seen, self.status(), [e["type"] for e in self.events()]), (["root"], [], ["ask"]))
            # "Answer on the terminal" needs no window.
            page_answer(self.sid, {"ask_id": "ask-1", "answer": {"terminal": True}})
            self.assertEqual(seen, ["root"])
        finally:
            B.require_unlock_if_outside_sandbox = orig

    def test_found_again_after_a_restart(self):
        # On the host: the card is found in events.jsonl and answered.
        meta = json.loads((self.root / self.sid / "meta.json").read_text())
        saved_meta = B.load_meta
        B.load_meta = lambda sid: dict(meta, tmux_location="host")
        self.addCleanup(setattr, B, "load_meta", saved_meta)
        saved = B.require_unlock_if_outside_sandbox
        B.require_unlock_if_outside_sandbox = lambda loc: None
        self.addCleanup(setattr, B, "require_unlock_if_outside_sandbox", saved)
        self.ask("permission")
        B._ask_open = {}
        B._ask_seen = {}
        self.assertEqual(page_answer(self.sid, {"ask_id": "ask-1", "answer": {"behavior": "allow", "session": True}}),
                         "このセッション中は許可")
        self.assertEqual(self.status()[0]["answer"], {"behavior": "allow", "session": True})

    def restart(self):
        B._ask_open = {}
        B._ask_seen = {}

    def test_a_containers_card_still_answers_after_a_restart(self):
        # The card and its request's hash are kept on the host (the user,
        # 2026-11-25: 再起動するとカードが使えなくなるのは面倒).
        body = self.ask("permission")
        self.restart()
        self.assertEqual(page_answer(self.sid, {"ask_id": "ask-1", "answer": {"behavior": "allow"}}), "許可")
        self.assertEqual(self.status()[0]["answer"], {"behavior": "allow"})
        rec = json.loads((B.ASK_ANSWERS_DIR / f"{self.sid}.json").read_text())
        self.assertEqual(rec["ask-1"], {"answer": {"behavior": "allow"}, "ask_hash": B._ask_hash(body)})
        kept = json.loads((B.ASK_ANSWERS_DIR / f"{self.sid}.open.json").read_text())
        self.assertEqual(kept, {"ask-1": {"hash": B._ask_hash(body)}})     # over: only the id stays
        self.assertEqual(oct((B.ASK_ANSWERS_DIR / f"{self.sid}.open.json").stat().st_mode & 0o777), "0o600")
        # ...and the id is still refused after one more restart.
        self.restart()
        B.ask_hook(self.sid, self.talkto, "ask-1", dict(body, summary="ls"))
        self.assertEqual(self.status()[-1], {"id": "ask-1", "status": "skip", "answer": None})

    def rewrite_log(self, old, new):
        path = self.root / self.sid / "events.jsonl"
        path.write_text(path.read_text().replace(old, new))

    def page(self):
        return B.events_page(self.sid)[0]

    def test_the_page_shows_the_hosts_card_not_the_log(self):
        # 漏洩対策 N1: events.jsonl is the box's to write. The page gets the
        # card aiza made, with its hash, while the card is open -- before a
        # restart and after it.
        body = self.ask("permission")
        self.rewrite_log("rm -rf build", "ls")
        for restarted in (False, True):
            if restarted:
                self.restart()
            [ev] = self.page()
            self.assertEqual(ev["summary"], "rm -rf build")
            card = {k: v for k, v in ev.items() if k not in ("type", "ask_id", "seq", "ts", "card_hash")}
            self.assertEqual(ev["card_hash"], B._ask_hash(card))
        # An answer for the card the log shows (or with no hash) is refused.
        forged = dict(card, summary="ls")
        for extra in ({"card_hash": B._ask_hash(forged)}, {"card_hash": None}):
            with self.assertRaises(ValueError):
                B.ask_answer(self.sid, dict({"ask_id": "ask-1", "answer": {"behavior": "allow"}}, **extra))
        self.assertEqual(self.status(), [])
        self.assertEqual(page_answer(self.sid, {"ask_id": "ask-1", "answer": {"behavior": "allow"}}), "許可")
        rec = json.loads((B.ASK_ANSWERS_DIR / f"{self.sid}.json").read_text())
        self.assertEqual(rec["ask-1"], {"answer": {"behavior": "allow"}, "ask_hash": B._ask_hash(body)})

    def test_a_field_added_in_the_log_changes_nothing(self):
        # 漏洩対策 N1: a gate_out written into the box's card skips none of
        # its checks (the kind and gate_out are the host's).
        self.ask("permission")
        self.rewrite_log('"kind": "permission"', '"kind": "permission", "gate_out": "o000000000001", "card_hash": "x"')
        self.restart()
        [ev] = self.page()
        self.assertNotIn("gate_out", ev)
        self.assertNotEqual(ev["card_hash"], "x")
        page_answer(self.sid, {"ask_id": "ask-1", "answer": {"behavior": "allow"}})
        self.assertEqual(self.status()[0]["answer"], {"behavior": "allow"})

    def test_a_card_aiza_does_not_hold_shows_no_answer(self):
        self.ask("permission")
        self.restart()
        (B.ASK_ANSWERS_DIR / f"{self.sid}.open.json").unlink()
        self.rewrite_log('"kind": "permission"', '"kind": "permission", "card_hash": "x"')
        [ev] = self.page()
        self.assertTrue(ev["unverified"])
        self.assertNotIn("card_hash", ev)

    def test_a_broken_record_makes_no_card(self):
        # 漏洩対策 N3: never written over (it holds the ids to refuse).
        B.ASK_ANSWERS_DIR.mkdir(parents=True)
        path = B.ASK_ANSWERS_DIR / f"{self.sid}.open.json"
        path.write_text("{broken")
        self.ask("permission")
        self.assertEqual(self.status(), [{"id": "ask-1", "status": "skip", "answer": None}])
        self.assertEqual(path.read_text(), "{broken")
        self.assertEqual([e for e in self.events() if e["type"] == "ask"], [])

    def test_a_containers_card_kept_nowhere_goes_to_the_terminal(self):
        # Made before the host kept cards, or the host's file lost.
        self.ask("permission")
        self.restart()
        (B.ASK_ANSWERS_DIR / f"{self.sid}.open.json").unlink()
        self.assertEqual(page_answer(self.sid, {"ask_id": "ask-1", "answer": {"behavior": "allow"}}), "端末で答える")
        self.assertEqual(self.status()[0]["answer"], {"terminal": True})

    def test_the_same_id_again_is_refused(self):
        # 漏洩対策 K1: a line added (or one changed) under an id already seen
        # makes no second card and never replaces the shown one.
        body = self.ask("permission")
        B.ask_hook(self.sid, self.talkto, "ask-1", dict(body, summary="ls"))
        asks = [e for e in self.events() if e["type"] == "ask"]
        self.assertEqual([a["summary"] for a in asks], ["rm -rf build"])
        self.assertEqual(self.status(), [{"id": "ask-1", "status": "skip", "answer": None}])

    def test_bad_answers(self):
        self.ask()
        for answer in ({"answers": {"Other question?": "x"}}, {"answers": {"Tea or coffee?": ""}},
                       {"answers": {}}, {"behavior": "allow"}, {"answers": {"Tea or coffee?": "x" * 3000}}):
            with self.assertRaises(ValueError, msg=answer):
                page_answer(self.sid, {"ask_id": "ask-1", "answer": answer})
        self.assertEqual(self.status(), [])

    def test_a_permission_answer_is_kept_where_no_session_writes(self):
        body = self.ask("permission")
        page_answer(self.sid, {"ask_id": "ask-1", "answer": {"behavior": "allow", "session": True}})
        rec = json.loads((B.ASK_ANSWERS_DIR / f"{self.sid}.json").read_text())
        self.assertEqual(rec, {"ask-1": {"answer": {"behavior": "allow", "session": True},
                                         "ask_hash": B._ask_hash(body)}})
        self.assertEqual(oct((B.ASK_ANSWERS_DIR / f"{self.sid}.json").stat().st_mode & 0o777), "0o600")

    def test_a_question_answer_is_not_kept(self):
        self.ask()
        page_answer(self.sid, {"ask_id": "ask-1", "answer": {"answers": {"Tea or coffee?": "Coffee"}}})
        self.assertFalse((B.ASK_ANSWERS_DIR / f"{self.sid}.json").exists())

    def test_ask_check_answers_only_the_containers_own_session(self):
        body = self.ask("permission")
        page_answer(self.sid, {"ask_id": "ask-1", "answer": {"behavior": "allow"}})
        q = {"session": self.sid, "id": "ask-1", "ask_hash": H.ask_hash(body)}
        metas = {self.sid: {"id": self.sid, "preset": "claude-tui", "tmux_location": "container"}}
        saved_meta, B.load_meta = B.load_meta, metas.get
        self.addCleanup(setattr, B, "load_meta", saved_meta)
        self.assertEqual(B.ask_check("devbox", q), {"ok": True, "answer": {"behavior": "allow"}})
        # 漏洩対策 K1: only for the request the card was made from.
        for other in (H.ask_hash(dict(body, summary="ls")), None, ""):
            self.assertEqual(B.ask_check("devbox", dict(q, ask_hash=other)), {"ok": True, "answer": None})
        self.assertFalse(B.ask_check("mail", q)["ok"])                       # the Email box asks for a devbox session
        self.assertEqual(B.ask_check("devbox", dict(q, id="ask-2")), {"ok": True, "answer": None})
        self.assertFalse(B.ask_check("devbox", dict(q, session="../x"))["ok"])
        saved = B.MAIL_PRESETS
        B.MAIL_PRESETS = {"mail-tui"}
        try:
            metas[self.sid] = {"id": self.sid, "preset": "mail-tui", "tmux_location": "container"}
            self.assertEqual(B.ask_check("mail", q)["answer"], {"behavior": "allow"})
            self.assertFalse(B.ask_check("devbox", q)["ok"])
        finally:
            B.MAIL_PRESETS = saved
        metas[self.sid] = {"id": self.sid, "preset": "host-shell", "tmux_location": "host"}
        self.assertFalse(B.ask_check("devbox", q)["ok"])                     # not a container's

    def test_deny_with_reason(self):
        self.ask("permission")
        self.assertEqual(page_answer(self.sid, {"ask_id": "ask-1", "answer": {"behavior": "deny", "message": " no "}}),
                         "拒否: no")
        self.assertEqual(self.status()[0]["answer"], {"behavior": "deny", "message": "no"})

    def test_terminal_answer_closes_once(self):
        self.ask()
        B.ask_close(self.sid, "ask-1", "terminal")
        B.ask_close(self.sid, "ask-1", "terminal")
        self.assertEqual([e["type"] for e in self.events()], ["ask", "ask_done"])
        with self.assertRaises(LookupError):
            page_answer(self.sid, {"ask_id": "ask-1", "answer": {"terminal": True}})

    def test_a_new_ask_closes_the_earlier_one(self):
        self.ask()
        B.ask_hook(self.sid, self.talkto, "ask-2", dict(QUESTION, kind="question", tool="AskUserQuestion",
                                                         terminal=True, session_id=CONV, pane=True))
        self.assertEqual([(e["type"], e["ask_id"]) for e in self.events()],
                         [("ask", "ask-1"), ("ask_done", "ask-1"), ("ask", "ask-2")])
        self.assertEqual(list(B._ask_open[self.sid]), ["ask-2"])

    def test_other_conversation_is_let_go(self):
        self.ask(session_id="1e000000-0000-4000-8000-000000000000", pane=False)
        self.assertEqual(self.events(), [])
        self.assertEqual(self.status()[0]["status"], "skip")

    def test_stop_closes_and_notification_does_not_buzz_twice(self):
        saved = B.threading.Timer

        class Timer:
            def __init__(s, *a):
                pass

            def start(s):
                pass
        B.threading.Timer = Timer
        try:
            self.ask("permission")
            B.task_hook(self.sid, {"hook_event_name": "Notification", "notification_type": "permission_prompt",
                                   "message": "Claude needs your permission", "session_id": CONV})
            self.assertEqual(len(self.pushes), 1)
            B.task_hook(self.sid, {"hook_event_name": "Stop", "session_id": CONV, "last_assistant_message": "x"})
        finally:
            B.threading.Timer = saved
        self.assertEqual(self.events()[-1]["how"], "terminal")
        self.assertEqual(B._ask_open, {})


class HookOutputTest(unittest.TestCase):
    def test_question_answers(self):
        payload = {"tool_input": QUESTION}
        out = H.output("perm", payload, {"answers": {"Tea or coffee?": "Tea"}})
        d = out["hookSpecificOutput"]["decision"]
        self.assertEqual((d["behavior"], d["updatedInput"]["answers"]), ("allow", {"Tea or coffee?": "Tea"}))
        out = H.output("pre", payload, {"answers": {"Tea or coffee?": "Tea"}})
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "allow")
        self.assertEqual(out["hookSpecificOutput"]["updatedInput"]["questions"], QUESTION["questions"])

    def test_session_allow_never_changes_the_mode(self):
        payload = {"permission_suggestions": [
            {"type": "addRules", "rules": [{"toolName": "Bash"}], "behavior": "allow", "destination": "localSettings"},
            {"type": "setMode", "mode": "bypassPermissions", "destination": "session"}]}
        d = H.output("perm", payload, {"behavior": "allow", "session": True})["hookSpecificOutput"]["decision"]
        self.assertEqual([(u["type"], u["destination"]) for u in d["updatedPermissions"]], [("addRules", "session")])

    def test_terminal_and_nothing(self):
        self.assertIsNone(H.output("perm", {}, {"terminal": True}))
        self.assertIsNone(H.output("perm", {}, None))
        self.assertIsNone(H.output("pre", {}, {"behavior": "allow"}))   # pre only answers questions or denies

    def test_deny(self):
        d = H.output("perm", {}, {"behavior": "deny", "message": "no"})["hookSpecificOutput"]["decision"]
        self.assertEqual(d, {"behavior": "deny", "message": "no"})


class HookRunTest(unittest.TestCase):
    """The hook as Claude Code runs it: request out, answer in."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "home" / ".aiza-state" / "sessions" / "bbbbbbbbbb01"
        self.dir.mkdir(parents=True, mode=0o700)
        for p in (self.dir, self.dir.parent, self.dir.parent.parent, self.dir.parent.parent.parent):
            p.chmod(0o700)
        self.talkto = self.dir / "talkto_out.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def run_hook(self, mode, payload, answer=None, status="answer", window=True, container=False, backend=None):
        """main() in a thread (the process-tree check would see the test's
        own parents), answering the request it writes like the backend.
        window: the unlock window open; container: run as in a container,
        where backend is what POST /ask-check answers."""
        import contextlib
        import io
        for f in (self.talkto, self.dir / "talkto_status.jsonl"):   # a second run in one test starts afresh
            f.unlink(missing_ok=True)
        saved = (H._th.read_payload, H._th.nested, H.signal.signal, H.root_window_open, os.environ.get("AIZA_TALKTO"),
                 H.in_container, H.backend_answer)
        H._th.read_payload = lambda: payload
        H._th.nested = lambda: False
        H.signal.signal = lambda *a: None
        self.windows = []
        H.root_window_open = lambda _t, tiers=("root",): self.windows.append(tiers) or window
        H.in_container = lambda: container
        self.checked = []
        self.hashes = []
        H.backend_answer = lambda _t, ask_id, h=None: self.checked.append(ask_id) or self.hashes.append(h) or backend
        os.environ["AIZA_TALKTO"] = str(self.talkto)
        buf = io.StringIO()
        old_argv = sys.argv
        sys.argv = ["aiza-ask-hook", mode]

        def go():
            with contextlib.redirect_stdout(buf):
                H.main()
        t = threading.Thread(target=go)
        try:
            t.start()
            req = None
            deadline = time.time() + 10
            while t.is_alive() and time.time() < deadline and (answer is not None or status != "answer"):
                if self.talkto.exists():
                    lines = [json.loads(l) for l in self.talkto.read_text().splitlines()]
                    req = next((l for l in lines if "ask" in l), None)
                    if req:
                        with open(self.dir / "talkto_status.jsonl", "a") as f:
                            f.write(json.dumps({"id": "other", "status": "delivered"}) + "\n")
                            f.write(json.dumps({"id": req["id"], "status": status, "answer": answer}) + "\n")
                        break
                time.sleep(0.05)
            t.join(10)
        finally:
            (H._th.read_payload, H._th.nested, H.signal.signal, H.root_window_open, env,
             H.in_container, H.backend_answer) = saved
            sys.argv = old_argv
            if env is None:
                os.environ.pop("AIZA_TALKTO", None)
            else:
                os.environ["AIZA_TALKTO"] = env
        self.assertFalse(t.is_alive())
        return req, buf.getvalue()

    def test_question_in_a_skipping_session(self):
        payload = {"tool_name": "AskUserQuestion", "tool_input": QUESTION, "permission_mode": "bypassPermissions",
                   "session_id": CONV, "hook_event_name": "PreToolUse"}
        req, out = self.run_hook("pre", payload, {"answers": {"Tea or coffee?": "Coffee"}})
        self.assertEqual((req["ask"]["kind"], req["ask"]["terminal"]), ("question", False))
        res = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(res["updatedInput"]["answers"], {"Tea or coffee?": "Coffee"})

    def test_pre_leaves_other_modes_to_permission_request(self):
        payload = {"tool_name": "AskUserQuestion", "tool_input": QUESTION, "permission_mode": "default"}
        req, out = self.run_hook("pre", payload)
        self.assertEqual(out, "")
        self.assertFalse(self.talkto.exists())

    def test_skip_returns_nothing(self):
        payload = {"tool_name": "AskUserQuestion", "tool_input": QUESTION, "permission_mode": "default"}
        req, out = self.run_hook("perm", payload, None, status="skip")
        self.assertEqual(out.strip(), "")

    # Permission prompts in every session (2026-11-24, the user: devbox も
    # カードを出す): an "allow" only where it can be trusted.
    BASH = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "permission_mode": "auto"}

    @unittest.skipIf(os.geteuid() == 0, "as root, root's own window is checked")
    def test_on_the_host_an_allow_needs_the_hosts_unlock_window(self):
        req, out = self.run_hook("perm", self.BASH, {"behavior": "allow"})
        self.assertEqual((req["ask"]["kind"], req["ask"]["summary"]), ("permission", "ls"))
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        self.assertEqual(self.windows, [("host", "root")])
        req, out = self.run_hook("perm", self.BASH, {"behavior": "allow"}, window=False)
        self.assertEqual(out, "")                       # left to the terminal

    @unittest.skipIf(os.geteuid() == 0, "as root, root's own window is checked")
    def test_in_a_container_an_allow_is_what_the_backend_recorded(self):
        req, out = self.run_hook("perm", self.BASH, {"behavior": "allow"}, container=True, backend={"behavior": "allow"})
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["decision"], {"behavior": "allow"})
        self.assertEqual(self.checked, [req["id"]])
        self.assertEqual(self.hashes, [B._ask_hash(req["ask"])])     # the request the backend read
        self.assertEqual(self.windows, [])
        # the answer file says allow, the backend has nothing (written by the container's agent)
        req, out = self.run_hook("perm", self.BASH, {"behavior": "allow"}, container=True, backend=None)
        self.assertEqual(out, "")
        # ... or the backend says deny
        req, out = self.run_hook("perm", self.BASH, {"behavior": "allow"}, container=True, backend={"behavior": "deny"})
        self.assertEqual(out, "")

    @unittest.skipIf(os.geteuid() == 0, "as root, root's own window is checked")
    def test_in_a_container_the_session_wide_allow_is_the_backends(self):
        payload = dict(self.BASH, permission_suggestions=[{"type": "addRules", "rules": [{"toolName": "Bash"}], "behavior": "allow"}])
        req, out = self.run_hook("perm", payload, {"behavior": "allow", "session": True}, container=True, backend={"behavior": "allow"})
        self.assertNotIn("updatedPermissions", json.loads(out)["hookSpecificOutput"]["decision"])

    @unittest.skipIf(os.geteuid() == 0, "as root, root's own window is checked")
    def test_a_deny_needs_no_check(self):
        req, out = self.run_hook("perm", self.BASH, {"behavior": "deny", "message": "no"}, container=True, backend=None)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["decision"], {"behavior": "deny", "message": "no"})
        self.assertEqual(self.checked, [])

    @unittest.skipIf(os.geteuid() == 0, "as root, root's own window is checked")
    def test_a_question_answer_needs_no_check(self):
        payload = {"tool_name": "AskUserQuestion", "tool_input": QUESTION, "permission_mode": "auto"}
        req, out = self.run_hook("perm", payload, {"answers": {"Tea or coffee?": "Tea"}}, container=True, backend=None)
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["decision"]["updatedInput"]["answers"], {"Tea or coffee?": "Tea"})
        self.assertEqual(self.checked, [])


if __name__ == "__main__":
    unittest.main()


class ToolLineTest(unittest.TestCase):
    """Progress: one chat line per tool call, from the conversation log."""

    def test_lines(self):
        cases = [
            (("Bash", {"command": "git status", "description": "Show working tree status"}), "Bash: Show working tree status"),
            (("Bash", {"command": "ls -la"}), "Bash: ls -la"),
            (("Edit", {"file_path": "/home/u/proj/README.md", "old_string": "a"}), "Edit: README.md"),
            (("Grep", {"pattern": "def main"}), "Grep: def main"),
            (("WebFetch", {"url": "https://example.org/a/b?c=d"}), "WebFetch: example.org"),
            (("mcp__claude_ai_Gmail__search_threads", {"query": "x"}), "search_threads"),
            (("TodoWrite", {"todos": []}), "TodoWrite"),
        ]
        for (name, inp), want in cases:
            self.assertEqual(B._tool_line(name, inp), want)

    def test_secrets_masked_and_cut(self):
        line = B._tool_line("Bash", {"command": "curl -H 'Authorization: Bearer " + "a1B2" * 12 + "' https://x"})
        self.assertNotIn("a1B2a1B2", line)
        self.assertIn("…", line)
        self.assertLessEqual(len(B._tool_line("Bash", {"command": "echo " + "x " * 200})), len("Bash: ") + B.TOOL_LINE_MAX + 1)

    def test_in_the_transcript_events(self):
        content = [{"type": "text", "text": "Looking."},
                   {"type": "tool_use", "name": "Read", "input": {"file_path": "/a/b.py"}},
                   {"type": "tool_use", "name": None, "input": {}}]
        self.assertEqual(B._assistant_block_events(content),
                         [{"type": "agent_output", "text": "Looking.", "ai": True}, {"type": "tool", "text": "Read: b.py"}])


class AutoDeniedTest(unittest.TestCase):
    """the deployment notes: an operation auto mode refused is marked in the
    chat, and the turn's end pushes one notification counting them."""

    DENIAL = ("Permission for this action was denied by the Claude Code auto mode classifier. "
              "Reason: [Destructive or Unwanted Actions]. If you have other tasks that don't depend on this action, continue.")

    def lines(self, *objs):
        return b"".join(json.dumps(o).encode() + b"\n" for o in objs)

    def setUp(self):
        self.pushed = []
        self.saved = (B.send_push_notification, B.load_meta, B.task_user_turn, B._take_pending_user)
        B.send_push_notification = lambda sid, msg: self.pushed.append((sid, msg)) or True
        B.load_meta = lambda sid: {"label": "root作業"}
        B.task_user_turn = lambda sid, ts: None
        B._take_pending_user = lambda sid, text: []
        B._auto_denied_turn.clear()

    def tearDown(self):
        (B.send_push_notification, B.load_meta, B.task_user_turn, B._take_pending_user) = self.saved

    def use(self, tid, cmd):
        return {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": tid, "name": "Bash", "input": {"command": cmd, "description": cmd}}]}}

    def result(self, tid, text, error=True):
        return {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": tid, "is_error": error, "content": [{"type": "text", "text": text}]}]}}

    def test_marked_and_pushed_once(self):
        buf = self.lines(self.use("t1", "rm -rf build"), self.result("t1", self.DENIAL),
                         self.use("t2", "ls"), self.result("t2", "ok", error=False),
                         self.use("t3", "ssh x"), self.result("t3", self.DENIAL.replace("[Destructive or Unwanted Actions]", "[Remote Shell Writes]")))
        _, events = B._split_assistant_text_events(buf, "aaaaaaaaaaaa")
        denied = [e for e in events if "denied" in e]
        self.assertEqual(denied, [{"type": "tool", "text": "Bash: rm -rf build", "denied": "Destructive or Unwanted Actions"},
                                  {"type": "tool", "text": "Bash: ssh x", "denied": "Remote Shell Writes"}])
        self.assertNotIn("continue", json.dumps(events))     # only the category, never the rest
        B._auto_denied_push("aaaaaaaaaaaa")
        # 漏洩対策 K2: the count and the first reason only, never the command.
        self.assertEqual(self.pushed, [("aaaaaaaaaaaa", "root作業: Auto モードで断られた操作 2 件(Destructive or Unwanted Actions)")])
        B._auto_denied_push("aaaaaaaaaaaa")
        self.assertEqual(len(self.pushed), 1)

    def test_no_reason_and_other_errors(self):
        text = "Permission for this action was denied by the Claude Code auto mode classifier. Reason: The server-side classifier judged this dangerous."
        _, events = B._split_assistant_text_events(
            self.lines(self.use("u1", "x"), self.result("u1", text), self.use("u2", "y"), self.result("u2", "exit 1")), None)
        self.assertEqual([e for e in events if "denied" in e], [{"type": "tool", "text": "Bash: x", "denied": ""}])
        B._auto_denied_push("bbbbbbbbbbbb")
        self.assertEqual(self.pushed, [])

    def test_new_turn_forgets_the_last_ones(self):
        human = {"type": "user", "message": {"content": "next please"}}
        B._split_assistant_text_events(self.lines(self.use("v1", "x"), self.result("v1", self.DENIAL), human), "cccccccccccc")
        B._auto_denied_push("cccccccccccc")
        self.assertEqual(self.pushed, [])

    def test_transcript_text_marks_it(self):
        out = B._sref_lines([{"type": "tool", "text": "Bash: x", "denied": ""}, {"type": "tool", "text": "Read: a"}])
        self.assertEqual(out, ["  ⛔ Bash: x", "  🔧 Read: a"])


class ToolReplayTest(unittest.TestCase):
    """Re-reading a conversation from the top (a backend restart, a resume)
    must not append its old tool calls to the end of the chat."""

    def test_old_tools_dropped_new_kept(self):
        events = [{"type": "tool", "text": "Read: a.py"}, {"type": "agent_output", "text": "old reply", "ai": True},
                  {"type": "tool", "text": "Bash: new"}, {"type": "agent_output", "text": "new reply", "ai": True}]
        kept = B._drop_already_shown(events, {("agent_output", "old reply"): 1})
        self.assertEqual([e["text"] for e in kept], ["Bash: new", "new reply"])

    def test_tool_lines_already_shown_cancel(self):
        events = [{"type": "agent_output", "text": "r", "ai": True}, {"type": "tool", "text": "Bash: x"}]
        self.assertEqual(B._drop_already_shown(events, {("agent_output", "r"): 1, ("tool", "Bash: x"): 1}), [])


class CodexShellResumeTest(unittest.TestCase):
    """↻ on an ended shell session that ran Codex: its conversation id."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.saved = B.session_dir
        B.session_dir = lambda sid: self.root / sid
        (self.root / "cccccccccc01").mkdir()

    def tearDown(self):
        B.session_dir = self.saved
        self.tmp.cleanup()

    def test_conv_of(self):
        p = self.root / "cccccccccc01" / "codex-active.json"
        self.assertIsNone(B._codex_conv_of("cccccccccc01"))
        p.write_text(json.dumps({"session_id": "01a1d929-2b9a-78a0-9c4a-58bef5d620c3", "active": True}))
        self.assertEqual(B._codex_conv_of("cccccccccc01"), "01a1d929-2b9a-78a0-9c4a-58bef5d620c3")
        p.write_text(json.dumps({"session_id": "../../x"}))
        self.assertIsNone(B._codex_conv_of("cccccccccc01"))
