"""The logo (static/icons): every file the pages and the manifest name is
served by the gateway's icon route, and nothing else is.

    python3 -m unittest discover -s tests -v
"""
import json
import re
import unittest
from pathlib import Path

from test_gateway_login import G

STATIC = Path(__file__).resolve().parent.parent / "static"


class IconsTest(unittest.TestCase):
    def test_every_named_icon_is_served_and_exists(self):
        named = {i["src"] for i in json.loads((STATIC / "manifest.json").read_text())["icons"]}
        for f in ("index.html", "sw.js"):
            named |= set(re.findall(r"/agents/icons/[\w.-]+", (STATIC / f).read_text()))
        self.assertTrue(named)
        for src in named:
            name = src.removeprefix("/agents/icons/")
            self.assertIn(name, G.ICON_FILES, src)
            self.assertTrue((STATIC / "icons" / name).is_file(), src)

    def test_only_listed_names(self):
        for name in G.ICON_FILES:
            self.assertRegex(name, r"^(aiza[\w-]*\.(svg|png)|favicon\.ico)$")
            self.assertTrue((STATIC / "icons" / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
