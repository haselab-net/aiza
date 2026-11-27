"""aiza-unlockd's window and token rules (the deployment notes), its verbs
called directly with a peer uid as SO_PEERCRED would give it: who may ask
about whom, that status never extends a window, that touch extends it only
for a tier the window has and never past its absolute end, that another
browser's key does not see the window, that lock ends it, and who may mint
a registration token. The passkey ceremony itself (fido2) is not run here.
Needs fido2 (the daemon's own venv): tests/test_unlockd.py runs this file
there.

    /opt/aiza/venv/bin/python3 -m unittest unlockd_cases -v    (in tests/)
"""
import getpass
import importlib.machinery
import importlib.util
import json
import os
import pwd
import tempfile
import time as real_time
import unittest
from pathlib import Path

ROOT = Path(os.environ["AIZA_ROOT"]) if os.environ.get("AIZA_ROOT") else Path(__file__).resolve().parents[1]
DAEMON = ROOT / "bin" / "aiza-unlockd"
ME = getpass.getuser()
MY_UID = pwd.getpwnam(ME).pw_uid
OTHER_UID = pwd.getpwnam("nobody").pw_uid


def load_daemon():
    tmp = Path(tempfile.mkdtemp(prefix="aiza-test-unlockd-"))
    (tmp / "webauthn.json").write_text(json.dumps({"rp_id": "example.org", "rp_name": "t", "origin": "https://example.org"}))
    src = DAEMON.read_text()
    line = 'WEBAUTHN_CONFIG_PATH = Path("/etc/aiza/webauthn.json")\n'
    assert src.count(line) == 1, "aiza-unlockd: WEBAUTHN_CONFIG_PATH moved"
    src = src.replace(line, f"WEBAUTHN_CONFIG_PATH = Path({str(tmp / 'webauthn.json')!r})\n")
    loader = importlib.machinery.SourceFileLoader("aiza_unlockd_under_test", str(DAEMON))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader(loader.name, loader))
    mod.__file__ = str(DAEMON)
    exec(compile(src, str(DAEMON), "exec"), mod.__dict__)
    mod.CRED_DIR = tmp / "passkeys"
    mod.CRED_DIR.mkdir()
    return mod


D = load_daemon()


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def time(self):
        return self.now

    def __getattr__(self, name):
        return getattr(real_time, name)


class WindowTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.saved = {k: getattr(D, k) for k in ("time", "_audit", "_revoke_access", "_grant_access", "_peer_sudo_user")}
        D.time = self.clock
        self.audit = []
        D._audit = lambda event, user, outcome, **f: self.audit.append((event, user, outcome, f.get("reason")))
        self.revoked = []
        D._revoke_access = lambda user: self.revoked.append(user) or True
        D._grant_access = lambda user: None
        D._peer_sudo_user = lambda pid: None
        D._unlocks.clear()
        D._unlock_keys.clear()
        D._reg_tokens.clear()

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(D, k, v)
        D._unlocks.clear()
        D._unlock_keys.clear()
        D._reg_tokens.clear()

    def open(self, tier="host", key=None, ago=0):
        at = self.clock.now - ago
        D._unlocks[ME] = (at, at + D.UNLOCK_TTL, tier)
        if key:
            D._unlock_keys.setdefault(ME, {})[key] = at

    def status(self, uid=None, **extra):
        return D.verb_status(MY_UID if uid is None else uid, 1, {"user": ME, **extra})

    def touch(self, tier, uid=None, **extra):
        return D.verb_touch(MY_UID if uid is None else uid, 1, {"user": ME, "tier": tier, **extra})

    def test_only_the_user_or_root_may_ask(self):
        self.open()
        for verb in (lambda u: self.status(u), lambda u: self.touch("host", u),
                     lambda u: D.verb_lock(u, 1, {"user": ME})):
            with self.assertRaises(PermissionError):
                verb(OTHER_UID)
        self.assertTrue(self.status(0)["unlocked"])                 # root may
        self.assertIn(ME, D._unlocks)                               # the refused lock did nothing
        with self.assertRaises(D.BadRequest):
            D.verb_status(0, 1, {"user": "no-such-user-xyz"})
        with self.assertRaises(D.BadRequest):
            D.verb_status(0, 1, {"user": "../etc/passwd"})

    def test_status_does_not_extend(self):
        self.open(ago=60)
        before = D._unlocks[ME]
        for _ in range(3):
            self.clock.now += 100
            self.assertTrue(self.status()["unlocked"])
        self.assertEqual(D._unlocks[ME], before)
        self.clock.now = before[1] + 1
        self.assertFalse(self.status()["unlocked"])
        self.assertIsNone(self.status()["expires_at"])

    def test_touch_extends_a_window_of_that_tier(self):
        self.open("host", ago=600)
        r = self.touch("host")
        self.assertEqual((r["ok"], r["expires_at"]), (True, int(self.clock.now + D.UNLOCK_TTL)))
        self.assertEqual(D._unlocks[ME][2], "host")

    def test_a_host_window_does_not_serve_root_and_is_left_alone(self):
        self.open("host", ago=600)
        before = D._unlocks[ME]
        r = self.touch("root")
        self.assertFalse(r["ok"])
        self.assertEqual(D._unlocks[ME], before)                    # neither extended nor ended
        self.assertEqual(self.audit[-1][3], "insufficient-tier")

    def test_a_root_window_serves_host_and_keeps_its_tier(self):
        self.open("root")
        self.assertTrue(self.touch("host")["ok"])
        self.assertEqual(D._unlocks[ME][2], "root")

    def test_touch_never_goes_past_the_absolute_end(self):
        self.open("host")
        start = D._unlocks[ME][0]
        while True:
            self.clock.now += D.UNLOCK_TTL - 1
            r = self.touch("host")
            if not r["ok"]:
                break
            self.assertLessEqual(r["expires_at"], start + D.UNLOCK_ABSOLUTE_MAX)
        self.assertGreaterEqual(self.clock.now, start + D.UNLOCK_ABSOLUTE_MAX - D.UNLOCK_TTL)
        self.assertFalse(self.status()["unlocked"])

    def test_unknown_tiers_are_refused(self):
        self.open("root")
        for tier in ("admin", "", "ROOT", None):
            with self.assertRaises(D.BadRequest):
                self.touch(tier)

    def test_another_browsers_key_does_not_see_the_window(self):
        self.open("host", key="k-mine")
        self.assertTrue(self.status(unlock_key="k-mine")["unlocked"])
        self.assertFalse(self.status(unlock_key="k-other")["unlocked"])
        self.assertFalse(self.status(unlock_key="")["unlocked"])
        self.assertFalse(self.touch("host", unlock_key="k-other")["ok"])
        self.assertTrue(self.status()["unlocked"])                  # no key: the CLI, the backend's own threads

    def test_lock_ends_the_window(self):
        self.open("root")
        self.assertEqual(D.verb_lock(MY_UID, 1, {"user": ME}), {"ok": True})
        self.assertNotIn(ME, D._unlocks)
        self.assertEqual(self.revoked, [ME])
        self.assertFalse(self.status()["unlocked"])

    def test_who_may_mint_a_registration_token(self):
        with self.assertRaises(PermissionError):
            D.verb_mint_registration_token(MY_UID, 1, {"user": ME, "tier": "root"})     # root only
        with self.assertRaises(PermissionError):
            D.verb_mint_registration_token(OTHER_UID, 1, {"user": ME, "tier": "host"})  # not someone else's
        self.assertEqual(D._reg_tokens, {})
        mine = D.verb_mint_registration_token(MY_UID, 1, {"user": ME, "tier": "host"})
        rooted = D.verb_mint_registration_token(0, 1, {"user": ME, "tier": "root"})
        self.assertEqual(D._reg_tokens[mine["token"]]["tier"], "host")
        self.assertEqual(D._reg_tokens[rooted["token"]]["tier"], "root")
        self.assertEqual(mine["expires_at"], int(self.clock.now + D.REG_TOKEN_TTL))
        self.assertNotEqual(mine["token"], rooted["token"])
        self.assertGreaterEqual(len(mine["token"]), 40)


if __name__ == "__main__":
    unittest.main()
