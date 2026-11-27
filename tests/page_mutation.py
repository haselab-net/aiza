"""Do the page flows notice when a way between pages breaks?
(the deployment notes) For every entry of tests/test_page_entries.py's
table, its calls (tests/page_entries.py's sites) are made to do nothing in a
copy of static/, and the flow the table names for it is run on that copy.
The flow must fail: a step lands on another page, the page's own check or
a script error complains, or a step finds nothing to press. An entry whose
flow still passes ("survived") is run but not checked -- its flow needs a
step that looks at what that entry does.

Not part of the suite (one Chrome run per entry, a few minutes):

    python3 tests/page_mutation.py [<part of an entry's name> ...]
"""
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from page_entries import ALIAS, sites  # noqa: E402
from page_sources import STATIC  # noqa: E402
from test_page_entries import ENTRIES, NOT_RUN  # noqa: E402
from test_page_flow import FLOWS, PageFlowTest, seen  # noqa: E402

NOOP = "(() => undefined)("
# Entries done twice for one move, so breaking one alone changes nothing:
# "<caller> -> <fn>": what else does it. None since 2026-11-24 (Back from a
# session: popstate and hashchange each closed it / opened 設定; now popstate
# alone does).
DOUBLE = {
}


def mutant(key, where, into):
    """A copy of static/ in `into` with each call of `key` doing nothing."""
    shutil.copytree(STATIC, into, dirs_exist_ok=True, ignore=shutil.ignore_patterns("icons"))
    (Path(into) / "icons").symlink_to(STATIC / "icons")
    fn = key.split(" -> ")[1]
    by_file = {}
    for name, i, col in where:
        by_file.setdefault(name, []).append((i, col))
    for name, spots in by_file.items():
        p = Path(into) / name
        lines = p.read_text(encoding="utf-8").split("\n")
        for i, col in sorted(spots, reverse=True):   # right to left: the columns stay right
            line = lines[i]
            tok = next((x for x in [fn] + [a for a, f in ALIAS.items() if f == fn] if line[col:col + len(x) + 1] == x + "("), None)
            assert tok, (key, name, i)
            lines[i] = line[:col] + NOOP + line[col + len(tok) + 1:]
        p.write_text("\n".join(lines), encoding="utf-8")


def caught(key):
    flow = ENTRIES[key]
    start, steps = FLOWS[flow]
    with tempfile.TemporaryDirectory() as d:
        mutant(key, sites()[key], d)
        got = PageFlowTest("test_flows").try_flow_on(start, steps, d)
    if isinstance(got, Exception):
        return True, f"{type(got).__name__}"
    if got.get("missing"):
        return True, "missing " + got["missing"]
    if got["errors"]:
        return True, got["errors"][0][:80]
    if seen(got, steps) != [w for _, _, w in steps]:
        return True, f"seen {seen(got, steps)}"
    return False, "the flow still passes"


def main():
    want = sys.argv[1:]
    keys = [k for k, v in ENTRIES.items() if not v.startswith(NOT_RUN) and (not want or any(w in k for w in want))]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(caught, keys))
    survived = [(k, why) for k, (ok, why) in zip(keys, results) if not ok and k not in DOUBLE]
    for k, (ok, why) in zip(keys, results):
        tag = "caught    " if ok else "double    " if k in DOUBLE else "SURVIVED  "
        print(tag + f"{k}  [{ENTRIES[k]}]  {why}" + (f" ({DOUBLE[k]})" if not ok and k in DOUBLE else ""))
    print(f"\n{sum(1 for ok, _ in results if ok)} of {len(keys)} broken entries caught by their flow,"
          f" {sum(1 for k, (ok, _) in zip(keys, results) if not ok and k in DOUBLE)} known double,"
          f" {len(survived)} survived")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()
