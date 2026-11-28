"""A closed room's seat keys stop at once (the public demo's audit L2,
2026-11-28): a seat key is good until the room's end, so when the door
closes a room early (by its owner, idle, by hand) it lists the room in
closed.json and the relay refuses its keys from then on, while another
room's keys still go through. Why this test: the two halves are separate
programs (docker/demo-host/aiza-demo-door and aiza-demo-relay) that only
meet in that file, so it runs the door's real close and then the relay's
real request handling against it.

    python3 -m unittest discover -s tests -v
"""
import asyncio
import importlib.machinery
import importlib.util
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

HOST_DIR = Path(__file__).resolve().parent.parent / "docker" / "demo-host"


def load(name, path):
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


class _Writer:
    def __init__(self):
        self.out = b""

    def get_extra_info(self, k):
        return ("10.77.0.9", 1234)

    def write(self, b):
        self.out += b

    async def drain(self):
        pass

    def close(self):
        pass


class ClosedRoomTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        (t / "state").mkdir()
        (t / "closed").mkdir()
        (t / "cred").mkdir()
        (t / "cred" / "relay.secret").write_text("s" * 64)
        (t / "cred" / "relay.json").write_text(json.dumps({"closed_file": str(t / "closed" / "closed.json")}))
        (t / "cred" / "anthropic.key").write_text("not-a-key")
        env = {"DOOR_STATE": str(t / "state"), "DOOR_CLOSED": str(t / "closed" / "closed.json"),
               "DOOR_HOST": "demo.example", "CREDENTIALS_DIRECTORY": str(t / "cred")}
        self.saved_env = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        self.door = load("aiza_demo_door", HOST_DIR / "aiza-demo-door")
        self.relay = load("aiza_demo_relay", HOST_DIR / "aiza-demo-relay")
        self.relay.configure()
        self.door.vmctl = lambda *a, **kw: type("P", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        self.ends = int(time.time()) + 3600
        with self.door.locked() as st:
            for rid in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):
                st["rooms"][rid] = {"ends": self.ends, "seats": {}}
            self.door.save(st)

    def tearDown(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def ask(self, room):
        key = self.relay.seat_key(room, "demo1", str(self.ends))
        req = (f"POST /anthropic/v1/messages HTTP/1.1\r\nHost: relay\r\nx-api-key: {key}\r\n\r\n").encode()

        async def go():
            r = asyncio.StreamReader()
            r.feed_data(req)
            r.feed_eof()
            w = _Writer()
            await self.relay.handle(r, w)
            return w.out
        out = asyncio.run(go())
        return int(out.split(b" ", 2)[1]), out

    def test_a_closed_rooms_keys_are_refused_at_once_and_others_go_on(self):
        self.assertEqual(self.ask("aaaaaaaaaaaa")[0], 411)      # open: past the key check (no body here)
        self.assertTrue(self.door.close_room("aaaaaaaaaaaa", "test"))
        code, out = self.ask("aaaaaaaaaaaa")
        self.assertEqual(code, 403)
        self.assertIn(b"closed", out)
        self.assertEqual(self.ask("bbbbbbbbbbbb")[0], 411)      # the other room: still good
        closed = Path(os.environ["DOOR_CLOSED"])
        self.assertEqual(oct(closed.stat().st_mode & 0o777), "0o644")   # the relay (another user) reads it

    def test_the_list_keeps_only_rooms_not_yet_ended(self):
        Path(os.environ["DOOR_CLOSED"]).write_text(json.dumps({"old000000000": int(time.time()) - 10}))
        self.door.close_room("bbbbbbbbbbbb", "test")
        self.assertEqual(json.loads(Path(os.environ["DOOR_CLOSED"]).read_text()), {"bbbbbbbbbbbb": self.ends})

    def test_no_list_is_none_closed_and_an_unreadable_one_closes_all(self):
        self.assertFalse(self.relay.room_closed("aaaaaaaaaaaa"))
        Path(os.environ["DOOR_CLOSED"]).write_text("{not json")
        self.assertTrue(self.relay.room_closed("aaaaaaaaaaaa"))
        self.assertEqual(self.ask("bbbbbbbbbbbb")[0], 403)


if __name__ == "__main__":
    unittest.main()
