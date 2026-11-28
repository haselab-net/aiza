"""A stand-in backend for driving the real page in headless Chrome
(tests/test_page_flow.py): serves static/ under /agents/, a few fake
sessions under /agents/api/, and a probe script that runs the steps it is
given and writes what it saw into the page."""
import http.server
import json
import os
import re
import threading
import time

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "static")
EXT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ext")
T0 = time.time()
# Each stand-in backend has its own state (flows run side by side):
# rev -- GET /agents/api/__bump moves the data on (a refresh then shows it);
# gated -- whether the gated session's history has asked for the passkey yet;
# faults -- "<METHOD> <path>" -> a list of answers given in turn before the
#   usual one (tests/test_page_failures.py; the path with its query before
#   the path alone): {"status", "body"} or
#   {"sse": [events]} (an event stream that sends them and ends); with
#   "after": "<METHOD> <path>" it is held until that request has been
#   answered (a late answer; alone, the usual answer comes late); with
#   "every": true it stays, for every such request. The probe
#   may add more with POST /agents/api/__faults (the same shape);
# log -- every API request, (method, path with its query, JSON body or None).


def sessions(st):
    out = [{"id": "aaaaaaaaaa%02d" % i, "label": "s%d" % i, "alive": True, "stopped": False, "waiting": False,
            "created_ts": T0 - i, "preset": "claude-tui", "tmux_location": "container",
            "task": {"state": "working", "ts": T0, "seen": True}} for i in range(3)]
    # s0 and s1 are linked (セッション連携)
    out[0]["link"] = {"id": "L1", "members": [{"id": "aaaaaaaaaa01", "label": "s1", "stopped": False}],
                      "partner": "aaaaaaaaaa01", "partner_label": "s1", "expires_ts": T0 + 3600}
    if st["rev"]:
        out[2]["task"] = {"state": "you", "ts": T0 + 1, "text": "見てください", "seen": False, "declared": True}
    # an ended one that can be resumed, and an archived one
    out.append({"id": "aaaaaaaaaa05", "label": "ended", "alive": False, "stopped": True, "created_ts": T0 - 9, "preset": "claude-tui",
                "tmux_location": "container", "claude_session_id": "c0ffee", "cwd": ""})
    out.append({"id": "aaaaaaaaaa09", "label": "archived", "alive": False, "stopped": True, "archived": True, "created_ts": T0 - 99,
                "preset": "claude-tui", "tmux_location": "container"})
    # on the host: one whose row is locked (no window), one whose history asks for the passkey once
    out.append({"id": "aaaaaaaaaa0b", "label": "", "alive": True, "locked": True, "created_ts": T0 - 20,
                "preset": "host-shell", "tmux_location": "host"})
    out.append({"id": "aaaaaaaaaa0c", "label": "gated", "alive": True, "created_ts": T0 - 21,
                "preset": "host-shell", "tmux_location": "host"})
    # and one whose history refuses twice (the retry after the unlock too)
    out.append({"id": "aaaaaaaaaa0d", "label": "gated2", "alive": True, "created_ts": T0 - 22,
                "preset": "host-shell", "tmux_location": "host"})
    return out


NEW = {"id": "aaaaaaaaaa07", "label": "new", "preset": "claude-tui", "tmux_location": "container", "alive": True,
       "created_ts": T0}
# POST answers by path (anything else answers {})
MAILED = {"id": "aaaaaaaaaa08", "label": "mailed", "preset": "mail-tui", "tmux_location": "container", "alive": True,
          "created_ts": T0}
ADOPTED = dict(NEW, id="aaaaaaaaaa06", label="work")
POSTS = {"/sessions": NEW, "/sessions/aaaaaaaaaa00/to-mailbox": MAILED, "/sessions/adopt": ADOPTED,
         "/unlock/begin-assertion": {"ok": True, "options": {"challenge": "AAAA", "allowCredentials": []}},
         "/unlock/finish-assertion": {"ok": True, "expires_at": T0 + 900, "tier": "root"}}
ISSUE = {"sessions": ["aaaaaaaaaa01"], "ref": "org/repo#1", "number": 1, "title": "t", "cloned": True, "assignees": []}
CAPS = {"root_shell": False, "login_list": False, "board": True, "mailbox": {"label": "Email", "codex": False},
        "ssh_machines": ["winbox"], "ssh_desktop": {}, "ssh_asleep": [], "ssh_machines_drives": ["winbox"],
        "unlock": {"unlocked": False, "expires_at": None, "enrolled": False, "enrolled_root": False, "tier": None}}
# the Windows machines' blackboard: s1 is using winbox
BOARD = {"available": True, "me": "u", "machines": ["winbox"], "feeds": {},
         "entries": [{"machine": "winbox", "user": "u", "session_id": "aaaaaaaaaa01", "label": "s1", "state": "using",
                      "source": "auto", "since": T0, "key": "k1"}]}
SEARCH = {"hits": [{"session_id": "aaaaaaaaaa01", "seq": 1, "ts": T0, "type": "user_message", "label": "s1",
                    "preset": "claude-tui", "archived": False, "snippet": "a needle here"}],
          "locked": 0, "truncated": False}


def tree(st):
    # a job with one open leaf under it: ⛓ and 🌳 have something to show
    node = lambda i, parent, title, **kw: dict({"id": i, "parent": parent, "title": title, "owner": "u",
                                                "members": [], "visibility": "self", "state": "open",
                                                "links": {}, "created_ts": T0 - 100}, **kw)
    nodes = [
        node("n00000000000a", None, "親の仕事"),
        node("n00000000000b", "n00000000000a", "子の仕事", ball={"kind": "person", "who": "u", "since": T0 - 5 * 86400},
             links={"session": "aaaaaaaaaa00"}, session_owner="u", linked_ts=T0 - 100, session_label="s0",
             session_gone=False),
    ]
    # someone else's node working on the session they share with me read-only (✍ take over)
    nodes.append(node("n00000000000d", None, "共有の仕事", owner="v", visibility="lab",
                      links={"session": "cccccccccc01"}, session_owner="v",
                      discord="https://discord.com/channels/900000000000000001/800000000000000001"))   # the deployment notes
    if st["rev"]:
        nodes[1]["ball"] = {"kind": "sleep", "since": T0, "until": T0 + 86400, "text": "待ち"}
        nodes.append(node("n00000000000c", "n00000000000a", "新しい子"))
    nodes += [dict(node(x["id"], x.get("parent"), x["title"]), **x) for x in st.get("tree_extra", [])]
    # the lab's users as tree_lab_users gives them: {"user", "name" (from GECOS)}
    return {"user": "u", "nodes": nodes, "tr_pending": 0, "lang": "ja",
            "lab_users": [{"user": "u", "name": "U"}, {"user": "v", "name": "V"}, {"user": "w", "name": "W"}]}


LOGIN = {"id": "bbbbbbbbbb01", "label": "login", "preset": "claude-login", "tmux_location": "container",
         "alive": True, "created_ts": T0}


# Before app.js: a stand-in speech recognizer (window.__say("…") hands it a
# finished phrase) and a voice that ends at once.
PRE_JS = r"""
// Every uncaught error and rejected promise of the page: the probes report them.
window.__jsErrors = [];
window.addEventListener("securitypolicyviolation", (e) => window.__jsErrors.push("csp: " + e.violatedDirective + " " + (e.blockedURI || "inline")));
window.addEventListener("error", (e) => window.__jsErrors.push("error: " + e.message));
window.addEventListener("unhandledrejection", (e) => window.__jsErrors.push("rejection: " + ((e.reason && e.reason.message) || e.reason) + ((e.reason && e.reason.stack && window.__jsStack) ? " " + e.reason.stack : "")));
// The page's own popups and toasts (the deployment notes) answered the way the
// probes' stand-ins for the browser's dialogs say: a ui.confirm by
// window.confirm(text), each field of a ui.ask by window.prompt(label,
// value) (null cancels; for a choice, its value or else the field of one's
// own), and a toast handed to window.alert. A probe that drives a popup
// itself sets window.__popManual.
new MutationObserver((muts) => {
  for (const m of muts) for (const el of m.addedNodes) {
    if (!(el instanceof HTMLElement)) continue;
    if (el.classList.contains("aiza-toast")) { try { window.alert(el.querySelector("span").textContent); } catch (e) {} continue; }
    if (!el.classList.contains("aiza-pop") || el.id === "desk-modal" || window.__popManual) continue;
    setTimeout(() => {
      if (!el.isConnected) return;
      const click = (q) => { const b = el.querySelector(q); if (b) b.click(); };
      if (el.classList.contains("aiza-pop-confirm")) {
        const yes = window.confirm(el.querySelector(".pop-text").textContent);
        return click(yes ? ".pop-actions button:last-child" : ".pop-actions .pop-cancel");
      }
      for (const f of el.querySelectorAll(".pop-field")) {
        const label = (f.querySelector(":scope > span") || {}).textContent || el.querySelector(".pop-head span").textContent;
        const input = f.querySelector(":scope > input:not(.pop-custom), :scope > textarea, :scope > select");
        const choices = [...f.querySelectorAll(".pop-choice")];
        const on = choices.find((b) => b.classList.contains("on"));
        const ans = window.prompt(label, input ? input.value : on ? on.dataset.value : "");
        if (ans === null || ans === undefined) {
          for (const x of el.querySelectorAll(".pop-field input, .pop-field textarea")) x.value = "";
          return click(".pop-cancel");
        }
        if (input) input.value = String(ans);
        else {
          const hit = choices.find((b) => b.dataset.value === String(ans));
          if (hit) hit.click();
          else { const c = f.querySelector(".pop-custom"); c.value = String(ans); c.dispatchEvent(new Event("input")); }
        }
      }
      click(".pop-actions button:last-child");
    }, 0);
  }
}).observe(document.documentElement, { childList: true, subtree: true });
window.__recs = [];
class FakeRec { constructor() { window.__recs.push(this); this.n = 0; } start() {} stop() {} abort() {} }
window.SpeechRecognition = FakeRec; window.webkitSpeechRecognition = FakeRec;
window.__say = (text) => {
  const r = window.__recs[window.__recs.length - 1];
  if (!r || !r.onresult) return false;
  const i = r.n++;
  const results = [];
  results[i] = Object.assign([{ transcript: text }], { isFinal: true });
  r.onresult({ resultIndex: i, results });
  return true;
};
try { speechSynthesis.speak = (u) => setTimeout(() => u.onend && u.onend(), 0); speechSynthesis.cancel = () => {}; } catch (e) {}
"""
# s2's history: one of every kind of event the chat draws (the shapes
# aiza-backend writes: append_event, _ask_clean, the attachment scan).
TEXT = ("説明です。**太字** と `code` と https://example.com/a\n\n```python\nprint(1)\n```\n\n"
        "| a | b |\n|---|---|\n| 1 | 2 |\n\n- 項目\n- 項目2")
EVERY = [
    {"type": "user_message", "text": "こんにちは"},
    {"type": "user_message", "text": "共有の人から", "from": "v"},
    {"type": "agent_thinking", "text": "考え中"},
    {"type": "tool", "text": "Bash(ls)"},
    {"type": "tool", "text": "Read(a.txt)"},
    {"type": "agent_output", "text": TEXT, "ai": True},
    {"type": "system", "text": "お知らせ"},
    {"type": "attachment", "filename": "a.txt", "source_filename": "a.txt"},
    {"type": "attachment", "filename": "d", "kind": "folder", "source_filename": "d"},
    {"type": "image", "filename": "p.png", "source_filename": "p.png"},
    {"type": "ask", "ask_id": "q1", "kind": "question", "tool": "AskUserQuestion", "terminal": False,
     "questions": [{"question": "どれにしますか", "header": "選択", "multiSelect": False,
                    "options": [{"label": "A", "description": "a"}, {"label": "B", "description": ""}]}]},
    {"type": "ask", "ask_id": "q0", "kind": "permission", "tool": "Bash", "terminal": False,
     "summary": "rm a", "can_session": True},
    {"type": "ask_done", "ask_id": "q0", "how": "phone"},
    {"type": "ask", "ask_id": "q2", "kind": "question", "tool": "AskUserQuestion", "terminal": False,
     "questions": [{"question": "複数", "header": "", "multiSelect": True,
                    "options": [{"label": "X", "description": ""}, {"label": "Y", "description": ""}]},
                   {"question": "二つ目", "header": "", "multiSelect": False,
                    "options": [{"label": "P", "description": ""}]}]},
]
EVERY = [dict(e, seq=i + 1, ts=T0 - 60 + i) for i, e in enumerate(EVERY)]
# /voice/command: what the server's model would answer for a phrase
VOICE = {"s1": {"action": "open", "session": "aaaaaaaaaa01", "say": "s1"},
         "セッションを閉じる": {"action": "close", "say": ""}}


NONE = object()
EVENTS = [{"seq": 1, "ts": T0, "type": "user_message", "text": "needle"}]
# GET answers besides the ones above, in the shapes aiza-backend answers
NO_CLAUDE = {"loggedIn": False, "authMethod": "none"}
NO_CODEX = {"loggedIn": False, "text": "Not logged in"}
GETS = {"/claude-auth": {"container": NO_CLAUDE, "host": NO_CLAUDE, "root": NO_CLAUDE, "ssh:winbox": NO_CLAUDE},
        "/codex-auth": {"container": NO_CODEX, "host": NO_CODEX, "root": NO_CODEX},
        "/config": {"ext": []}, "/handoffs": {"handoffs": []}, "/prefs": {},
        "/tree/week": {"since": T0 - 7 * 86400, "done": [], "moving": [], "stuck": [], "pingpong": []},
        "/unlock/status": {"ok": True, "unlocked": False, "enrolled": False},
        "/ssh-workdirs": {"dir": "", "drives": ["/c"], "subdirs": []},
        "/shared/v/search": {"hits": [], "locked": 0, "truncated": False},
        # aiza-usage-collect's usage.json: this week and the one before, two people
        "/usage": {"generated": T0, "since": T0 - 30 * 86400, "names": {"u": "U", "v": "V"},
                   "rows": [{"week": time.strftime("%Y-%m-%d", time.localtime(T0 - k * 7 * 86400 - time.localtime(T0).tm_wday * 86400)),
                             "who": w, "owner": o, "node": n, "msgs": 3, "sessions": 1, "tokens": 1000, "cost": 0.5}
                            for k in (0, 1) for w, o, n in (("u", "u", "n00000000000b"), ("v", "v", None), ("v", "u", None))]}}
# POST answers by the path's end
POST_ENDS = {"/archive": dict(NEW, archived=True), "/unarchive": NEW, "/stop": {"ok": True}, "/messages": {"ok": True}, "/keys": {"ok": True},
             "/attach": {"path": "/inbox/upload"},
             "/delete": {"ok": True}, "/ask": {"text": "A"}, "/join": {"ok": True},
             "/page-check": {"ok": True}}
# "<method> <path>" the page asked that has no answer of its own here (it
# got {}): tests/test_page_flow.py lists them.
UNANSWERED = set()


def _load_gateway():
    from test_gateway_login import load_gateway
    return load_gateway()


_GATEWAY = _load_gateway()


def make_handler(probe_js, st, static=STATIC):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, data, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            if ctype.startswith("text/html"):
                # The pages run under the policy a demo room enforces
                # (aiza-gateway's page_csp, the deployment notes): a script it
                # would block shows up as a page error (PRE_JS).
                self.send_header("Content-Security-Policy", _GATEWAY.page_csp(data))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            p = self.path.split("?")[0].split("#")[0]
            if p.startswith("/agents/api/"):
                q = p[len("/agents/api"):]
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                try:
                    body = json.loads(raw) if raw else None
                except ValueError:
                    body = None
                st["log"].append((self.command, self.path[len("/agents/api"):], body))
                full = f"{self.command} {self.path[len('/agents/api'):]}"
                if q == "/config" and st["ext"]:
                    conf = {"ext": [{"name": n, "js": [f for f in sorted(os.listdir(os.path.join(EXT, n, "static"))) if f.endswith(".js")],
                                     "css": [f for f in sorted(os.listdir(os.path.join(EXT, n, "static"))) if f.endswith(".css")]}
                                    for n in st["ext"]]}
                    return self.send(200, json.dumps(conf).encode(), "application/json")
                if q == "/__faults":   # more faults from the probe, for a step later on
                    for k, v in (body or {}).items():
                        st["faults"].setdefault(k, []).extend(v)
                    return self.send(200, b"{}", "application/json")
                try:
                    queue = st["faults"].get(full) or st["faults"].get(f"{self.command} {q}")
                    if queue:
                        f = queue[0] if queue[0].get("every") else queue.pop(0)
                        if "after" in f:
                            # held until another request has been answered (a late answer)
                            with st["cond"]:
                                st["cond"].wait_for(lambda: f["after"] in st["answered"], timeout=10)
                            if "status" not in f and "body" not in f and "sse" not in f:
                                queue = None
                        if queue is not None:
                            return self.answer_fault(f)
                    return self.answer(p, q, body)
                finally:
                    with st["cond"]:
                        st["answered"].update({full, f"{self.command} {q}"})
                        st["cond"].notify_all()
            return self.answer(p, None, None)

        def answer_fault(self, f):
            if "sse" in f:
                data = "".join(f"data: {json.dumps(ev)}\n\n" for ev in f["sse"])
                return self.send(200, ("retry: 200\n\n" + data).encode(), "text/event-stream")
            return self.send(f.get("status", 200), json.dumps(f.get("body", {})).encode(), "application/json")

        def answer(self, p, q, body):
            if q is not None:
                if q == "/__bump":
                    st["rev"] += 1
                obj = {"/me": {"username": "u", "user": "u"}, "/sessions": {"sessions": sessions(st) + [LOGIN]},
                       "/shared-with-me": {"sessions": [dict(sessions(st)[0], id="cccccccccc01", owner="v",
                                                             label="shared",
                                                             share_mode="write" if st.get("joined") else "read")]}, "/folders": st["folders"],
                       "/session-order": {"order": st["order"]}, "/tree": tree(st),
                       "/claude-auth/login": LOGIN, "/search": SEARCH, "/capabilities": CAPS,
                       "/board": BOARD, "/issue": ISSUE,
                       "/tmux-sessions": {"sessions": [{"name": "work", "location": "container"}]},
                       "/workdirs": {"dir": "", "subdirs": []}, "/claude-conversations": {"conversations": []},
                       **GETS, **st["gets"]}.get(q, NONE)
                gate = {"/sessions/aaaaaaaaaa0c/events/page": 1, "/sessions/aaaaaaaaaa0d/events/page": 2}.get(q, 0)
                if st["gated"] < gate:
                    st["gated"] += 1   # the first read(s) ask for the passkey (the deployment notes)
                    return self.send(403, json.dumps({"error": "unlock", "unlock_required": True, "tier": "host"}).encode(),
                                     "application/json")
                if q.endswith("/events/page"):
                    obj = {"events": EVENTS, "has_more": False}
                if q == "/sessions/aaaaaaaaaa02/events/page":
                    obj = {"events": EVERY, "has_more": False}
                if q == "/sessions/bbbbbbbbbb01/events/page":   # the login pane has ended
                    obj = {"events": [{"seq": 1, "ts": T0, "type": "session_ended"}], "has_more": False}
                if self.command == "POST":
                    ans = POSTS.get(q, NONE)
                    for end, a in POST_ENDS.items():
                        if ans is NONE and q.endswith(end):
                            ans = a
                    if ans is not NONE:
                        obj = ans
                if q == "/folders/ops" and self.command == "POST":
                    try:
                        obj = folder_ops(st["folders"], (body or {}).get("ops"))
                    except ValueError as e:
                        return self.send(400, json.dumps({"error": str(e)}).encode(), "application/json")
                if q == "/session-order" and self.command == "POST":
                    st["order"] = list((body or {}).get("order") or [])
                    obj = {"ok": True}
                if q == "/tree" and self.command == "POST" and (body or {}).get("op") == "take":
                    obj = {"ok": True, "node": {}, "session": "aaaaaaaaaa09"}   # tree_take: the new session
                if q == "/voice/command" and self.command == "POST":
                    obj = VOICE.get(((body or {}).get("text") or "").strip(), {"action": "none"})
                if q.startswith("/shared/v/") and q.endswith("/events/page"):
                    obj = {"events": EVENTS, "has_more": False}
                if re.fullmatch(r"(/shared/v)?/sessions/\w+/events", q):
                    return self.send(204, b"", "text/event-stream")   # no live stream here
                if "/files/" in q:
                    return self.send(404, b"", "text/plain")   # an attachment's file: not kept here
                if obj is NONE:
                    UNANSWERED.add(f"{self.command} {q}")
                    obj = {}
                if self.command == "POST" and q.endswith("/join"):
                    st["joined"] = True   # a read-only share taken as co-working
                return self.send(200, json.dumps(obj).encode(), "application/json")
            m = re.match(r"^/agents/ext/([a-z0-9-]+)/([A-Za-z0-9._-]+)$", p)
            if m and m.group(1) in st["ext"]:
                f = os.path.join(EXT, m.group(1), "static", m.group(2))
                if os.path.isfile(f):
                    ctype = "text/css" if f.endswith(".css") else "application/javascript"
                    with open(f, "rb") as fh:
                        return self.send(200, fh.read(), ctype)
            if p.startswith("/email/"):   # the Email box's page (its own server in real life)
                return self.send(200, b"<!doctype html><title>box</title><p id=news>news</p>", "text/html; charset=utf-8")
            if p == "/agents/pre.js":
                return self.send(200, PRE_JS.encode(), "application/javascript")
            if p == "/agents/probe.js":
                return self.send(200, probe_js.encode(), "application/javascript")
            rel = p[len("/agents/"):] if p.startswith("/agents/") else None
            # The tabs' addresses (the deployment notes) are the page too, as the
            # gateway answers them; /todo is sent on to /work/ball there.
            if p in ("/todo", "/work", "/work/ball", "/work/week", "/work/usage", "/inbox", "/settings"):
                rel = ""
            if rel == "" or rel == "index.html":
                with open(os.path.join(static, "index.html"), encoding="utf-8") as fh:
                    html = fh.read()
                html = html.replace("</body>", '<script src="/agents/probe.js"></script></body>')
                html = html.replace('<script src="/agents/i18n.js">', '<script src="/agents/pre.js"></script><script src="/agents/i18n.js">', 1)
                return self.send(200, html.encode(), "text/html; charset=utf-8")
            f = os.path.normpath(os.path.join(static, rel or ""))
            if rel and f.startswith(os.path.normpath(static)) and os.path.isfile(f):
                ctype = "application/javascript" if f.endswith(".js") else "text/css" if f.endswith(".css") \
                    else "application/json" if f.endswith(".json") \
                    else "text/html; charset=utf-8" if f.endswith(".html") \
                    else "image/svg+xml" if f.endswith(".svg") else "application/octet-stream"
                with open(f, "rb") as fh:
                    return self.send(200, fh.read(), ctype)
            self.send(404, b"", "text/plain")
        do_POST = do_GET
    return H


FOLDER = {"parent": None, "archived": False, "last_stopped": [], "workdir": "", "shared_with": [], "shared_read": [],
          "tree_roots": []}


def folder_ops(doc, ops):
    """POST /folders/ops on the folders document `doc` (changed in place), as
    aiza-backend's apply_folder_ops does it: put (create, or change the given
    fields; "before" moves it), delete, assign, tree_root, share, unshare."""
    if not isinstance(ops, list):
        raise ValueError("ops must be a list")
    folders = doc["folders"]
    for op in ops:
        kind = op.get("op")
        if kind == "put":
            f = op["folder"]
            cur = next((x for x in folders if x["id"] == f["id"]), None)
            merged = {**(cur or {"id": f["id"], "name": "", **FOLDER}),
                      **{k: v for k, v in f.items() if k in ("id", "name", "parent", "archived", "last_stopped", "workdir")}}
            if cur is not None and op.get("before") is None:
                folders[folders.index(cur)] = merged
                continue
            if cur is not None:
                folders.remove(cur)
            at = next((i for i, x in enumerate(folders) if x["id"] == op.get("before")), len(folders))
            folders.insert(at, merged)
        elif kind == "delete":
            if any(x.get("parent") == op["id"] for x in folders):
                raise ValueError("folder has folders in it")
            folders[:] = [x for x in folders if x["id"] != op["id"]]
            doc["assign"] = {k: v for k, v in doc["assign"].items() if v != op["id"]}
        elif kind == "tree_root":
            for x in folders:
                x["tree_roots"] = [r for r in x.get("tree_roots") or [] if r != op["node"]] + (
                    [op["node"]] if x["id"] == op.get("folder") else [])
        elif kind == "assign":
            doc["assign"][op["session"]] = op["folder"]
        elif kind in ("share", "unshare"):   # the deployment notes (the user's name not checked here)
            f = next((x for x in folders if x["id"] == op.get("id")), None)
            if f is None or not op.get("username"):
                raise ValueError("no such folder" if f is None else "invalid username")
            if kind == "share" and op.get("mode") == "write" and op["username"] == "*":
                raise ValueError("only read-only sharing can be with everyone")
            for key in ("shared_with", "shared_read"):
                f[key] = [u for u in f.get(key) or [] if u != op["username"]]
            if kind == "share":
                f["shared_with" if op.get("mode") == "write" else "shared_read"].append(op["username"])
        else:
            raise ValueError(f"unknown op {kind!r}")
    return doc


def serve(probe_js, static=STATIC, faults=None, folders=None, tree_extra=None, ext=None, gets=None):
    """static: the page's files (a test may serve a changed copy); faults:
    answers to give first (see above); folders: the folders document to
    start from ({"folders": [{"id", "name", ...}], "assign": {session: folder}};
    the missing fields as the real one has them); tree_extra: more work-tree
    nodes ({"id", "parent", "title", ...}, the rest as tree() makes them); ext: extensions to load
    (names under ext/, their static/ files as /config lists them); gets: more GET answers (an
    extension's own, {path: answer}). srv.state["log"] is what
    was asked; srv.state["folders"] and ["order"] what the page saved."""
    doc = {"folders": [dict(FOLDER, **f) for f in (folders or {}).get("folders", [])],
           "assign": dict((folders or {}).get("assign", {}))}
    st = {"rev": 0, "gated": 0, "faults": {k: list(v) for k, v in (faults or {}).items()}, "log": [],
          "cond": threading.Condition(), "answered": set(), "folders": doc, "order": [],
          "tree_extra": list(tree_extra or []), "ext": list(ext or []), "gets": dict(gets or {})}
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(probe_js, st, static))
    srv.state = st
    srv.handle_error = lambda request, address: None   # Chrome closing a connection mid-answer is no failure
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
