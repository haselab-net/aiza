// The to-do page (the deployment notes): its one Preact root (TodoPage, TodoList,
// TodoTree), its state (setTodo) and opening / closing it. The tree itself: tree.js.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after page.js and before app.js. What runs here at
// load uses only this file and the earlier ones. Moved out of app.js
// 2026-11-24; the indentation is app.js's.
"use strict";

  // The to-do list (the deployment notes, 2026-11-07): whose turn each session is, from
  // the 「状態:」 line the AI ends its reply with (from Stop hooks and Codex
  // public final answers). Your turn first, then 寝かせ whose date came, AI working,
  // 寝かせ, and 済み not looked at yet. Extensions may add entries on top and
  // to a session's entry (aizaExt todo).
  const todoBadge = document.getElementById("todo-badge");
  const todoModalEl = document.getElementById("todo-modal");
  // Its own URL (2026-11-08, the user: "やることを Email のように URL を分けたい。
  // そこからクリックするとセッションのページへ。ボタンではなくてただリンクを"):
  // since 2026-11-25 仕事's views /work/ball, /work/week, /work/usage
  // (the deployment notes; /todo is sent to /work/ball), every entry a plain
  // link to its session.
  const TODO_PAGE = ui.tabs.start.tab === "work" && ui.tabs.start.view !== "tree";
  // 仕事's view <-> the to-do list's view and 見方 (the deployment notes). 番ごと
  // is the list for now; its tree and 人と AI stay inside it until 仕事's
  // tree takes them over (the design's stages 4 and 5).
  const TODO_OF_VIEW = { ball: { view: "list" }, week: { view: "tree", mode: "week" }, usage: { view: "tree", mode: "usage" } };
  const viewOfTodo = (x) => (x.view === "tree" && !x.chain && (x.mode === "week" || x.mode === "usage") ? x.mode : "ball");
  function taskDue(s) {
    return s.task && s.task.state === "snooze" && (s.task.until || 0) * 1000 <= Date.now();
  }
  function taskGroup(s) {
    const tk = s.task;
    if (s.archived || s.owner || s.locked) return null;
    // A confirmation on the screen puts the session in "you" -- unless ✓/💤
    // was pressed on it by hand since (2026-11-10, the user: チェックしても手番の
    // リストから消えない; Ex5 sat on the weekly-limit question). The next
    // message or reply replaces the by-hand state, so a later question shows again.
    const byHand = tk && tk.by_hand && (tk.state === "done" || tk.state === "snooze");
    if (s.waiting && s.alive && !byHand) return "you";
    if (!tk) return null;
    if (tk.state === "you") return "you";
    if (tk.state === "snooze") return taskDue(s) ? "due" : "snooze";
    if (tk.state === "working") return s.alive ? "working" : null;
    if (tk.state === "done") return tk.seen ? null : "done";
    return null;
  }
  function updateTodoBadge() {
    const n = lastSessions.filter((s) => ["you", "due"].includes(taskGroup(s))).length;
    todoBadge.hidden = !n;
    todoBadge.textContent = n > 99 ? "99+" : String(n || "");
  }
  async function taskSet(s, body) {
    try {
      const r = await api(`/sessions/${encodeURIComponent(s.id)}/task`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      s.task = r.task || undefined;
      taskLocal.set(s.id, { seq: ++taskSeq, task: s.task });
      for (const x of lastSessions) if (x.id === s.id) x.task = s.task;
    } catch (e) { alert(e.message); }
    updateTodoBadge();
  }
  function markTaskSeen(s) {
    if (s && !s.owner && s.task && !s.task.seen) {
      s.task.seen = true;
      taskSet(s, { seen: true });
    }
  }
  // the deployment notes: the "your turn" push waits 10 minutes and goes only if
  // nobody has looked. A session on screen in a focused page someone has
  // used in the last few minutes is being looked at: say so every 30 s (the
  // backend writes only when it changes; a seen push is taken back). This
  // device's own notification for it closes at once.
  let lastUserActivity = Date.now();
  for (const ev of ["pointerdown", "keydown", "wheel", "touchstart"]) {
    window.addEventListener(ev, () => { lastUserActivity = Date.now(); }, { passive: true, capture: true });
  }
  function closeSessionNotifications(id) {
    if (!id || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.getRegistration("/work")
      .then((r) => r && r.getNotifications({ tag: id }))
      .then((ns) => (ns || []).forEach((n) => n.close()))
      .catch(() => {});
  }
  function watchingPing() {
    const id = chatNow.id;
    if (!id || chatNow.owner || document.visibilityState !== "visible" || !document.hasFocus()
        || Date.now() - lastUserActivity > 5 * 60 * 1000) return;
    closeSessionNotifications(id);
    api(`/sessions/${encodeURIComponent(id)}/task`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ seen: true }),
    }).then((r) => {
      const task = (r && r.task) || undefined;
      for (const x of lastSessions) if (x.id === id) x.task = task;
    }).catch(() => {});
  }
  setInterval(watchingPing, 30000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") watchingPing(); });
  function snoozeChoices() {
    const at9 = (d) => { d.setHours(9, 0, 0, 0); return d; };
    const now = new Date();
    const tomorrow = at9(new Date(now.getTime() + 86400000));
    const in3 = at9(new Date(now.getTime() + 3 * 86400000));
    const mon = at9(new Date(now.getTime() + ((8 - now.getDay()) % 7 || 7) * 86400000));
    return [[t("todo.tomorrow"), tomorrow], [t("todo.in_3_days"), in3], [t("todo.next_monday"), mon]];
  }
  function fmtUntil(ts) {
    const d = new Date(ts * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getMonth() + 1}/${d.getDate()} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }
  // Tracked handoffs (the plan's stage 2): what this user's sessions handed
  // to another with 「済み — 〈相手〉へ引き継ぎ」, until the sender closes it.
  let handoffs = [], handoffsAt = 0, handoffsKey = "";
  function refreshHandoffs() {
    if (Date.now() - handoffsAt < 20000) return;
    handoffsAt = Date.now();
    api("/handoffs").then((r) => {
      handoffs = r.handoffs || [];
      const key = JSON.stringify(handoffs);
      if (key !== handoffsKey) { handoffsKey = key; if (todoOn()) renderTodo(); }
    }).catch(() => {});
  }
  function handoffRow(h) {
    const row = document.createElement("div");
    row.className = "item";
    const st = h.done_ts ? t("todo.done_check_close")
      : h.to_gone ? t("todo.other_session_gone")
      : ({ working: t("todo.other_side_working"), you: t("todo.waiting_on_there"), snooze: t("todo.other_side_waiting"), done: t("todo.other_side_done") }[h.to_state] || t("common.delivered"));
    row.innerHTML = `
      <a class="body" href="/agents/#${encodeURIComponent(h.to)}">
        <div class="who">🔁 ${escapeHtml(h.from_label)} → ${escapeHtml(h.to_label)}</div>
        <div class="msg">${escapeHtml(h.head || "")}</div>
        <div class="when">${escapeHtml(st + " · " + fmtStamp(h.ts))}</div>
      </a>`;
    const btns = document.createElement("span");
    btns.className = "btns";
    const b = document.createElement("button");
    b.textContent = "✓"; b.title = t("common.close"); b.className = "check";
    b.addEventListener("click", async (e) => {
      e.preventDefault();
      try {
        await api(`/handoffs/${encodeURIComponent(h.id)}`, { method: "POST" });
        handoffs = handoffs.filter((x) => x.id !== h.id);
        handoffsKey = JSON.stringify(handoffs);
      } catch (err) { alert(err.message); }
      renderTodo();
    });
    btns.appendChild(b);
    row.appendChild(btns);
    return row;
  }

  // The work tree (the plan's stage 2): the same page, a second view.
  // Which view, kept in this browser so a reload stays on the tree (2026-11-15,
  // the user: 木で todo をリロードしたときに一覧に戻らないように).
  // (The tree's own state -- treeData, treeAt, weekData, usageData ... -- is tree.js's.)
  // The to-do view to open with (localStorage, as before) while ui.todo is
  // closed; ui.todo holds the one shown.
  let todoLast = { view: "list", mode: "tree" };
  try { if (localStorage.getItem("aiza-todo-view") === "tree") todoLast.view = "tree"; } catch (e) {}
  // Within the tree view (the plan's stage 3): the tree, by person and AI (B),
  // the week's summary; and the chain holding one job up (C, from a row's ⋯).
  try { todoLast.mode = localStorage.getItem("aiza-tree-mode") || "tree"; } catch (e) {}
  if (TODO_PAGE) todoLast = { ...todoLast, ...TODO_OF_VIEW[ui.tabs.start.view] };
  // ✓/💤/⏰'s sequence (the deployment notes): taskLocal's entries newer than a list refresh win over it.
  let taskSeq = 0;
  const todoOn = () => !!ui.get().todo;
  const todoNow = () => ui.get().todo || { ...todoLast, chain: null };
  const todoIs = (view, mode) => { const x = ui.get().todo; return !!x && x.view === view && (!mode || x.mode === mode); };
  // A change to the shown to-do list (its view, the tree's 見方, ⛓): it is
  // drawn again by the subscription below -- the one way it is redrawn for
  // these, renderTodo (which waits while a row is dragged).
  function setTodo(patch) {
    const next = { ...todoNow(), ...patch };
    todoLast = { view: next.view, mode: next.mode };
    if (ui.get().todo) ui.set({ todo: next });
  }
  ui.subscribe((st, prev) => { if (st.todo && prev.todo && st.todo !== prev.todo) renderTodo(); });
  // A 見方 chosen inside the list moves 仕事's view (and its address) with it.
  ui.subscribe((st, prev) => {
    if (!st.todo || st.todo === prev.todo || st.tab !== "work") return;
    const v = viewOfTodo(st.todo);
    if (v !== st.view) { ui.set({ view: v }); history.replaceState(history.state, "", ui.tabs.path() + location.search); ui.tabs.bar(); }
  });
  // The tree view and its menus: tree.js.
  // Usage (an estimate at API list prices, not a subscription's bill).
  function fmtCost(c) { return c == null ? "" : c >= 10 ? `$${c.toFixed(0)}` : `$${c.toFixed(2)}`; }
  function fmtTokens(n) { return n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n || 0); }

  // A part still made by a DOM function: made again on every draw.
  function DomBox({ build }) {
    const ref = PH.useRef(null);
    PH.useLayoutEffect(() => { const el = ref.current; el.innerHTML = ""; build(el); });
    return html`<div class="dom-box" ref=${ref}></div>`;
  }
  function TodoTree() {
    PH.useEffect(() => {
      if (treeData && Date.now() - treeAt > 20000) loadTree();   // the page's own refresh reads it again
      if (!treeData) loadTree();
    });
    if (!treeData) return html`<div key="msg" class="empty">${t("common.loading")}</div>`;
    if (treeData.unavailable) return html`<div key="msg" class="empty">${t("common.host_no_work_tree")}</div>`;
    const { mode, chain } = todoNow();
    const legacy = chain ? renderChain : mode === "week" ? renderWeek : mode === "usage" ? renderUsage : null;
    if (!legacy) { setTimeout(() => setTodo({ view: "list" }), 0); return null; }   // its tree and 人と AI are 仕事's tree and 番ごと now
    return html`<${DomBox} key=${"legacy-" + (chain ? "chain" : mode)} build=${legacy} />`;
  }

  // Not in the middle of a drag (⠿): held until it ends. (An open ⋯ no
  // longer needs this: the tree view keeps it through a refresh.)
  let todoRenderHeld = null;
  function renderTodo() {
    if (treeDrag) {
      if (!todoRenderHeld) todoRenderHeld = setInterval(() => {
        if (treeDrag) return;
        clearInterval(todoRenderHeld); todoRenderHeld = null;
        if (todoOn()) renderTodo();
      }, 300);
      return;
    }
    refreshHandoffs();
    const box = todoModalEl.querySelector(".box");
    // Only Preact draws in .box: what was there before its first draw goes.
    if (!todoRootDrawn) { box.innerHTML = ""; todoRootDrawn = true; }
    window.preact.render(html`<${TodoPage} />`, box);
  }
  let todoRootDrawn = false;
  let todoEverLoaded = false;   // loadTodo has had an answer (else 「確認中…」)
  // The to-do page (2026-11-23: one Preact root, with the tree's work).
  // Since the deployment notes 段5: 仕事's views 🙋 番ごと (TodoList), 📅 週 and
  // 📊 利用 (TodoTree), with ⛓ over them; the tabs say where one is, so no
  // heading, no 一覧 | 木 (仕事's own tree took that over) and no 📨 row
  // (新着 is a tab).
  function TodoPage() {
    const view = todoNow().view;
    return view === "tree" ? html`<${TodoTree} key="tree-view" />` : html`<${TodoList} key="list-view" />`;
  }
  // A row still made by its DOM function (todoRow, handoffRow), made again
  // only when its own data changes (sig): what is open in a row (💤's date,
  // a typed note) stays through the 30-second refresh.
  function DomRow({ sig, build }) {
    const ref = PH.useRef(null);
    PH.useLayoutEffect(() => { const el = ref.current; el.innerHTML = ""; el.appendChild(build()); }, [sig]);
    return html`<div class="dom-row" ref=${ref}></div>`;
  }
  function TodoList() {
    if (!todoEverLoaded && !lastSessions.length) return html`<div class="empty">${t("common.checking")}</div>`;
    const groups = { you: [], due: [], working: [], snooze: [], done: [] };
    for (const s of lastSessions) {
      const g = taskGroup(s);
      if (g) groups[g].push(s);
    }
    const tsOf = (s) => (s.task && s.task.ts) || 0;
    for (const g of Object.values(groups)) g.sort((a, b) => tsOf(b) - tsOf(a));
    groups.snooze.sort((a, b) => (a.task.until || 0) - (b.task.until || 0));
    // Each group with its own mark and colour (2026-11-09, the user: 済みと待ちが
    // 一緒に表示される -- the small grey headings ran together).
    const TITLES = { you: "🙋 " + t("common.turn"), due: "⏰ " + t("todo.snoozes_now_due"), working: "⚙️ " + t("todo.ai_working"),
      snooze: "💤 " + t("common.waiting_snoozed"), done: "✓ " + t("todo.done_not_checked_yet") };
    const sig = (s, g) => JSON.stringify([g, s.label, s.alive, s.waiting, s.preset, s.task, s.owner,
      window.aizaExt.todoRows(s)]);
    const out = [];
    for (const g of ["you", "due", "working", "snooze", "done"]) {
      if (!groups[g].length) continue;
      out.push(html`<div key=${"h-" + g} class=${"group " + g}>${TITLES[g]} (${groups[g].length})</div>`);
      for (const s of groups[g]) out.push(html`<${DomRow} key=${"s-" + s.id} sig=${sig(s, g)} build=${() => todoRow(s, g)} />`);
    }
    if (handoffs.length) {
      out.push(html`<div key="h-handoff" class="group handoff">🔁 ${t("todo.handed_off")} (${handoffs.length})</div>`);
      const order = [...handoffs].sort((a, b) => (!!b.done_ts - !!a.done_ts) || (b.ts - a.ts));
      for (const x of order) out.push(html`<${DomRow} key=${"x-" + x.id} sig=${JSON.stringify(x)} build=${() => handoffRow(x)} />`);
    }
    // From the work tree (段5, what 人と AI showed): its open items no session
    // of this list holds -- mine and waiting on others open, someone else's
    // and nobody's yet folded.
    const turns = ui.trees.turns();
    if (!turns) loadTree();
    else {
      const { out: tt, byId, me } = turns;
      const sec = (k, title, folded, withWho) => {
        const list = tt[k];
        if (!list.length) return;
        const open = !folded || todoTurnsOpen.has(k);
        out.push(html`<div key=${"h-t" + k} class=${"group turns " + k + (folded ? " foldable" : "")}
          onClick=${folded ? () => { open ? todoTurnsOpen.delete(k) : todoTurnsOpen.add(k); renderTodo(); } : undefined}>
          ${folded ? (open ? "▾ " : "▸ ") : ""}${title} (${list.length})</div>`);
        if (open) out.push(html`<${DomRow} key=${"t-" + k} sig=${JSON.stringify(list.map((n) => [n.id, n.title, n.ball, n.tr]))}
          build=${() => ui.trees.turnRows(list, byId, me, k === "others")} />`);
      };
      sec("you", "🙋 " + t("todo.your_turn_in_the_tree"), false, false);
      sec("ext", "✉ " + t("tree.waiting_on_others"), false, false);
      sec("others", "🧑 " + t("todo.others_turn"), true, true);
      sec("none", "○ " + t("tree.nobody_holds_yet"), true, false);
    }
    if (!out.length) return html`<div class="empty">${t("todo.nothing_do_right_now")}</div>`;
    return out;
  }
  // The folded groups of 番ごと opened by a tap (this page only).
  const todoTurnsOpen = new Set();
  function todoRow(s, g) {
    const tk = s.task || {};
    const row = document.createElement("div");
    row.className = "item" + (tk.seen === false ? " unseen" : "");
    let what = tk.text || "";
    if (g === "you" && s.waiting && !(tk.state === "you" && tk.prompt)) what = t("common.waiting") + (what ? ` — ${what}` : "");
    else if (g === "you" && !what) what = tk.declared === false ? t("todo.stopped_no_status_given") : t("common.needs");
    const sub = [];
    if (g === "snooze" || g === "due") sub.push("💤 " + fmtUntil(tk.until));
    if (g === "snooze" && !s.alive) sub.push(t("todo.stopped_now_open_continue"));
    if (tk.ts && g !== "snooze") sub.push(fmtStamp(tk.ts));
    if (s.usage && s.usage.cost != null) sub.push("≈" + fmtCost(s.usage.cost) + " · " + fmtTokens(s.usage.tokens) + " tok");
    // What extensions add to this entry (aizaExt todo.rows): a title in
    // place of the label, link buttons.
    const extra = window.aizaExt.todoRows(s);
    const extraTitle = (extra.find((x) => x && x.title) || {}).title;
    for (const x of extra) if (x && x.note) sub.push(x.note);
    row.innerHTML = `
      <a class="body" href="/agents/#${encodeURIComponent(s.id)}">
        <div class="who">${typeIcon(s)}${escapeHtml(extraTitle || s.label)}</div>
        ${what ? `<div class="msg">${escapeHtml(what)}</div>` : ""}
        ${sub.length ? `<div class="when">${escapeHtml(sub.join(" · "))}</div>` : ""}
      </a>`;
    const btns = document.createElement("span");
    btns.className = "btns";
    const add = (label, title, fn) => {
      const b = document.createElement("button");
      b.textContent = label; b.title = title;
      b.addEventListener("click", async (e) => { e.preventDefault(); await fn(); renderTodo(); });
      btns.appendChild(b);
    };
    for (const x of extra) {
      if (!x || !x.href) continue;
      const a = document.createElement("a");
      a.href = x.href; a.textContent = x.icon || "↗"; if (x.tip) a.title = x.tip;
      btns.appendChild(a);
    }
    // ✓ (2026-11-10, the user): the row turns green and folds away, and an
    // 8-second "元に戻す" (as after 🗄) puts the task back exactly as it was.
    const check = (label, body, said) => {
      const b = document.createElement("button");
      b.textContent = "✓"; b.title = label; b.className = "check";
      b.addEventListener("click", async (e) => {
        e.preventDefault();
        const before = s.task ? JSON.parse(JSON.stringify(s.task)) : null;
        row.style.maxHeight = row.offsetHeight + "px";
        void row.offsetHeight;
        row.classList.add("checked");
        await taskSet(s, body);
        showUndoToast(t(said, { label: s.label }), async () => {
          try {
            const r = await api(`/sessions/${encodeURIComponent(s.id)}/task`, {
              method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ restore: before }),
            });
            s.task = r.task || undefined;
            taskLocal.set(s.id, { seq: ++taskSeq, task: s.task });
            for (const x of lastSessions) if (x.id === s.id) x.task = s.task;
          } catch (err) { alert(err.message); }
          updateTodoBadge();
          renderTodo();
          showUndoToast(t("todo.restored_label", { label: s.label }), false);
        });
        setTimeout(() => {
          const cur = lastSessions.find((x) => x.id === s.id);
          if (cur && cur !== s) cur.task = s.task;
          if (todoOn()) renderTodo();
        }, 850);
      });
      btns.appendChild(b);
    };
    if (g !== "done") check(t("common.mark_done"), { state: "done" }, "todo.marked_label_done");
    else check(t("todo.checked"), { seen: true }, "todo.marked_label_seen");
    if (g === "you" || g === "due" || g === "done") {
      add("💤", t("todo.snooze"), async () => {
        const ch = snoozeChoices();
        const ans = prompt(t("todo.snooze_until_when") + "\n" + ch.map((c, i) => `${i + 1}: ${c[0]} (${fmtUntil(c[1] / 1000)})`).join("\n")
          + "\n" + t("todo.or_month_day_hh_mm"), "1");
        if (ans == null) return;
        let when = null;
        const k = parseInt(ans, 10);
        if (/^\d$/.test(ans.trim()) && ch[k - 1]) when = ch[k - 1][1];
        const m = ans.trim().match(/^(\d{1,2})\/(\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?$/);
        if (m) {
          const now = new Date();
          when = new Date(now.getFullYear(), +m[1] - 1, +m[2], m[3] ? +m[3] : 9, m[4] ? +m[4] : 0);
          if (when < now) when.setFullYear(when.getFullYear() + 1);
        }
        if (!when) return alert(t("todo.could_not_read_date"));
        await taskSet(s, { state: "snooze", until: when.getTime() / 1000 });
      });
    }
    if (g === "snooze") add("⏰", t("todo.do_now"), () => taskSet(s, { state: "you" }));
    row.appendChild(btns);
    return row;
  }
  async function loadTodo(light) {
    // The extensions' own parts of this list need them loaded (/todo
    // opened directly starts before they are).
    if (extLoaded) await extLoaded;
    await Promise.all([
      refreshSessions({ light: !!light }).catch(() => {}),
      ...window.aizaExt.loadAll(),
    ]);
    todoEverLoaded = true;
    if (todoOn()) renderTodo();
  }
  // In the same page (2026-11-08, after trying voice mode): a new page has
  // no user activation, so the browser would not let voice mode speak there.
  // ✅ and the entries still are links (/todo, /agents/#<id>; a middle click
  // or a new tab works as before), but a plain click switches the view here
  // and moves the URL with history.pushState; Back returns.
  const plainClick = (e) => e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
  // view: 仕事's view to show (ball | week | usage), else the one last shown.
  // Never a history entry of its own (the deployment notes: a view of a tab).
  function showTodoView(push, view) {
    if (view && TODO_OF_VIEW[view]) todoLast = { ...todoLast, ...TODO_OF_VIEW[view] };
    if (todoOn()) {
      if (view && viewOfTodo(ui.get().todo) !== view) ui.set({ todo: { ...todoLast, chain: null } });
      loadTodo(true);
      return;
    }
    const show = () => {
      ui.set({ todo: { ...todoLast, chain: null } });
      document.body.classList.add("todo-page");
      document.title = t("common.todo") + " - " + t("common.ai_za");
      // At once from the list this page already has (2026-11-10, the user:
      // やることが確認中で結構待ちます), then again when the fresh one arrives.
      // "確認中…" only when there is no list yet (/todo opened directly).
      renderTodo();   // 「確認中…」 by itself until there is a list
      todoModalEl.hidden = false;
      loadTodo(true);
    };
    const afterOverlay = () => {
      if (chatNow.id) {
        // Closing pops the session's own history entry (async): show after.
        chatNow.close();
        setTimeout(show, 120);
      } else show();
    };
    // Something an extension shows over the page (aizaExt closeOverlay)
    // goes first.
    if (!window.aizaExt.closeOverlay(() => setTimeout(afterOverlay, 0))) afterOverlay();
  }
  // Closed: an open ⋯ of the tree goes with it (the tree's element stays,
  // and the next opening showed the old ⋯ still open -- タスクR 2026-11-23).
  function closeTodoState() {
    treeMenuClose();
    ui.set({ todo: null });
    if (todoRootDrawn && html) { window.preact.render(null, todoModalEl.querySelector(".box")); todoRootDrawn = false; }
  }
  function hideTodoView(then) {
    if (!todoOn()) { if (then) then(); return; }
    const done = () => {
      closeTodoState();
      document.body.classList.remove("todo-page");
      document.title = `${t("common.ai_za")} (${SHORT_HOSTNAME})`;
      todoModalEl.hidden = true;
      refreshSessions().catch(() => {});
      if (then) then();
    };
    done();
  }
  // A session from the to-do list or the tree: on top of /todo, not instead
  // of it (Back closes the session and the popstate below shows the list
  // again), in this page (voice mode goes on).
  function openSessionOverTodo(meta) {
    closeTodoState();
    document.body.classList.remove("todo-page");
    document.title = `${t("common.ai_za")} (${SHORT_HOSTNAME})`;
    todoModalEl.hidden = true;
    chatNow.open(meta);
  }
  todoModalEl.addEventListener("click", (e) => {
    const a = e.target.closest("a");
    if (!a || !plainClick(e)) return;
    const href = a.getAttribute("href") || "";
    const m = /^\/agents\/#([0-9a-f]{8,32})$/.exec(href);
    if (m) {
      e.preventDefault();
      const meta = lastSessions.find((x) => x.id === m[1]);
      if (!meta) return;
      openSessionOverTodo(meta);
    } else if (href === "/agents/" || href === "/work") {
      e.preventDefault();
      ui.tabs.show("work", "tree");
    }
  });
  if (TODO_PAGE) {
    // After every page script has run, not just this file (2026-11-24: a
    // setTimeout(0) could fire while a later script, api.js, was still being
    // fetched -- "api is not defined" on /todo opened directly).
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => showTodoView(false, ui.tabs.start.view), { once: true });
    else setTimeout(() => showTodoView(false, ui.tabs.start.view), 0);
  }
  // The to-do views are 仕事's (page.js showTab): its own to give.
  ui.pages.showTodo = (view) => showTodoView(false, view);
  ui.pages.hideTodo = () => hideTodoView();
  ui.pages.todoOn = () => todoOn();
  setInterval(() => { if (todoOn() && document.visibilityState === "visible") loadTodo(true); }, 30000);
  document.addEventListener("visibilitychange", () => { if (todoOn() && document.visibilityState === "visible") loadTodo(true); });
