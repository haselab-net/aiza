"""The page's own scripts, as the page tests read them: every static/*.js
but the vendored libraries and the service worker (the deployment notes).
app.js may be split into several files (one <script> each); the checks go
over all of them, by name, never by one file's line numbers."""
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"
SKIP = {"sw.js"}


def sources():
    """{file name: text}, in name order."""
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(STATIC.glob("*.js")) if p.name not in SKIP}
