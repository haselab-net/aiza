"""Questions and permission prompts of Claude on the ssh machines
(the deployment notes): the bash hook aiza-ask-hook-remote, run for real against a
fake $HOME, and the backend's ask_remote_hook / ask_remote_answer with the
machine's files reached directly instead of over ssh.

    python3 -m unittest discover -s tests -v
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from test_ask_hook import B, H, CONV, QUESTION, page_answer

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "bin" / "aiza-ask-hook-remote"
SID = "aaaaaaaaaa07"


@unittest.skipUnless(shutil.which("openssl") and shutil.which("bash"), "needs openssl and bash")
class RemoteAskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "remote-home"
        (self.home / ".aiza-talkto").mkdir(parents=True)
        (self.root / SID).mkdir()
        (self.root / SID / "meta.json").write_text(json.dumps(
            {"id": SID, "claude_session_id": CONV, "tmux_location": "ssh:winbox-a"}))
        key = self.root / "ask-sign.key"
        subprocess.run(["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(key)], check=True, capture_output=True)
        self.saved = {k: getattr(B, k) for k in ("session_dir", "send_push_notification", "set_task", "_ask_open",
                                                 "ASK_ORDER_WAIT", "_task_push_later", "ASK_SIGN_KEY",
                                                 "_ssh_put_ask_status", "_ask_remote", "load_meta", "_ask_seen",
                                                 "ASK_ANSWERS_DIR", "SSH_MACHINES")}
        # winbox-a is an ssh machine here whatever this host's list says (its
        # ssh: location needs no unlock window, as on a host that has it).
        B.SSH_MACHINES = dict(B.SSH_MACHINES, **{"winbox-a": B.SSH_MACHINES.get("winbox-a", {})})
        B.ASK_ANSWERS_DIR = self.root / "ask-answers"
        B._ask_seen = {}
        # The machines' presets come from /etc/aiza/ssh_machines.json: read the meta as it is.
        B.load_meta = lambda sid: json.loads((self.root / sid / "meta.json").read_text())
        B.ASK_SIGN_KEY = key
        B._ask_sign_pub_cache.clear()
        B.ASK_ORDER_WAIT = 0.1
        B.session_dir = lambda sid: self.root / sid
        B.send_push_notification = lambda sid, msg: None
        B._task_push_later = lambda sid, msg, ts: None
        B.set_task = lambda sid, task, **kw: None
        B._ask_open = {}
        B._ask_remote = {}
        B._next_seq.pop(SID, None)
        self.put = []

        def put(machine, session_id, line):
            # What _ssh_put_ask_status does there, here.
            self.put.append(line)
            with open(self.home / ".aiza-talkto" / f"{session_id}.status.jsonl", "a") as f:
                f.write(json.dumps(line, separators=(",", ":")) + "\n")
        B._ssh_put_ask_status = put
        self.env = dict(os.environ, HOME=str(self.home), AIZA_TALKTO_ID=SID, AIZA_ASK_PUB=B._ask_sign_pub(),
                        TMUX_PANE="%3")

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(B, k, v)
        B._ask_sign_pub_cache.clear()
        B._next_seq.pop(SID, None)
        self.tmp.cleanup()

    def start(self, mode, payload, env=None):
        return subprocess.Popen(["bash", str(HOOK), mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env or self.env, text=True)

    def request(self, proc, payload):
        proc.stdin.write(json.dumps(payload))
        proc.stdin.close()
        f = self.home / ".aiza-talkto" / f"{SID}.jsonl"
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if f.exists() and f.read_text().strip():
                items = B._parse_talkto_lines(f.read_bytes().split(b"\n"))
                f.unlink()
                return items
            time.sleep(0.05)
        self.fail("no request from the hook")

    def finish(self, proc):
        proc.wait(10)
        with proc.stdout, proc.stderr:
            return proc.stdout.read(), proc.stderr.read()

    def card(self, payload, mode="perm"):
        proc = self.start(mode, payload)
        items = self.request(proc, payload)
        self.assertEqual(len(items), 1)
        ask_id, (kind, info) = items[0]
        self.assertEqual(kind, "ask_remote")
        B.ask_remote_hook(SID, "winbox-a", ask_id, info)
        return proc, ask_id

    def test_allow_round_trip(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "make test"}, "session_id": CONV,
                   "permission_mode": "default"}
        proc, ask_id = self.card(payload)
        ev = B._ask_find(SID, ask_id)
        self.assertEqual((ev["kind"], ev["summary"]), ("permission", "make test"))
        page_answer(SID, {"ask_id": ask_id, "answer": {"behavior": "allow"}})
        out, _ = self.finish(proc)
        self.assertEqual(json.loads(out), H.output("perm", payload, {"behavior": "allow"}))

    def test_question_answer(self):
        payload = {"tool_name": "AskUserQuestion", "tool_input": QUESTION, "session_id": CONV,
                   "permission_mode": "bypassPermissions"}
        proc, ask_id = self.card(payload, mode="pre")
        page_answer(SID, {"ask_id": ask_id, "answer": {"answers": {"Tea or coffee?": "Tea"}}})
        out, _ = self.finish(proc)
        got = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(got["permissionDecision"], "allow")
        self.assertEqual(got["updatedInput"]["answers"], {"Tea or coffee?": "Tea"})

    def test_forged_and_replayed_answers_print_nothing(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /data"}, "session_id": CONV}
        proc, ask_id = self.card(payload)
        status = self.home / ".aiza-talkto" / f"{SID}.status.jsonl"
        # What the AI on the shared account could write: an allow with no
        # valid signature, then one signed for another request's input.
        import base64
        allow = base64.b64encode(json.dumps(H.output("perm", payload, {"behavior": "allow"})).encode()).decode()
        other = B._ask_sign(f"{B.ASK_SIGN_PREFIX}|{ask_id}|{'0' * 64}|{allow}")
        with open(status, "a") as f:
            f.write(json.dumps({"id": ask_id, "status": "answer", "out": allow, "sig": other},
                               separators=(",", ":")) + "\n")
        out, err = self.finish(proc)
        self.assertEqual(out, "")
        self.assertIn("signature", err)

    def test_terminal_and_unknown_cards_skip(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": CONV}
        proc, ask_id = self.card(payload)
        page_answer(SID, {"ask_id": ask_id, "answer": {"terminal": True}})
        out, _ = self.finish(proc)
        self.assertEqual(out, "")
        self.assertEqual(self.put[-1], {"id": ask_id, "status": "skip"})
        # A request held neither in memory nor on the host: skip too.
        proc, ask_id = self.card(payload)
        B._ask_remote.clear()
        (B.ASK_ANSWERS_DIR / f"{SID}.open.json").unlink()
        page_answer(SID, {"ask_id": ask_id, "answer": {"behavior": "allow"}})
        self.assertEqual(self.put[-1], {"id": ask_id, "status": "skip"})
        self.assertEqual(self.finish(proc)[0], "")

    def test_allow_after_a_restart(self):
        # The request is kept on the host: a restarted backend still signs
        # the answer (the user, 2026-11-25).
        payload = {"tool_name": "Bash", "tool_input": {"command": "make test"}, "session_id": CONV,
                   "permission_mode": "default"}
        proc, ask_id = self.card(payload)
        B._ask_remote.clear()
        B._ask_open = {}
        B._ask_seen = {}
        page_answer(SID, {"ask_id": ask_id, "answer": {"behavior": "allow"}})
        out, _ = self.finish(proc)
        self.assertEqual(json.loads(out), H.output("perm", payload, {"behavior": "allow"}))
        kept = json.loads((B.ASK_ANSWERS_DIR / f"{SID}.open.json").read_text())
        self.assertEqual(list(kept[ask_id]), ["hash"])      # over: the request is dropped

    def test_old_and_big_requests_are_not_kept(self):
        # 漏洩対策 N2: the request is the tool's whole input.
        payload = {"tool_name": "Bash", "tool_input": {"command": "make test"}, "session_id": CONV}
        proc, ask_id = self.card(payload)
        path = B.ASK_ANSWERS_DIR / f"{SID}.open.json"
        kept = json.loads(path.read_text())
        kept[ask_id]["remote"]["ts"] -= B.ASK_REMOTE_MAX_AGE + 1
        path.write_text(json.dumps(kept))
        B._ask_remote.clear()
        B._ask_open = {}
        B._ask_seen = {}
        page_answer(SID, {"ask_id": ask_id, "answer": {"behavior": "allow"}})
        self.assertEqual(self.put[-1], {"id": ask_id, "status": "skip"})
        self.assertEqual(self.finish(proc)[0], "")
        self.assertNotIn("remote", json.loads(path.read_text())[ask_id])
        big = {"tool_name": "Write", "tool_input": {"file_path": "a", "content": "x" * (B.ASK_REMOTE_MAX_BYTES + 1)},
               "session_id": CONV}
        B.ask_remote_hook(SID, "winbox-a", "ask-00000000000000ff",
                          {"mode": "perm", "raw": json.dumps(big).encode(), "pane": 1})
        self.assertNotIn("remote", json.loads(path.read_text()).get("ask-00000000000000ff", {}))

    def test_the_same_id_again_keeps_the_first_request(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "make test"}, "session_id": CONV}
        proc, ask_id = self.card(payload)
        other = {"tool_name": "Bash", "tool_input": {"command": "rm -rf /data"}, "session_id": CONV}
        B.ask_remote_hook(SID, "winbox-a", ask_id, {"mode": "perm", "raw": json.dumps(other).encode(), "pane": 1})
        self.assertEqual(self.put[-1], {"id": ask_id, "status": "skip"})
        self.assertEqual(B._ask_find(SID, ask_id)["summary"], "make test")
        page_answer(SID, {"ask_id": ask_id, "answer": {"behavior": "allow"}})
        out, _ = self.finish(proc)
        self.assertEqual(json.loads(out), H.output("perm", payload, {"behavior": "allow"}))

    def test_pre_only_for_a_skipping_question(self):
        # Not skipping: the bash side lets it go without a request.
        payload = {"tool_name": "AskUserQuestion", "tool_input": QUESTION, "permission_mode": "default"}
        proc = self.start("pre", payload)
        proc.stdin.write(json.dumps(payload)); proc.stdin.close()
        self.assertEqual(self.finish(proc)[0], "")
        self.assertFalse((self.home / ".aiza-talkto" / f"{SID}.jsonl").exists())

    def test_outside_an_aiza_pane_does_nothing(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        for drop in ("AIZA_TALKTO_ID", "AIZA_ASK_PUB"):
            env = dict(self.env)
            env.pop(drop)
            proc = self.start("perm", payload, env=env)
            proc.stdin.write(json.dumps(payload)); proc.stdin.close()
            self.assertEqual(self.finish(proc)[0], "")
        self.assertFalse((self.home / ".aiza-talkto" / f"{SID}.jsonl").exists())

    def test_hook_ended_by_the_terminal_closes_the_card(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": CONV}
        proc, ask_id = self.card(payload)
        proc.terminate()
        self.finish(proc)
        lines = B._parse_talkto_lines((self.home / ".aiza-talkto" / f"{SID}.jsonl").read_bytes().split(b"\n"))
        self.assertEqual(lines, [(None, ("ask_done", {"ask_id": ask_id, "how": "terminal"}))])


class InstallTest(unittest.TestCase):
    """aiza-task-hook-install also puts the ask hook in the machine's
    settings: once, replacing its own earlier entries, keeping the rest."""

    def test_merged(self):
        import importlib.machinery
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("hook_install", str(ROOT / "bin" / "aiza-task-hook-install"))
        m = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
        loader.exec_module(m)
        own = {"matcher": "Bash", "hooks": [{"type": "command", "command": "mine"}]}
        settings = {"hooks": {"PreToolUse": [own],
                              "PermissionRequest": [{"hooks": [{"type": "command", "command": "~/.local/bin/aiza-ask-hook perm"}]}]}}
        hooks = m.merged(m.merged(settings))["hooks"]
        self.assertEqual(hooks["PreToolUse"], [own, {"matcher": "AskUserQuestion", "hooks": [
            {"type": "command", "command": "~/.local/bin/aiza-ask-hook pre", "timeout": 1728000}]}])
        self.assertEqual(hooks["PermissionRequest"], [{"hooks": [
            {"type": "command", "command": "~/.local/bin/aiza-ask-hook perm", "timeout": 1728000}]}])
        self.assertEqual(len(hooks["Stop"]), 1)


class RemotePaneEnvTest(unittest.TestCase):
    def test_no_key_no_cards(self):
        saved = B.ASK_SIGN_KEY
        B.ASK_SIGN_KEY = Path("/nonexistent/ask-sign.key")
        B._ask_sign_pub_cache.clear()
        try:
            self.assertIsNone(B._ask_sign_pub())
        finally:
            B.ASK_SIGN_KEY = saved
            B._ask_sign_pub_cache.clear()


if __name__ == "__main__":
    unittest.main()
