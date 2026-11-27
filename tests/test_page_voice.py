"""Voice mode (the deployment notes, static/voice.js), in headless Chrome against the
stand-in backend (the deployment notes). The speech recognizer is
page_harness's stand-in (a phrase is handed to it as a result, a guess or a
settled one); the voices and the short tones are the stand-ins of
test_page_speak.py plus one for the tones, so each case checks what was
heard, what the page did, what it said back and which tone it gave:
- dictation into the open chat's box: a guess shown where the cursor is and
  replaced by what settles, 改行, 読んで, 送信, 取り消し, 入力終わり;
- the server's answers (/voice/command): send (only after 「はい」), the
  task's state and a date, read, interrupt, stop (asked first), resume,
  the Email page, the to-do view and back;
- an answer taken from the guess (and not again when it settles), and our
  own voice caught by the microphone not taken as words;
- failures: a send that fails, a command that fails, the microphone refused;
- 「次」: the sessions whose turn is yours, one by one, with a summary;
  Google's voice for what it says when read-aloud is set to it.

    python3 -m unittest discover -s tests -v
"""
import datetime
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_failures as F   # (not its class itself: unittest would run it here again)
from test_page_flow import CHROME
from test_page_speak import FAKES

S0, S1 = F.S0, F.S1
S2, ENDED_ID = "aaaaaaaaaa02", "aaaaaaaaaa05"
CMD = "POST /voice/command"
ENDED = {F.STREAM: [{"sse": []}]}

# The tones (an AudioContext that writes down each tone's pitches) and a
# result handed to the recognizer: a guess (final false) or a settled one at
# the same index as the guess before it (or, ahead, at the next one).
HELP = FAKES + r"""
  window.__hz = [];
  window.AudioContext = class { constructor() { this.currentTime = 0; this.destination = {}; } resume() {}
    createOscillator() { const o = { frequency: {}, connect: (g) => g, start: () => window.__hz.push(o.frequency.value), stop: () => {} }; return o; }
    createGain() { return { gain: { setValueAtTime() {}, exponentialRampToValueAtTime() {} }, connect: (d) => d }; } };
  window.__res = (text, final, ahead) => {
    const r = window.__recs[window.__recs.length - 1]; if (ahead) r.n++; const i = r.n; if (final) r.n++;
    const results = []; results[i] = Object.assign([{ transcript: text }], { isFinal: final }); r.onresult({ resultIndex: i, results });
  };
  window.__st = () => document.querySelector('#voice-bar .st').textContent;
  window.__opened = []; window.open = (u) => { window.__opened.push(String(u)); return null; };
"""
VOICE_ON = "document.getElementById('audio-btn').click(); tap('.audio-menu button', '🎙 音声モード オフ')"
SAID = "window.__said.map((x) => x[0])"
BOX = "document.getElementById('text')"
TONES = {"on": [660, 880], "start": [880], "sent": [784, 1175], "cancel": [523, 392], "back": [660], "err": [220]}


def say(text, wait=600):
    return (f"window.__say({text!r})", wait)


def cmd(**a):
    return {"body": a}


# name: (faults, [(js, wait ms)])
CASES = {
    "dictation into the open chat's box": (ENDED, [
        (HELP, 300),
        (VOICE_ON, 600),
        ("out.on = [!document.getElementById('voice-bar').hidden, window.__st(), document.getElementById('audio-btn').classList.contains('on')];"
         " window.__hz = []; window.__say('入力')", 600),
        (f"out.st = window.__st(); out.startHz = window.__hz.slice(); {BOX}.value = '前後'; {BOX}.setSelectionRange(1, 1); window.__res('こんに', false)", 300),
        (f"out.guess = {BOX}.value; window.__res('こんにちは', true)", 300),
        (f"out.settled = {BOX}.value; window.__say('改行')", 300),
        (f"out.newline = {BOX}.value; window.__said = []; window.__say('読んで')", 600),
        (f"out.read = {SAID}; window.__hz = []; window.__say('送信')", 1500),
        (f"out.sentHz = window.__hz.slice(); out.afterSend = [{BOX}.value, window.__st()]; {BOX}.value = '消すもの'; window.__hz = []; window.__say('取り消し')", 600),
        (f"out.cancelled = [{BOX}.value, window.__st(), window.__hz]; {BOX}.blur(); {BOX}.focus()", 300),
        ("out.focused = window.__st(); window.__hz = []; window.__say('入力終わり')", 600),
        ("out.ended = [window.__st(), window.__hz]; document.querySelector('#voice-bar .off').click()", 300),
        ("out.off = [document.getElementById('voice-bar').hidden, document.getElementById('audio-btn').classList.contains('on')]", 100),
    ]),
    "the server's answers": ({**ENDED, CMD: [
        cmd(action="send", session=S1, text="やあ"),
        cmd(action="send", session=S1, text="やめる"),
        cmd(action="send", session=S1),
        cmd(action="task", session=S1, state="snooze", until="2026-12-01"),
        cmd(action="task", session=S1, state="snooze", until="いつか"),
        cmd(action="task", session=S1, state="done"),
        cmd(action="read", session=S1, read_text="読む文です"),
        cmd(action="interrupt", session=S1),
        cmd(action="stop", session=S1),
        cmd(action="show", what="email"),
        cmd(action="show", what="todo"),
        cmd(action="show"),
        cmd(action="resume", session=ENDED_ID),
        cmd(action="none", say="わかりません"),
    ]}, [
        (HELP, 300),
        (VOICE_ON, 600),
        ("window.__said = []; window.__say('一つ目')", 800),
        ("out.ask1 = [window.__st(), " + SAID + "]; window.__hz = []; window.__say('はい')", 1200),
        ("out.yesHz = window.__hz.slice(); window.__say('二つ目')", 800),
        ("window.__hz = []; window.__say('いいえ')", 600),
        ("out.noHz = window.__hz.slice(); window.__said = []; window.__say('三つ目')", 800),
        ("out.noText = " + SAID + "; window.__say('四つ目')", 800),
        ("window.__said = []; window.__say('五つ目')", 800),
        ("out.noDate = " + SAID + "; window.__say('六つ目')", 800),
        ("window.__said = []; window.__say('七つ目')", 1500),
        ("out.read = [" + SAID + ", window.__aizaSession()]; window.__say('八つ目')", 800),
        ("window.__said = []; window.__say('九つ目')", 800),
        ("out.ask9 = " + SAID + "; window.__said = []; window.__say('たぶん')", 800),
        ("out.unclear = " + SAID + "; window.__say('はい')", 1500),
        ("out.afterStop = window.__aizaSession(); window.__say('十')", 800),
        ("out.email = window.__opened; window.__said = []; window.__say('十一')", 1200),
        ("out.todo = [" + SAID + ", location.hash]; window.__say('十二')", 1200),
        ("out.back = location.hash; window.__said = []; window.__say('十三')", 2500),
        ("out.resume = " + SAID + "; window.__said = []; window.__say('十四')", 800),
        ("out.other = " + SAID, 100),
    ]),
    "an answer from the guess; our own voice not taken": ({**ENDED, CMD: [cmd(action="send", session=S1, text="やあ")]}, [
        (HELP, 300),
        (VOICE_ON, 600),
        ("window.__say('送ってほしい')", 800),
        ("window.__res('はい', false)", 800),
        ("window.__res('はい', true, true)", 800),   # settled as a result of its own (Android does)
        ("window.__said = []; window.__say('もう一度')", 800),
        ("out.again = " + SAID + "; window.__say('送りますか')", 800),
        ("out.st = window.__st()", 100),
    ]),
    "いいえ just after 「はい か いいえ で」": ({**ENDED, CMD: [cmd(action="send", session=S1, text="やめる"), cmd(action="send", session=S1, text="やあ")]}, [
        (HELP, 300),
        (VOICE_ON, 600),
        ("window.__say('一つ目')", 800),
        ("window.__said = []; window.__say('たぶん')", 800),
        ("out.unclear = " + SAID + "; window.__hz = []; window.__say('いいえ')", 600),
        ("out.noHz = window.__hz.slice(); window.__say('二つ目')", 800),
        ("window.__say('はい')", 1200),
    ]),
    "failures: a send, a command, the microphone": ({**ENDED,
        CMD: [cmd(action="send", session=S1, text="やあ"), {"status": 500, "body": {"error": "x"}}, cmd(action="interrupt", session=S1)],
        f"POST /sessions/{S1}/messages": [{"status": 502, "body": {"error": "bad gateway"}}],
        f"POST /sessions/{S1}/keys": [{"status": 502, "body": {"error": "bad gateway"}}]}, [
        (HELP, 300),
        (VOICE_ON, 600),
        ("window.__say('送って')", 800),
        ("window.__said = []; window.__hz = []; window.__say('はい')", 1500),
        ("out.sendFail = [" + SAID + ", window.__hz]; window.__hz = []; window.__say('壊れた')", 1000),
        ("out.cmdFail = window.__hz.slice(); window.__said = []; window.__say('中断させて')", 1500),
        ("out.keysFail = " + SAID + "; window.__recs[window.__recs.length - 1].onerror({ error: 'not-allowed' })", 300),
        ("out.refused = [document.getElementById('voice-bar').hidden, window.__alerts]", 100),
    ]),
    "次: whose turn is yours, one by one; the fixed words": ({**ENDED,
        "POST /voice/summary": [{"every": True, "body": {"say": "要約です"}}]}, [
        (HELP + "fetch('/agents/api/__bump')", 300),
        (VOICE_ON, 600),
        ("window.__say('戻る')", 800),
        ("window.__said = []; window.__say('中断')", 600),
        ("out.noSession = " + SAID + "; window.__said = []; window.__say('次')", 2500),
        ("out.next = [" + SAID + ", window.__aizaSession()]; window.__said = []; window.__say('次')", 2500),
        ("out.again = [" + SAID + ", window.__aizaSession()]; window.__said = []; window.__say('読んで')", 1200),
        ("out.summary = " + SAID + "; window.__said = []; window.__say('もう一度')", 800),
        ("out.repeat = " + SAID + "; window.__hz = []; window.__say('入力停止')", 600),
        ("out.dictEnd = [window.__hz, window.__said.length]; window.__said = []; window.__say('おしまい')", 1200),
        ("out.bye = [" + SAID + ", document.getElementById('voice-bar').hidden]", 100),
    ]),
    "Google's voice for what it says": ({**ENDED, CMD: [cmd(action="none", say="日本語で答えます"), cmd(action="none", say="別の答えです")]}, [
        (HELP + "localStorage.setItem('aiza-speak-engine', 'cloud')", 300),
        (VOICE_ON, 600),
        ("window.__tts = []; window.__said = []; window.__say('答えて')", 2000),
        ("out.tts = window.__tts; out.device = " + SAID + "; window.__ttsFail = 100; window.__tts = []; window.__said = []; window.__say('二つ目')", 3000),
        ("out.fallback = [window.__tts.length, " + SAID + "]; window.__say('ストップ')", 300),
    ]),
}


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageVoiceTest(unittest.TestCase):
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

    def test_dictation_into_the_open_chats_box(self):
        out = self.got("dictation into the open chat's box")
        self.assertEqual(out["on"], [True, "🎙 聞いています", True])
        self.assertEqual(out["st"], "✍️ 入力中(「s0」)— 「送信」で送る・「取り消し」で消す・「入力終わり」でやめる")
        self.assertEqual(out["startHz"], TONES["start"])
        self.assertEqual(out["guess"], "前こんに後")           # the guess where the cursor was
        self.assertEqual(out["settled"], "前こんにちは後")     # replaced by what settled
        self.assertEqual(out["newline"], "前こんにちは\n後")
        self.assertEqual(out["read"], ["前こんにちは", "後"])   # 読んで reads the box
        self.assertEqual(self.posted(out, f"/sessions/{S0}/messages"), [{"text": "前こんにちは\n後", "submit": True, "typed": True}])
        self.assertEqual(out["sentHz"], TONES["sent"])
        self.assertEqual(out["afterSend"][0], "")
        self.assertTrue(out["afterSend"][1].startswith("✍️"))   # dictation goes on after a send
        self.assertEqual(out["cancelled"], ["", "🎙 聞いています", TONES["cancel"]])
        self.assertTrue(out["focused"].startswith("✍️"))          # a tap into the box starts it again
        self.assertEqual(out["ended"], ["🎙 聞いています", TONES["back"]])
        self.assertEqual(out["off"], [True, False])

    def test_the_servers_answers(self):
        out = self.got("the server's answers")
        posts = [(p, b) for m, p, b in out["log"] if m == "POST" and p != "/voice/command" and "/sessions/" in p and not p.endswith("/resize")]
        until = datetime.datetime(2026, 12, 1, 9, 0).timestamp()   # a date alone is 9:00 of it
        self.assertEqual(posts, [
            (f"/sessions/{S1}/messages", {"text": "やあ", "submit": True}),      # sent after 「はい」 only
            (f"/sessions/{S1}/task", {"state": "snooze", "until": until}),     # (「やめる」 was not: 「いいえ」)
            (f"/sessions/{S1}/task", {"state": "done"}),
            (f"/sessions/{S1}/keys", {"key": "Escape", "ctrl": False, "alt": False, "shift": False}),
            (f"/sessions/{S1}/stop", None),
        ])
        self.assertEqual(out["ask1"], ["❓ 「s1」へ「やあ」。送りますか", ["「s1」へ「やあ」。", "送りますか"]])
        self.assertEqual(out["yesHz"], TONES["sent"])
        self.assertEqual(out["noHz"], TONES["cancel"])
        self.assertEqual(out["noText"], ["何を送りますか"])
        self.assertEqual(out["noDate"], ["日付は？"])
        self.assertEqual(out["read"], [["読む文です"], S1])          # opened, then read
        self.assertEqual(out["ask9"], ["「s1」を停止しますか"])
        self.assertEqual(out["unclear"], ["はい か いいえ で"])
        self.assertIsNone(out["afterStop"])                           # stopped the open one: back to the list
        self.assertEqual(out["email"], ["/email/"])
        self.assertEqual(out["todo"][0], ["やること、0件"])
        self.assertEqual(out["resume"], ["ended"])
        self.assertEqual(out["other"], ["わかりません"])
        cmds = [b for m, p, b in out["log"] if m == "POST" and p == "/voice/command"]
        self.assertEqual(len(cmds), 14)
        self.assertEqual(cmds[-1]["current"], "aaaaaaaaaa07")          # the resumed session is open

    def test_an_answer_from_the_guess_and_not_our_own_voice(self):
        out = self.got("an answer from the guess; our own voice not taken")
        # 「はい」 acted on as a guess, not again when it settled
        self.assertEqual(self.posted(out, f"/sessions/{S1}/messages"), [{"text": "やあ", "submit": True}])
        self.assertEqual(out["again"], ["「s1」へ「やあ」。", "送りますか"])     # もう一度: the last thing said
        # 「送りますか」 just after it is our own voice: not shown, not sent to the server
        self.assertEqual(out["st"], "👂 もう一度")
        self.assertEqual([b["text"] for b in self.posted(out, "/voice/command")], ["送ってほしい"])

    def test_no_just_after_asking_again(self):
        # 「いいえ」 is in 「はい か いいえ で」 just said, but it is the answer (it was taken
        # for our own voice, and a later 「はい」 sent what had been declined)
        out = self.got("いいえ just after 「はい か いいえ で」")
        self.assertEqual(out["unclear"], ["はい か いいえ で"])
        self.assertEqual(out["noHz"], TONES["cancel"])
        self.assertEqual(self.posted(out, f"/sessions/{S1}/messages"), [{"text": "やあ", "submit": True}])

    def test_failures(self):
        out = self.got("failures: a send, a command, the microphone")
        self.assertEqual(out["sendFail"], [["送信失敗"], TONES["err"]])
        self.assertEqual(out["cmdFail"][:1], TONES["err"])
        self.assertEqual(out["keysFail"], ["中断失敗"])
        self.assertEqual(out["refused"], [True, ["マイクを許可してください"]])

    def test_next_and_the_fixed_words(self):
        out = self.got("次: whose turn is yours, one by one; the fixed words")
        self.assertEqual(out["noSession"], ["セッションを開いて"])
        self.assertEqual(out["next"], [["s2。", "見てください", "要約です"], S2])
        self.assertEqual(out["again"], [["s2。", "見てください", "要約です"], S2])   # the only one: round again
        self.assertEqual(out["summary"], ["要約です"])
        self.assertEqual(out["repeat"], ["要約です"])
        self.assertEqual(out["dictEnd"], [TONES["back"], 1])    # 入力停止 outside dictation: nothing stopped
        self.assertEqual(self.posted(out, f"/sessions/{S2}/stop"), [])
        self.assertEqual(out["bye"], [["終わります"], True])

    def test_googles_voice_for_what_it_says(self):
        out = self.got("Google's voice for what it says")
        self.assertEqual(out["tts"], [["ja-JP-Wavenet-A", "日本語で答えます"]])
        self.assertEqual(out["device"], [])
        self.assertEqual(out["fallback"], [1, ["別の答えです"]])   # Google failed: the device's voice

    @staticmethod
    def posted(out, path):
        return [b for m, p, b in out["log"] if m == "POST" and p == path]


if __name__ == "__main__":
    unittest.main()
