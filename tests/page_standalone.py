"""A page outside the app (a page of its own under /agents/, no app.js), in
headless Chrome against the stand-in backend (page_harness): the page's
files are copied, the given ones put next to them, and the test's probe put
into the page -- stubs at its very start (before its own scripts), the steps
at its end. What the probe saw comes back as page_run.run_page gives it.
Used by the extensions' page tests (ext/<name>/tests)."""
import os
import shutil
import tempfile

from page_harness import STATIC
from page_run import run_page, steps_js

HEAD = r"""<script>
window.__errs = [];
addEventListener("error", (e) => window.__errs.push("error: " + e.message));
addEventListener("unhandledrejection", (e) => window.__errs.push("rejection: " + ((e.reason && e.reason.message) || e.reason)));
__STUBS__
</script>"""
PROBE = r"""<script>
(function () {
  const out = {};
  const text = (sel) => { const e = document.querySelector(sel); return e ? e.textContent.trim() : null; };
  const steps = __STEPS__;
  let i = 0;
  function next() {
    if (i === steps.length) {
      out.errors = window.__errs;
      const pre = document.createElement("pre"); pre.id = "probe-out";
      pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
      return;
    }
    const [fn, wait] = steps[i++];
    try { fn(); } catch (e) { out.thrown = String(e); }
    setTimeout(next, wait);
  }
  setTimeout(next, 800);
})();
</script>"""
EVERY = lambda body: [{"every": True, "body": body}]


def run_standalone(files, page, stubs, faults, steps, static=None):
    """files: {path under /agents/: a file to put there, or its text};
    page: the URL to open (/agents/<one of them>?...); stubs: JS run first
    in the page; faults: the stand-in's answers; steps: [(js, wait ms)],
    the first 800 ms after the page has loaded, `out` and `text(sel)` at hand."""
    with tempfile.TemporaryDirectory() as d:
        copy = os.path.join(d, "static")
        shutil.copytree(static or STATIC, copy)
        for rel, src in files.items():
            dst = os.path.join(copy, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.isdir(str(src)):
                shutil.copytree(src, dst, dirs_exist_ok=True)
            elif os.path.isfile(str(src)):
                shutil.copy(src, dst)
            else:
                with open(dst, "w", encoding="utf-8") as fh:
                    fh.write(src)
        p = os.path.join(copy, page.split("/agents/", 1)[1].split("?")[0])
        with open(p, encoding="utf-8") as fh:
            html = fh.read()
        head = HEAD.replace("__STUBS__", stubs)
        html = html.replace("<head>", "<head>" + head, 1) if "<head>" in html else head + html
        probe = PROBE.replace("__STEPS__", steps_js(steps))
        html = html.replace("</body>", probe + "</body>", 1) if "</body>" in html else html + probe
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(html)
        return run_page("", {"faults": faults}, 3000 + sum(w for _, w in steps), start=page, static=copy)
