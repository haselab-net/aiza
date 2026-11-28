// One session's chat (the chat page): the events drawn as bubbles (markdown, tables,
// code, links, attachments, questions, tools), the screen, the agents pane, the
// history paging, jumping to a message, and opening / closing a session.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after page.js and before app.js. What runs here at
// load uses only this file and the earlier ones. Moved out of app.js
// 2026-11-24; the indentation is app.js's.
"use strict";

  // This file's own elements of the page (only it uses them; from page.js, 2026-11-24).
  const composerEl = document.getElementById("composer");
  const chatOwnerBadgeEl = document.getElementById("chat-owner-badge");
  const keyToolbarEl = document.getElementById("key-toolbar");
  const screenBtn = document.getElementById("screen-btn");
  const screenWrapEl = document.getElementById("screen-wrap");
  const screenPaneEl = document.getElementById("screen-pane");
  const screenLiveBtnEl = document.getElementById("screen-live-btn");
  const agentsBtn = document.getElementById("agents-btn");
  const agentsPaneEl = document.getElementById("agents-pane");

  // The open session (the deployment notes: a variable is assigned only in
  // the file that declares it): set by openSession / closeSession here; the
  // other files read them, and change them through this file's functions.
  let currentSessionId = null;
  let currentPreset = null;
  // The full meta object for the currently-open session, kept alongside the
  // individual current* fields above (which predate this) specifically so
  // updateUnlockNotice() can read tmux_location/alive without plumbing them
  // through as separate globals of their own. null while on the session list.
  let currentSessionMeta = null;
  // Username of the session's owner when it's someone else's session opened
  // via sharing; null for a session that is the current
  // user's own. sessionPath()/sessionApiUrl() key off this to route every
  // per-session call through /shared/<owner>/... instead of the normal
  // /sessions/... path.
  let currentOwner = null;
  // What the other scripts read about the open session (the deployment notes,
  // 2026-11-24): this one entry instead of the variables themselves. Only read
  // there; the session is opened and closed through open() / close().
  const chatNow = {
    get id() { return currentSessionId; },
    get preset() { return currentPreset; },
    get meta() { return currentSessionMeta; },
    get owner() { return currentOwner; },
    open: (...a) => openSession(...a),
    close: () => closeSession(),
  };
  // Set just before opening a "claude-login*" session from the auth page's
  // ログイン button, so closeSession() knows to return there instead of the
  // session list (the chat view's own edge-swipe-right-to-go-back gesture,
  // aiza's usual entry point, is unaffected -- it always goes through this
  // same closeSession()).
  let sessionOpenedFromAuth = false;
  // Set once the open login session (claude-login* / codex-login*) has ended:
  // there is nothing left to do in it, so any tap in the chat view goes back
  // (2026-10-17, user request: having to find ← after logging in was unclear).
  let tapToLeave = false;
  const isLoginPreset = (p) => /^(claude|codex)-login/.test(String(p || ""));
  let currentEventSource = null;
  // The bubble currently showing an "attach"-preset session's still-changing
  // tail line (see the live_tail case in renderEvent) -- updated in place on
  // each new live_tail event instead of appending a fresh bubble every poll.
  // Reset to null on any other event type, so the *next* live_tail starts a
  // new bubble rather than resuming a now-stale one.
  let liveBubbleEl = null;
  // The open session's live events stop (also when the login is lost, page.js).
  function stopSessionEvents() {
    if (currentEventSource) currentEventSource.close();
    currentEventSource = null;
  }
  // The settings page's ログイン opens its login session: closing it goes back there.
  function openSessionFromAuth(meta) {
    sessionOpenedFromAuth = true;
    openSession(meta);
  }

  // Auto-scroll only while the reader is already at (or near) the bottom
  // (2026-10-05, at the user's request: "新着があると自動で一番下にスクロール
  // してしまうのが不便"). Scrolled up to read something, new output no longer
  // yanks the view down -- the "↓ 新着" button appears instead and takes
  // them there on tap. Must be read BEFORE appending, since the append
  // itself changes scrollHeight.
  const NEAR_BOTTOM_PX = 80;
  const newMsgBtnEl = document.getElementById("new-msg-btn");
  function chatNearBottom() {
    return messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < NEAR_BOTTOM_PX;
  }
  function scrollChatToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
    newMsgBtnEl.classList.remove("visible");
  }
  // follow: chatNearBottom() as measured before the append.
  function afterChatAppend(follow) {
    if (follow) scrollChatToBottom();
    else newMsgBtnEl.classList.add("visible");
  }
  newMsgBtnEl.addEventListener("click", scrollChatToBottom);
  messagesEl.addEventListener("scroll", () => {
    if (chatNearBottom()) newMsgBtnEl.classList.remove("visible");
  });

  function addThinkingIndicator() {
    removeThinkingIndicator();
    const div = document.createElement("div");
    div.className = "bubble agent thinking";
    div.id = "thinking-indicator";
    div.textContent = t("chat.thinking");
    const follow = chatNearBottom();
    messagesEl.appendChild(div);
    if (follow) scrollChatToBottom();
  }

  function removeThinkingIndicator() {
    const el = document.getElementById("thinking-indicator");
    if (el) el.remove();
  }

  // Fills an element with text, turning bare http(s) URLs into real links.
  // Built from text nodes, anchors and <strong> rather than innerHTML, so
  // pane output still can't inject markup. URL-linking was added for the
  // `claude auth login` flow, whose whole point is a URL the user has to
  // open from the phone, but it applies to any output -- an agent printing
  // a dev-server or PR link included. **bold** is Claude Code's own most
  // common markdown emphasis in its replies (headings, code fences, lists
  // etc. are left as plain text -- this is deliberately just the one marker
  // that shows up constantly and reads badly as literal asterisks, not a
  // markdown renderer).
  const INLINE_RE = /(https?:\/\/[^\s<>"'`、。，．（）［］｛｝「」『』【】〔〕〈〉《》“”‘’！？：；]+)|\*\*([^\n*]+?)\*\*/g;

  // The URL pattern above is greedy, so prose like "(see https://x/y)" or
  // 「https://x/y」 used to link "https://x/y)" and the page failed to open
  // (2026-10-07, at the user's request). If the URL is preceded by an opening
  // bracket or quote, it ends at the first matching closer. Otherwise trailing
  // sentence punctuation and closers with no opener inside the URL are dropped
  // (so a Wikipedia-style ".../Foo_(bar)" keeps its ")"). Japanese
  // punctuation never belongs to a URL typed in prose, so INLINE_RE already
  // stops there ("https://x/y、次は").
  const URL_PAIRS = {
    "(": ")", "[": "]", "{": "}", "<": ">", "\"": "\"", "'": "'", "`": "`",
    "（": "）", "［": "］", "｛": "｝", "「": "」", "『": "』", "【": "】",
    "〔": "〕", "〈": "〉", "《": "》", "“": "”", "‘": "’",
  };
  const URL_CLOSERS = { ")": "(", "]": "[", "}": "{" };
  const URL_TRAILING_RE = /[.,;:!?*]+$/;

  function trimUrl(url, before) {
    const closer = URL_PAIRS[before];
    if (closer) {
      // Skip closers balanced by an opener inside the URL itself.
      let depth = 0;
      for (let i = 0; i < url.length; i++) {
        if (url[i] === closer && depth === 0) { url = url.slice(0, i); break; }
        if (closer !== before && url[i] === before) depth++;
        else if (url[i] === closer) depth--;
      }
    }
    for (;;) {
      const t = url.replace(URL_TRAILING_RE, "");
      const last = t.slice(-1);
      const opener = URL_CLOSERS[last];
      if (opener && t.split(opener).length < t.split(last).length) {
        url = t.slice(0, -1);
      } else if (t === url) {
        return url;
      } else {
        url = t;
      }
    }
  }

  // Markdown tables (2026-10-05, at the user's request: Claude Code writes
  // them often and they read badly as raw pipes on a phone) are the one
  // block-level construct rendered for real: a "| a | b |" header line
  // immediately followed by a "|---|:--:|" separator line, then every
  // following line that still contains a "|". Built with DOM calls like the
  // rest of this function -- never innerHTML -- and each cell goes through
  // the same inline link/bold handling.
  const TABLE_SEP_RE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/;

  function splitTableRow(line) {
    let t = line.trim();
    if (t.startsWith("|")) t = t.slice(1);
    if (t.endsWith("|") && !t.endsWith("\\|")) t = t.slice(0, -1);
    return t.split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, "|"));
  }

  function buildTable(headerLine, sepLine, bodyLines) {
    const header = splitTableRow(headerLine);
    const aligns = splitTableRow(sepLine).map((c) =>
      c.startsWith(":") && c.endsWith(":") ? "center" : c.endsWith(":") ? "right" : "");
    const wrap = document.createElement("div");
    wrap.className = "md-table-wrap";
    const table = document.createElement("table");
    table.className = "md-table";
    const addRow = (parent, cells, tag) => {
      const tr = document.createElement("tr");
      for (let i = 0; i < header.length; i++) {
        const cell = document.createElement(tag);
        if (aligns[i]) cell.style.textAlign = aligns[i];
        appendInline(cell, cells[i] ?? "");
        tr.appendChild(cell);
      }
      parent.appendChild(tr);
    };
    const thead = document.createElement("thead");
    addRow(thead, header, "th");
    table.appendChild(thead);
    const tbody = document.createElement("tbody");
    for (const line of bodyLines) addRow(tbody, splitTableRow(line), "td");
    table.appendChild(tbody);
    wrap.appendChild(table);
    return wrap;
  }

  // Fenced code blocks (2026-10-31, at the user's request: box-drawing
  // diagrams in Claude's replies came out ragged). They are laid out as a
  // terminal would: no wrapping (the block scrolls sideways instead of the
  // bubble's pre-wrap folding long lines), and every non-ASCII character in
  // a fixed cell -- 2ch for East Asian wide/fullwidth characters and emoji,
  // 1ch for the rest (box drawing, arrows). The CJK fallback font's own
  // glyph widths are not exactly 2ch, so without the cells a line with
  // Japanese in it drifts against one without.
  const FENCE_RE = /^\s*(```|~~~)/;
  const WIDE_RE = /[ᄀ-ᅟ⺀-〾ぁ-㏿㐀-䶿一-鿿ꀀ-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦\u{1F300}-\u{1F64F}\u{1F900}-\u{1F9FF}\u{20000}-\u{3FFFD}]/u;

  function buildCodeBlock(lines) {
    const pre = document.createElement("pre");
    pre.className = "md-code";
    let ascii = "";
    const flushAscii = () => {
      if (ascii) pre.appendChild(document.createTextNode(ascii));
      ascii = "";
    };
    lines.forEach((line, n) => {
      if (n) ascii += "\n";
      for (const ch of line) {
        if (ch <= "\x7e") { ascii += ch; continue; }
        flushAscii();
        const cell = document.createElement("span");
        cell.className = WIDE_RE.test(ch) ? "cw2" : "cw1";
        cell.textContent = ch;
        pre.appendChild(cell);
      }
    });
    flushAscii();
    // Copy button (2026-11-20, the user: コマンドをコピペしやすいように).
    // It sits on a wrapper so it stays put while the block scrolls sideways.
    const wrap = document.createElement("div");
    wrap.className = "md-code-wrap";
    wrap.appendChild(pre);
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "md-copy";
    btn.textContent = "⧉";
    btn.title = btn.ariaLabel = t("common.copy");
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      copyCodeText(pre.textContent, btn);
    });
    wrap.appendChild(btn);
    return wrap;
  }

  function copyCodeText(text, btn) {
    const done = (ok) => {
      btn.textContent = ok ? "✓" : "✗";
      btn.classList.toggle("ok", ok);
      setTimeout(() => { btn.textContent = "⧉"; btn.classList.remove("ok"); }, 1500);
    };
    const fallback = () => {
      // Without the Clipboard API (not a secure context, or refused): the
      // old way through a hidden text area.
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.className = "copy-source";   // style.css: unseen
      document.body.appendChild(ta);
      ta.select();
      let ok = false;
      try { ok = document.execCommand("copy"); } catch { ok = false; }
      ta.remove();
      done(ok);
    };
    if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(() => done(true), fallback);
    else fallback();
  }

  function setTextWithLinks(el, text) {
    el.textContent = "";
    const lines = text.split("\n");
    let plain = [];
    const flushPlain = () => {
      if (plain.length) appendInline(el, plain.join("\n"));
      plain = [];
    };
    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const fence = line.match(FENCE_RE);
      if (fence) {
        // An unclosed fence (a reply still streaming in) runs to the end.
        flushPlain();
        const body = [];
        let j = i + 1;
        while (j < lines.length && !lines[j].trimStart().startsWith(fence[1])) body.push(lines[j++]);
        el.appendChild(buildCodeBlock(body));
        i = j;
        // Like a table, the block is its own break.
        if (i + 1 < lines.length && lines[i + 1].trim() === "") i++;
        continue;
      }
      // GFM's own rule: the separator must have exactly as many cells as
      // the header (which also keeps a lone "--" line from counting).
      if (line.includes("|") && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1])
          && splitTableRow(line).length >= 2
          && splitTableRow(lines[i + 1]).length === splitTableRow(line).length) {
        // The newline that ended the text before the table is the table's
        // own block break now -- keeping it would add an empty line.
        flushPlain();
        const body = [];
        let j = i + 2;
        while (j < lines.length && lines[j].includes("|") && lines[j].trim() !== "") body.push(lines[j++]);
        el.appendChild(buildTable(line, lines[i + 1], body));
        i = j - 1;
        // Same for the line break right after it.
        if (i + 1 < lines.length && lines[i + 1].trim() === "") i++;
        continue;
      }
      plain.push(line);
    }
    flushPlain();
  }

  function appendInline(el, text) {
    let last = 0;
    for (const m of text.matchAll(INLINE_RE)) {
      if (m.index > last) el.appendChild(document.createTextNode(text.slice(last, m.index)));
      if (m[1]) {
        const url = trimUrl(m[1], text[m.index - 1]);
        const a = document.createElement("a");
        a.href = url;
        a.textContent = url;
        a.target = "_blank";
        a.rel = "noopener noreferrer";
        el.appendChild(a);
        last = m.index + url.length;
        continue;
      }
      const strong = document.createElement("strong");
      strong.textContent = m[2];
      el.appendChild(strong);
      last = m.index + m[0].length;
    }
    if (last < text.length) el.appendChild(document.createTextNode(text.slice(last)));
  }

  // ---- the live screen panel --------------------------------------------
  //
  // The chat log is append-only: it can show a menu appearing, but not the
  // cursor moving *within* it, because that is an in-place redraw of rows
  // that were already committed as a bubble. That made Claude Code's
  // selection menus unusable from a phone — arrow keys were delivered and
  // the cursor did move, but nothing on screen said so. This panel shows the
  // pane exactly as tmux renders it, refreshed on every change, so a menu is
  // always readable and answerable. The chat log is left alone: it stays the
  // transcript, this is the current state.

  let screenVisible = false;
  let latestScreen = "";
  // Whether the pane is showing the live tail (kept in sync with every SSE
  // "screen" push) or a one-shot full-scrollback fetch the user scrolled up
  // into (2026-08-31) -- while the latter,
  // applyScreen must not overwrite what's on screen out from under the user
  // just because the live pane changed somewhere below what they're reading.
  let screenAtLive = true;
  let screenHistoryLoading = false;
  // How many _screen_backlog lines have been pulled into view so far, and
  // whether the backend says there are more further back -- same shape as
  // the chat log's oldestLoadedSeq/hasMoreHistory
  // (2026-09-01). Reset whenever screenAtLive goes
  // true, since the next pull starts a fresh walk from the live end again.
  let screenHistoryLoaded = 0;
  let screenHistoryHasMore = true;

  // The single place screenAtLive ever changes, so the button that is the
  // *guaranteed* way back to live (see its own CSS/HTML comments) can never
  // drift out of sync with it -- 2026-09-01: the bug this fixes was exactly
  // that drift, not the flag itself. Before this, three call sites each set
  // `screenAtLive = true` directly and none of them touched the button
  // (which did not exist yet), so there was no way back to live once
  // loadScreenHistory set it false other than fully closing and reopening
  // the panel (setScreenVisible's own reset) -- reported by the user as
  // menu-navigation and post-send screen updates silently stopping until
  // they closed and reopened the panel every time.
  function setScreenAtLive(on) {
    screenAtLive = on;
    screenLiveBtnEl.classList.toggle("visible", !on);
    if (on) {
      screenHistoryLoaded = 0;
      screenHistoryHasMore = true;
      screenPaneEl.textContent = latestScreen;
      screenPaneEl.scrollTop = screenPaneEl.scrollHeight;
    }
  }
  screenLiveBtnEl.addEventListener("click", () => setScreenAtLive(true));

  function applyScreen(text) {
    latestScreen = text;
    if (!screenVisible || !screenAtLive) return;
    // Keep the bottom pinned unless the user has scrolled up to read.
    const atBottom =
      screenPaneEl.scrollHeight - screenPaneEl.scrollTop - screenPaneEl.clientHeight < 24;
    screenPaneEl.textContent = text;
    if (atBottom) screenPaneEl.scrollTop = screenPaneEl.scrollHeight;
  }

  // Scrolling to the very top of the live tail pages backward through
  // _screen_backlog -- the lines aiza-backend itself has recorded
  // scrolling off this pane over time (GET .../screen?before=N,
  // screen_history_page) -- and prepends each page above what is already
  // shown, same "don't jump" shape as the chat log's own loadOlderHistory.
  // 2026-09-01: replaces the
  // previous day's one-shot `?full=1` (raw `capture-pane -S -`), which
  // only ever worked for a plain, non-fullscreen pane -- tmux keeps no
  // scrollback at all for the alternate screen a fullscreen program
  // (claude-tui, or `claude` run by hand) draws in, so that approach came
  // back identical to the live tail there, however far the user pulled.
  // This backlog is built by aiza-backend's own poll loop instead, so it
  // works the same way for both kinds of pane.
  async function loadScreenHistory() {
    if (screenHistoryLoading || (!screenAtLive && !screenHistoryHasMore) || !currentSessionId) return;
    screenHistoryLoading = true;
    const still = ui.ticket("session");
    try {
      const r = await api(sessionPath(
        currentSessionId, `/screen?before=${screenHistoryLoaded}`, currentOwner));
      if (!screenVisible || !still()) return;
      screenHistoryHasMore = r.has_more;
      if (!r.text) return;  // nothing (further) to show -- has_more above still applies
      const prevScrollHeight = screenPaneEl.scrollHeight;
      const prevScrollTop = screenPaneEl.scrollTop;
      // #screen-pane's current text is already exactly what belongs below
      // this new page -- the live tail if this is the first pull (setScreenAtLive(false)
      // below only flips the flag/button, it never touches the DOM), or a
      // previously-loaded older page if this is a further pull while
      // already browsing history.
      screenPaneEl.textContent = `${r.text}\n${screenPaneEl.textContent}`;
      screenHistoryLoaded += r.text.split("\n").length;
      setScreenAtLive(false);
      // Same "don't jump" anchor as the chat log's loadOlderHistory.
      screenPaneEl.scrollTop = prevScrollTop + (screenPaneEl.scrollHeight - prevScrollHeight);
    } catch (e) {
      // Scrolling up again retries; nothing to surface for a background fetch.
    } finally {
      screenHistoryLoading = false;
    }
  }

  // The primary trigger for reaching/leaving history mode. computeScreenRows
  // deliberately keeps #screen-pane's content SCREEN_OVERFLOW_BUFFER_ROWS
  // taller than the panel can show at once
  // (2026-09-01), so real, always-present overflow -- and
  // therefore a working "scroll" event -- normally exists to drag into.
  // Before that buffer existed (2026-08-31 through early 2026-09-01), a
  // pane sized to fill the panel *exactly* never overflowed it at all, so
  // this listener alone was not enough -- see the touch/wheel fallback
  // below, kept for the one case the buffer does not cover (a session
  // with barely any content yet, e.g. a freshly opened plain shell, where
  // even the padded height does not reach the panel's own max-height).
  screenPaneEl.addEventListener("scroll", () => {
    if (screenPaneEl.scrollTop < 24) {
      loadScreenHistory();
      return;
    }
    if (!screenAtLive &&
        screenPaneEl.scrollHeight - screenPaneEl.scrollTop - screenPaneEl.clientHeight < 24) {
      setScreenAtLive(true);
    }
  });

  // Fallback for when there is truly nothing to scroll into yet (see the
  // "scroll" listener's own comment) -- a hand-rolled drag gesture, same
  // shape as the header's own pull-to-refresh, which needs the identical trick for the identical reason
  // (nothing there ever overflows either). Armed only when already at
  // scrollTop 0, so a panel that *is* legitimately scrollable still drags
  // normally on the way there (the "scroll" listener above takes over
  // once it arrives). Not preventDefault'd, same reasoning as the
  // header's version.
  (function () {
    const PULL_THRESHOLD = 50;
    let startY = null;
    let pulling = false;
    screenPaneEl.addEventListener("touchstart", (e) => {
      if (e.touches.length !== 1 || screenPaneEl.scrollTop > 0) { startY = null; return; }
      startY = e.touches[0].clientY;
      pulling = false;
    }, { passive: true });
    screenPaneEl.addEventListener("touchmove", (e) => {
      if (startY === null || e.touches.length !== 1) return;
      pulling = e.touches[0].clientY - startY > PULL_THRESHOLD;
    }, { passive: true });
    screenPaneEl.addEventListener("touchend", () => {
      if (pulling && screenAtLive) loadScreenHistory();
      startY = null;
      pulling = false;
    });
  })();
  // A mouse wheel is a real device event independent of whether the
  // element has anything to scroll (unlike touch, which produces no
  // "scroll" event at all over non-overflowing content) -- so this alone
  // already covers a desktop browser without needing a drag gesture.
  screenPaneEl.addEventListener("wheel", (e) => {
    if (screenAtLive && e.deltaY < 0 && screenPaneEl.scrollTop <= 0) loadScreenHistory();
  }, { passive: true });

  function setScreenVisible(on) {
    screenVisible = on;
    screenWrapEl.classList.toggle("visible", on);
    screenBtn.classList.toggle("active", on);
    // agentsBtn now floats inside #screen-wrap (2026-08-28), so it's
    // unreachable once this closes -- force the agents pane closed with it
    // rather than leaving it open with no way to close it.
    if (!on) { setAgentsVisible(false); return; }
    setScreenAtLive(true);
    // A session may have been idle since before this client connected, in
    // which case no "screen" event has arrived yet — fetch the current one.
    if (!currentSessionId) return;
    // The pane's size was only ever set once, at creation -- a session
    // opened again later on a differently-sized device (or adopted from one
    // that was never sized for this screen at all) can be too wide, or too
    // short/tall, for a fullscreen TUI to lay itself out readably. Re-
    // applying the current screen's own size every time this panel opens
    // (not just at creation) is what the user actually asked for
    // (2026-08-15 -- extended to height
    // 2026-08-31) -- cheap and idempotent,
    // so no harm in doing it unconditionally rather than only for sessions
    // known to need it.
    api(sessionPath(currentSessionId, "/resize", currentOwner), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cols: computeScreenCols(), rows: computeScreenRows() }),
    }).catch(() => {});
    const still = ui.ticket("session");   // (the deployment notes) not another session's screen
    api(sessionPath(currentSessionId, "/screen", currentOwner))
      .then((r) => { if (screenVisible && still() && r.text) applyScreen(r.text); })
      .catch(() => {});
  }

  screenBtn.addEventListener("click", () => setScreenVisible(!screenVisible));

  // ---- Claude Code's own subagent (Task-tool) logs ------------------------
  //
  // A session's chat log only ever shows the *parent* conversation's own
  // text -- a subagent Claude Code spawned via the Agent/Task tool does its
  // own work out of view (see list_subagents/get_subagent_log in
  // aiza-backend). This panel lists whatever subagents the current
  // conversation has spawned and, tapped, shows that one's own transcript.
  // Same on-demand "ask fresh, no persistent stream" shape as the screen
  // panel, just polled on an interval instead of pushed via SSE, since a
  // subagent list/log changes far less often than a pane's screen.

  let agentsVisible = false;
  let agentsPollTimer = null;
  let currentAgentId = null;         // null while showing the list, not a detail
  let currentAgentDescription = "";

  function stopAgentsPoll() {
    if (agentsPollTimer) {
      clearInterval(agentsPollTimer);
      agentsPollTimer = null;
    }
  }

  function renderAgentsList(subagents) {
    if (!subagents.length) {
      agentsPaneEl.innerHTML = `<div class="agents-empty">${t("chat.no_subagents_yet")}</div>`;
      return;
    }
    agentsPaneEl.innerHTML = "";
    for (const a of subagents) {
      const row = document.createElement("button");
      row.className = "agent-row";
      const type = document.createElement("span");
      type.className = "agent-type";
      type.textContent = `[${a.agent_type || "?"}]`;
      row.appendChild(type);
      row.appendChild(document.createTextNode(a.description || a.agent_id));
      row.addEventListener("click", () => showAgentDetail(a.agent_id, a.description || a.agent_id));
      agentsPaneEl.appendChild(row);
    }
  }

  function renderAgentDetail(description, text) {
    agentsPaneEl.innerHTML = "";
    const header = document.createElement("div");
    header.className = "agent-detail-header";
    const back = document.createElement("button");
    back.textContent = t("chat.list");
    back.addEventListener("click", () => {
      currentAgentId = null;
      agentsPaneEl.innerHTML = `<div class="agents-empty">${t("common.loading")}</div>`;
      refreshAgentsList();
    });
    header.appendChild(back);
    header.appendChild(document.createTextNode(description));
    agentsPaneEl.appendChild(header);
    const body = document.createElement("div");
    body.className = "agent-detail-body";
    setTextWithLinks(body, text || t("chat.nothing_here_yet"));
    agentsPaneEl.appendChild(body);
  }

  function refreshAgentsList() {
    if (!currentSessionId) return;
    const still = ui.ticket("session");
    api(sessionPath(currentSessionId, "/subagents", currentOwner))
      .then((r) => { if (agentsVisible && still() && currentAgentId === null) renderAgentsList(r.subagents); })
      .catch(() => {});
  }

  function refreshAgentDetail() {
    if (!currentSessionId || currentAgentId === null) return;
    const agentId = currentAgentId;
    const still = ui.ticket("session");
    api(sessionPath(currentSessionId, `/subagents/${agentId}`, currentOwner))
      .then((r) => {
        if (agentsVisible && still() && currentAgentId === agentId) renderAgentDetail(currentAgentDescription, r.text);
      })
      .catch(() => {});
  }

  function showAgentDetail(agentId, description) {
    currentAgentId = agentId;
    currentAgentDescription = description;
    agentsPaneEl.innerHTML = `<div class="agents-empty">${t("common.loading")}</div>`;
    refreshAgentDetail();
  }

  function setAgentsVisible(on) {
    agentsVisible = on;
    agentsPaneEl.classList.toggle("visible", on);
    agentsBtn.classList.toggle("active", on);
    stopAgentsPoll();
    if (!on) return;
    currentAgentId = null;
    agentsPaneEl.innerHTML = `<div class="agents-empty">${t("common.loading")}</div>`;
    refreshAgentsList();
    agentsPollTimer = setInterval(() => {
      if (currentAgentId === null) refreshAgentsList();
      else refreshAgentDetail();
    }, 4000);
  }

  agentsBtn.addEventListener("click", () => setAgentsVisible(!agentsVisible));

  // ---- outbox attachments (images, 3D models, anything else) --------------
  //
  // Every file a session drops in $AIZA_OUTBOX arrives as one "attachment"
  // event with a "kind" the backend detected from the extension
  // (outbox_attachment_kind in aiza-backend) -- this is the one place that
  // decides how each kind actually renders. A GLB a session generates
  // (media-cli's generators) has nothing a plain <img> can show it with,
  // which was the whole reason "kind" exists at all (2026-08-15, at the
  // user's request).
  // `filename` is what actually gets fetched -- this is a backend-made
  // immutable copy (`_frozen_...`), not the name the session's tool used.
  // `displayName` (falls back to `filename` for old events with no
  // source_filename) is what a human should see: the clean original name.
  // `mtl` (the deployment notes, 2026-09-22) is only ever set alongside a
  // kind="model3d" .obj: the same-stem .mtl aiza-backend paired it with,
  // itself unfrozen (see _scan_outbox_for_attachments's own comment on
  // why an OBJ+MTL pair is served by its real names instead).
  function renderAttachment(div, sessionId, filename, kind, displayName, mtl) {
    const url = sessionApiUrl(sessionId, `/files/${encodeURIComponent(filename)}`, currentOwner);
    const label = displayName || filename;
    if (kind === "image") {
      const img = document.createElement("img");
      // Native lazy loading, and set *before* src: history replay on session
      // open appends every past attachment top-to-bottom while the view is
      // pinned to the bottom, so without this every image -- oldest first --
      // competed for the browser's limited concurrent connections and the
      // newest (the one actually on screen) could end up starved out
      // entirely on sessions with many images. `loading` has to be set
      // before `src` -- the browser decides eager-vs-lazy at the moment the
      // src is assigned, not retroactively (2026-08-19, user report).
      img.loading = "lazy";
      img.decoding = "async";
      img.src = url;
      // Tap to view full-size: same "open a new tab" shape as the model3d
      // card below, rather than a same-page lightbox -- a plain image URL
      // as the whole document already gets the browser's own native
      // pinch-zoom/pan/scroll for free, no custom viewer code needed
      // (2026-08-19, at the user's request).
      img.addEventListener("click", () => window.open(url, "_blank"));
      div.appendChild(img);
      return;
    }
    if (kind === "folder") {
      // A directory a session dropped in outbox/ (the deployment notes) --
      // unlike every other kind here, `filename` is a directory name, not
      // something GET .../files/<filename> can serve. Opens a dedicated
      // page (own tab, same "give it the whole screen" reasoning as
      // model3d below) that walks it one level at a time via
      // GET .../outbox-dirs, rather than a same-page modal.
      const btn = document.createElement("button");
      btn.className = "attachment-card";
      btn.innerHTML = `<span class="attachment-icon"><span class="dir-icon"></span></span><span class="attachment-name"></span>`;
      btn.querySelector(".attachment-name").textContent = label;
      btn.addEventListener("click", () => {
        const params = new URLSearchParams({ session: sessionId, dir: filename, name: label });
        if (currentOwner) params.set("owner", currentOwner);
        window.open(`${window.aizaBase}/agents/outbox-browse.html?${params}`, "_blank");
      });
      div.appendChild(btn);
      return;
    }
    if (kind === "model3d") {
      const btn = document.createElement("button");
      btn.className = "attachment-card";
      btn.innerHTML = `<span class="attachment-icon">🧊</span><span class="attachment-name"></span>`;
      btn.querySelector(".attachment-name").textContent = label;
      // A new tab, not a same-page modal: opening a 3D model this way gives
      // an orbit/zoom-capable viewer the whole screen instead of fighting
      // the chat view's own scroll/swipe. The actual viewer page is an
      // extension's concern (aizaExt model3d) -- the published core has no
      // dedicated 3D viewer of its own, so absent that, the plain file just
      // opens as the browser's own default handling for whatever this
      // attachment's mime type is.
      btn.addEventListener("click", () => {
        // An .obj needs the viewer's separate three.js path, and its mtl
        // (if aiza-backend found and paired one) alongside it -- everything
        // else (glb/gltf) keeps the plain two-arg call it always had.
        let taken;
        if (filename.toLowerCase().endsWith(".obj")) {
          const mtlUrl = mtl ? sessionApiUrl(sessionId, `/files/${encodeURIComponent(mtl)}`, currentOwner) : null;
          taken = window.aizaExt.model3d(url, label, { type: "obj", mtl: mtlUrl });
        } else {
          taken = window.aizaExt.model3d(url, label);
        }
        if (!taken) window.open(url, "_blank");
      });
      div.appendChild(btn);
      return;
    }
    // Fallback for anything else outbox_attachment_kind doesn't recognize
    // (e.g. a batch media job's zip) -- a plain download link, better than
    // silently showing nothing.
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    a.className = "attachment-card";
    a.innerHTML = `<span class="attachment-icon">📄</span><span class="attachment-name"></span>`;
    a.querySelector(".attachment-name").textContent = label;
    div.appendChild(a);
  }

  // Claude's thinking (agent_thinking, 2026-10-13): dimmed and folded to a
  // few lines so it doesn't crowd out the replies; a tap unfolds it.
  function renderThought(div, text) {
    div.className = "bubble agent thought";
    div.title = t("chat.thinking_tap_all");
    setTextWithLinks(div, text);
    speechSource.set(div, text); // read only when tapped (resumeSpeaking)
    div.addEventListener("click", (e) => {
      if (e.target.closest("a")) return;
      div.classList.toggle("open");
    });
  }

  // A question or permission prompt from aiza-ask-hook ("ask"), answered
  // here with buttons; "ask_done" closes it (answered here, on the
  // terminal, or given up). Either may come first when older history is
  // paged in, so both are remembered by id.
  const askEls = new Map();
  const askDone = new Map();
  function askShowDone(div, done) {
    div.classList.add("done");
    setTimeout(updateStatusCard, 0);
    for (const el of div.querySelectorAll("button, input")) el.disabled = true;
    let note = div.querySelector(".ask-note");
    if (!note) { note = document.createElement("div"); note.className = "ask-note"; div.appendChild(note); }
    const how = { phone: t("chat.answered"), terminal: t("chat.answered_on_terminal"), timeout: t("chat.timed_out_answer_on_terminal") }[done.how] || t("chat.closed");
    note.textContent = done.text ? `${how}: ${done.text}` : how;
  }
  function closeAsk(ev) {
    askDone.set(ev.ask_id, ev);
    const div = askEls.get(ev.ask_id);
    if (div) askShowDone(div, ev);
  }
  function renderAsk(div, sessionId, ev) {
    div.className = "bubble ask";
    askEls.set(ev.ask_id, div);
    const mine = !currentOwner;
    const owner = currentOwner;
    const send = async (answer, btn) => {
      for (const el of div.querySelectorAll("button, input")) el.disabled = true;
      try {
        const r = await withUnlockRetry(() => api(sessionPath(sessionId, "/ask", owner), {
          method: "POST", headers: { "Content-Type": "application/json" },
          // The card's hash as aiza gave it: the answer is for exactly what
          // this card shows (漏洩対策 N1).
          body: JSON.stringify({ ask_id: ev.ask_id, answer, card_hash: ev.card_hash }),
        }));
        closeAsk({ ask_id: ev.ask_id, how: "phone", text: r.text });
      } catch (e) {
        if (String(e.message).includes("もう答えられません")) closeAsk({ ask_id: ev.ask_id, how: "gone", text: t("chat.can_no_longer_answered") });
        else { for (const el of div.querySelectorAll("button, input")) el.disabled = false; ui.toast(e.message, { error: true }); }
      }
    };
    const mkBtn = (label, cls, fn) => {
      const b = document.createElement("button");
      b.type = "button"; b.className = cls || ""; b.textContent = label;
      b.addEventListener("click", fn);
      return b;
    };
    const row = () => { const r = document.createElement("div"); r.className = "ask-row"; div.appendChild(r); return r; };
    if (ev.unverified) {
      // aiza no longer holds this card (it only stands in the chat's log,
      // which the session can write): its text proves nothing, so no answer
      // here but "on the terminal".
      const head = document.createElement("div");
      head.className = "ask-q";
      const q0 = ev.kind === "question" && Array.isArray(ev.questions) && ev.questions[0];
      head.textContent = ev.kind === "question" ? String((q0 && q0.question) || t("chat.ask_unverified_question")) : t("chat.allow_tool_run", { tool: ev.tool || "?" });
      div.appendChild(head);
      if (ev.kind !== "question" && ev.summary) {
        const code = document.createElement("code");
        code.className = "ask-sum";
        code.textContent = String(ev.summary);
        div.appendChild(code);
      }
      const note = document.createElement("div");
      note.className = "ask-note";
      note.textContent = t("chat.ask_unverified");
      div.appendChild(note);
      if (!ev.gate_out && mine) row().appendChild(mkBtn(t("chat.answer_on_terminal"), "ask-term", () => send({ terminal: true })));
      const done = askDone.get(ev.ask_id);
      if (done) askShowDone(div, done);
      return;
    }
    if (ev.kind === "question") {
      // One question with one answer: tapping an option sends it. Otherwise
      // choose (or write) for every question, then one 送る for the whole
      // card; nothing goes before it (the user, 2026-11-15).
      const parts = [];
      const instant = (ev.questions || []).length === 1 && !ev.questions[0].multiSelect;
      for (const q of ev.questions || []) {
        const head = document.createElement("div");
        head.className = "ask-q";
        head.textContent = q.header ? `${q.header} — ${q.question}` : q.question;
        div.appendChild(head);
        const r = row();
        const picked = new Set();
        for (const o of q.options || []) {
          const b = mkBtn(o.label, "ask-opt", () => {
            if (q.multiSelect) {
              picked.has(o.label) ? picked.delete(o.label) : picked.add(o.label);
            } else if (instant) {
              send({ answers: { [q.question]: o.label } });
              return;
            } else {
              const was = picked.has(o.label);
              picked.clear();
              if (!was) picked.add(o.label);
            }
            for (const x of r.querySelectorAll(".ask-opt")) x.classList.toggle("on", picked.has(x.textContent));
            update();
          });
          if (o.description) b.title = o.description;
          r.appendChild(b);
        }
        const other = document.createElement("input");
        other.type = "text"; other.className = "ask-other"; other.placeholder = t("chat.other_type_press_enter");
        other.addEventListener("input", () => update());
        div.appendChild(other);
        parts.push({ q, picked, other, head });
      }
      const value = (p) => p.other.value.trim() || [...p.picked].join(", ");
      const goRow = row();
      const go = mkBtn(t("common.send"), "ask-go ask-send", () => {
        let missing = false;
        for (const p of parts) { const m = !value(p); p.head.classList.toggle("missing", m); missing = missing || m; }
        if (missing) return;
        const answers = {};
        for (const p of parts) answers[p.q.question] = value(p);
        send({ answers });
      });
      goRow.appendChild(go);
      // A phone keyboard's Enter often only confirms the IME: Enter in a box
      // sends only when every question has an answer.
      for (const p of parts) p.other.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); go.click(); }
      });
      function update() {
        for (const p of parts) if (value(p)) p.head.classList.remove("missing");
        go.classList.toggle("ready", parts.every(value));
      }
    } else {
      const head = document.createElement("div");
      head.className = "ask-q";
      head.textContent = t("chat.allow_tool_run", { tool: ev.tool });
      div.appendChild(head);
      const code = document.createElement("code");
      code.className = "ask-sum";
      code.textContent = ev.summary || "";
      div.appendChild(code);
      // An outward action from the Email box (the deployment notes): everything it
      // would do -- recipients, the whole text, attachments -- on a page.
      if (ev.gate_out && mine) row().appendChild(mkBtn("📄 " + t("chat.see_everything"), "ask-opt", () => showOutPage(sessionId, ev.gate_out)));
      const r = row();
      r.appendChild(mkBtn(t("common.allow"), "ask-go", () => send({ behavior: "allow" })));
      if (ev.can_session) r.appendChild(mkBtn(t("chat.allow_session"), "ask-opt", () => send({ behavior: "allow", session: true })));
      const why = document.createElement("input");
      why.type = "text"; why.className = "ask-other"; why.placeholder = t("chat.reason_denying_optional");
      r.appendChild(mkBtn(t("chat.deny"), "ask-no", () => send({ behavior: "deny", message: why.value.trim() })));
      div.appendChild(why);
    }
    const foot = row();
    // 「答えずにチャットで書く」 (2026-11-27, the user): as Esc on the terminal
    // -- the card closes, the agent stops, and the box is ready for the
    // message. Not on an outward action's card (the deployment notes): 拒否 is that.
    if (!ev.gate_out) foot.appendChild(mkBtn(t("chat.dismiss_write_in_chat"), "ask-term ask-dismiss", async () => {
      await send({ dismiss: true });
      const box = document.getElementById("text");
      if (box && div.classList.contains("done")) box.focus();
    }));
    if (ev.gate_out) { /* answered here only: the terminal has no say over it */ }
    else if (!ev.terminal) foot.appendChild(mkBtn(t("chat.answer_on_terminal"), "ask-term", () => send({ terminal: true })));
    else { const n = document.createElement("span"); n.className = "ask-hint"; n.textContent = t("chat.can_also_answer_on_terminal"); foot.appendChild(n); }
    if (!mine) for (const el of div.querySelectorAll("button, input")) el.disabled = true;
    const done = askDone.get(ev.ask_id);
    if (done) askShowDone(div, done);
  }

  // The full content of an outward action (the deployment notes, 2026-11-20, the
  // user: カードに宛先と中身の全文を見られるページへのリンク。本人だけ). From
  // aiza's memory (or the box, checked against the card's hash); every
  // value is shown as text, nothing from it is rendered as HTML.
  async function showOutPage(sessionId, oid) {
    let d;
    try {
      d = await withUnlockRetry(() => api(`/sessions/${encodeURIComponent(sessionId)}/out/${encodeURIComponent(oid)}`));
    } catch (e) { ui.toast(e.message, { error: true }); return; }
    const box = document.createElement("div");
    box.className = "out-page";
    const inner = document.createElement("div");
    inner.className = "out-inner";
    box.appendChild(inner);
    const add = (label, text, cls) => {
      const h = document.createElement("div"); h.className = "out-k"; h.textContent = label; inner.appendChild(h);
      const v = document.createElement(cls === "pre" ? "pre" : "div"); v.className = "out-v"; v.textContent = text; inner.appendChild(v);
    };
    const title = document.createElement("h3");
    title.textContent = `${d.tool}(${d.id})`;
    inner.appendChild(title);
    const state = d.used ? (d.done ? (d.done.ok ? t("chat.done") : t("chat.failed")) : t("common.running_2"))
      : d.answer === "allow" ? t("chat.allowed") : d.answer === "deny" ? t("chat.not_allowed") : d.answer === "cancel" ? t("chat.withdrawn") : t("chat.waiting_answer");
    add(t("common.state"), state);
    if (d.error) add(t("chat.content"), d.error);
    const a = d.action || {};
    if (d.mail) {
      const m = d.mail;
      add(t("chat.to"), (m.to || []).join("\n") || "-", "pre");
      if ((m.cc || []).length) add("Cc", m.cc.join("\n"), "pre");
      if ((m.bcc || []).length) add("Bcc", m.bcc.join("\n"), "pre");
      add(t("chat.from"), m.from || t("chat.default"));
      if (m.reply_to) add(t("chat.reply_to_header"), m.reply_to);
      if (m.sender) add("Sender", m.sender);
      const raw = Object.entries(m.heads_raw || {}).map(([k, v]) => `${k}: ${v}`).join("\n");
      if (raw) add(t("chat.address_headers_as_written"), raw, "pre");
      add(t("chat.subject"), m.subject || "");
      add(t("common.kind"), m.reply ? t("chat.reply") : t("chat.new_mail"));
      add(t("common.text"), m.text || (m.html_only ? t("chat.html_only_mail_shown_html") + "\n" + m.html_only : ""), "pre");
      const h = document.createElement("div"); h.className = "out-k"; h.textContent = t("common.attachments"); inner.appendChild(h);
      const list = document.createElement("div"); list.className = "out-v"; inner.appendChild(list);
      if (!(m.attachments || []).length) list.textContent = t("common.none");
      (m.attachments || []).forEach((x, i) => {
        const link = document.createElement("a");
        link.href = `${window.aizaBase}/agents/api/sessions/${encodeURIComponent(sessionId)}/out/${encodeURIComponent(oid)}/att/${i}`;
        link.textContent = `${x.name}(${x.size} ${t("chat.bytes")}、${x.type})`;
        link.setAttribute("download", x.name);
        list.appendChild(link); list.appendChild(document.createElement("br"));
      });
    } else if (d.kind === "trash") {
      add(t("chat.threads_move_trash"), (a.threads || []).map((x) => `${x.subject || t("chat.no_subject")} — ${x.from || "?"} — ${x.date || ""}(${x.count} ${t("common.messages")}、${x.id})`).join("\n"), "pre");
    } else if (d.kind === "slack" || d.kind === "discord") {
      add(t("chat.post"), `${a.channel_url}\n${a.channel ? t("chat.channel_name_declared", { x: a.channel }) : ""}`, "pre");
      if (a.thread_ts) add(t("chat.reply_in_thread"), a.thread_ts, "pre");
      add(t("common.text"), a.text || "", "pre");
      if ((a.attachments || []).length) {
        const h = document.createElement("div"); h.className = "out-k"; h.textContent = t("common.attachments"); inner.appendChild(h);
        const list = document.createElement("div"); list.className = "out-v"; inner.appendChild(list);
        a.attachments.forEach((x, i) => {
          const link = document.createElement("a");
          link.href = `${window.aizaBase}/agents/api/sessions/${encodeURIComponent(sessionId)}/out/${encodeURIComponent(oid)}/att/${i}`;
          link.textContent = `${x.name}(${x.size} ${t("chat.bytes")})`;
          link.setAttribute("download", x.name);
          list.appendChild(link); list.appendChild(document.createElement("br"));
        });
      }
    } else if (d.kind === "form") {
      add(t("chat.sent"), a.url || "");
      add(t("chat.values_fill_in"), (a.fields || []).map((f) => `${f.label || f.selector}: ${f.value}`).join("\n"), "pre");
      add(t("chat.submit_button"), a.submit || "");
    }
    add(t("common.hash"), d.hash);
    const btns = document.createElement("div"); btns.className = "out-btns"; inner.appendChild(btns);
    const close = () => box.remove();
    const mk = (label, cls, fn) => { const b = document.createElement("button"); b.type = "button"; b.className = cls; b.textContent = label; b.addEventListener("click", fn); btns.appendChild(b); return b; };
    if (!d.answer && !d.used && !d.error) {
      const answer = async (allow) => {
        for (const b of btns.querySelectorAll("button")) b.disabled = true;
        try {
          await withUnlockRetry(() => api(`/sessions/${encodeURIComponent(sessionId)}/out/${encodeURIComponent(oid)}`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ allow }) }));
          close();
        } catch (e) { for (const b of btns.querySelectorAll("button")) b.disabled = false; ui.toast(e.message, { error: true }); }
      };
      mk(t("common.allow"), "ask-go", () => answer(true));
      mk(t("chat.do_not_allow"), "ask-no", () => answer(false));
    }
    mk(t("common.close"), "", close);
    box.addEventListener("click", (e) => { if (e.target === box) close(); });
    document.body.appendChild(box);
  }

  // One line per tool call ("tool", from Claude's own conversation log):
  // a run of them folds into one line showing the latest and how many more
  // (tap to see all), so the replies stay readable.
  // "denied": Claude Code's auto mode refused it (the deployment notes): its own
  // line, never folded away, with the reason's category.
  function renderTool(div, ev) {
    if (typeof ev.denied === "string") {
      div.className = "toolline denied";
      const why = ev.denied ? t("chat.tool_denied_why", { reason: ev.denied }) : "";
      div.textContent = `⛔ ${t("chat.tool_denied")}: ${ev.text}${why}`;
      div.title = div.textContent;
      return;
    }
    div.className = "toolline";
    div.textContent = `🔧 ${ev.text}`;
  }
  function toolJoin(div) {
    const prev = div.previousElementSibling;
    if (!prev || !div.classList.contains("toolline") || div.classList.contains("denied")
        || prev.classList.contains("denied")) return;
    let group = null;
    if (prev.classList.contains("toolgroup")) {
      group = prev;
    } else if (prev.classList.contains("toolline")) {
      group = document.createElement("details");
      group.className = "toolgroup";
      group.appendChild(document.createElement("summary"));
      const body = document.createElement("div");
      body.className = "tg-body";
      group.appendChild(body);
      prev.replaceWith(group);
      body.appendChild(prev);
    } else {
      return;
    }
    group.querySelector(".tg-body").appendChild(div);
    const lines = group.querySelectorAll(".toolline");
    group.querySelector("summary").textContent =
      `${lines[lines.length - 1].textContent}  ` + t("chat.n_more", { n: lines.length - 1 });
  }

  function renderEvent(sessionId, ev) {
    // Ephemeral, and not a conversation event: it carries no seq, is never
    // written to events.jsonl, and must not disturb the chat log — including
    // the thinking indicator, which every other event clears.
    if (ev.type === "screen") {
      applyScreen(ev.text);
      return;
    }
    // A message that waited in Claude's queue, written again where Claude
    // really took it (aiza-backend _take_pending_user, 2026-11-11): the
    // first copy goes, so a reply never reads as the answer to it.
    if (ev.type === "user_taken") {
      // Claude took a queued message where it stands (nothing in between);
      // also sent when the stream (re)opens, for any taken while away.
      takeQueued(ev.taken);
      return;
    }
    if (typeof ev.moved_from === "number") {
      movedSeqs.add(ev.moved_from);
      takeQueued(ev.moved_from);
      const old = messagesEl.querySelector(`[data-seq="${ev.moved_from}"]`);
      if (old) old.remove();
    }
    if (typeof ev.seq === "number" && movedSeqs.has(ev.seq)) return;

    // Headless preset turns only ever produce a single final agent_output
    // (no incremental streaming), so the wait between
    // a user_message and the reply can be several seconds with nothing else
    // happening; any new event means "no longer just waiting".
    removeThinkingIndicator();

    if (ev.type === "live_tail") {
      // Update the still-in-progress tail line in place -- see
      // _watch_attached_session in aiza-backend. Any *other* event type
      // (including a settled agent_output for the same session) means this
      // particular live bubble is done changing, so the next live_tail
      // should start a fresh one instead of resuming this one.
      const follow = chatNearBottom();
      if (!liveBubbleEl) {
        liveBubbleEl = document.createElement("div");
        liveBubbleEl.className = "bubble agent live";
        chatInsert(liveBubbleEl);
      }
      setTextWithLinks(liveBubbleEl, ev.text);
      afterChatAppend(follow);
      return;
    }
    // The live bubble was only ever a preview of not-yet-settled content --
    // whatever real event just arrived (agent_output, typically) supersedes
    // it, sometimes with byte-identical text (a no-output command like `cd`
    // settles to exactly what the live bubble already showed). Dropping
    // just the reference and leaving the element in #messages produced two
    // visibly duplicate bubbles; removing it here is what "supersedes"
    // needs to actually mean.
    if (liveBubbleEl) {
      liveBubbleEl.remove();
      liveBubbleEl = null;
    }

    if (ev.type === "ask_done") {
      closeAsk(ev);
      return;
    }
    const div = buildBubble(sessionId, ev);
    if (!div) return;
    if (ev.type === "session_ended" && sessionId === currentSessionId) {
      chatDotEl.className = "dot stopped";
      // A dead session's pane has nothing further to arrive -- see
      // updateUnlockNotice()'s own alive check.
      if (currentSessionMeta) currentSessionMeta.alive = false;
      updateUnlockNotice();
      updateChatResumeBtn();
      // A claude-login pane ends exactly when `claude auth login` is done,
      // success or failure -- i.e. this is the moment the auth panel's
      // answer changed, and the user should not have to press ⟳ to find out.
      if (isLoginPreset(currentPreset)) {
        refreshAuthStatus();
        div.textContent += "\n" + t("chat.tap_anywhere_go_back");
        tapToLeave = true;
        composerEl.style.display = "none";
        keyToolbarEl.classList.remove("visible");
      }
    }
    // One's own message always scrolls down (it was just sent from the
    // composer below); a relayed/shared one (ev.from) follows the rule.
    const follow = chatNearBottom() || (ev.type === "user_message" && !ev.from);
    if (ev.type === "user_message" && ev.queued && !renderingHistory) {
      // Shown at once, then Claude's output still going on its previous turn
      // goes above it until Claude takes it (2026-11-11, the user: 届いたことは
      // 早く分かるように表示し、あとでクロードの返事が割り込む形に).
      div.classList.add("queued");
      div.title = t("chat.waiting_claude_take");
      div.dataset.queuedAt = String(Date.now());
      messagesEl.appendChild(div);
      queuedUserEls.push(div);
    } else if (ev.type === "user_message" && !ev.moved_from) {
      messagesEl.appendChild(div);
    } else {
      chatInsert(div);
    }
    toolJoin(div);
    afterChatAppend(follow);
    return div;
  }

  // Messages sent while Claude was busy that Claude has not taken yet
  // (renderEvent, live only): the oldest is where new output goes in.
  const queuedUserEls = [];
  let renderingHistory = false;
  const QUEUED_GIVE_UP_MS = 10 * 60 * 1000;  // never told it was taken: stop holding the bottom
  function chatInsert(el) {
    while (queuedUserEls.length && (!queuedUserEls[0].isConnected
           || Date.now() - Number(queuedUserEls[0].dataset.queuedAt) > QUEUED_GIVE_UP_MS)) {
      queuedUserEls.shift().classList.remove("queued");
    }
    if (queuedUserEls.length) messagesEl.insertBefore(el, queuedUserEls[0]);
    else messagesEl.appendChild(el);
  }
  function takeQueued(seq) {
    // Claude reads the queue in order: this one and any sent before it.
    while (queuedUserEls.length && !(Number(queuedUserEls[0].dataset.seq) > seq)) {
      queuedUserEls.shift().classList.remove("queued");
    }
  }

  // ---- chat history paging ------------------------------------------------
  //
  // A long-running session's events.jsonl can run to thousands of lines --
  // replaying all of it through SSE on every open (the old behavior) made
  // the initial render slow: thousands of DOM nodes and scrollTop-forced
  // reflows, not network transfer, dominated the wait (2026-08-28, at the
  // user's request). Now only the last HISTORY_PAGE_LIMIT events are loaded
  // up front (via GET .../events/page, plain JSON, not SSE); the SSE stream
  // then opens with ?since=<newest loaded seq> so it never replays what was
  // already fetched. Scrolling to the top of #messages fetches the next
  // page further back on demand, same shape as any other lazy-loaded chat
  // history.

  const HISTORY_PAGE_LIMIT = 50;
  let oldestLoadedSeq = null;   // seq of the oldest event currently rendered
  const movedSeqs = new Set();  // first copies of queued messages (renderEvent)
  let hasMoreHistory = false;
  let loadingHistory = false;
  const historyTopEl = document.createElement("div");
  historyTopEl.className = "history-top";

  function setHistoryTopText(text) {
    historyTopEl.textContent = text;
    historyTopEl.style.display = text ? "" : "none";
  }

  // One event's bubble, for the live tail (renderEvent, which adds what an
  // event does to the open session) and for older history pages alike;
  // null for what draws nothing (live_tail, screen, ask_done and unknown
  // types are handled by the callers or skipped).
  function buildBubble(sessionId, ev) {
    const div = document.createElement("div");
    if (typeof ev.seq === "number") div.dataset.seq = ev.seq; // jump target for search (jumpToSeq)
    if (ev.type === "user_message") {
      div.className = "bubble user";
      // ev.from is set only when a shared collaborator, not
      // the owner, sent this -- shown as a name prefix so a co-worked
      // session's log stays legible about who typed what.
      if (ev.from) {
        const who = document.createElement("span");
        who.className = "from";
        who.textContent = `${ev.from}: `;
        div.appendChild(who);
      }
      div.appendChild(document.createTextNode(ev.text));
      // Two different acts land in the same log, so they have to look
      // different: without this marker, a 送信 still sitting unentered in the
      // pane is indistinguishable from one that was already run.
      if (ev.submit === false) {
        const tag = document.createElement("span");
        tag.className = "nosubmit";
        tag.textContent = t("chat.no_enter");
        div.appendChild(tag);
      }
    } else if (ev.type === "agent_output") {
      div.className = "bubble agent";
      setTextWithLinks(div, ev.text);
      const need = needsYouOf(ev.text);
      if (need !== null) div.dataset.needsYou = need;
      if (speakable(currentPreset, ev)) speechSource.set(div, ev.text);
    } else if (ev.type === "agent_thinking") {
      renderThought(div, ev.text);
    } else if (ev.type === "image") {
      // Legacy event type: every outbox file was called "image" before
      // "attachment"+"kind" existed (2026-08-15) -- old sessions'
      // events.jsonl still has these, and they really were always images.
      // New events use "attachment" below.
      div.className = "bubble agent";
      const img = document.createElement("img");
      const imgUrl = sessionApiUrl(sessionId, `/files/${encodeURIComponent(ev.filename)}`, currentOwner);
      img.loading = "lazy";
      img.decoding = "async";
      img.src = imgUrl;
      img.addEventListener("click", () => window.open(imgUrl, "_blank"));
      div.appendChild(img);
    } else if (ev.type === "attachment") {
      div.className = "bubble agent";
      renderAttachment(div, sessionId, ev.filename, ev.kind, ev.source_filename, ev.mtl);
    } else if (ev.type === "session_ended") {
      div.className = "bubble system";
      // exit_status is only present when the pane was kept around long
      // enough to be read (aiza-backend's remain-on-exit path); a nonzero
      // one is worth showing, since the message that explains it is the
      // bubble immediately above this one.
      div.textContent = ev.exit_status
        ? t("chat.session_ended_exit_code_code", { code: ev.exit_status })
        : t("chat.session_ended");
    } else if (ev.type === "system") {
      div.className = "bubble system";
      // A message the server makes carries its key (ev.msg, the deployment notes): said
      // in the reader's language. One saved before keys has only its
      // Japanese text; the known ones are looked up by it.
      const old = !ev.msg && window.aizaI18n.fromText(ev.text);
      const m = ev.msg || (old ? { key: old } : null);
      div.textContent = m ? t(m.key, m.vars) : (ev.text || "");
    } else if (ev.type === "ask") {
      renderAsk(div, sessionId, ev);
    } else if (ev.type === "tool") {
      renderTool(div, ev);
    } else {
      return null;
    }
    return div;
  }

  // 「要判断」 to look at (2026-11-27, the user approved, the deployment notes):
  // when the latest reply ends with 「状態: 要判断 — …」 and no question or
  // permission card is open, a small card under it -- ✓ 確認した sends
  // 「確認しました」 (resuming a stopped session first), 後で only folds it.
  // The next reply or message takes it away. A choice to make comes as an
  // AskUserQuestion card instead (the rule the sessions are given).
  const NEEDS_YOU_RE = /(?:^|\n)[ \t]*状態[:：][ \t]*要判断[ \t]*(?:[—–-][ \t]*(.*?))?[ \t]*$/;
  function needsYouOf(text) {
    const m = NEEDS_YOU_RE.exec(String(text || "").replace(/\s+$/, ""));
    return m ? (m[1] || "") : null;
  }
  const statusFolded = new Set();   // "<session>/<seq>" folded with 後で, in this page
  let statusCardEl = null;
  function updateStatusCard() {
    const last = [...messagesEl.querySelectorAll(".bubble.agent, .bubble.user")].pop();
    const readOnly = currentShareMode === "read" || !!(currentSessionMeta && currentSessionMeta.read_only);
    const askOpen = !!messagesEl.querySelector(".bubble.ask:not(.done)");
    const want = last && last.dataset.needsYou !== undefined && !readOnly && !askOpen && currentSessionId ? last : null;
    if (!want) { if (statusCardEl) { statusCardEl.remove(); statusCardEl = null; } return; }
    const key = `${currentOwner || ""}/${currentSessionId}/${want.dataset.seq}`;
    if (statusCardEl && statusCardEl.dataset.key === key) {
      if (statusCardEl.previousElementSibling !== want) want.after(statusCardEl);
      return;
    }
    if (statusCardEl) statusCardEl.remove();
    const el = document.createElement("div");
    el.className = "status-card";
    el.dataset.key = key;
    const what = document.createElement("span");
    what.className = "status-card-what";
    what.textContent = "🙋 " + (want.dataset.needsYou || t("chat.needs_you"));
    const ok = document.createElement("button");
    ok.type = "button"; ok.className = "status-card-ok"; ok.textContent = "✓ " + t("chat.status_checked");
    const later = document.createElement("button");
    later.type = "button"; later.className = "status-card-later"; later.textContent = t("chat.status_later");
    const fold = (on) => { el.classList.toggle("folded", on); if (on) statusFolded.add(key); else statusFolded.delete(key); };
    later.addEventListener("click", () => fold(true));
    what.addEventListener("click", () => { if (el.classList.contains("folded")) fold(false); });
    const sid = currentSessionId, owner = currentOwner;
    ok.addEventListener("click", async () => {
      ok.disabled = later.disabled = true;
      const text = t("chat.status_checked_message");
      const here = () => chatNow.id === sid && chatNow.owner === owner;
      try {
        let to = sid;
        if (currentSessionMeta && currentSessionMeta.alive === false && here()) to = await resumeToSend(sid, owner, here);
        await withUnlockRetry(() => api(sessionPath(to, "/messages", to === sid ? owner : null), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, submit: true, typed: true, ...(to !== sid ? { wait_ready: true } : {}) }),
        }));
      } catch (e) {
        ok.disabled = later.disabled = false;
        ui.toast(t("chat.could_not_send_checked_err", { err: e.message }), { error: true });
      }
    });
    el.append(what, ok, later);
    if (statusFolded.has(key)) el.classList.add("folded");
    want.after(el);
    statusCardEl = el;
  }
  let statusCardQueued = false;
  new MutationObserver((muts) => {
    if (muts.every((m) => [...m.addedNodes, ...m.removedNodes].every((n) => n === statusCardEl || (n.classList && n.classList.contains("status-card"))))) return;
    if (statusCardQueued) return;
    statusCardQueued = true;
    setTimeout(() => { statusCardQueued = false; updateStatusCard(); }, 0);
  }).observe(messagesEl, { childList: true });

  async function loadOlderHistory(limit = HISTORY_PAGE_LIMIT) {
    if (loadingHistory || !hasMoreHistory || oldestLoadedSeq === null || !currentSessionId) return false;
    loadingHistory = true;
    setHistoryTopText(t("common.loading"));
    const sessionId = currentSessionId;
    const owner = currentOwner;
    try {
      const page = await api(sessionPath(sessionId, `/events/page?before=${oldestLoadedSeq}&limit=${limit}`, owner));
      if (sessionId !== currentSessionId) return false; // switched sessions while this was in flight
      const prevScrollHeight = messagesEl.scrollHeight;
      const prevScrollTop = messagesEl.scrollTop;
      const frag = document.createDocumentFragment();
      for (const ev of page.events) if (typeof ev.moved_from === "number") movedSeqs.add(ev.moved_from);
      for (const ev of page.events) {
        if (movedSeqs.has(ev.seq)) continue;
        if (ev.type === "ask_done") { closeAsk(ev); continue; }
        const div = buildBubble(sessionId, ev);
        if (div) { frag.appendChild(div); toolJoin(div); }
      }
      messagesEl.insertBefore(frag, historyTopEl.nextSibling);
      // Keeps whatever the user was looking at in place rather than jumping
      // as new content grows the pane above it.
      messagesEl.scrollTop = prevScrollTop + (messagesEl.scrollHeight - prevScrollHeight);
      hasMoreHistory = page.has_more;
      if (page.events.length) oldestLoadedSeq = Math.min(...page.events.map((e) => e.seq));
      setHistoryTopText(hasMoreHistory ? "" : t("common.start_conversation"));
      return true;
    } catch (e) {
      setHistoryTopText(t("chat.loading_failed_scroll_try_again"));
      return false;
    } finally {
      loadingHistory = false;
    }
  }

  messagesEl.addEventListener("scroll", () => {
    if (messagesEl.scrollTop < 80) loadOlderHistory();
  });

  // ---- jump to one event (chat search, 2026-10-11) -------------------------
  //
  // Loads older pages until the event with this seq is rendered, then
  // scrolls it to the middle of #messages and flashes it. Pages are sized to
  // reach the target in as few requests as possible (the backend caps a
  // page at 500).
  let pendingJumpSeq = null;
  let pendingJumpTerms = [];

  // The first occurrence of any of `terms` inside `el`, as a Range, plus
  // every occurrence for highlighting -- a bubble can be far taller than
  // the screen (a pasted log), where centering the bubble itself would
  // leave the match off-screen.
  function findTermRanges(el, terms) {
    const ranges = [];
    if (!terms.length) return ranges;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const lower = node.data.toLowerCase();
      for (const t of terms) {
        for (let j = lower.indexOf(t); j !== -1; j = lower.indexOf(t, j + t.length)) {
          const r = document.createRange();
          r.setStart(node, j);
          r.setEnd(node, j + t.length);
          ranges.push(r);
        }
      }
    }
    return ranges;
  }

  async function jumpToSeq(sessionId, seq, terms = []) {
    const find = () => messagesEl.querySelector(`[data-seq="${seq}"]`);
    let el = find();
    while (!el && sessionId === currentSessionId && hasMoreHistory
           && oldestLoadedSeq !== null && oldestLoadedSeq > seq) {
      const need = Math.min(500, oldestLoadedSeq - seq + 10);
      if (!(await loadOlderHistory(need))) break;
      el = find();
    }
    if (!el || sessionId !== currentSessionId) return;
    const ranges = findTermRanges(el, terms);
    if (ranges.length && window.CSS && CSS.highlights && typeof Highlight === "function") {
      CSS.highlights.set("search-term", new Highlight(...ranges));
    }
    const position = () => {
      const first = ranges.length ? ranges[0].getBoundingClientRect() : null;
      if (first && first.height && el.getBoundingClientRect().height > messagesEl.clientHeight) {
        const box = messagesEl.getBoundingClientRect();
        messagesEl.scrollTop += first.top - box.top - messagesEl.clientHeight / 2;
      } else {
        el.scrollIntoView({ block: "center" });
      }
    };
    position();
    // Images and 3D models above the target finish loading after this and
    // push it down; keep it in place for a few seconds, until the user
    // scrolls by hand or leaves the session.
    const stopEvents = ["wheel", "touchstart", "pointerdown", "keydown"];
    let timer = null;
    const stop = () => {
      clearInterval(timer);
      for (const t of stopEvents) messagesEl.removeEventListener(t, stop);
    };
    for (const t of stopEvents) messagesEl.addEventListener(t, stop, { passive: true });
    const until = Date.now() + 5000;
    timer = setInterval(() => {
      if (Date.now() > until || sessionId !== currentSessionId || !el.isConnected) stop();
      else position();
    }, 250);
    el.classList.remove("search-hit");
    void el.offsetWidth; // restart the animation if the same bubble is hit twice
    el.classList.add("search-hit");
  }

  async function connectSessionEvents(meta) {
    oldestLoadedSeq = null;
    movedSeqs.clear();
    queuedUserEls.length = 0;
    hasMoreHistory = false;
    loadingHistory = false;
    setHistoryTopText("");
    let since = 0;
    let replayAll = false;
    try {
      // host/root/Email sessions need this browser's passkey window just to
      // be read (the deployment notes, 2026-10-09): ask for it here, where
      // the tap that opened the session still counts as a user gesture.
      const page = await withUnlockRetry(() => api(sessionPath(meta.id, `/events/page?limit=${HISTORY_PAGE_LIMIT}`, currentOwner)));
      if (meta.id !== currentSessionId) return; // switched sessions while this was in flight
      renderingHistory = true;
      try { for (const ev of page.events) renderEvent(meta.id, ev); } finally { renderingHistory = false; }
      hasMoreHistory = page.has_more;
      if (page.events.length) {
        oldestLoadedSeq = page.events[0].seq;
        since = page.events[page.events.length - 1].seq;
      }
      // Only worth saying for an actual (if short) conversation -- a brand
      // new, still-empty session has nothing to mark the "start" of yet.
      setHistoryTopText(!hasMoreHistory && page.events.length ? t("common.start_conversation") : "");
      if (pendingJumpSeq !== null) {
        const seq = pendingJumpSeq;
        pendingJumpSeq = null;
        await jumpToSeq(meta.id, seq, pendingJumpTerms);
      }
    } catch (e) {
      if (e.unlockRequired) {
        setHistoryTopText(t("chat.reading_session_needs_passkey_unlock"));
        autoAskPasskey(`history:${meta.id}`, async () => {
          await ensureUnlocked(e.unlockTier);
          if (currentSessionId === meta.id) openSession(meta);
        }, null, () => currentSessionId === meta.id);
        return;
      }
      replayAll = true;
      // Falls through to a from-scratch SSE replay (since=0) below -- worse
      // than the fast path, but still correct, and the initial history
      // fetch failing at all should be rare.
    }
    if (meta.id !== currentSessionId) return;
    // Survives backend restarts (2026-10-06, user report "この会話がチャットに
    // 出てません"): while aiza-backend restarts the gateway answers this
    // stream with an error status, and EventSource then gives up for good
    // (readyState CLOSED) -- the chat silently stopped updating until the
    // page was reloaded. On CLOSED, reopen after a short delay from the last
    // seq actually received. The browser's own automatic reconnect (for a
    // dropped-but-200 stream) reuses the original ?since=, so events are
    // de-duplicated by seq here too. Ephemeral ones (no seq: "screen") are
    // always passed through.
    let lastSeq = since;
    const openedAt = Date.now() / 1000;
    const open = () => {
      if (meta.id !== currentSessionId) return;
      if (currentEventSource) currentEventSource.close();
      const es = new EventSource(sessionApiUrl(meta.id, `/events?since=${lastSeq}`, currentOwner));
      currentEventSource = es;
      es.onmessage = (e) => {
        let ev;
        try {
          ev = JSON.parse(e.data);
        } catch (err) {
          console.error("bad event", err);
          return;
        }
        if (typeof ev.seq === "number") {
          if (ev.seq <= lastSeq) return;
          lastSeq = ev.seq;
        }
        let el = null;
        try {
          el = renderEvent(meta.id, ev);
        } catch (err) {
          console.error("bad event", err);
        }
        // Read aloud only what arrives after the history page. If that page
        // failed, this stream replays from seq 0 and only replies newer than
        // the open itself count (ts is the server's clock, hence the slack).
        if (speakable(meta.preset, ev) && meta.id === currentSessionId
            && !(replayAll && !(ev.ts > openedAt - 60))) speak(ev.text, el);
      };
      es.onerror = () => {
        if (es.readyState !== EventSource.CLOSED) return; // the browser is retrying by itself
        setTimeout(async () => {
          if (currentEventSource !== es || meta.id !== currentSessionId) return;
          // The backend also ends the stream when the passkey window closes;
          // reopening would only be refused again every 3 seconds.
          try {
            await api(sessionPath(meta.id, `/events/page?limit=1`, currentOwner));
          } catch (err) {
            if (err.unlockRequired) {
              setHistoryTopText(t("chat.passkey_unlock_expired_open_again"));
              return;
            }
            if (err.loginLost) return;   // the login box is up; the reload after logging in reopens it
          }
          if (currentEventSource === es && meta.id === currentSessionId) open();
        }, 3000);
      };
    };
    open();
  }

  // A session read through the work tree (plan stage 14): its header offers
  // the two ways to take the work on, as the tree's ⋯ does.
  const takeBtns = document.createElement("span");
  takeBtns.id = "take-btns";
  function showTakeButtons(meta, readOnly) {
    takeBtns.replaceChildren();
    if (!takeBtns.parentNode && chatOwnerBadgeEl.parentNode) chatOwnerBadgeEl.after(takeBtns);
    if (!meta.owner || !readOnly) return;
    const owner = meta.owner, sid = meta.id;
    api("/tree").then((r) => {
      if (currentSessionId !== sid) return;
      const n = (r.nodes || []).find((x) => x.links && x.links.session === sid && (x.session_owner || x.owner) === owner);
      if (!n) return;
      const mkb = (label, fn) => {
        const b = document.createElement("button");
        b.type = "button"; b.className = "take-btn"; b.textContent = label;
        b.addEventListener("click", fn);
        takeBtns.appendChild(b);
      };
      mkb("✍ " + t("common.co_work_2"), async () => {
        try {
          await api(sessionPath(sid, "/join", owner), { method: "POST" });
          const metas = await refreshSessions();
          const m = (metas || lastSessions).find((x) => x.id === sid && x.owner === owner);
          if (m) openSession(m);
        } catch (e) { ui.toast(e.message, { error: true }); }
      });
      mkb("🤛 " + t("common.take_on"), async () => {
        if (!(await ui.confirm(t("chat.take_p_on_new_session", { p: n.title })))) return;
        try {
          const r2 = await api("/tree", { method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ op: "take", id: n.id }) });
          const metas = await refreshSessions();
          const m = (metas || lastSessions).find((x) => x.id === r2.session && !x.owner);
          if (m) openSession(m);
        } catch (e) { ui.toast(e.message, { error: true }); }
      });
    }).catch(() => {});
  }

  function openSession(meta, jumpSeq = null, jumpTerms = []) {
    // From やること (a voice 「次」 or 「…を開いて」, say): leave it first, so
    // the session gets the app's URL and Back returns to the list.
    if (todoOn()) return hideTodoView(() => openSession(meta, jumpSeq, jumpTerms));
    tapToLeave = false;
    markTaskSeen(meta);  // the deployment notes: a 済み looked at leaves the list
    if (!meta.owner) closeSessionNotifications(meta.id);
    pendingJumpSeq = jumpSeq;
    pendingJumpTerms = jumpTerms;
    if (window.CSS && CSS.highlights) CSS.highlights.delete("search-term");
    // Going back from here should land on this session's own machine's
    // list -- matters when it was opened by a notification or a reload's
    // hash rather than by tapping it in that list.
    selectMachine(sessionMachine(meta));
    currentSessionId = meta.id;
    ui.moved("session");
    setTimeout(() => { restoreLoginDraft(meta.id); restoreUnsent(meta); }, 0);
    currentPreset = meta.preset;
    currentSessionMeta = meta;
    openFolderPath(folderOfSession(meta));
    updateUnlockNotice();
    // Set by refreshSharedWithMe() tagging -- absent (falsy)
    // for one's own sessions, which is the only case sessionPath()/
    // sessionApiUrl() need to tell apart.
    currentOwner = meta.owner || null;
    chatLabelEl.textContent = typeIcon(meta) + screenBadge(meta) + meta.label;
    setSessionShare(meta);
    // Read-only: a session shared read-only, or someone else's session on a
    // shared ssh:<machine> adopted only to watch (the deployment notes).
    const readOnly = currentShareMode === "read" || !!meta.read_only;
    chatOwnerBadgeEl.textContent = currentOwner
      ? (readOnly ? t("chat.owner_s_shared_log_read", { owner: currentOwner }) : t("chat.shared_owner", { owner: currentOwner }))
      : meta.read_only ? t("chat.owner_s_session_watch_only", { owner: meta.remote_owner || "?" }) : "";
    showTakeButtons(meta, readOnly);
    // The panel itself is now always reachable (2026-08-28): it also holds
    // 💾 save, which a shared viewer needs too. The sharing *management*
    // controls rendered inside stay owner-only (renderSharePane checks
    // currentOwner) -- managing sharing on a session shared *to* me is not
    // something sharing is meant to also grant.
    shareBtn.title = currentOwner ? t("common.save") : t("common.link_share_save");
    updateShareBtnColor();
    setShareVisible(false);
    chatDotEl.className = `dot ${meta.alive ? "alive" : "stopped"}`;
    messagesEl.innerHTML = "";
    newMsgBtnEl.classList.remove("visible"); // belonged to the previous session
    messagesEl.appendChild(historyTopEl);
    setHistoryTopText("");
    liveBubbleEl = null;
    showPage("chat");   // also hides 設定 when a login was opened from it (closeSession goes back there)
    // #chat-header (back/label/screen/share/reload/stop) replaces it
    // while chatting -- two stacked header bars was too much on a phone
    // screen (2026-08-15, at the user's request). #reload-btn itself moved
    // into #chat-header rather than being lost along with this.
    // Both the soft keyboard and the screen panel are about a real pane, so
    // neither applies to the headless preset.
    const hasPane = !sessionKind(meta).headless && !readOnly;
    keyToolbarEl.classList.toggle("visible", hasPane);
    // Watching someone else's pane is what the screen panel is for; a
    // read-only share is the chat log only (the deployment notes).
    screenBtn.style.display = hasPane || meta.read_only ? "" : "none";
    composerEl.style.display = readOnly ? "none" : "";
    // "Type without submitting" needs somewhere for the characters to sit
    // between calls, which only a real pane has -- a headless turn is a whole
    // message or nothing, so 実行 is the only button there.
    sendBtn.classList.toggle("hidden", !hasPane);
    latestScreen = "";
    setScreenVisible(false);
    setAgentsVisible(false);
    pushSessionHistory();
    setHash(meta.id);
    updatePatrolBar();

    stopSessionEvents();
    stopSpeaking();
    updateSpeakBtn();
    updateChatResumeBtn();
    connectSessionEvents(meta);
  }

  function closeSession() {
    tapToLeave = false;
    const wentBack = popSessionHistory();
    stopSessionEvents();
    stopSpeaking();
    closeSpeakPop();
    closeAudioMenu();
    currentSessionId = null;
    currentOwner = null;
    ui.moved("session");
    setSessionShare(null);
    currentSessionMeta = null;
    updateUnlockNotice();
    keyToolbarEl.classList.remove("visible");
    setScreenVisible(false);
    setAgentsVisible(false);
    // Back to the tab it was opened over (the deployment notes): 設定 for a
    // login opened there -- openAuthView() also does the refreshAuthStatus()
    // that case needs ("coming back from a claude-login session is exactly
    // when this changed, and there is no event to tell us it did") --, 仕事
    // in the view it was in, or an extension's tab.
    const fromSettings = ui.get().tab === "settings";
    sessionOpenedFromAuth = false;
    ui.tabs.back();
    if (!fromSettings) refreshAuthStatus();
    refreshSessions();
    refreshTmuxSessions();
    // A finished conversation is itself resumable, and an agent may have
    // created directories -- so both pickers are re-read on the way back.
    refreshWorkdirs(false);
    // Closed by ← (or a swipe): the history.back() above lands after this,
    // on the page shown here, and its hashchange (if any) is done already.
    if (wentBack) backPopped();
  }
