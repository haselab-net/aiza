"""The display language (the deployment notes): every word the pages show has a key,
"<area>.<name>", and its Japanese, English and Simplified Chinese side by
side (none of them the source). The code says t("<key>"), the markup
data-i18n="<key>", and a message the server makes carries its key. Needs node.

    python3 -m unittest discover -s tests -v
"""
import html.parser
import json
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
# The deployment's own pages: the site extension's (ext/site), or, in an
# older layout, the ai-sandbox-server mirror's (the deployment notes).
SITE = next((d for d in (ROOT / "ext" / "site" / "host" / "opt" / "aiza" / "static", ROOT.parent / "opt" / "aiza" / "static")
             if d.is_dir()), ROOT / "ext" / "site" / "host" / "opt" / "aiza" / "static")
# Those that show in the reader's language.
SITE_I18N = ("login.html", "email-unlock.html", "passkey-register.html", "signup.html", "signup_done.html", "not_registered.html")
# The extensions' page files (ext/README.md) define their own words the same way.
EXT_JS = sorted((ROOT / "ext").glob("*/static/*.js"))
EXTS = {p.name for p in (ROOT / "ext").iterdir() if p.is_dir()}
SITE_PAGES = [SITE / n for n in SITE_I18N if (SITE / n).exists()]
PAGE_JS = [f for f in sorted(STATIC.glob("*.js")) if f.name not in ("sw.js", "i18n.js")]
HTML = [STATIC / "index.html", STATIC / "outbox-browse.html"] + SITE_PAGES
LANGS = ("ja", "en", "zh-CN")
KEY = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)+$")
JA = re.compile(r"[぀-ヿ㐀-鿿]")
BLOCK = re.compile(r"/\* i18n-begin \*/([\s\S]*?)/\* i18n-end \*/")
VOID = ("br", "img", "input", "meta", "link", "hr", "source", "wbr", "area", "base", "col", "embed", "track")

DUMP = """
global.window = {}; global.document = { documentElement: {} };
global.localStorage = { getItem: () => process.argv[2], setItem() {} };
require(process.argv[1]);
const i = window.aizaI18n;
const core = Object.keys(i._words);
// The deployment pages' and extensions' own words, the same define() they make in the page.
for (const f of process.argv.slice(3)) {
  const src = require("fs").readFileSync(f, "utf8");
  for (const m of src.matchAll(/\\/\\* i18n-begin \\*\\/([\\s\\S]*?)\\/\\* i18n-end \\*\\//g)) eval(m[1]);
}
console.log(JSON.stringify({ words: i._words, core, lang: i.lang(),
  sample: i.t("links.link_b", { a: "X", b: "Y" }),
  missing: i.t("no.such_key"),
  old: i.fromText(i._words["auth.login.claude_first"].ja) }));
"""


def node(lang, extra=True):
    out = subprocess.run(["node", "-e", DUMP, str(STATIC / "i18n.js"), lang]
                         + ([str(p) for p in EXT_JS + SITE_PAGES] if extra else []),
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def t_literals(files):
    """Every string literal t() is called with directly."""
    out = set()
    for f in files:
        for m in re.finditer(r"""(?<![\w.$])t\(\s*(["'])((?:(?!\1)[^\\\n]|\\.)*)\1""", f.read_text()):
            out.add(m.group(2))
    return out


class Markup(html.parser.HTMLParser):
    """data-i18n keys, and Japanese text or attributes the markup shows with no key."""

    def __init__(self):
        super().__init__()
        self.keys, self.bare, self.stack, self.skip = set(), [], [], 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style"):
            self.skip += 1
        for k, v in a.items():
            if k.startswith("data-i18n") and v:
                self.keys.add(v)
            if k in ("title", "placeholder", "aria-label") and v and JA.search(v) and f"data-i18n-{k}" not in a:
                self.bare.append(f"{tag}[{k}]: {v}")
        if tag not in VOID:
            self.stack.append("data-i18n" in a)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        if self.stack and tag not in VOID:
            self.stack.pop()

    def handle_data(self, d):
        if not self.skip and JA.search(d) and not (self.stack and self.stack[-1]) and "__" not in d:
            self.bare.append(d.strip()[:60])


def markup(f):
    p = Markup()
    p.feed(f.read_text())
    return p


class I18nTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = node("en")
        cls.words = cls.d["words"]

    def test_every_key_used_is_defined(self):
        lits = t_literals(PAGE_JS + EXT_JS + [STATIC / "outbox-browse.html"] + SITE_PAGES)
        self.assertGreater(len(lits), 400)
        self.assertEqual(sorted(k for k in lits if JA.search(k)), [], "Japanese in t(): give the word a key")
        self.assertEqual(sorted(k for k in lits if not KEY.match(k)), [], "t() is called with a key")
        self.assertEqual(sorted(k for k in lits if k not in self.words), [])
        for f in HTML:
            with self.subTest(f.name):
                self.assertEqual(sorted(k for k in markup(f).keys if k not in self.words), [])

    def test_every_word_has_three_languages_with_the_same_names(self):
        for k, w in self.words.items():
            self.assertRegex(k, KEY)
            self.assertEqual(sorted(w), sorted(LANGS), k)
            for lang in LANGS:
                self.assertTrue(isinstance(w[lang], str) and w[lang], (k, lang))
            names = {lang: set(re.findall(r"\{(\w+)\}", w[lang])) for lang in LANGS}
            self.assertEqual(names["en"], names["ja"], k)
            self.assertEqual(names["zh-CN"], names["ja"], k)

    def test_no_key_is_defined_twice(self):
        seen = {}
        for f in [STATIC / "i18n.js"] + EXT_JS + SITE_PAGES:
            for m in BLOCK.finditer(f.read_text()):
                for k in re.findall(r'^\s*"([a-z][a-z0-9_.]+)": \{$', m.group(1), re.M):
                    self.assertNotIn(k, seen, f"{k}: {f.name} and {seen.get(k)}")
                    seen[k] = f.name
        self.assertEqual(len(seen), len(self.words))

    def test_every_key_is_used(self):
        # A key is named somewhere outside the dictionaries: t("…") or a table
        # t() is given (a "…" literal), data-i18n="…", or the server's messages.
        text = ""
        mjs = sorted(p for p in ROOT.rglob("*.mjs") if "node_modules" not in p.parts and "test" not in p.parts)
        for f in PAGE_JS + EXT_JS + HTML + [SITE / "email-off.html", ROOT / "bin" / "aiza-backend", ROOT / "ext" / "site" / "gateway.py"] + mjs:
            text += BLOCK.sub("", f.read_text())
        unused = sorted(k for k in self.words if f'"{k}"' not in text and f"'{k}'" not in text)
        self.assertEqual(unused, [])

    def test_the_markup_has_no_word_without_a_key(self):
        for f in HTML:
            with self.subTest(f.name):
                self.assertEqual(markup(f).bare, [])

    def test_t(self):
        self.assertEqual(self.d["sample"], "Link “X” and “Y”.")
        self.assertEqual(node("zh-CN")["sample"], "将连接「X」与「Y」。")
        self.assertEqual(node("ja")["sample"], "「X」と「Y」をつなぎます。")
        self.assertEqual(self.d["missing"], "no.such_key")
        self.assertEqual(node("xx")["lang"], "ja")  # unknown stored value

    def test_the_servers_messages_are_keys(self):
        # What a login pane's chat says first (aiza-backend LOGIN_SAY): the
        # event carries the key; one saved before keys is found by its text.
        from test_shared_search import B
        for k in B.LOGIN_SAY.values():
            self.assertIn(k, self.words)
        self.assertEqual(B.login_say("claude", "first"), {"type": "system", "msg": {"key": "auth.login.claude_first", "vars": {}}})
        self.assertEqual(self.d["old"], "auth.login.claude_first")

    def test_core_dictionary_has_no_deployment_words(self):
        # The published core must not carry this deployment's own pages
        # (the deployment notes): those define() their words themselves.
        for k in node("en", extra=False)["core"]:
            self.assertFalse(k.split(".")[0] in EXTS, k)
            self.assertNotIn("strongSwan", self.words[k]["en"])
            self.assertNotIn("setup.bat", self.words[k]["en"])


if __name__ == "__main__":
    unittest.main()
