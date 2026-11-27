"""The chat's own drawing, in headless Chrome against the stand-in backend
(the deployment notes): what the flows (test_page_flow.py) and the failure
cases (test_page_failures.py) never reach --
- an older page of history draws every kind of event as the first page does
  (two builders once; one now);
- the question and permission cards (the deployment notes): what each answer posts;
- an outward action's full page (the deployment notes): every value as text, the
  attachments as links, allow / deny, and no buttons once it is answered;
- the live stream: a queued message stays below what Claude still writes
  until Claude takes it, a message written again where Claude took it
  replaces the first copy, a live tail is replaced by what settles;
- the attachments: what a tap opens; the copy button of a code block;
- the screen panel (the pane's text, its older lines, back to live) and
  the subagents' panel, and that neither shows an answer about a session
  the user has since left.

    python3 -m unittest discover -s tests -v
"""
import json
import unittest
from concurrent.futures import ThreadPoolExecutor

import test_page_failures as F   # (not its class itself: unittest would run it here again)
from page_harness import EVERY, T0
from test_page_flow import CHROME

S0 = F.S0
FIRST = F.PAGE + "?limit=50"
OLDER = F.PAGE + "?before=100&limit=50"


def ev(seq, type_, **kw):
    return {"seq": seq, "ts": T0 + seq, "type": type_, **kw}


# Every kind the chat draws (EVERY, s2's history) and a few more.
HIST = [dict(e) for e in EVERY] + [
    ev(20, "user_message", text="未送信", submit=False),
    ev(21, "attachment", filename="m.obj", kind="model3d", source_filename="m.obj", mtl="m.mtl"),
    ev(22, "attachment", filename="b.zip", source_filename="b.zip"),
    ev(23, "session_ended", exit_status=2),
    ev(24, "system", text="お知らせ2"),
]
LAST = ev(100, "agent_output", text="最後")

# In the page: the chat's bubbles as (class, text), and what window.open opened.
HELP = r"""
  window.__shape = () => [...document.querySelectorAll("#messages > *")].filter((e) => !e.classList.contains("history-top"))
    .map((e) => [e.className, e.textContent.replace(/\s+/g, " ").trim(), e.dataset.seq || ""]);
  window.__opened = []; window.open = (u) => { window.__opened.push(String(u)); return null; };
"""


def card(**kw):
    return {"body": {"events": [ev(1, "ask", ask_id="a1", terminal=False, **kw)], "has_more": False}}


PERMISSION = dict(kind="permission", tool="aiza-out slack", summary="投稿先: #x", gate_out="o1")
SLACK_OUT = {"tool": "aiza-out slack", "id": "o1", "kind": "slack", "hash": "h" * 64,
             "action": {"kind": "slack", "channel": "#x", "channel_url": "https://example.slack.com/archives/C1",
                        "text": "<b>本文</b>", "attachments": [{"name": "a b.pdf", "size": 3}, {"name": "c.png", "size": 5}]}}
MAIL_OUT = {"tool": "aiza-out mail", "id": "o1", "kind": "mail", "hash": "h" * 64, "action": {"kind": "mail"},
            "mail": {"to": ["x@example.com"], "cc": ["y@example.com"], "bcc": [], "from": "", "subject": "件名",
                     "reply": True, "text": "本文", "attachments": []}}
OUT = f"GET /sessions/{S0}/out/o1"
ANSWER = {f"POST /sessions/{S0}/out/o1": [{"body": {"ok": True}}]}
ASK = f"POST /sessions/{S0}/ask"
STREAM = F.STREAM
QUESTIONS = [q for q in EVERY if q.get("ask_id") == "q2"][0]["questions"]
ONE = [q for q in EVERY if q.get("ask_id") == "q1"][0]["questions"]
OUT_TEXT = "out.page = [...document.querySelectorAll('.out-page .out-k, .out-page .out-v, .out-page h3')].map((e) => e.textContent);" \
           " out.links = [...document.querySelectorAll('.out-page a')].map((e) => [e.getAttribute('href'), e.getAttribute('download')]);" \
           " out.buttons = [...document.querySelectorAll('.out-page button')].map((e) => e.textContent)"

S1 = F.S1
SCREEN = {f"GET /sessions/{S0}/screen": [{"every": True, "body": {"text": "画面S0"}}],
          f"GET /sessions/{S0}/screen?before=0": [{"body": {"text": "古い1\n古い2", "has_more": True}}],
          f"GET /sessions/{S0}/screen?before=2": [{"body": {"text": "", "has_more": False}}]}
AGENTS = {f"GET /sessions/{S0}/subagents": [{"every": True, "body": {"subagents": [
              {"agent_id": "g1", "agent_type": "Explore", "description": "探す"}, {"agent_id": "g2"}]}}],
          f"GET /sessions/{S0}/subagents/g1": [{"every": True, "body": {"text": "見つけた https://example.com/x"}}]}
RESIZE = {f"POST /sessions/{s}/resize": [{"every": True, "body": {"ok": True}}] for s in (S0, S1)}
PANE = "document.getElementById('screen-pane')"
AGENTS_PANE = "document.getElementById('agents-pane')"
OPEN_S1 = f"window.aizaExt.app.openSessionById('{S1}')"
# Taps the given buttons the moment s1's chat is open (no timer: a held
# answer stops the page's clock until it is let go).
ON_S1 = ("const mo = new MutationObserver(() => { if (window.__aizaSession() !== '" + S1 + "') return; mo.disconnect();"
         " for (const id of __IDS__) document.getElementById(id).click(); });"
         " mo.observe(document.getElementById('messages'), { childList: true, subtree: true });")

# name: (faults, [(js, wait ms)])
CASES = {
    "history: the first page": ({FIRST: [{"body": {"events": HIST + [LAST], "has_more": False}}]}, [
        (HELP, 300),
        ("out.shape = window.__shape()", 100),
    ]),
    "history: an older page": ({FIRST: [{"body": {"events": [LAST], "has_more": True}}],
                                OLDER: [{"body": {"events": HIST, "has_more": False}}]}, [
        (HELP, 300),
        ("scrollTop()", 1500),
        ("out.shape = window.__shape()", 100),
    ]),
    "ask: one question, a tap answers": ({FIRST: [card(kind="question", tool="AskUserQuestion", questions=ONE)]}, [
        ("tap('.ask .ask-opt', 'A')", 800),
        ("out.note = document.querySelector('.ask .ask-note').textContent;"
         " out.disabled = [...document.querySelectorAll('.ask button')].every((b) => b.disabled)", 100),
    ]),
    "ask: questions, 送る waits for every one": ({FIRST: [card(kind="question", tool="AskUserQuestion", questions=QUESTIONS)]}, [
        ("tap('.ask .ask-send', '送る')", 300),
        ("out.lacking = document.querySelectorAll('.ask .ask-q.missing').length; tap('.ask .ask-opt', 'X'); tap('.ask .ask-opt', 'Y');"
         " tap('.ask .ask-opt', 'X'); tap('.ask .ask-opt', 'Y')", 300),
        ("out.ready0 = document.querySelector('.ask .ask-send').classList.contains('ready');"
         " const o = document.querySelectorAll('.ask .ask-other')[1]; o.value = '自由に'; o.dispatchEvent(new Event('input'))", 300),
        ("out.ready1 = document.querySelector('.ask .ask-send').classList.contains('ready');"
         " out.lacking1 = document.querySelectorAll('.ask .ask-q.missing').length;"
         " document.querySelectorAll('.ask .ask-other')[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))", 800),
        ("out.lacking2 = document.querySelectorAll('.ask .ask-q.missing').length; tap('.ask .ask-opt', 'Y')", 300),
        ("tap('.ask .ask-send', '送る')", 800),
    ]),
    "ask: a permission denied with a reason": ({FIRST: [card(kind="permission", tool="Bash", summary="rm a", can_session=True)]}, [
        ("document.querySelector('.ask input.ask-other').value = '危ない'; tap('.ask .ask-no', '拒否')", 800),
    ]),
    "ask: a card no longer open": ({FIRST: [card(kind="permission", tool="Bash", summary="rm a")],
                                    ASK: [{"status": 409, "body": {"error": "もう答えられません"}}]}, [
        ("tap('.ask .ask-go', '許可')", 800),
        ("out.note = document.querySelector('.ask .ask-note').textContent", 100),
    ]),
    "out: a post's page, allowed": ({FIRST: [card(**PERMISSION)], OUT: [{"body": SLACK_OUT}], **ANSWER}, [
        ("out.term = !!document.querySelector('.ask .ask-term'); tap('.ask .ask-opt', '📄 全文を見る')", 800),
        (OUT_TEXT, 100),
        ("tap('.out-page button', '許可')", 800),
        ("out.closed = !document.querySelector('.out-page')", 100),
    ]),
    "out: a mail's page, not allowed": ({FIRST: [card(**PERMISSION)], OUT: [{"body": MAIL_OUT}], **ANSWER}, [
        ("tap('.ask .ask-opt', '📄 全文を見る')", 800),
        (OUT_TEXT, 100),
        ("tap('.out-page button', '許可しない')", 800),
        ("out.closed = !document.querySelector('.out-page')", 100),
    ]),
    "out: done, no answer to give": ({FIRST: [card(**PERMISSION)],
                                      OUT: [{"body": dict(SLACK_OUT, answer="allow", used=True, done={"ok": True})}]}, [
        ("tap('.ask .ask-opt', '📄 全文を見る')", 800),
        (OUT_TEXT, 100),
        ("tap('.out-page button', '閉じる')", 300),
        ("out.closed = !document.querySelector('.out-page')", 100),
    ]),
    "live: a queued message stays below until taken": ({STREAM: [{"sse": [
        ev(2, "user_message", text="待ち", queued=True),
        ev(3, "agent_output", text="前の続き"),
        ev(4, "user_taken", taken=2),
        ev(5, "agent_output", text="返事"),
    ]}]}, [
        (HELP, 1500),
        ("out.shape = window.__shape()", 100),
    ]),
    "live: a message written again where Claude took it": ({STREAM: [{"sse": [
        ev(2, "user_message", text="待ち", queued=True),
        ev(3, "agent_output", text="前の続き"),
        ev(4, "user_message", text="待ち", moved_from=2),
        ev(5, "agent_output", text="返事"),
    ]}]}, [
        (HELP, 1500),
        ("out.shape = window.__shape()", 100),
    ]),
    "live: a live tail, then what settles": ({STREAM: [{"sse": [
        {"type": "live_tail", "text": "途中"},
        {"type": "live_tail", "text": "途中まで"},
    ]}]}, [
        # the stream ended; the page opens it again every 3 s: that one brings what settled
        (HELP, 300),
        ("out.live = window.__shape(); fetch('/agents/api/__faults', { method: 'POST', body: JSON.stringify("
         + json.dumps({STREAM: [{"sse": [ev(2, "agent_output", text="できた")]}]}, ensure_ascii=False) + ") })", 4000),
        ("out.shape = window.__shape()", 100),
    ]),
    "attachments: what a tap opens": ({FIRST: [{"body": {"events": HIST, "has_more": False}}]}, [
        (HELP, 300),
        ("for (const e of document.querySelectorAll('#messages img, #messages button.attachment-card')) e.click();"
         " out.opened = window.__opened; out.links = [...document.querySelectorAll('#messages a.attachment-card')].map((a) => a.getAttribute('href'))", 300),
    ]),
    "code: the copy button": ({FIRST: [{"body": {"events": [ev(1, "agent_output", text="```\nls -l 日本\n```")], "has_more": False}}]}, [
        ("window.__copied = []; Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (t) => { window.__copied.push(t); } } });"
         " document.querySelector('#messages .md-copy').click()", 100),
        ("out.copied = window.__copied; out.mark = document.querySelector('#messages .md-copy').textContent", 2000),
        ("out.after = document.querySelector('#messages .md-copy').textContent;"
         " Object.defineProperty(navigator, 'clipboard', { value: { writeText: async () => { throw new Error('no'); } } });"
         " document.execCommand = () => true; document.querySelector('#messages .md-copy').click()", 100),
        ("out.fallback = document.querySelector('#messages .md-copy').textContent", 100),
    ]),
    "screen: the pane, its older lines, back to live": ({**SCREEN, **RESIZE, STREAM: [{"sse": [{"type": "screen", "text": "流れS0"}]}]}, [
        ("document.getElementById('screen-btn').click()", 800),
        (f"out.shown = {PANE}.textContent; out.live0 = document.getElementById('screen-live-btn').classList.contains('visible');"
         f" {PANE}.dispatchEvent(new WheelEvent('wheel', {{ deltaY: -50 }}))", 800),
        (f"out.older = {PANE}.textContent; out.live1 = document.getElementById('screen-live-btn').classList.contains('visible');"
         f" {PANE}.scrollTop = 0; {PANE}.dispatchEvent(new Event('scroll'))", 800),
        (f"out.older2 = {PANE}.textContent; document.getElementById('screen-live-btn').click()", 300),
        (f"out.back = {PANE}.textContent; document.getElementById('screen-btn').click()", 300),
        ("out.closed = !document.getElementById('screen-wrap').classList.contains('visible')", 100),
    ]),
    "screen: an answer about the session left": ({
        f"GET /sessions/{S0}/screen": [{"after": f"GET /sessions/{S1}/screen", "body": {"text": "画面S0"}}],
        f"GET /sessions/{S1}/screen": [{"body": {"text": ""}}], **RESIZE}, [
        (ON_S1.replace("__IDS__", "['screen-btn']") + f" document.getElementById('screen-btn').click(); {OPEN_S1}", 1500),
        (f"out.shown = {PANE}.textContent; out.at = window.__aizaSession()", 100),
    ]),
    "agents: the list, one's log, back": ({**AGENTS, **SCREEN, **RESIZE}, [
        ("document.getElementById('screen-btn').click(); document.getElementById('agents-btn').click()", 800),
        (f"out.rows = [...{AGENTS_PANE}.querySelectorAll('.agent-row')].map((e) => e.textContent); {AGENTS_PANE}.querySelector('.agent-row').click()", 800),
        (f"out.detail = {AGENTS_PANE}.textContent; out.link = ({AGENTS_PANE}.querySelector('a') || {{}}).href || '';"
         f" {AGENTS_PANE}.querySelector('.agent-detail-header button').click()", 800),
        (f"out.again = {AGENTS_PANE}.querySelectorAll('.agent-row').length; document.getElementById('screen-btn').click()", 300),
        (f"out.closed = !{AGENTS_PANE}.classList.contains('visible')", 100),
    ]),
    "agents: an answer about the session left": ({
        f"GET /sessions/{S0}/subagents": [{"after": f"GET /sessions/{S1}/subagents", "body": {"subagents": [{"agent_id": "g0", "description": "S0の"}]}}],
        f"GET /sessions/{S1}/subagents": [{"status": 500, "body": {"error": "x"}}],
        f"GET /sessions/{S0}/screen": [{"every": True, "body": {"text": ""}}],
        f"GET /sessions/{S1}/screen": [{"every": True, "body": {"text": ""}}], **RESIZE}, [
        (ON_S1.replace("__IDS__", "['screen-btn', 'agents-btn']")
         + f" document.getElementById('screen-btn').click(); document.getElementById('agents-btn').click(); {OPEN_S1}", 1500),
        (f"out.shown = {AGENTS_PANE}.textContent", 100),
    ]),
}


@unittest.skipUnless(CHROME, "headless Chrome is needed for the page tests")
class PageChatTest(unittest.TestCase):
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

    @staticmethod
    def posted(out, path):
        return [b for m, p, b in out["log"] if m == "POST" and p == path]

    def test_an_older_page_draws_as_the_first_page_does(self):
        first = self.got("history: the first page")["shape"]
        older = self.got("history: an older page")["shape"]
        self.assertEqual(older, first)
        kinds = {c for c, _, _ in first}
        for k in ("bubble user", "bubble agent", "bubble agent thought", "bubble system", "toolgroup"):
            self.assertIn(k, kinds)
        self.assertIn(["bubble system", "セッションは終了しました (終了コード 2)", "23"], first)
        self.assertIn(["bubble user", "未送信⏎なし", "20"], first)

    def test_one_question_is_answered_by_a_tap(self):
        out = self.got("ask: one question, a tap answers")
        self.assertEqual(self.posted(out, f"/sessions/{S0}/ask"), [{"ask_id": "a1", "answer": {"answers": {"どれにしますか": "A"}}}])
        self.assertEqual(out["note"], "答えました: A")
        self.assertTrue(out["disabled"])

    def test_questions_go_together_once_each_has_an_answer(self):
        out = self.got("ask: questions, 送る waits for every one")
        self.assertEqual(out["lacking"], 2)
        self.assertFalse(out["ready0"])     # X and Y tapped twice: none picked
        self.assertFalse(out["ready1"])     # 複数 still has none
        self.assertEqual(out["lacking1"], 0)   # a mark goes once a question had an answer
        self.assertEqual(out["lacking2"], 1)   # Enter did not send, and marked the one without
        self.assertEqual(self.posted(out, f"/sessions/{S0}/ask"),
                         [{"ask_id": "a1", "answer": {"answers": {"複数": "Y", "二つ目": "自由に"}}}])

    def test_a_permission_denied_with_a_reason(self):
        out = self.got("ask: a permission denied with a reason")
        self.assertEqual(self.posted(out, f"/sessions/{S0}/ask"),
                         [{"ask_id": "a1", "answer": {"behavior": "deny", "message": "危ない"}}])

    def test_a_card_no_longer_open_says_so(self):
        out = self.got("ask: a card no longer open")
        self.assertEqual(out["note"], "終わりました: もう答えられません")
        self.assertEqual(out["alerts"], [])

    def test_a_posts_page_shows_it_all_as_text_and_allows(self):
        out = self.got("out: a post's page, allowed")
        self.assertFalse(out["term"])    # an outward action is answered here only
        page = out["page"]
        self.assertEqual(page[0], "aiza-out slack(o1)")
        self.assertIn("許可を待っています", page)
        self.assertIn("#x\nhttps://example.slack.com/archives/C1", page)
        self.assertIn("<b>本文</b>", page)     # as text, not HTML
        self.assertIn("h" * 64, page)
        self.assertEqual(out["links"], [[f"/agents/api/sessions/{S0}/out/o1/att/0", "a b.pdf"],
                                        [f"/agents/api/sessions/{S0}/out/o1/att/1", "c.png"]])
        self.assertEqual(out["buttons"], ["許可", "許可しない", "閉じる"])
        self.assertEqual(self.posted(out, f"/sessions/{S0}/out/o1"), [{"allow": True}])
        self.assertTrue(out["closed"])

    def test_a_mails_page_and_not_allowing_it(self):
        out = self.got("out: a mail's page, not allowed")
        page = out["page"]
        for v in ("x@example.com", "y@example.com", "件名", "返信", "本文", "なし"):
            self.assertIn(v, page)
        self.assertNotIn("Bcc", page)
        self.assertEqual(self.posted(out, f"/sessions/{S0}/out/o1"), [{"allow": False}])
        self.assertTrue(out["closed"])

    def test_an_answered_action_has_nothing_to_answer(self):
        out = self.got("out: done, no answer to give")
        self.assertIn("実行済み", out["page"])
        self.assertEqual(out["buttons"], ["閉じる"])
        self.assertTrue(out["closed"])

    def test_a_queued_message_stays_below_until_taken(self):
        out = self.got("live: a queued message stays below until taken")
        self.assertEqual([(t, s) for _, t, s in out["shape"]], [("needle", "1"), ("前の続き", "3"), ("待ち", "2"), ("返事", "5")])
        self.assertNotIn("queued", " ".join(c for c, _, _ in out["shape"]))

    def test_a_message_written_again_replaces_its_first_copy(self):
        out = self.got("live: a message written again where Claude took it")
        self.assertEqual([(t, s) for _, t, s in out["shape"]], [("needle", "1"), ("前の続き", "3"), ("待ち", "4"), ("返事", "5")])

    def test_a_live_tail_is_replaced_by_what_settles(self):
        out = self.got("live: a live tail, then what settles")
        self.assertEqual([(c, t) for c, t, _ in out["live"] if "live" in c], [("bubble agent live", "途中まで")])
        self.assertEqual([t for _, t, _ in out["shape"]], ["needle", "できた"])

    def test_what_a_tap_on_an_attachment_opens(self):
        out = self.got("attachments: what a tap opens")
        files = f"/agents/api/sessions/{S0}/files/"
        self.assertEqual([u.replace(files, "F:") for u in out["opened"]], [
            f"/agents/outbox-browse.html?session={S0}&dir=d&name=d",
            "F:p.png",
            "F:m.obj",                  # no 3D viewer here: the file itself
        ])
        self.assertEqual(out["links"], [files + "a.txt", files + "b.zip"])

    def test_the_copy_button(self):
        out = self.got("code: the copy button")
        self.assertEqual(out["copied"], ["ls -l 日本"])
        self.assertEqual(out["mark"], "✓")
        self.assertEqual(out["after"], "⧉")
        self.assertEqual(out["fallback"], "✓")   # the clipboard refused: the old way

    def test_the_screen_pane_its_older_lines_and_back_to_live(self):
        out = self.got("screen: the pane, its older lines, back to live")
        self.assertEqual(out["shown"], "画面S0")
        self.assertFalse(out["live0"])
        self.assertEqual(out["older"], "古い1\n古い2\n画面S0")
        self.assertTrue(out["live1"])          # the way back to live shows while reading back
        self.assertEqual(out["older2"], out["older"])   # nothing more back there
        self.assertEqual(out["back"], "画面S0")
        self.assertTrue(out["closed"])
        resized = self.posted(out, f"/sessions/{S0}/resize")
        self.assertEqual(len(resized), 1)
        self.assertEqual(sorted(resized[0]), ["cols", "rows"])

    def test_a_late_screen_does_not_show_in_another_session(self):
        out = self.got("screen: an answer about the session left")
        self.assertEqual(out["at"], S1)
        self.assertEqual(out["shown"], "")   # s1 has nothing on its screen yet

    def test_the_subagents_list_and_a_log(self):
        out = self.got("agents: the list, one's log, back")
        self.assertEqual(out["rows"], ["[Explore]探す", "[?]g2"])
        self.assertIn("見つけた", out["detail"])
        self.assertEqual(out["link"], "https://example.com/x")
        self.assertEqual(out["again"], 2)
        self.assertTrue(out["closed"])          # closing the screen closes it too

    def test_a_late_subagents_list_does_not_show_in_another_session(self):
        out = self.got("agents: an answer about the session left")
        self.assertNotIn("S0の", out["shown"])


if __name__ == "__main__":
    unittest.main()
