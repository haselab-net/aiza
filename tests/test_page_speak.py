"""Reading replies aloud (the deployment notes, static/speak.js), in headless Chrome
against the stand-in backend (the deployment notes). In the page the
device's voice, the <audio> player and Google's voices (/agents/tts) are
stand-ins that write down what they were given, so each case checks what
was read, by which voice and at what speed:
- 🔊 on from the menu: a live reply read in pieces, English by an English
  voice, links and code not read out, each language's own speed;
- a tap pauses; a tap on a sentence reads from there, through the replies
  below (not the thoughts, unless tapped);
- the settings: speed, voice, Google's voices, the speaker, 試す;
- Google failing: that piece once more, then the device's voice, and after
  three failures the device's voice without asking Google;
- other sessions' replies (the deployment notes): name and summary, after the
  chat's own; the lock screen's ⏸ turns both off;
- a tab back from hiding restarts a piece that stalled there.

    python3 -m unittest discover -s tests -v
"""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_failures as F   # (not its class itself: unittest would run it here again)
from page_harness import T0
from test_page_flow import CHROME

S0 = F.S0
FIRST = F.PAGE + "?limit=50"
STREAM = F.STREAM

# The stand-ins, put in by each case's first step (after the page loaded; the
# page looks them up at each use).
FAKES = r"""
  window.__said = []; window.__cancels = 0; window.__hold = false;
  window.SpeechSynthesisUtterance = class { constructor(t) { this.text = t; this.lang = ''; this.rate = 1; this.voice = null; } };
  const V = (name, lang, voiceURI, x) => Object.assign({ name, lang, voiceURI, default: false, localService: true }, x || {});
  window.__voices = [V('Kyoko', 'ja-JP', 'kyoko', { default: true }), V('Google 日本語', 'ja-JP', 'gja', { localService: false }),
                     V('Samantha', 'en_US', 'sam'), V('Google US English', 'en-US', 'gen', { localService: false })];
  speechSynthesis.getVoices = () => window.__voices;
  speechSynthesis.speak = (u) => { if (u.text === ' ') return; window.__said.push([u.text, u.lang, u.rate, u.voice ? u.voice.name : '']);
    window.__last = u; if (!window.__hold) setTimeout(() => u.onend && u.onend(), 0); };
  speechSynthesis.cancel = () => { window.__cancels++; };
  window.__played = []; window.__sinks = []; window.__ms = {};
  HTMLMediaElement.prototype.play = function () { window.__played.push([this.loop ? 'loop' : 'tts', this.playbackRate]);
    if (!this.loop) setTimeout(() => this.onended && this.onended(), 0); return Promise.resolve(); };
  HTMLMediaElement.prototype.pause = function () {};
  HTMLMediaElement.prototype.setSinkId = function (id) { window.__sinks.push(id); return Promise.resolve(); };
  try { navigator.mediaSession.setActionHandler = (a, f) => { window.__ms[a] = f; }; } catch (e) {}
  window.__cloud = [{ name: 'ja-JP-Wavenet-A', lang: 'ja-JP', kind: 'Wavenet', gender: 'FEMALE' },
                    { name: 'ja-JP-Standard-B', lang: 'ja-JP', kind: 'Standard', gender: 'MALE' },
                    { name: 'en-US-Wavenet-D', lang: 'en-US', kind: 'Wavenet', gender: 'MALE' }];
  window.__tts = []; window.__ttsFail = 0;
  const realFetch = window.fetch;
  window.fetch = (url, opt) => {
    const u = String(url);
    if (u.endsWith('/agents/tts/voices')) return Promise.resolve(new Response(JSON.stringify({ voices: window.__cloud })));
    if (u.endsWith('/agents/tts')) {
      const b = JSON.parse(opt.body); window.__tts.push([b.voice, b.text]);
      if (window.__ttsFail > 0) { window.__ttsFail--; return Promise.resolve(new Response('x', { status: 500 })); }
      return Promise.resolve(new Response(new Blob(['mp3'])));
    }
    return realFetch(url, opt);
  };
  window.__menu = () => [...document.querySelectorAll('.audio-menu button')].filter((b) => !b.hidden).map((b) => b.textContent);
  // a tap on the sentence that starts with `s` in the bubble that has it (a click there, as a finger's)
  window.__tapAt = (s) => {
    const w = document.createTreeWalker(document.getElementById('messages'), NodeFilter.SHOW_TEXT);
    for (let n = w.nextNode(); n; n = w.nextNode()) {
      const i = n.data.indexOf(s); if (i < 0) continue;
      n.parentElement.scrollIntoView({ block: 'center' });
      const r = document.createRange(); r.setStart(n, i); r.setEnd(n, i + 1);
      const b = r.getBoundingClientRect();
      n.parentElement.dispatchEvent(new MouseEvent('click', { bubbles: true, clientX: b.left + b.width / 2, clientY: b.top + b.height / 2 }));
      return true;
    }
    return false;
  };
"""
SAID = "out.said = window.__said.map((x) => x.slice())"


def faults(add):
    """A step that gives the stand-in more answers (the chat's stream, reopened every 3 s, brings them)."""
    return f"fetch('/agents/api/__faults', {{ method: 'POST', body: JSON.stringify({json.dumps(add, ensure_ascii=False)}) }})"


def ev(seq, type_, text, **kw):
    return {"seq": seq, "ts": T0 + 100 + seq, "type": type_, "text": text, **kw}


def live(*events):
    return faults({STREAM: [{"sse": list(events)}]})


MENU_ON = "document.getElementById('audio-btn').click(); tap('.audio-menu button', '🔇 読み上げ オフ')"
LIVE = "最初の文です。English is read in English. 詳しくは https://example.com/a を見て。\n```\ncode\n```"
HIST = [ev(1, "user_message", "質問"),
        ev(2, "agent_output", "一つ目の文です。二つ目の文です。三つ目の文です。"),
        ev(3, "agent_thinking", "考えたことです。"),
        ev(4, "agent_output", "次の返事です。")]
ENDED = {STREAM: [{"sse": []}]}

# name: (faults, [(js, wait ms)])
CASES = {
    "on from the menu, a live reply in pieces": (ENDED, [
        (FAKES + "localStorage.setItem('aiza-speak-rate', '1.5'); localStorage.setItem('aiza-speak-rate-en', '2');"
                 " localStorage.setItem('aiza-speak-voice', 'kyoko')", 100),
        ("document.getElementById('audio-btn').click(); out.menu = window.__menu(); tap('.audio-menu button', '🔇 読み上げ オフ')", 500),
        ("out.menu2 = window.__menu(); out.active = document.getElementById('audio-btn').classList.contains('active');"
         " out.loop = window.__played.filter((p) => p[0] === 'loop').length; " + live(ev(2, "agent_output", LIVE)), 4500),
        (SAID + "; document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))", 300),
        ("out.menuGone = !document.querySelector('.audio-menu'); out.stored = localStorage.getItem('aiza-speak')", 100),
    ]),
    "a tap pauses, a tap reads from that sentence on": ({FIRST: [{"body": {"events": HIST, "has_more": False}}], **ENDED}, [
        (FAKES, 300),
        (MENU_ON + "; document.getElementById('audio-btn').click()", 500),
        ("window.__said = []; window.__hold = true; out.tapped = window.__tapAt('二つ目')", 300),
        ("out.fromTap = window.__said.map((x) => x[0]); out.mark = [...document.querySelectorAll('#messages .bubble.speaking')].map((b) => b.textContent);"
                " document.querySelector('#messages .bubble.agent').click()", 300),
        ("out.paused = [document.getElementById('audio-btn').classList.contains('paused'), document.getElementById('audio-btn').title];"
         " window.__said = []; window.__hold = false; window.__tapAt('一つ目')", 1000),
        ("out.fromFirst = window.__said.map((x) => x[0]); window.__said = []; window.__tapAt('考えたこと')", 1000),
        ("out.thought = window.__said.map((x) => x[0]); out.open = document.querySelector('#messages .thought').classList.contains('open')", 100),
    ]),
    "the settings, 試す, Google's voices and the speaker": (ENDED, [
        (FAKES + "navigator.mediaDevices.enumerateDevices = async () => [{ kind: 'audiooutput', deviceId: 'default', label: '' },"
                 " { kind: 'audiooutput', deviceId: 'spk2', label: '' }, { kind: 'audioinput', deviceId: 'mic', label: '' }];"
                 " navigator.mediaDevices.getUserMedia = async () => ({ getTracks: () => [] });", 100),
        ("document.getElementById('audio-btn').click(); tap('.audio-menu button', '⚙ 設定')", 500),
        ("const p = document.querySelector('#speak-settings'); out.menuGone = !document.querySelector('.audio-menu');"
         " out.heads = [...p.querySelectorAll('.speak-pop-lang')].map((e) => e.textContent);"
         " out.selects = [...p.querySelectorAll('label')].filter((l) => !l.hidden).map((l) => [l.firstChild.textContent, [...l.querySelector('select').options].map((o) => o.value)]);"
         " const s = [...p.querySelectorAll('select')]; s[1].value = '2'; s[1].dispatchEvent(new Event('change'));"
         " s[2].value = 'gja'; s[2].dispatchEvent(new Event('change'));"
         " s[0].value = 'cloud'; s[0].dispatchEvent(new Event('change'))", 500),
        ("const p = document.querySelector('#speak-settings'); const s = [...p.querySelectorAll('select')];"
         " out.cloudSelects = [...p.querySelectorAll('label')].filter((l) => !l.hidden).map((l) => [l.firstChild.textContent, [...l.querySelector('select').options].map((o) => o.textContent)]);"
         " out.note = p.querySelector('.speak-pop-note').textContent;"
         " s[3].value = 'ja-JP-Standard-B'; s[3].dispatchEvent(new Event('change'));"
         " const sink = s[s.length - 1]; sink.value = '?ask'; sink.dispatchEvent(new Event('change'))", 500),
        ("const s = [...document.querySelectorAll('#speak-settings select')]; const sink = s[s.length - 1];"
         " out.sinks = [...sink.options].map((o) => o.value); sink.value = 'spk2'; sink.dispatchEvent(new Event('change'));"
         " out.sinkNow = window.__sinks.slice();"
         " tap('#speak-settings button', '試す')", 1500),
        ("out.tts = window.__tts; out.played = window.__played.filter((p) => p[0] === 'tts'); out.sinkIds = window.__sinks;"
         " out.stored = ['aiza-speak-rate', 'aiza-speak-voice', 'aiza-speak-engine', 'aiza-speak-cvoice', 'aiza-speak-sink'].map((k) => localStorage.getItem(k));"
         " document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }))", 300),
        # ⚙ 設定 of the 🔊 menu went to 設定's card (2026-11-26): the chat closed, 設定 shown
        ("out.page = window.__aizaPage(); out.popGone = !document.querySelector('.speak-pop:not(.inline)')", 100),
    ]),
    "Google failing: once more, then the device's voice, then off": (ENDED, [
        (FAKES + "localStorage.setItem('aiza-speak-engine', 'cloud'); window.__ttsFail = 100", 100),
        (MENU_ON, 3000),
        ("out.first = [window.__tts.length, window.__said.map((x) => x[0])]; " + live(ev(2, "agent_output", "一つ目。二つ目。三つ目。")), 9000),
        ("out.tts = window.__tts.map((x) => x[1]); " + SAID, 100),
    ]),
    "other sessions: name and summary; the lock screen's ⏸": ({"POST /voice/summary": [{"every": True, "body": {"say": "要約です"}}]}, [
        (FAKES, 100),
        ("document.getElementById('audio-btn').click(); out.menu = window.__menu(); tap('.audio-menu button', '🔇 裏も読む オフ')", 500),
        ("out.menu2 = window.__menu(); fetch('/agents/api/__bump')", 21500),
        ("out.bg = window.__said.map((x) => x[0]); window.__ms.pause()", 300),
        ("out.after = window.__menu(); out.stored = [localStorage.getItem('aiza-speak'), localStorage.getItem('aiza-speak-bg')];"
         " window.__said = []; window.__ms.play()", 300),
        ("out.played = window.__said.map((x) => x[0]); out.on = document.getElementById('audio-btn').classList.contains('active')", 100),
    ]),
    "a piece stalled in a hidden tab starts again": (ENDED, [
        (FAKES + "window.__hold = true", 100),
        (MENU_ON, 500),
        ("out.before = window.__said.length; document.dispatchEvent(new Event('visibilitychange'))", 300),
        (SAID + "; document.getElementById('about-btn').click(); out.about = !document.getElementById('about-modal').hidden;"
                " document.getElementById('about-modal').click()", 300),
        ("out.aboutGone = document.getElementById('about-modal').hidden", 100),
    ]),
}

@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageSpeakTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with ThreadPoolExecutor(max_workers=4) as pool:
            cls.results = dict(zip(CASES, pool.map(lambda v: F.PageFailureTest.run_case(*v), CASES.values())))

    def got(self, name):
        out = self.results[name]
        self.assertNotIn("unfinished", out, name)
        self.assertNotIn("thrown", out)
        self.assertNotIn("missing", out)
        self.assertEqual(out["errors"], [])
        return out

    def test_on_from_the_menu_a_live_reply_in_pieces(self):
        out = self.got("on from the menu, a live reply in pieces")
        self.assertEqual(out["menu"], ["🔇 読み上げ オフ", "🎙 音声モード オフ", "🔇 裏も読む オフ", "⚙ 設定"])
        self.assertEqual(out["menu2"][0], "🔊 読み上げ オン")
        self.assertTrue(out["active"])
        self.assertGreaterEqual(out["loop"], 1)          # the keep-alive clip plays while 🔊 is on
        self.assertEqual(out["said"], [
            ["読み上げをオンにしました", "ja-JP", 1.5, "Kyoko"],       # the chosen voice, the display language's speed
            ["最初の文です。", "ja-JP", 1.5, "Kyoko"],
            ["English is read in English.", "en-US", 2, "Google US English"],   # English's own speed; Google first
            ["詳しくは リンク を見て。", "ja-JP", 1.5, "Kyoko"],     # a link is not spelled out
            ["(コード省略)", "ja-JP", 1.5, "Kyoko"],                  # nor code
        ])
        self.assertTrue(out["menuGone"])                 # a tap outside closes the menu
        self.assertEqual(out["stored"], "1")

    def test_a_tap_pauses_and_a_tap_reads_from_that_sentence(self):
        out = self.got("a tap pauses, a tap reads from that sentence on")
        self.assertTrue(out["tapped"])
        self.assertEqual(out["fromTap"], ["二つ目の文です。"])   # from the tapped sentence (it holds: no onend)
        self.assertEqual(out["mark"], ["一つ目の文です。二つ目の文です。三つ目の文です。"])
        self.assertEqual(out["paused"], [True, "読み上げを一時停止中: 吹き出しをタップでそこから再開"])
        # from the first sentence, through the reply below -- not the thought between
        self.assertEqual(out["fromFirst"], ["一つ目の文です。", "二つ目の文です。", "三つ目の文です。", "次の返事です。"])
        self.assertEqual(out["thought"], ["考えたことです。", "次の返事です。"])   # a tapped thought is read, then the replies below
        self.assertTrue(out["open"])

    def test_the_settings_try_google_and_the_speaker(self):
        out = self.got("the settings, 試す, Google's voices and the speaker")
        self.assertTrue(out["menuGone"])
        self.assertEqual(out["page"], "auth")
        self.assertEqual(out["heads"], ["日本語", "英語"])
        self.assertEqual(out["selects"][0], ["読み上げ", ["", "cloud"]])
        self.assertEqual(out["selects"][1][1], ["0.75", "1", "1.25", "1.5", "1.75", "2", "2.5"])
        self.assertEqual(out["selects"][2], ["声", ["", "kyoko", "gja"]])        # the display language's voices only
        self.assertEqual(out["selects"][4], ["声", ["", "sam", "gen"]])           # en_US counts as English
        names = [o for k, o in out["cloudSelects"] if k == "声"]
        self.assertEqual(names[0], ["Wavenet-A (♀)", "Standard-B (♂)"])
        self.assertEqual(names[1], ["Wavenet-D (♂)"])
        self.assertIn("出力先", [k for k, _ in out["cloudSelects"]])
        self.assertEqual(out["note"], "")
        self.assertEqual(out["sinks"], ["", "spk2"])      # names asked for: the "(名前を出す…)" row is gone
        # each piece in its language's chosen voice (the next one is asked for while one plays)
        self.assertEqual(sorted(out["tts"]), [["en-US-Wavenet-D", "This is how English replies will be read."],
                                              ["ja-JP-Standard-B", "この速さと声で読み上げます。"]])
        self.assertEqual(out["played"], [["tts", 2], ["tts", 2]])
        self.assertEqual(out["sinkNow"], ["spk2"])        # the chosen speaker at once, not only at the next play
        self.assertIn("spk2", out["sinkIds"])
        self.assertEqual(out["stored"], ["2", "gja", "cloud", "ja-JP-Standard-B", "spk2"])
        self.assertTrue(out["popGone"])

    def test_google_failing_falls_back_and_then_stays_off(self):
        out = self.got("Google failing: once more, then the device's voice, then off")
        self.assertEqual(out["first"], [2, ["読み上げをオンにしました"]])   # asked twice, then the device read it
        self.assertEqual([x[0] for x in out["said"]], ["読み上げをオンにしました", "一つ目。", "二つ目。", "三つ目。"])
        # each failed piece is asked twice (二つ目 once more ahead, while 一つ目 was on); three failed
        # pieces keep Google off: 三つ目 only had the ask ahead
        self.assertEqual({x: out["tts"].count(x) for x in out["tts"]},
                         {"読み上げをオンにしました": 2, "一つ目。": 2, "二つ目。": 3, "三つ目。": 1})

    def test_other_sessions_by_name_and_summary_and_the_lock_screen(self):
        out = self.got("other sessions: name and summary; the lock screen's ⏸")
        self.assertEqual(out["menu2"][2], "🔊 裏も読む オン")
        self.assertEqual(out["bg"], ["ほかのセッションの返事も読み上げます", "s2。", "要約です"])
        self.assertEqual(self.posted(out, "/voice/summary"), [{"session_id": "aaaaaaaaaa02", "brief": True}])
        self.assertEqual(out["after"][2], "🔇 裏も読む オフ")
        self.assertEqual(out["stored"], ["0", "0"])
        self.assertEqual(out["played"], ["読み上げをオンにしました"])   # the lock screen's ▶ turns 🔊 on
        self.assertTrue(out["on"])

    def test_a_piece_stalled_in_a_hidden_tab_starts_again(self):
        out = self.got("a piece stalled in a hidden tab starts again")
        self.assertEqual(out["before"], 1)
        self.assertEqual([x[0] for x in out["said"]], ["読み上げをオンにしました"] * 2)
        self.assertTrue(out["about"])
        self.assertTrue(out["aboutGone"])

    @staticmethod
    def posted(out, path):
        return [b for m, p, b in out["log"] if m == "POST" and p == path]


if __name__ == "__main__":
    unittest.main()
