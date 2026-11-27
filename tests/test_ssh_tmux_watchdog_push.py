"""aiza-ssh-tmux-watchdog's push (the root audit R5, 2026-11-24): it runs as
root and reads each notified user's own push subscriptions, a file that user
can write. It reads it without following a link anywhere on the way, only a
regular file of the user's own with one name, and posts only to the browsers'
push services -- not to whatever URL the file names.

    python3 -m unittest discover -s tests -v
"""
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def load():
    loader = importlib.machinery.SourceFileLoader("aiza_ssh_tmux_watchdog", str(ROOT / "bin" / "aiza-ssh-tmux-watchdog"))
    mod = importlib.util.module_from_spec(importlib.util.spec_from_loader("aiza_ssh_tmux_watchdog", loader))
    loader.exec_module(mod)
    return mod


W = load()
FCM = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": "x", "auth": "y"}}
WNS = {"endpoint": "https://wns2-pn1p.notify.windows.com/w/?token=abc", "keys": {}}
EVIL = {"endpoint": "http://127.0.0.1:8878/agents/api/x", "keys": {}}


class PushEndpointTest(unittest.TestCase):
    def test_the_push_services_only(self):
        ok = ["https://fcm.googleapis.com/fcm/send/a", "https://updates.push.services.mozilla.com/wpush/v2/a",
              "https://web.push.apple.com/a", "https://wns2-pn1p.notify.windows.com/w/?token=a",
              "https://FCM.googleapis.com:443/a"]
        bad = ["http://fcm.googleapis.com/a", "https://fcm.googleapis.com.example.org/a",
               "https://example.org/fcm.googleapis.com", "https://user@fcm.googleapis.com/a",
               "https://fcm.googleapis.com:8443/a", "https://127.0.0.1/a", "https://notify.windows.com.evil/a",
               "https://evilnotify.windows.com/a", "", None, 5, "https://[::1/a"]
        for u in ok:
            self.assertTrue(W.push_endpoint_ok(u), u)
        for u in bad:
            self.assertFalse(W.push_endpoint_ok(u), u)


class ReadSubscriptionsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / ".aiza-state").mkdir(parents=True)
        self.pw = SimpleNamespace(pw_dir=str(self.home), pw_uid=os.getuid())
        self.subs = self.home / ".aiza-state" / "push_subscriptions.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_own_file_read_and_other_endpoints_dropped(self):
        self.subs.write_text(json.dumps([FCM, EVIL, WNS, "junk"]))
        self.assertEqual(W.read_subscriptions(self.pw), [FCM, WNS])

    def test_a_linked_file_is_not_read(self):
        other = Path(self.tmp.name) / "secret.json"
        other.write_text(json.dumps([FCM]))
        self.subs.symlink_to(other)
        with self.assertRaises(OSError):
            W.read_subscriptions(self.pw)

    def test_a_linked_state_folder_is_not_followed(self):
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        (elsewhere / "push_subscriptions.json").write_text(json.dumps([FCM]))
        (self.home / ".aiza-state").rmdir()
        (self.home / ".aiza-state").symlink_to(elsewhere)
        with self.assertRaises(OSError):
            W.read_subscriptions(self.pw)

    def test_a_hard_link_is_not_read(self):
        other = Path(self.tmp.name) / "other.json"
        other.write_text(json.dumps([FCM]))
        os.link(other, self.subs)
        with self.assertRaises(ValueError):
            W.read_subscriptions(self.pw)

    def test_someone_elses_folder_is_not_read(self):
        self.subs.write_text(json.dumps([FCM]))
        with self.assertRaises(ValueError):
            W.read_subscriptions(SimpleNamespace(pw_dir=str(self.home), pw_uid=os.getuid() + 1))

    def test_not_a_list(self):
        self.subs.write_text(json.dumps({"endpoint": FCM["endpoint"]}))
        self.assertEqual(W.read_subscriptions(self.pw), [])


if __name__ == "__main__":
    unittest.main()
