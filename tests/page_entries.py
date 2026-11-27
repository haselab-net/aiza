"""Where app.js moves between pages: every call of a page-moving function,
keyed "<caller> -> <function>". The caller is the named function around the
call, or for a listener at the top level "on <target> <event>". Used by
tests/test_page_entries.py (the deployment notes)."""
import collections
import re

from page_sources import sources

NAV = ["showPage", "openSession", "closeSession", "openAuthView", "showTodoView", "hideTodoView",
       "applyMachineFilter", "selectMachine", "openBoardMachine", "setTodo", "openBoard", "closeBoard"]
# chat.js's entry for the open session (the deployment notes): the other
# files open and close it through chatNow, which counts as the call itself.
ALIAS = {"chatNow.open": "openSession", "chatNow.close": "closeSession"}
_DEF = re.compile(r"^(\s*)(?:async\s+)?function\s+(\w+)\s*\(")
_LISTEN = re.compile(r"^\s{0,4}([\w.()\"'#-]+?)\.addEventListener\(\"(\w+)\"")
_METHOD = re.compile(r"^\s{4}(?:async\s+)?(\w+)(?:\([^)]*\)\s*\{|:\s*\()")


def entries():
    c = collections.Counter()
    for k, where in sites().items():
        c[k] = len(where)
    return c


def sites():
    """"<caller> -> <function>": [(file, line index, column)] of each call."""
    out = collections.defaultdict(list)
    for name, text in sources().items():
        for k, i, col in _sites(text):
            out[k].append((name, i, col))
    return out


def _sites(text):
    lines = text.split("\n")
    spans = []   # (start, end, indent, name) of named functions
    for i, l in enumerate(lines):
        m = _DEF.match(l)
        if not m:
            continue
        ind = len(m.group(1))
        end = next((k for k in range(i + 1, len(lines))
                    if lines[k].startswith(" " * ind + "}") and len(lines[k]) - len(lines[k].lstrip()) == ind), len(lines))
        spans.append((i, end, ind, m.group(2)))

    def caller(i):
        inner = [s for s in spans if s[0] < i <= s[1]]
        if inner:
            return max(inner, key=lambda s: s[0])[3]
        for j in range(i, max(-1, i - 200), -1):
            m = _LISTEN.match(lines[j])
            if m:
                ind = len(lines[j]) - len(lines[j].lstrip())
                end = next((k for k in range(j + 1, len(lines))
                            if len(lines[k]) - len(lines[k].lstrip()) == ind and lines[k].strip().startswith("}")), len(lines))
                if i > end:
                    break   # that listener ended above: the call is plain top-level code
                target = re.sub(r'document\.getElementById\("([\w-]+)"\)', r"#\1", m.group(1))
                return f"on {target} {m.group(2)}"
            m = _METHOD.match(lines[j])
            if m and j < i:
                return f"app.{m.group(1)}"   # the page's API for extensions (aizaExt.app)
            if m and j == i:
                return f"app.{m.group(1)}"
        for j in range(i, -1, -1):   # the top-level statement it is in
            if re.match(r"^  \S", lines[j]) and not lines[j].strip().startswith(("}", "//")):
                return "top: " + lines[j].strip()[:40]
        return "(top)"

    for i, l in enumerate(lines):
        if l.strip().startswith("//"):
            continue
        if re.match(r"^\s*(?:" + "|".join(a.split(".")[1] for a in ALIAS) + r"):\s*\(", l):
            continue   # chatNow's own open / close: they pass the call on, not a way of their own
        for f in NAV:
            for m in re.finditer(r"(?<![\w.])" + f + r"\(", l):
                if re.match(r"^\s*(?:async\s+)?function\s+" + f + r"\b", l):
                    continue
                yield f"{caller(i)} -> {f}", i, m.start()
        for al, f in ALIAS.items():
            for m in re.finditer(r"(?<![\w.])" + re.escape(al) + r"\(", l):
                yield f"{caller(i)} -> {f}", i, m.start()


if __name__ == "__main__":
    for k, n in sorted(entries().items()):
        print(f"{n} {k}")
