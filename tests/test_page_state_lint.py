"""the deployment notes: which page is shown is changed only by
showPage() and read only from currentPage. Anything else touching the
pages' display -- the cause of the settings page staying on screen with
the machine menu saying this host (2026-11-23) -- fails here.

    python3 -m unittest discover -s tests -v
"""
import re
import unittest

from page_sources import sources

PAGE_STYLE = re.compile(r"\b(viewList|viewChat|viewAuth|topHeaderEl)\.style\.display\b")


def body(text, name):
    if f"  function {name}(" not in text:
        return (-1, -1)
    start = text.index(f"  function {name}(")
    return start, text.index("\n  }\n", start)


class PageStateLintTest(unittest.TestCase):
    def test_only_show_page_and_check_page(self):
        stray = []
        found = 0
        for name, src in sources().items():
            allowed = [body(src, "showPage"), body(src, "checkPage")]
            found += sum(1 for a, _ in allowed if a >= 0)
            for m in PAGE_STYLE.finditer(src):
                if any(a <= m.start() <= b for a, b in allowed):
                    continue
                line = src.count("\n", 0, m.start()) + 1
                text = src.splitlines()[line - 1].strip()
                if text.startswith("//"):
                    continue
                stray.append(f"{name}:{line}: {text[:100]}")
        self.assertEqual(found, 2, "showPage and checkPage, once each")
        self.assertEqual(stray, [], "use showPage()/currentPage instead")


if __name__ == "__main__":
    unittest.main()
