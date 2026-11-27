"""Processes in a Podman box (the deployment notes, 2026-11-25): the host may see
a box process's owner but not its /proc/<pid>/environ or fd. So a devbox
session's Codex rollout and ssh are looked for from inside the devbox
(_container_procs: a python run there with `sandbox --stdin exec`), and the
Email box's Codex pid check falls back to the box pid plus its start time.

    python3 -m unittest discover -s tests -p 'test_podman_proc.py'
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_shared_search import B


class ScanScriptTest(unittest.TestCase):
    """The script itself, run here as it runs in the devbox."""

    def test_lists_a_process_with_its_talkto_rollout_and_ssh_line(self):
        with tempfile.TemporaryDirectory() as d:
            roll = Path(d) / ".codex" / "sessions" / "2026" / "rollout-x.jsonl"
            roll.parent.mkdir(parents=True)
            roll.write_text("")
            talk = f"{d}/.aiza/aaaaaaaaaa01/talkto_out.jsonl"
            # a stand-in for codex (holds the rollout open) and one for ssh (its argv[0] is "ssh")
            holder = subprocess.Popen([sys.executable, "-c", f"f=open({str(roll)!r});import time;time.sleep(30)"],
                                      env={**os.environ, "AIZA_TALKTO": talk})
            ssh = subprocess.Popen(["bash", "-c", "exec -a ssh sleep 30", "x", "winbox-a"],
                                   env={**os.environ, "AIGW_TALKTO": talk.replace("/.aiza/", "/.aigw/")})
            plain = subprocess.Popen(["sleep", "30"], env={k: v for k, v in os.environ.items() if not k.endswith("TALKTO")})
            try:
                time.sleep(0.5)
                script = B._CONTAINER_PROC_SCAN % (B.CODEX_ROLLOUT_FD_RE.pattern, sorted(B.BOARD_SSH_PROGS))
                out = json.loads(subprocess.run([sys.executable, "-"], input=script, capture_output=True, text=True, timeout=30).stdout)
            finally:
                for p in (holder, ssh, plain):
                    p.kill()
                    p.wait()
            mine = [p for p in out if p["talkto"] == talk]
            self.assertTrue(any(p.get("rollouts") and p["rollouts"][0][1] == str(roll) for p in mine), out)
            self.assertTrue(any(p.get("argv", [""])[0] == "ssh" for p in mine), out)   # AIGW_ read as AIZA_
            self.assertFalse(any("rollouts" not in p and "argv" not in p for p in out))


class ContainerScanTest(unittest.TestCase):
    def setUp(self):
        self.saved = {n: getattr(B, n) for n in ("_board_ssh_names",)}
        self.saved_run = B.subprocess.run
        self.calls = []
        self.answer = []

        def run(argv, **kw):
            if argv[:4] == ["sandbox", "--stdin", "exec", "--"]:
                self.calls.append((argv, kw.get("input", "")))
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.answer), "")
            return self.saved_run(argv, **kw)
        B.subprocess.run = run
        B._container_procs_cache.update(at=0.0, procs=[])

    def tearDown(self):
        B.subprocess.run = self.saved_run
        for n, v in self.saved.items():
            setattr(B, n, v)
        B._container_procs_cache.update(at=0.0, procs=[])

    def test_a_devbox_codex_is_found_from_inside_and_asked_once_a_while(self):
        t = "/s/.aiza/aaaaaaaaaa01/talkto_out.jsonl"
        self.answer = [{"talkto": t, "rollouts": [[1.0, "/s/.codex/sessions/old.jsonl"], [5.0, "/s/.codex/sessions/new.jsonl"]]},
                       {"talkto": "/s/.aiza/other/talkto_out.jsonl", "rollouts": [[9.0, "/s/.codex/sessions/theirs.jsonl"]]}]
        self.assertEqual(B._codex_rollout_of(t, "container"), "/s/.codex/sessions/new.jsonl")
        self.assertIsNone(B._codex_rollout_of("/s/.aiza/nobody/talkto_out.jsonl", "container"))
        self.assertEqual(len(self.calls), 1)                         # kept for CONTAINER_PROC_SCAN_TTL
        argv, script = self.calls[0]
        self.assertEqual(argv, ["sandbox", "--stdin", "exec", "--", "python3", "-"])   # the script on stdin, not argv
        self.assertIn("AIZA_TALKTO", script)

    def test_host_sessions_do_not_ask_the_devbox(self):
        B._codex_rollout_of("/h/.aiza-state/x/talkto_out.jsonl", "host")
        self.assertEqual(self.calls, [])

    def test_a_failed_scan_is_nothing_found(self):
        def run(argv, **kw):
            self.calls.append(argv)
            return subprocess.CompletedProcess(argv, 1, "", "no devbox")
        B.subprocess.run = run
        self.assertIsNone(B._codex_rollout_of("/s/x", "container"))

    def test_board_counts_ssh_in_the_devbox_only_while_a_devbox_session_lives(self):
        B._board_ssh_names = lambda: {"winbox-a": "winbox-a"}
        t = "/s/.aiza/aaaaaaaaaa01/talkto_out.jsonl"
        self.answer = [{"talkto": t, "argv": ["ssh", "winbox-a", "ls"]},
                       {"talkto": "/s/.aiza/unknown/talkto_out.jsonl", "argv": ["ssh", "winbox-a"]}]
        got = B._board_ssh_uses({t: "aaaaaaaaaa01"}, in_devbox=True)
        self.assertEqual(got.get(("aaaaaaaaaa01", "winbox-a")), "ssh winbox-a ls")
        self.assertEqual(len(got), 1)
        self.calls.clear()
        B._container_procs_cache.update(at=0.0, procs=[])
        B._board_ssh_uses({t: "aaaaaaaaaa01"}, in_devbox=False)
        self.assertEqual(self.calls, [])                             # a stopped devbox is not started for this


class BoxPidDeniedTest(unittest.TestCase):
    """_box_host_pid when the box's environments cannot be read (Podman)."""

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("root reads mode-000 files")
        self.tmp = tempfile.TemporaryDirectory()
        self.proc = Path(self.tmp.name)

    def tearDown(self):
        for p in self.proc.glob("*/environ"):
            p.chmod(0o600)
        self.tmp.cleanup()

    def p(self, pid, ppid, nspid, start, env=None):
        d = self.proc / str(pid)
        d.mkdir()
        (d / "status").write_text(f"Name:\tx\nPPid:\t{ppid}\nNSpid:\t{nspid}\n")
        (d / "stat").write_text(f"{pid} (codex) S {ppid} " + " ".join(["0"] * 17) + f" {start} 0 0\n")
        e = d / "environ"
        e.write_text((env or "").replace(" ", "\0"))
        if env is None:
            e.chmod(0)

    def test_the_box_pid_and_its_start_time(self):
        self.p(700, 2, "700\t41", 111)        # the devbox's own pid 41
        self.p(900, 2, "900\t41", 222)        # the Email box's pid 41, this session's
        f = lambda **kw: B._box_host_pid(41, "aaaaaaaaaa01", proc=str(self.proc), **kw)
        self.assertEqual(f(starttime=222), 900)
        self.assertEqual(f(starttime=111), 700)
        self.assertIsNone(f(starttime=333))
        self.assertIsNone(f())                # without a start time the pid alone is not enough

    def test_readable_environments_still_decide(self):
        self.p(900, 2, "900\t41", 222, "AIZA_TALKTO=/m/.aiza/bbbbbbbbbb01/talkto_out.jsonl")
        self.assertIsNone(B._box_host_pid(41, "aaaaaaaaaa01", proc=str(self.proc), starttime=222))


if __name__ == "__main__":
    unittest.main()
