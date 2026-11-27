"""Which lines of bin/aiza-backend (and the other Python tools in bin/) the
test suite never runs: the suite runs in this process under sys.monitoring
(Python 3.12+, no packages), every line event in those files is recorded, and
the lines with code that never ran are listed by the function they are in.
Not a test -- a map for where the next test should go.

    python3 tests/backend_coverage.py [--lines] [--file aiza-backend] [--out FILE]
"""
import dis
import os
import sys
import types
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] if Path(__file__).resolve().parent.name == "tests" else Path(os.environ["AIZA_ROOT"])
TOOL = sys.monitoring.COVERAGE_ID


def code_lines(code, out, names, outer="(top level)"):
    """Every line with code in this code object and the ones inside it."""
    name = outer if code.co_name == "<module>" else code.co_qualname
    for _, _, line in code.co_lines():
        if line is not None:
            out.add(line)
            names.setdefault(line, name)
    for c in code.co_consts:
        if isinstance(c, types.CodeType):
            code_lines(c, out, names, name)


def main():
    argv = sys.argv[1:]
    show_lines = "--lines" in argv
    only = argv[argv.index("--file") + 1] if "--file" in argv else None
    out = open(argv[argv.index("--out") + 1], "w") if "--out" in argv else sys.stdout   # the tests print too
    files = {str(p): p.name for p in sorted((ROOT / "bin").iterdir())
             if p.is_file() and not p.suffix and b"python3" in p.read_bytes()[:60].split(b"\n")[0]}
    if only:
        files = {k: v for k, v in files.items() if v == only}
    ran = defaultdict(set)

    def on_line(code, line):
        f = code.co_filename
        if f in files:
            ran[f].add(line)
        return sys.monitoring.DISABLE     # each (code, line) once is enough

    sys.monitoring.use_tool_id(TOOL, "aiza-coverage")
    sys.monitoring.register_callback(TOOL, sys.monitoring.events.LINE, on_line)
    sys.monitoring.set_events(TOOL, sys.monitoring.events.LINE)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "tests"))
    suite = unittest.TestLoader().discover(str(ROOT / "tests"), pattern="test*.py")
    result = unittest.TextTestRunner(stream=open(os.devnull, "w"), verbosity=0).run(suite)
    sys.monitoring.set_events(TOOL, 0)
    sys.monitoring.free_tool_id(TOOL)
    print = lambda *a: __builtins__.print(*a, file=out, flush=True)   # noqa: A001
    print(f"# tests: {result.testsRun} run, {len(result.failures)} failed, {len(result.errors)} errors")
    for path, name in sorted(files.items(), key=lambda kv: kv[1]):
        src = Path(path).read_text()
        lines, names = set(), {}
        code_lines(compile(src, path, "exec"), lines, names)
        never = sorted(lines - ran[path])
        print(f"{name}: {len(never)} of {len(lines)} code lines never ran")
        by = defaultdict(list)
        for ln in never:
            by[names[ln]].append(ln)
        for fn, lns in sorted(by.items(), key=lambda kv: -len(kv[1]))[:None if show_lines else 25]:
            print(f"  {len(lns):5d}  {fn}" + (f"  {lns}" if show_lines else ""))


if __name__ == "__main__":
    main()
