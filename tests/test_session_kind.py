"""The page's sessionKind(meta) (static/app.js): what a session is, decided
once (2026-11-23, the user: 分岐が早めに合流して組み合わせ爆発が起きないの
が良い). Checked against every preset the backend can store, so a new preset
is covered without editing this file: root exactly where it runs as root,
the place from where it runs, the program from the preset or meta.launch.

    python3 -m unittest discover -s tests -v
"""
import json
import shutil
import subprocess
import unittest

from page_sources import sources
from test_shared_search import B

APP = "\n".join(sources().values())   # sessionKind is in page.js, the presets in app.js


def piece(start, end):
    return start + APP.split(start, 1)[1].split(end, 1)[0]


@unittest.skipUnless(shutil.which("node"), "node is needed for page function tests")
class SessionKindTest(unittest.TestCase):
    def kinds(self, metas):
        src = "\n".join([
            piece("  const MAIL_PRESETS_UI = ", ";\n") + ";",
            piece("  const HEADLESS_PRESETS = ", ";\n") + ";",
            "let desktopBase = {};",
            piece("  function sessionMachine(meta) {", "\n  }\n") + "\n  }",
            piece("  function sessionKind(meta) {", "\n  }\n") + "\n  }",
            "console.log(JSON.stringify(" + json.dumps(metas) + ".map(sessionKind)));",
        ])
        out = subprocess.run(["node", "-e", src], text=True, capture_output=True, check=True)
        return json.loads(out.stdout)

    def test_every_backend_preset(self):
        metas = []
        for name, p in B.TMUX_PRESETS.items():
            metas.append({"preset": name, "tmux_location": p["location"]})
        for name, (base, launch) in B.LAUNCH_PRESETS.items():
            loc = B.TMUX_PRESETS.get(base, {}).get("location", "container")
            metas.append({"preset": base, "tmux_location": loc, "launch": launch, "_as": name})
        metas.append({"preset": "claude", "tmux_location": "container"})
        metas.append({"preset": "shell-gpu1", "tmux_location": "ssh:gpu1"})
        metas.append({"preset": "claude-tui-gpu1", "tmux_location": "ssh:gpu1"})
        for m, k in zip(metas, self.kinds([{k: v for k, v in m.items() if k != "_as"} for m in metas])):
            what = m.get("_as") or m["preset"]
            loc = m["tmux_location"]
            self.assertEqual(k["root"], loc == "root", what)
            if m["preset"] in ("mail-tui", "mail-shell"):
                self.assertEqual(k["place"], "mail", what)
            else:
                self.assertEqual(k["place"], {"root": "root", "host": "host"}.get(loc, "ssh" if loc.startswith("ssh:") else "dev"), what)
            if m.get("launch"):
                self.assertEqual(k["ai"], m["launch"], what)
            if "login" in m["preset"]:
                self.assertTrue(k["login"], what)
                self.assertIsNone(k["ai"], what)

    def test_table(self):
        rows = [
            ({"preset": "root-shell", "tmux_location": "root"},
             {"place": "root", "root": True, "ai": None, "localShell": True, "tui": False}),
            ({"preset": "root-shell", "tmux_location": "root", "launch": "claude"},
             {"place": "root", "root": True, "ai": "claude", "localShell": True}),
            ({"preset": "claude-login-root", "tmux_location": "root"},
             {"place": "root", "root": True, "login": True, "ai": None}),
            ({"preset": "host-shell", "tmux_location": "host", "launch": "codex"},
             {"place": "host", "root": False, "ai": "codex", "localShell": True}),
            ({"preset": "mail-shell", "tmux_location": "host", "launch": "codex"},
             {"place": "mail", "ai": "codex", "localShell": False}),
            ({"preset": "mail-tui", "tmux_location": "container"},
             {"place": "mail", "ai": "claude", "tui": False}),
            ({"preset": "codex-tui", "tmux_location": "container"},
             {"place": "dev", "ai": "codex", "tui": True}),
            ({"preset": "claude-tui-gpu1", "tmux_location": "ssh:gpu1"},
             {"place": "ssh", "ai": "claude", "tui": True, "machine": "gpu1"}),
            ({"preset": "claude", "tmux_location": "container"},
             {"place": "dev", "ai": "claude", "headless": True}),
            ({}, {"place": "dev", "root": False, "ai": None}),
        ]
        for (meta, want), got in zip(rows, self.kinds([r[0] for r in rows])):
            for k, v in want.items():
                self.assertEqual(got[k], v, (meta, k))


@unittest.skipUnless(shutil.which("node"), "node is needed for page function tests")
class FormPresetsTest(unittest.TestCase):
    """FORM_PRESETS: one row per preset the new-session form starts, agreeing
    with what the backend does with each (2026-11-23, five lists before)."""

    def form(self, presets, ssh=()):
        src = "\n".join([
            "let sshCwdMachines = " + json.dumps(list(ssh)) + ";",
            piece("  const FORM_PRESETS = ", "\n  };\n") + "\n  };",
            piece("  function presetForm(p) {", "\n  }\n") + "\n  }",
            piece("  const KIND_PLACE = ", "\n  };\n") + "\n  };",
            "console.log(JSON.stringify({kp: KIND_PLACE, f: " + json.dumps(presets) + ".map(presetForm)}));",
        ])
        out = subprocess.run(["node", "-e", src], text=True, capture_output=True, check=True)
        return json.loads(out.stdout)

    def test_agrees_with_backend(self):
        r = self.form([])
        offered = {p for row in r["kp"].values() for p in row.values()}
        names = sorted(offered | {"claude", "codex-tui"})
        got = dict(zip(names, self.form(names)["f"]))
        for p in offered:
            self.assertIsNotNone(got[p]["picker"], p)       # every offered preset has a row
        for p, f in got.items():
            base, launch = B.LAUNCH_PRESETS.get(p, (p, None))
            # the cwd/resume shape create_session takes for it
            if base in B.CWD_PRESETS:
                self.assertEqual((f["picker"], f["resume"]), ("claude", True), p)
            elif base in B.SHELL_CWD_PRESETS:
                self.assertEqual(f["picker"], "shell", p)
                self.assertEqual(f["resume"], False, p)
            if f["picker"] == "shell":
                loc = B.TMUX_PRESETS.get(base, {}).get("location", "container")
                self.assertEqual(f["scope"], {"container": "sandhome"}.get(loc, loc), p)
            # never the skip row as root with Claude (the backend drops it)
            if base == "root-shell" and launch == "claude":
                self.assertIsNone(f["skip"], p)

    def test_machine_claude(self):
        r = self.form(["claude-tui-winbox", "claude-tui-linuxbox", "nope"], ssh=["winbox"])["f"]
        self.assertEqual((r[0]["picker"], r[0]["resume"]), ("ssh", True))
        self.assertIsNone(r[1]["picker"])
        self.assertEqual(r[2], {"picker": None, "scope": None, "resume": False, "skip": None})


if __name__ == "__main__":
    unittest.main()
