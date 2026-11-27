"""One page test run: the stand-in backend (page_harness.serve) with the
given settings, the page opened at `start` in headless Chrome for `budget`
ms of virtual time, and what the probe wrote into the page back, with what
the page asked (log) and what it saved (folders, order)."""
import json
import re
import subprocess
import tempfile

from page_harness import serve
from test_page_flow import CHROME

STEPS = "  const steps = __STEPS__;"


def steps_js(steps):
    """[(js, wait ms)] as the probes' steps array."""
    return "[" + ",".join(f"[() => {{ {s} }}, {w}]" for s, w in steps) + "]"


def run_page(probe, settings=None, budget=8000, start="/agents/", static=None, height=1400):
    """static: another copy of the page's files (a check that the tests
    notice it broken)."""
    srv = serve(probe, **(settings or {}), **({"static": static} if static else {}))
    try:
        with tempfile.TemporaryDirectory() as prof:
            r = subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={prof}",
                                f"--virtual-time-budget={budget}", f"--window-size=420,{height}",
                                "--dump-dom", f"http://127.0.0.1:{srv.server_address[1]}{start}"],
                               capture_output=True, text=True, timeout=180)
    finally:
        srv.shutdown()
        srv.server_close()
    m = re.search(r'<pre id="probe-out">(.*?)</pre>', r.stdout, re.S)
    out = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")) \
        if m else {"unfinished": True}
    out["log"], out["folders"] = srv.state["log"], srv.state["folders"]
    return out


def posted(out, method_path):
    """The JSON bodies of every `<METHOD> <path>` the page sent."""
    method, path = method_path.split(" ", 1)
    return [b for m, p, b in out["log"] if m == method and p == path]
