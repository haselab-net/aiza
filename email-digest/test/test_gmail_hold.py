"""gmail.py hides the threads the digest's gate held back (2026-11-25): list leaves their messages out (also a reply that
came later without the label), thread / show / attachment / draft --reply-to refuse them (exit 3), list --held gives only
ids and dates, hold / unhold keep the label and the local list. A fake Gmail service; the Google libraries are stubbed.

    python3 -m unittest discover -s test -p 'test_gmail_hold.py'
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _stub_google():
    for name in ("google", "google.oauth2", "google.oauth2.credentials", "google.auth", "google.auth.transport",
                 "google.auth.transport.requests", "google_auth_oauthlib", "google_auth_oauthlib.flow",
                 "googleapiclient", "googleapiclient.discovery", "googleapiclient.errors"):
        sys.modules.setdefault(name, types.ModuleType(name))
    sys.modules["google.oauth2.credentials"].Credentials = object
    sys.modules["google.auth.transport.requests"].Request = object
    sys.modules["google_auth_oauthlib.flow"].Flow = object
    sys.modules["googleapiclient.discovery"].build = lambda *a, **k: None
    sys.modules["googleapiclient.errors"].HttpError = type("HttpError", (Exception,), {})


class Req:
    def __init__(self, fn):
        self.fn = fn

    def execute(self):
        return self.fn()


class FakeGmail:
    """messages: id -> {threadId, labelIds, subject}. One label 'Label_9' named 'AI保留' exists unless no_label."""

    def __init__(self, messages, no_label=False):
        self.msgs, self.label_list, self.modified = messages, ([] if no_label else [{"id": "Label_9", "name": "AI保留"}]), []

    def users(self):
        return self

    def msg(self, i):
        m = self.msgs[i]
        return {"id": i, "threadId": m["threadId"], "labelIds": m.get("labelIds", []), "snippet": "s",
                "payload": {"headers": [{"name": "Subject", "value": m.get("subject", "")}, {"name": "Date", "value": "d-" + i}],
                            "body": {"data": ""}}}

    # labels().list / create
    def labels(self):
        g = self

        class L:
            def list(self, userId):
                return Req(lambda: {"labels": g.label_list})

            def create(self, userId, body):
                def f():
                    g.label_list.append({"id": "Label_new", "name": body["name"]})
                    return g.label_list[-1]
                return Req(f)
        return L()

    def messages(self):
        g = self

        class M:
            def list(self, userId, **kw):
                return Req(lambda: {"messages": [{"id": i} for i in g.msgs]})

            def get(self, userId, id, **kw):
                return Req(lambda: g.msg(id))

            def attachments(self):
                class A:
                    def get(self, **kw):
                        return Req(lambda: {"data": ""})
                return A()
        return M()

    def threads(self):
        g = self

        class T:
            def get(self, userId, id, **kw):
                return Req(lambda: {"id": id, "messages": [g.msg(i) for i, m in g.msgs.items() if m["threadId"] == id]})

            def modify(self, userId, id, body):
                return Req(lambda: g.modified.append((id, body)) or {})
        return T()

    def new_batch_http_request(self):
        g = self

        class B:
            def __init__(self):
                self.reqs = []

            def add(self, req, callback):
                self.reqs.append((req, callback))

            def execute(self):
                for r, cb in self.reqs:
                    cb(None, r.execute(), None)
        return B()


class GmailHoldTest(unittest.TestCase):
    def setUp(self):
        _stub_google()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["MAILBOX_DIR"] = self.tmp.name
        self.addCleanup(os.environ.pop, "MAILBOX_DIR", None)
        (Path(self.tmp.name) / ".gmail").mkdir()
        (Path(self.tmp.name) / ".gmail" / "token.json").write_text(json.dumps({"scopes": ["https://www.googleapis.com/auth/gmail.modify"]}))
        spec = importlib.util.spec_from_file_location("gmail_under_test", ROOT / "gmail.py")
        self.g = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.g)
        self.svc = FakeGmail({
            "m1": {"threadId": "a1", "subject": "普通"},
            "m2": {"threadId": "a2", "subject": "保留(ラベル)", "labelIds": ["Label_9"]},
            "m3": {"threadId": "a3", "subject": "保留のスレッドへの後の返信"},
        })
        self.g.service = lambda: self.svc

    def run_cmd(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        sys.argv = ["gmail.py", *argv]
        code = 0
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                self.g.main()
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
        return code, out.getvalue(), err.getvalue()

    def held(self, *tids):
        (Path(self.tmp.name) / ".gmail" / "held-threads").write_text("".join(t + "\n" for t in tids))

    def test_list_leaves_out_labelled_and_listed_threads(self):
        self.held("a3")
        code, out, _ = self.run_cmd("list", "-n", "10")
        self.assertEqual(code, 0)
        self.assertEqual([json.loads(l)["threadId"] for l in out.splitlines()], ["a1"])
        self.assertNotIn("保留", out)

    def test_held_only_gives_ids_and_dates(self):
        self.held("a3")
        _, out, _ = self.run_cmd("list", "--held")
        rows = [json.loads(l) for l in out.splitlines()]
        self.assertEqual([r["threadId"] for r in rows], ["a2", "a3"])
        self.assertEqual(set(rows[0]), {"id", "threadId", "date"})

    def test_without_any_hold_nothing_is_asked_or_hidden(self):
        self.svc = FakeGmail({"m1": {"threadId": "a1"}, "m2": {"threadId": "a2", "labelIds": ["Label_9"]}}, no_label=True)
        _, out, _ = self.run_cmd("list")
        self.assertEqual(len(out.splitlines()), 2)

    def test_thread_show_attachment_refuse(self):
        self.held("a3")
        for argv in (["thread", "a2"], ["thread", "a3"], ["show", "m2"], ["show", "m3"], ["attachment", "m2", "a", os.path.join(self.tmp.name, "x")]):
            code, out, err = self.run_cmd(*argv)
            self.assertEqual(code, 3, argv)
            self.assertEqual(out, "", argv)
            self.assertIn("保留中", err)
        code, out, _ = self.run_cmd("thread", "a1")
        self.assertEqual(code, 0)
        self.assertIn("普通", out)

    def test_hold_and_unhold(self):
        self.svc.label_list = []    # the label does not exist yet: hold creates it
        code, _, _ = self.run_cmd("hold", "a1")
        self.assertEqual(code, 0)
        self.assertEqual(self.svc.modified, [("a1", {"addLabelIds": ["Label_new"], "removeLabelIds": []})])
        self.assertEqual(self.g.held_threads(), {"a1"})
        self.assertEqual(os.stat(Path(self.tmp.name) / ".gmail" / "held-threads").st_mode & 0o777, 0o600)
        self.run_cmd("unhold", "a1")
        self.assertEqual(self.svc.modified[-1], ("a1", {"addLabelIds": [], "removeLabelIds": ["Label_new"]}))
        self.assertEqual(self.g.held_threads(), set())


if __name__ == "__main__":
    unittest.main()
