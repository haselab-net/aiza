"""Which code of the page's scripts the page flows (tests/test_page_flow.py)
the failure cases (tests/test_page_failures.py) and the others never run (the deployment notes): every flow in headless Chrome with V8's block
coverage on, the runs merged, and the lines no flow reached listed by the
function they are in. Not a test -- a map for where the next flow or test
should go.

    python3 tests/page_coverage.py            # summary by function
    python3 tests/page_coverage.py --lines    # and every line no flow ran
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_harness import serve  # noqa: E402
from page_sources import sources  # noqa: E402
from test_page_flow import CHROME, FLOWS, PROBE  # noqa: E402
import test_page_app  # noqa: E402
import test_page_chat  # noqa: E402
import test_page_speak  # noqa: E402
import test_page_voice  # noqa: E402
import test_page_failures  # noqa: E402
import test_page_late  # noqa: E402
import test_page_form  # noqa: E402
import test_page_links  # noqa: E402
import test_page_list  # noqa: E402
import test_page_tree  # noqa: E402
import test_page_folders  # noqa: E402
import test_page_first_use  # noqa: E402
import test_page_share  # noqa: E402
import test_page_todo  # noqa: E402
import test_page_tree_views  # noqa: E402
from test_page_flow import KEEP_PROBE, LIST_KEEP_PROBE  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "static"
FILES = list(sources())


class Pipe:
    """Chrome DevTools over --remote-debugging-pipe (fd 3 in, fd 4 out,
    one JSON message per NUL)."""

    def __init__(self, prof):
        r1, w1 = os.pipe()   # we -> chrome (its fd 3)
        r2, w2 = os.pipe()   # chrome -> we (its fd 4)

        def child():
            # through fds out of the way first: r1/w2 may themselves be 3 or 4
            a, b = os.dup(r1), os.dup(w2)
            a2, b2 = os.dup2(a, 100), os.dup2(b, 101)
            os.dup2(a2, 3)
            os.dup2(b2, 4)
            os.set_inheritable(3, True)
            os.set_inheritable(4, True)
        self.proc = subprocess.Popen([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
                                      f"--user-data-dir={prof}", "--remote-debugging-pipe", "--window-size=420,800",
                                      "about:blank"], preexec_fn=child, close_fds=False,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.close(r1)
        os.close(w2)
        self.w = os.fdopen(w1, "wb", buffering=0)
        self.r = os.fdopen(r2, "rb", buffering=0)
        self.buf = b""
        self.n = 0
        self.events = []

    def read(self):
        while b"\0" not in self.buf:
            chunk = self.r.read(1 << 16)
            if not chunk:
                raise EOFError("chrome went away")
            self.buf += chunk
        msg, self.buf = self.buf.split(b"\0", 1)
        return json.loads(msg)

    def call(self, method, params=None, session=None):
        self.n += 1
        m = {"id": self.n, "method": method, "params": params or {}}
        if session:
            m["sessionId"] = session
        self.w.write(json.dumps(m).encode() + b"\0")
        while True:
            msg = self.read()
            if msg.get("id") == self.n:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
            self.events.append(msg)

    def wait(self, method):
        for i, e in enumerate(self.events):
            if e.get("method") == method:
                return self.events.pop(i)
        while True:
            msg = self.read()
            if msg.get("method") == method:
                return msg
            self.events.append(msg)

    def close(self):
        try:
            self.call("Browser.close")
        except Exception:
            pass
        self.proc.wait(timeout=20)


def jobs():
    """(name, probe, start, the stand-in's settings, budget ms) for every page
    test: the flows, the failure, late and chat cases, the list's, the links' and the form's, the tree's, the kept panels."""
    out = [(name, PROBE.replace("__STEPS__", json.dumps([[a, arg] for a, arg, _ in steps])), start, {},
            4000 + 1200 * len(steps)) for name, (start, steps) in FLOWS.items()]
    steps_js = lambda steps: "[" + ",".join(f"[() => {{ {s} }}, {w}]" for s, w in steps) + "]"
    for cases in (test_page_failures.CASES, test_page_late.CASES, test_page_chat.CASES, test_page_speak.CASES, test_page_voice.CASES):
        for name, (faults, steps) in cases.items():
            out.append((name, test_page_failures.PROBE.replace("__STEPS__", steps_js(steps)), f"#{test_page_failures.S0}",
                        {"faults": faults}, 4000 + sum(w for _, w in steps)))
    for name, (folders, steps) in test_page_list.CASES.items():
        probe = test_page_failures.PROBE.replace("  const steps = __STEPS__;",
                                                 test_page_list.HELPERS + "  const steps = " + steps_js(steps) + ";")
        out.append((name, probe, "", {"folders": folders}, 4000 + sum(w for _, w in steps)))
    for cases in (test_page_links.CASES, test_page_form.CASES):
        for name, (faults, steps) in cases.items():
            probe = test_page_failures.PROBE.replace("  const steps = __STEPS__;",
                                                     test_page_list.HELPERS + "  const steps = " + steps_js(steps) + ";")
            out.append((name, probe, "", {"faults": faults}, 4000 + sum(w for _, w in steps)))
    for name, steps in test_page_tree.CASES.items():
        out.append((name, test_page_tree.PROBE.replace("__STEPS__", steps_js(steps)), "",
                    {"folders": test_page_tree.FOLDERS, "tree_extra": test_page_tree.EXTRA}, 6000 + sum(w for _, w in steps)))
    # test_page_folders, _share, _todo, _tree_views: (settings, steps); the todo's are faults only
    for mod in (test_page_folders, test_page_share):
        for name, (settings, steps) in mod.CASES.items():
            out.append((name, mod.probe(steps), "", settings, 4000 + sum(w for _, w in steps)))
    for name, (faults, steps) in test_page_todo.CASES.items():
        out.append((name, test_page_todo.probe(steps), "", {"faults": faults}, 4000 + sum(w for _, w in steps)))
    for name, (faults, steps) in test_page_tree_views.CASES.items():
        out.append((name, test_page_tree_views.probe(steps), "",
                    {"faults": faults, "folders": test_page_tree.FOLDERS, "tree_extra": test_page_tree_views.EXTRA},
                    6000 + sum(w for _, w in steps)))
    for name, (faults, steps) in test_page_first_use.MAIN.items():
        out.append((name, test_page_failures.PROBE.replace("__STEPS__", steps_js(steps)), "",
                    {"faults": faults}, 4000 + sum(w for _, w in steps)))
    # test_page_app: the ones that need no extra files served
    for name, (faults, steps, extra) in test_page_app.CASES.items():
        if not extra:
            out.append((name, test_page_failures.PROBE.replace("__STEPS__", steps_js(steps)), "",
                        {"faults": faults}, 4000 + sum(w for _, w in steps)))
    out += [("tree keeps", KEEP_PROBE, "", {}, 60000), ("list keeps", LIST_KEEP_PROBE, "", {}, 60000)]
    return out


def run(name, probe, start, settings, budget):
    srv = serve(probe, **settings)
    try:
        with tempfile.TemporaryDirectory() as prof:
            p = Pipe(prof)
            try:
                target = next(t for t in p.call("Target.getTargets")["targetInfos"] if t["type"] == "page")
                s = p.call("Target.attachToTarget", {"targetId": target["targetId"], "flatten": True})["sessionId"]
                p.call("Page.enable", session=s)
                p.call("Profiler.enable", session=s)
                p.call("Profiler.startPreciseCoverage", {"callCount": False, "detailed": True}, session=s)
                p.call("Emulation.setVirtualTimePolicy", {"policy": "pause"}, session=s)
                path = start if start.startswith("/") else f"/agents/{start}"
                p.call("Page.navigate", {"url": f"http://127.0.0.1:{srv.server_address[1]}{path}"}, session=s)
                p.call("Emulation.setVirtualTimePolicy", {"policy": "pauseIfNetworkFetchesPending",
                                                         "budget": budget}, session=s)
                p.wait("Emulation.virtualTimeBudgetExpired")
                out = p.call("Runtime.evaluate", {"expression": "(document.getElementById('probe-out')||{}).textContent||''",
                                                  "returnByValue": True}, session=s)["result"].get("value")
                cov = p.call("Profiler.takePreciseCoverage", session=s)["result"]
            finally:
                p.close()
    finally:
        srv.shutdown()
        srv.server_close()
    return out, cov


def ran_bytes(cov, name, size):
    """1 for every byte of static/<name> this run executed."""
    ranges = []
    for script in cov:
        if script["url"].split("?")[0].endswith("/agents/" + name):
            for f in script["functions"]:
                ranges += [(r["startOffset"], r["endOffset"], r["count"]) for r in f["ranges"]]
    ranges.sort(key=lambda r: (r[0], -r[1]))   # outer first: an inner range overrides it
    got = bytearray(size)
    for a, b, n in ranges:
        b = min(b, size)
        got[a:b] = (b"\1" if n else b"\0") * (b - a)
    return got


def main():
    show_lines = "--lines" in sys.argv
    with ThreadPoolExecutor(max_workers=4) as pool:
        js = jobs()
        results = list(pool.map(lambda j: run(*j), js))
    # one that did not finish is run once more, alone (four Chromes at once can
    # leave one short of its virtual time: 2026-11-24, once in 83, then 6 of 6)
    results = [r if r[0] else run(*j) for j, r in zip(js, results)]
    names = [j[0] for j in js]
    bad = [n for n, (out, _) in zip(names, results) if not out]
    for name in FILES:
        # V8's offsets count UTF-16 units: work on the text as such.
        text = (STATIC / name).read_text(encoding="utf-8")
        units = text.encode("utf-16-le")
        size = len(units) // 2
        ran = bytearray(size)
        for _, cov in results:
            got = ran_bytes(cov, name, size)
            ran = bytearray(x | y for x, y in zip(ran, got))
        # line -> whether any code on it ran / none did
        lines = text.split("\n")
        pos = 0
        missed = []
        for i, line in enumerate(lines):
            n = len(line.encode("utf-16-le")) // 2
            code = line.strip()
            if code and not code.startswith("//") and code not in ("}", "});", "};", "})", "]", "],", ")", ");"):
                seg = ran[pos:pos + n]
                if not any(seg):
                    missed.append(i)
            pos += n + 1
        total = sum(1 for l in lines if l.strip() and not l.strip().startswith("//"))
        print(f"{name}: {len(missed)} of {total} code lines never ran in {len(results)} runs")
        # by the innermost named function each missed line is in
        spans = []
        for i, l in enumerate(lines):
            m = re.match(r"^(\s*)(?:async\s+)?function\s+(\w+)", l)
            if m:
                ind = len(m.group(1))
                end = next((k for k in range(i + 1, len(lines)) if lines[k].startswith(" " * ind + "}")
                            and len(lines[k]) - len(lines[k].lstrip()) == ind), len(lines))
                spans.append((i, end, m.group(2)))
        fn_at = {}
        for i in missed:
            inner = [sp for sp in spans if sp[0] <= i <= sp[1]]
            fn_at[i] = max(inner)[2] if inner else "(top level)"
        by = {}
        for i in missed:
            by.setdefault(fn_at[i], []).append(i + 1)
        for fn, ls in sorted(by.items(), key=lambda kv: -len(kv[1])):
            print(f"  {len(ls):4d}  {fn}" + (f"  {ls}" if show_lines else ""))
    if bad:
        print("flows whose probe did not finish:", bad)


if __name__ == "__main__":
    main()
