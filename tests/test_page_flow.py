"""The page's moves between its pages, run in headless Chrome against a
stand-in backend (the deployment notes). Each row of FLOWS is a start
URL and steps; after every step the page must be on the expected page and
its own check (checkPage: one page shown, header, machine menu, session)
must have found nothing. A new way of moving between pages gets a row here.

    python3 -m unittest discover -s tests -v
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest

from page_harness import serve

CHROME = shutil.which("google-chrome") or shutil.which("chromium") or shutil.which("chromium-browser")

# start hash, [(action, argument, expected page)]
#   hash: location.hash = arg   back: history.back()   menu: the machine menu
#   ("auth" = 設定, else a machine)   wait: nothing   has / none: a selector that must / must not match
# The expected page may go on with " m:<machine>" and/or " @<session id>": then
# that machine must be the one looked at / that session the open one (else
# they are not compared).
# A swipe from left to right over the messages (the chat's way back).
SWIPE = ("const el = document.getElementById('messages');"
         "const tt = (x) => new Touch({ identifier: 1, target: el, clientX: x, clientY: 200 });"
         "el.dispatchEvent(new TouchEvent('touchstart', { touches: [tt(20)], changedTouches: [tt(20)], bubbles: true }));"
         "el.dispatchEvent(new TouchEvent('touchend', { touches: [], changedTouches: [tt(220)], bubbles: true }));")


# Voice mode on: the 🎙 menu (the list's or the chat's), then 音声モード.
def VOICE_BTN(page):
    return ("eval", "(document.getElementById('audio-btn').offsetParent ? document.getElementById('audio-btn')"
                    " : document.getElementById('voice-btn')).click()", page)


def VOICE_ON(page):
    return ("click", ".audio-menu button.voice", page)


# The page is "list" | "chat" | "auth", then " todo:list" or
# " todo:tree/<見方 or chain>" while the to-do list is open.
FLOWS = {
    "reload on settings": ("#auth", [("wait", None, "auth")]),
    # Back from a session returns to the tab it was opened over (the deployment notes).
    "settings, then a session by its link, back": ("#auth", [("hash", "#aaaaaaaaaa00", "chat"), ("back", None, "auth")]),
    "settings, then this host's list by link": ("#auth", [("hash", "#machine=local", "list")]),
    "list, a session, back": ("", [("hash", "#aaaaaaaaaa01", "chat"), ("back", None, "list")]),
    "settings and back by the menu": ("", [("menu", "auth", "auth"), ("menu", "local", "list")]),
    "reload on a session, back": ("#aaaaaaaaaa02", [("wait", None, "chat"), ("back", None, "list")]),
    "settings, a session, settings again": ("", [("menu", "auth", "auth"), ("hash", "#aaaaaaaaaa00", "chat"),
                                                 ("back", None, "auth"), ("menu", "local", "list"), ("menu", "auth", "auth")]),
    "仕事's views: 番ごと, 週, 利用, 木": ("", [
        ("click", "#work-views a[data-view=ball]", "list todo:list"),
        ("click", "#work-views a[data-view=week]", "list todo:tree/week"),
        ("click", "#work-views a[data-view=usage]", "list todo:tree/usage"),
        ("click", "#work-views a[data-view=ball]", "list todo:list"),
        ("click", "#work-views a[data-view=tree]", "list")]),
    "tree: a shared root's 💬 Discord link": ("", [
        ("wait", None, "list"),
        ("has", ".wtree a.tdiscord[href='https://discord.com/channels/900000000000000001/800000000000000001'][target=_blank][title='Discord で話す'][aria-label='Discord で話す']",
         "list"),
        ("none", ".wtree a.tdiscord:not([href^='https://discord.com/channels/'])", "list")]),
    "仕事 opens with its last view": ("", [
        ("click", "#work-views a[data-view=week]", "list todo:tree/week"),
        ("click", "#tabs a[data-tab=settings]", "auth"),
        ("click", "#tabs a[data-tab=work]", "list todo:tree/week")]),
    # The tabs (the deployment notes): roots, switched without history entries.
    "tabs: 設定, 仕事, its views": ("", [
        ("click", "#tabs a[data-tab=settings]", "auth"),
        ("click", "#tabs a[data-tab=work]", "list"),
        ("click", "#work-views a[data-view=week]", "list todo:tree/week"),
        ("click", "#work-views a[data-view=usage]", "list todo:tree/usage"),
        ("click", "#work-views a[data-view=ball]", "list todo:list"),
        ("click", "#tabs a[data-tab=settings]", "auth"),
        ("click", "#tabs a[data-tab=work]", "list todo:list"),
        ("click", "#work-views a[data-view=tree]", "list")]),
    "a session over 週, back to 週": ("", [
        ("click", "#work-views a[data-view=week]", "list todo:tree/week"),
        ("hash", "#aaaaaaaaaa01", "chat"),
        ("back", None, "list todo:tree/week")]),
    "list: tap a session row, ← back": ("", [("click", ".session-row[data-session-id=aaaaaaaaaa01]", "chat"),
                                                ("click", "#back-btn", "list")]),
    "to-do list: open a session from it, back returns to it": ("", [
        ("click", "#work-views a[data-view=ball]", "list todo:list"),
        ("click", "#todo-modal a.body[href='/agents/#aaaaaaaaaa00']", "chat"),
        ("back", None, "list todo:list")]),
    "⛓ from a node's ⋯, ← back to the tree": ("", [
        ("wait", None, "list"),
        ("click", ".wtree button.tmore[title='操作']", "list"),
        ("text", ".tmenu button|止めているもの", "list todo:tree/chain"),
        ("click", "#todo-modal .tree-back", "list")]),
    "⛓, then 🌳 to the branch": ("", [
        ("wait", None, "list"),
        ("click", ".wtree button.tmore[title='操作']", "list"),
        ("text", ".tmenu button|止めているもの", "list todo:tree/chain"),
        ("click", "#todo-modal button.tmore[title='木で見る']", "list")]),
    "設定's ログイン, back to 設定": ("", [
        ("menu", "auth", "auth"),
        ("click", "button.auth-login[data-scope=container]", "chat"),
        ("click", "#back-btn", "auth")]),
    "設定's ログイン, browser Back to 設定": ("", [
        ("menu", "auth", "auth"),
        ("click", "button.auth-login[data-scope=container]", "chat"),
        ("back", None, "auth")]),
    "a session, then a list link": ("#aaaaaaaaaa00", [("wait", None, "chat"), ("hash", "#machine=local", "list")]),
    "番ごと, 設定, 仕事: 番ごと again": ("", [("click", "#work-views a[data-view=ball]", "list todo:list"),
                                       ("click", "#tabs a[data-tab=settings]", "auth"),
                                       ("click", "#tabs a[data-tab=work]", "list todo:list")]),
    "a session shared with me": ("", [("click", "#shared-toggle-btn", "list"),
                                      ("click", "#shared-list .shared-folder", "list"),
                                      ("click", "#shared-list .shared-row", "chat"),
                                      ("back", None, "list")]),
    "the blackboard: open, close": ("", [("click", "#machine-btn", "list overlay:board"),
                                         ("click", "#board-modal", "list")]),
    "start a new session": ("", [("click", "#create-btn", "chat")]),
    # セッションを始める (the deployment notes 段3): a layer over the tab when
    # opened from elsewhere (the tree's ▶, a folder's ⋯); ＋ 🤖 AI opens it
    # in the top row's panel instead, with no layer (2026-11-27, the deployment notes).
    "start screen: open, Back closes it": ("", [("eval", "ui.start.open({})", "list overlay:start"), ("back", None, "list")]),
    "start screen: ✕": ("", [("eval", "ui.start.open({})", "list overlay:start"), ("click", "#start-modal .close", "list")]),
    "start screen in the panel: ✕": ("", [("click", "#start-btn", "list"), ("has", "#tool-panel #start-modal:not([hidden])", "list"),
                                         ("click", "#start-modal .close", "list")]),
    "start screen: 開始 becomes the chat, Back to the tab": ("", [
        ("click", "#start-btn", "list"), ("click", "#create-btn", "chat"), ("back", None, "list")]),
    "start screen: an ssh machine in どこで": ("", [
        ("click", "#start-btn", "list"),
        ("eval", "const p = document.getElementById('place'); p.value = 'ssh:winbox'; p.dispatchEvent(new Event('change'))",
         "list m:winbox"),
        ("has", "#preset option[value='claude-tui-winbox']", "list m:winbox")]),
    "start screen opened for a machine": ("", [("eval", "ui.start.open({ place: 'ssh:winbox' })", "list overlay:start m:winbox")]),
    "stop a session from its chat": ("#aaaaaaaaaa00", [("wait", None, "chat"), ("click", "#chat-dot", "list")]),
    "resume an ended session from its chat": ("#aaaaaaaaaa05", [("wait", None, "chat @aaaaaaaaaa05"),
                                                                ("click", "#chat-dot", "chat @aaaaaaaaaa07"),
                                                                ("back", None, "list")]),
    "the archived list": ("", [("click", "#archive-toggle-btn", "list"), ("click", "#archived-list .session-row", "chat"),
                               ("back", None, "list")]),
    "search, open a hit": ("", [("click", "#search-toggle-btn", "list"),
                                ("eval", "document.getElementById('search-input').value = 'needle';"
                                         "document.getElementById('search-form').requestSubmit()", "list"),
                                ("click", ".search-hit-row", "chat"), ("back", None, "list")]),
    "share pane: → a linked session": ("#aaaaaaaaaa00", [("wait", None, "chat"), ("click", "#share-btn", "chat"),
                                                       ("text", ".share-links button|→ s1", "chat @aaaaaaaaaa01")]),
    "share pane: 🔗 add another goes to the list": ("#aaaaaaaaaa00", [("wait", None, "chat"), ("click", "#share-btn", "chat"),
                                                                    ("text", ".share-links button|ほかのセッション", "list")]),
    "share pane: move to the Email box": ("#aaaaaaaaaa00", [("wait", None, "chat"), ("click", "#share-btn", "chat"),
                                                          ("click", "#move-mail-btn", "chat @aaaaaaaaaa08")]),
    "share pane: 🌳 to its branch": ("#aaaaaaaaaa00", [("wait", None, "chat"), ("click", "#share-btn", "chat"),
                                                     ("click", "#tree-jump-btn", "list")]),   # 仕事's tree (段5)
    # 設定 is no machine of the panel any more (the deployment notes): another machine from it.
    "blackboard: no 設定 in its list": ("", [("click", "#machine-btn", "list overlay:board"),
        ("eval", "if ([...document.querySelectorAll('#board-modal .mpick')].some((b) => b.textContent.includes('設定'))) throw new Error('設定 in the panel')",
         "list overlay:board"),
        ("click", "#board-modal .mpick", "list")]),
    "blackboard: this host from a session": ("#aaaaaaaaaa00", [("wait", None, "chat"),
                                                             ("click", "#machine-btn", "chat overlay:board"),
                                                             ("click", "#board-modal .mpick", "list")]),
    "blackboard: ✕": ("", [("click", "#machine-btn", "list overlay:board"), ("click", "#board-modal .close", "list")]),
    "blackboard: open a session using a machine": ("", [("click", "#machine-btn", "list overlay:board"),
                                                       ("click", "#board-modal a.open", "chat")]),
    "a row locked behind the passkey": ("", [("click", ".session-row[data-session-id=aaaaaaaaaa0b]", "chat")]),
    "a session whose history asks for the passkey": ("#aaaaaaaaaa0c", [("wait", None, "chat"), ("wait", None, "chat"),
                                                                       ("has", "#messages .bubble.user", "chat")]),
    "a session whose history asks for the passkey again after the unlock": ("#aaaaaaaaaa0d", [
        ("wait", None, "chat"), ("wait", None, "chat"), ("has", "#messages .bubble.user", "chat")]),
    "take over a session shared with me read-only": ("", [
        ("click", "#shared-toggle-btn", "list"), ("click", "#shared-list .shared-folder", "list"),
        ("click", "#shared-list .shared-row", "chat @cccccccccc01"), ("text", ".take-btn|書き込み可", "chat @cccccccccc01"),
        ("none", ".take-btn", "chat @cccccccccc01")]),
    "attach a tmux session": ("", [("click", ".tmux-row button", "chat")]),
    "a GitHub issue link": ("#issue=org%2Frepo%231", [("wait", None, "chat")]),
    "patrol: next": ("#aaaaaaaaaa00", [("wait", None, "chat @aaaaaaaaaa00"), ("click", "#patrol-next", "chat @bbbbbbbbbb01")]),
    "patrol: archive goes to the next": ("#aaaaaaaaaa00", [("wait", None, "chat @aaaaaaaaaa00"),
                                                         ("click", "#patrol-archive", "chat @bbbbbbbbbb01")]),
    "another machine's list by link, then a session here": ("", [("hash", "#machine=winbox", "list m:winbox"),
                                                                ("hash", "#aaaaaaaaaa00", "chat m:local")]),
    "patrol: delete the last one goes to the list": ("#aaaaaaaaaa00", [
        ("wait", None, "chat"),
        ("eval", "const f = document.getElementById('patrol-filter'); f.value = 'waiting'; f.dispatchEvent(new Event('change'))", "chat"),
        ("click", "#patrol-delete", "list")]),
    "an extension opens a session by id": ("", [("eval", "window.aizaExt.app.openSessionById('aaaaaaaaaa01')", "chat")]),
    "an extension opens a session over the to-do list": ("", [
        ("click", "#work-views a[data-view=ball]", "list todo:list"),
        ("eval", "window.aizaExt.app.openSession(window.aizaExt.app.sessions()[1])", "chat")]),
    "/todo opened directly": ("/todo", [("wait", None, "list todo:list")]),
    # The tabs' addresses opened directly (the deployment notes), and the old ones.
    "/work/week opened directly": ("/work/week", [("wait", None, "list todo:tree/week"),
                                                  ("has", "#work-views a.on[data-view=week]", "list todo:tree/week")]),
    # 設定's cards (the deployment notes): 表示, AI のログイン, 読み上げと音声, 通知, そのほか, アカウント.
    "設定's cards": ("/settings", [("wait", None, "auth"),
                                  ("has", ".set-card:nth-of-type(1) #lang-select", "auth"),
                                  ("has", ".set-card:nth-of-type(2) #auth-rows .auth-row", "auth"),
                                  ("has", ".set-card:nth-of-type(2) #login-list-row", "auth"),
                                  # laid open, no balloon (2026-11-26)
                                  ("has", ".set-card:nth-of-type(3) #speak-settings.inline select", "auth"),
                                  ("has", ".set-card:nth-of-type(4) #notify-on", "auth"),
                                  ("none", "#chrome-kill-row", "auth"),
                                  ("has", "#ext-slot-settings[hidden]", "auth"),   # no extension here: no card
                                  ("has", ".set-card:nth-of-type(6) #logout-btn", "auth")]),
    "/settings opened directly": ("/settings", [("wait", None, "auth"), ("click", "#tabs a[data-tab=work]", "list")]),
    "/settings, a session by its link, back to 設定": ("/settings#aaaaaaaaaa00", [("wait", None, "chat"), ("back", None, "auth")]),
    "/agents/#auth is /settings now": ("#auth", [("wait", None, "auth"), ("has", "#tabs a.on[data-tab=settings]", "auth")]),
    "設定's ログイン ended, a tap goes back to 設定": ("", [
        ("menu", "auth", "auth"),
        ("click", "button.auth-login[data-scope=container]", "chat"),
        ("click", "#messages", "auth")]),
    "a swipe right goes back": ("#aaaaaaaaaa00", [("wait", None, "chat"), ("eval", SWIPE, "list")]),
    "voice: a session by its name, 戻って": ("", [VOICE_BTN("list"), VOICE_ON("list"),
                                                ("eval", "window.__say('s1')", "chat"),
                                                ("eval", "window.__say('戻って')", "list")]),
    "voice: やること, 戻って": ("", [VOICE_BTN("list"), VOICE_ON("list"),
                                  ("eval", "window.__say('やること')", "list todo:list"),
                                  ("eval", "window.__say('戻って')", "list")]),
    "voice: close the session (the server's answer)": ("#aaaaaaaaaa00", [
        ("wait", None, "chat"), VOICE_BTN("chat"), VOICE_ON("chat"),
        ("eval", "window.__say('セッションを閉じる')", "list")]),
    "voice: 停止, はい": ("#aaaaaaaaaa00", [("wait", None, "chat"), VOICE_BTN("chat"), VOICE_ON("chat"),
                                          ("eval", "window.__say('停止')", "chat"),
                                          ("eval", "window.__say('はい')", "list")]),
    "a session with every kind of event, answer its question": ("#aaaaaaaaaa02", [
        ("wait", None, "chat"),
        ("text", "#messages .ask button|A", "chat"),
        ("back", None, "list")]),
    # A voice 「やること」 from a session: 番ごと, the session closed (the
    # tabs are not on screen in a chat; the deployment notes).
    "to-do list from a session": ("#aaaaaaaaaa00", [("wait", None, "chat"), ("eval", "window.aizaExt.app.showTab('work', 'ball')", "list todo:list")]),
}

PROBE = r"""
(function () {
  const steps = __STEPS__;
  const out = { seen: [] };
  // Dialogs answer yes / "1" (what each would be asked is not what is tested).
  window.confirm = () => true; window.prompt = () => "1"; window.alert = () => {};
  // The passkey: a stand-in credential (the stand-in backend takes it), and
  // the page counted as focused (autoAskPasskey asks only then).
  document.hasFocus = () => true;
  try { Object.defineProperty(navigator.credentials, "get", { value: async () => ({ toJSON: () => ({ id: "fake" }) }) }); } catch (e) {}
  const sel = () => document.getElementById("machine-select");
  function act(a, arg) {
    if (a === "hash") location.hash = arg;
    else if (a === "back") history.back();
    else if (a === "forward") history.forward();
    else if (a === "eval") { try { (0, eval)(arg); } catch (e) { out.missing = "eval: " + e.message; } }
    else if (a === "menu") { sel().value = arg; sel().dispatchEvent(new Event("change")); }
    else if (a === "has") { if (!document.querySelector(arg)) out.missing = "nothing shows " + arg; }
    else if (a === "none") { if (document.querySelector(arg)) out.missing = "still shows " + arg; }
    else if (a === "click") { const el = document.querySelector(arg); if (el) el.click(); else out.missing = arg; }
    else if (a === "text") {
      const [q, text] = arg.split("|");
      const el = [...document.querySelectorAll(q)].find((x) => x.textContent.includes(text));
      if (el) el.click(); else out.missing = arg;
    }
  }
  let i = 0;
  function next() {
    if (i > 0) {
      const sid = window.__aizaSession && window.__aizaSession();
      out.seen.push(window.__aizaPage ? window.__aizaPage() + " m:" + window.__aizaMachine() + (sid ? " @" + sid : "") : null);
      if (window.__aizaCheckPage) window.__aizaCheckPage("step " + i);
    }
    if (i === steps.length) {
      out.errors = (window.__aizaPageErrors || ["no checkPage"]).concat(window.__jsErrors || []);
      const pre = document.createElement("pre"); pre.id = "probe-out";
      pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
      return;
    }
    const [a, arg] = steps[i++];
    act(a, arg);
    setTimeout(next, 900);
  }
  setTimeout(next, 2500);
})();
"""


def seen(got, steps):
    """The pages the probe saw, with the open session only where a step
    names one."""
    def keep(g, want):
        if g is None:
            return g
        kinds = {w[:2] for w in want.split(" ")}
        return " ".join(x for x in g.split(" ") if not (x[:1] == "@" and "@" not in {k[:1] for k in kinds})
                        and not (x[:2] == "m:" and "m:" not in kinds))
    return [keep(g, want) for g, (_, _, want) in zip(got["seen"], steps)] + got["seen"][len(steps):]


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page flow tests")
class PageFlowTest(unittest.TestCase):
    def try_flow(self, start, steps):
        try:
            return self.run_flow(start, steps)
        except Exception as e:   # reported under the flow's own name
            return e

    def try_flow_on(self, start, steps, static):
        """The same, on another copy of the page's files (tests/page_mutation.py)."""
        try:
            return self.run_flow(start, steps, static)
        except Exception as e:
            return e

    def run_flow(self, start, steps, static=None):
        probe = PROBE.replace("__STEPS__", json.dumps([[a, arg] for a, arg, _ in steps]))
        srv = serve(probe, static) if static else serve(probe)
        try:
            with tempfile.TemporaryDirectory() as prof:
                path = start if start.startswith("/") else f"/agents/{start}"
                url = f"http://127.0.0.1:{srv.server_address[1]}{path}"
                r = subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu",
                                    f"--user-data-dir={prof}", f"--virtual-time-budget={4000 + 1200 * len(steps)}",
                                    "--window-size=420,800", "--dump-dom", url],
                                   capture_output=True, text=True, timeout=90)
        finally:
            srv.shutdown()
            srv.server_close()
        m = re.search(r'<pre id="probe-out">(.*?)</pre>', r.stdout, re.S)
        self.assertIsNotNone(m, "the probe did not finish")
        return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))

    def test_flows(self):
        # Several Chromes at once (each flow has its own stand-in backend and
        # profile): the whole table in well under a minute.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = dict(zip(FLOWS, pool.map(lambda kv: self.try_flow(*kv[1]), FLOWS.items())))
        for name, (start, steps) in FLOWS.items():
            with self.subTest(name):
                got = results[name]
                if isinstance(got, Exception):
                    raise got
                self.assertEqual(seen(got, steps), [want for _, _, want in steps], name)
                self.assertEqual(got["errors"], [], name)
                self.assertNotIn("missing", got, name)
        # Every API path the page asked has its own answer in the stand-in
        # (an unknown one got {}, and the page may break on that where the
        # real backend's answer would not break it: /ssh-workdirs, 2026-11-23).
        import page_harness
        self.assertEqual(sorted({re.sub(r"[0-9a-f]{10,32}", "<id>", x) for x in page_harness.UNANSWERED}), [],
                         "give these an answer in tests/page_harness.py (GETS / POST_ENDS)")


KEEP_PROBE = r"""
(function () {
  const out = {};
  const q = (sel) => document.querySelector(sel);
  const byText = (sel, text) => [...document.querySelectorAll(sel)].find((x) => x.textContent.includes(text));
  const shownMenu = () => [...document.querySelectorAll(".wtree .tmenu")].find((m) => !m.hidden && getComputedStyle(m).display !== "none");
  const steps = [
    () => q("#work-views a[data-view=tree]").click(),   // 仕事's tree (the deployment notes 段5)
    () => {},
    () => q(".wtree button.tmore[title='操作']").click(),
    // A panel with an input: ✏️ 名前を変える (＋ 子を足す left the ⋯ for the
    // top row's ＋ 🌳, 2026-11-27; ▶'s 新規 opens the start screen since the deployment notes 段3).
    () => { const b = byText(".tmenu button", "名前を変える"); if (b) b.click(); else out.missing = "rename"; },
    () => {
      const m = shownMenu(); out.menu = !!m;
      const inp = m && [...m.querySelectorAll("input")].find((x) => x.type !== "hidden" && getComputedStyle(x).display !== "none" && !x.closest("[hidden]"));
      if (!inp) { out.missing = "input"; return; }
      inp.focus(); inp.value = "abc"; inp.dispatchEvent(new Event("input", { bubbles: true }));
      window.__k = { m, inp, row: q('.wtree [data-id="n00000000000b"]'), rowText: (q('.wtree [data-id="n00000000000b"]') || {}).textContent };
      fetch("/agents/api/__bump");
    },
    () => {},   // the 30 s refresh comes in between (virtual time)
    () => {
      const k = window.__k || {};
      const row = q('.wtree [data-id="n00000000000b"]');
      out.sameMenu = !!k.m && shownMenu() === k.m;
      out.sameInput = !!k.inp && k.inp.isConnected && k.inp.value === "abc";
      out.focus = document.activeElement === k.inp;
      out.sameRow = !!row && row === k.row;
      out.rowChanged = !!row && row.textContent !== k.rowText;
      out.newRow = !!q('.wtree [data-id="n00000000000c"]');
      document.body.click();
    },
    () => { out.closedOutside = !shownMenu(); out.errors = window.__aizaPageErrors.concat(window.__jsErrors); },
  ];
  const waits = [2500, 900, 900, 900, 900, 36000, 900, 900];
  let i = 0;
  function next() {
    if (i === steps.length) {
      const pre = document.createElement("pre"); pre.id = "probe-out";
      pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
      return;
    }
    steps[i++]();
    setTimeout(next, waits[i] || 900);
  }
  setTimeout(next, waits[0]);
})();
"""


LIST_KEEP_PROBE = r"""
(function () {
  const out = {};
  const row = (id) => { const a = document.querySelector(`#todo-modal a.body[href='/agents/#${id}']`); return a && a.closest(".item"); };
  const steps = [
    () => document.querySelector("#work-views a[data-view=ball]").click(),
    () => { window.__r1 = row("aaaaaaaaaa01"); window.__r2 = row("aaaaaaaaaa02"); out.rows = !!(window.__r1 && window.__r2); fetch("/agents/api/__bump"); },
    () => {},
    () => {
      out.sameUnchanged = row("aaaaaaaaaa01") === window.__r1;
      const r2 = row("aaaaaaaaaa02");
      out.changedRedrawn = !!r2 && r2 !== window.__r2 && r2.textContent.includes("見てください");
      out.errors = window.__aizaPageErrors.concat(window.__jsErrors);
    },
  ];
  const waits = [2500, 1500, 36000, 900, 900];
  let i = 0;
  function next() {
    if (i === steps.length) {
      const pre = document.createElement("pre"); pre.id = "probe-out";
      pre.textContent = JSON.stringify(out); document.body.appendChild(pre);
      return;
    }
    steps[i++]();
    setTimeout(next, waits[i] || 900);
  }
  setTimeout(next, waits[0]);
})();
"""


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page flow tests")
class TreeKeepsTest(PageFlowTest):
    """タスクR's check (2026-11-23): with a ⋯ panel open and text typed in it,
    the data changes and the page is drawn again; the panel, the text, the
    focus and the row elements stay, the row shows the new state and the new
    node appears, and a click outside still closes the panel."""

    def test_flows(self):
        pass   # (the flows run once, in PageFlowTest)

    def test_open_panel_survives_a_refresh(self):
        srv = serve(KEEP_PROBE)
        try:
            with tempfile.TemporaryDirectory() as prof:
                url = f"http://127.0.0.1:{srv.server_address[1]}/agents/"
                r = subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={prof}",
                                    "--virtual-time-budget=60000", "--window-size=420,900", "--dump-dom", url],
                                   capture_output=True, text=True, timeout=120)
        finally:
            srv.shutdown()
            srv.server_close()
        m = re.search(r'<pre id="probe-out">(.*?)</pre>', r.stdout, re.S)
        self.assertIsNotNone(m, "the probe did not finish")
        got = json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&"))
        self.assertEqual(got, {"menu": True, "sameMenu": True, "sameInput": True, "focus": True, "sameRow": True,
                               "rowChanged": True, "newRow": True, "closedOutside": True, "errors": []})

    def run_probe(self, probe):
        srv = serve(probe)
        try:
            with tempfile.TemporaryDirectory() as prof:
                url = f"http://127.0.0.1:{srv.server_address[1]}/agents/"
                r = subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", f"--user-data-dir={prof}",
                                    "--virtual-time-budget=60000", "--window-size=420,900", "--dump-dom", url],
                                   capture_output=True, text=True, timeout=120)
        finally:
            srv.shutdown()
            srv.server_close()
        m = re.search(r'<pre id="probe-out">(.*?)</pre>', r.stdout, re.S)
        self.assertIsNotNone(m, "the probe did not finish")
        return json.loads(m.group(1).replace("&quot;", '"').replace("&amp;", "&"))

    def test_list_rows_kept_unless_changed(self):
        """The to-do list's rows: one whose data did not change is the same
        element after the refresh (what is open in it stays), one that
        changed is drawn again with the new state."""
        self.assertEqual(self.run_probe(LIST_KEEP_PROBE),
                         {"rows": True, "sameUnchanged": True, "changedRedrawn": True, "errors": []})


if __name__ == "__main__":
    unittest.main()
