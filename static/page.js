// The page's state and the pieces every other script leans on (aiza):
// which page is shown (ui, showPage, checkPage), what kind a session is
// (sessionKind), the new-session form's table (FORM_PRESETS), Preact + htm
// (html, PH).
//
// The first of the page's own scripts (the deployment notes): one
// global scope with tree.js and app.js, loaded before them. What runs here
// at load may use only this file and the vendored libraries; the functions
// use the later files' names when they are called. The indentation is
// app.js's, where this came from (2026-11-24).
"use strict";

  const viewList = document.getElementById("view-list");
  const viewChat = document.getElementById("view-chat");
  const viewAuth = document.getElementById("view-auth");
  const topHeaderEl = document.getElementById("top-header");

  // The page shown (the deployment notes, 2026-11-23, after the settings
  // page stayed on screen with the machine menu saying this host): "list" |
  // "chat" | "auth". Changed only by showPage(), which also sets the header
  // and the machine menu from it; read it here, never from the elements'
  // style. checkPage() then looks at the screen itself and reports what
  // does not agree (console, window.__aizaPageErrors for the tests, and
  // once per kind to the backend's log).
  // The page's state in one place (the deployment notes; agreed with the
  // tree's Preact work 2026-11-23): ui.get(), ui.set(patch) and
  // ui.subscribe(fn(state, prev)). No signals library: if one comes later,
  // makeStore is what it replaces.
  //   page  "list" | "chat" | "auth"   (showPage)
  //   todo  null (closed) | { view: "list"|"tree",
  //         mode: "tree"|"people"|"week"|"usage", chain: node id | null }
  //         (showTodoView / hideTodoView / setTodo)
  //   overlay null | "board" (the Windows machines' blackboard) |
  //         "ext:<name>" (an extension's view over the page, app.overlay)
  function makeStore(init) {
    let state = init;
    const subs = new Set();
    return {
      get: () => state,
      set(patch) {
        const prev = state;
        state = { ...state, ...patch };
        for (const f of [...subs]) f(state, prev);
      },
      subscribe(f) { subs.add(f); return () => subs.delete(f); },
    };
  }
  // ---- The tabs (the deployment notes, 2026-11-25, the user's design) ---------
  // The page's top: 仕事 (/work, with its views /work/ball|week|usage), the
  // extensions' tabs (aizaExt tabs: 新着 /inbox) and 設定 (/settings). A tab
  // is a root: switching tabs replaces the URL and adds no history entry, so
  // Back never goes from one tab to another (the user: 設定や新着のような
  // タブからは、戻るで戻らないほうが良い). What is over a tab (a session,
  // a panel) is pushed, and Back closes it back to that tab.
  //   tab   "work" | "settings" | an extension's tab id ("inbox")
  //   view  仕事's view: "tree" (the session list) | "ball" | "week" | "usage"
  //         (the to-do page, the deployment notes), null on the other tabs
  // A path of this page without a demo seat's base (the deployment notes); as it is on a deployment.
  function localPath(p) { return window.aizaBase && p.startsWith(window.aizaBase + "/") ? p.slice(window.aizaBase.length) : p; }
  const WORK_PATHS = { tree: "/work", ball: "/work/ball", week: "/work/week", usage: "/work/usage" };
  function tabFromPath(path) {
    let p = String(path || "");
    p = localPath(p);
    p = p.replace(/\/+$/, "") || "/";
    if (p === "/settings") return { tab: "settings", view: null };
    const m = /^\/work(?:\/(ball|week|usage))?$/.exec(p);
    if (m) return { tab: "work", view: m[1] || "tree" };
    // An extension's tab (aizaExt tabs): known once the extensions are
    // loaded, so kept by its path until then (startTabs, app.js).
    if (/^\/[a-z]+$/.test(p) && p !== "/agents" && p !== "/todo") return { tab: p.slice(1), view: null, ext: true };
    if (p === "/todo") return { tab: "work", view: "ball" };
    return { tab: "work", view: "tree" };   // /agents/ (the old address) and anything else
  }
  function tabPath(tab, view) {
    const b = window.aizaBase;
    if (tab === "work") return b + (WORK_PATHS[view] || WORK_PATHS.tree);
    if (tab === "settings") return b + "/settings";
    const x = window.aizaExt.tab(tab);
    return b + (x ? x.path : "/" + tab);
  }
  // Where the page opened. The old addresses become the new ones at once:
  // /agents/ -> /work, /agents/#auth -> /settings; a session's /agents/#<id>
  // (a notification's, a shared link) keeps its #<id>: /work#<id>.
  const START_TAB = (() => {
    let at = tabFromPath(location.pathname);
    if (location.hash === "#auth") at = { tab: "settings", view: null };
    const hash = location.hash === "#auth" ? "" : location.hash;
    const url = tabPath(at.tab, at.view) + location.search + hash;
    if (location.pathname + location.search + location.hash !== url) history.replaceState(null, "", url);
    return at;
  })();
  const ui = makeStore({ page: "list", todo: null, overlay: null, tab: START_TAB.tab, view: START_TAB.view });
  ui.localPath = localPath;   // for the other scripts (todo.js's links)
  const pageNow = () => ui.get().page;
  // A late answer must not write into what the user has since moved to
  // (the deployment notes, 2026-11-24): take a ticket before the first
  // await, and after each await write only while ticket() still holds.
  //   ui.ticket()              the page, the machine and the session
  //   ui.ticket("session", …)  only those of: "page" (showPage to another
  //                            page), "machine" (another machine looked at),
  //                            "session" (a session opened or closed, even
  //                            the same one again)
  //   ui.ticket("search")      any other name: the newest ticket of that name
  //                            wins (an earlier one no longer holds)
  // What a dropped answer carried that the user made (typed text, an
  // attached file's path) is not dropped with it: see unsentFor (app.js).
  const moves = { page: 0, machine: 0, session: 0 };
  ui.moved = (kind) => { moves[kind] = (moves[kind] || 0) + 1; };
  ui.ticket = (...kinds) => {
    if (!kinds.length) kinds = ["page", "machine", "session"];
    for (const k of kinds) if (!(k in { page: 1, machine: 1, session: 1 })) ui.moved(k);
    const at = kinds.map((k) => moves[k] || 0);
    return () => kinds.every((k, i) => (moves[k] || 0) === at[i]);
  };
  function showPage(page) {
    if (page !== ui.get().page) ui.moved("page");
    // 設定 is the settings tab; the list shown from it is 仕事's.
    if (page === "auth") ui.set({ page, tab: "settings", view: null });
    else if (page === "list" && ui.get().tab === "settings") ui.set({ page, tab: "work", view: "tree" });
    else ui.set({ page });
    // A session over an extension's tab: its page goes until the session closes (returnToTab).
    const tab = ui.get().tab;
    if (page === "chat" && tab !== "work" && tab !== "settings") window.aizaExt.tabHide(tab);
    updateTabBar();
    viewList.style.display = page === "list" ? "block" : "none";
    viewAuth.style.display = page === "auth" ? "flex" : "none";
    viewChat.style.display = page === "chat" ? "flex" : "none";
    topHeaderEl.style.display = page === "chat" ? "none" : "flex";
    if (machineSelectEl.options.length) {
      machineSelectEl.value = page === "auth" ? "auth" : currentMachine;
      updateMachineBtn();
    }
    setTimeout(() => checkPage("showPage " + page), 0);
  }
  // The tab bar and 仕事's views: which one is on, the views only on 仕事.
  const tabsEl = document.getElementById("tabs");
  const workViewsEl = document.getElementById("work-views");
  function updateTabBar() {
    const st = ui.get();
    for (const b of tabsEl.querySelectorAll("[data-tab]")) {
      const on = b.dataset.tab === st.tab;
      b.classList.toggle("on", on);
      b.setAttribute("aria-selected", on ? "true" : "false");
    }
    workViewsEl.hidden = st.tab !== "work" || st.page === "chat";
    for (const b of workViewsEl.querySelectorAll("[data-view]")) b.classList.toggle("on", b.dataset.view === st.view);
    document.body.dataset.tab = st.page === "chat" ? "" : st.tab;
  }
  // 仕事's view last shown: 仕事 chosen again comes back to it.
  let lastWorkView = START_TAB.tab === "work" ? START_TAB.view : "tree";
  ui.subscribe((st) => { if (st.tab === "work" && st.view) lastWorkView = st.view; });
  // To a tab (and 仕事's view): what was over the page goes (an open session
  // is not: the tabs are not on screen while one is), the tab's own page is
  // shown, and the URL is replaced -- no history entry (see above).
  function showTab(tab, view) {
    const prev = ui.get().tab;
    if (tab !== "work" && tab !== "settings" && !window.aizaExt.tab(tab)) { tab = "work"; view = "tree"; }
    if (tab === "work") view = WORK_PATHS[view] ? view : lastWorkView;
    else view = null;
    if (prev !== tab && prev !== "work" && prev !== "settings") window.aizaExt.tabHide(prev);
    if (tab === "settings") { if (ui.pages.todoOn()) ui.pages.hideTodo(); ui.pages.settings(); updateTabBar(); return; }
    ui.set({ tab, view });
    if (pageNow() === "auth") showPage("list");
    if (tab === "work" && view !== "tree") ui.pages.showTodo(view);
    else if (ui.pages.todoOn()) ui.pages.hideTodo();
    if (tab !== "work") window.aizaExt.tabShow(tab);
    setHash(tab === "work" && view === "tree" ? listHash() : "");
    updateTabBar();
  }
  // After a session over a tab is closed: the tab again, as it was.
  function returnToTab() {
    const { tab, view } = ui.get();
    if (tab === "settings") { ui.pages.settings(); return; }
    showPage("list");
    if (tab === "work" && view !== "tree") ui.pages.showTodo(view);
    else if (tab !== "work") window.aizaExt.tabShow(tab);
    if (tab === "work" && view === "tree") setHash(listHash());
    updateTabBar();
  }
  tabsEl.addEventListener("click", (e) => {
    const a = e.target.closest("[data-tab]");
    if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    showTab(a.dataset.tab);
  });
  workViewsEl.addEventListener("click", (e) => {
    const a = e.target.closest("[data-view]");
    if (!a || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    showTab("work", a.dataset.view);
  });
  // An extension's tab button (aizaExt tabs), added once the extensions are loaded.
  function addExtTabs() {
    const slot = document.getElementById("ext-slot-tabs");
    slot.textContent = "";
    for (const x of window.aizaExt.tabs()) {
      const a = document.createElement("a");
      a.className = "tab";
      a.dataset.tab = x.id;
      a.href = window.aizaBase + x.path;
      a.setAttribute("role", "tab");
      a.textContent = x.label;
      const n = document.createElement("span");
      n.className = "n";
      n.hidden = true;
      n.id = `tab-badge-${x.id}`;
      a.appendChild(n);
      slot.appendChild(a);
    }
    updateTabBar();
  }
  // The tabs for the other scripts, through the base (the deployment notes),
  // and the pages a tab shows, which their own files give (ui.pages: todo.js
  // the to-do views, form.js 設定).
  ui.tabs = { show: showTab, back: returnToTab, addExt: addExtTabs, bar: updateTabBar, start: START_TAB, path: () => appPath() };
  ui.pages = {};
  window.__aizaTab = () => `${ui.get().tab}${ui.get().view ? "/" + ui.get().view : ""}`;   // tests/test_page_flow.py
  window.__aizaPage = () => {
    const x = ui.get().todo;
    return pageNow() + (x ? ` todo:${x.view}` + (x.view === "tree" ? `/${x.chain ? "chain" : x.mode}` : "") : "")
      + (ui.get().overlay ? ` overlay:${ui.get().overlay}` : "");
  };   // for tests/test_page_flow.py,
  window.__aizaCheckPage = (w) => checkPage(w);   // which checks after every step itself
  window.__aizaSession = () => chatNow.id;   // and which session is open
  window.__aizaMachine = () => currentMachine;     // on which machine
  const pageErrorsSent = new Set();
  window.__aizaPageErrors = [];
  function checkPage(where) {
    const bad = [];
    const els = { list: viewList, chat: viewChat, auth: viewAuth };
    // With the to-do list open, body.todo-page hides the page under it; on
    // an extension's tab its page does (the deployment notes).
    const extTab = !["work", "settings"].includes(ui.get().tab) && pageNow() === "list";
    const under = ui.get().todo || extTab ? null : getComputedStyle;
    const shown = under ? Object.keys(els).filter((k) => under(els[k]).display !== "none") : [pageNow()];
    if (shown.length !== 1 || shown[0] !== pageNow()) bad.push(`shown ${shown.join("+") || "none"} for ${pageNow()}`);
    const headerShown = under ? under(topHeaderEl).display !== "none" : pageNow() !== "chat";
    if (headerShown !== (pageNow() !== "chat")) bad.push(`header ${headerShown ? "shown" : "hidden"} on ${pageNow()}`);
    if (machineSelectEl.options.length && (machineSelectEl.value === "auth") !== (pageNow() === "auth")) {
      bad.push(`machine menu "${machineSelectEl.value === "auth" ? "auth" : "machine"}" on ${pageNow()}`);
    }
    if (pageNow() === "chat" && !chatNow.id) bad.push("chat with no session");
    // The to-do list over the page (ui.todo): its box and the body's class.
    const todoEl = document.getElementById("todo-modal");
    if (todoEl && todoEl.hidden === !!ui.get().todo) bad.push(`to-do list ${todoEl.hidden ? "hidden" : "shown"} with ui.todo ${ui.get().todo ? "set" : "null"}`);
    if (document.body.classList.contains("todo-page") !== !!ui.get().todo) bad.push("body.todo-page disagrees with ui.todo");
    // What is over the page (ui.overlay): the blackboard, an extension's view.
    const ov = ui.get().overlay;
    const boardEl = document.getElementById("board-modal");
    if (boardEl && boardEl.hidden === (ov === "board")) bad.push(`blackboard ${boardEl.hidden ? "hidden" : "shown"} with overlay ${ov}`);
    const extShown = !!document.querySelector(".ext-overlay:not([hidden])");
    if (extShown !== (typeof ov === "string" && ov.startsWith("ext:"))) bad.push(`extension view ${extShown ? "shown" : "hidden"} with overlay ${ov}`);
    if (pageNow() !== "chat" && chatNow.id) bad.push(`${pageNow()} with a session open`);
    for (const b of bad) {
      const msg = `page check (${where}): ${b}`;
      console.error(msg);
      window.__aizaPageErrors.push(msg);
      if (!pageErrorsSent.has(b) && loginReady) {
        pageErrorsSent.add(b);
        api("/page-check", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ where: String(where).slice(0, 80), what: b.slice(0, 160) }) }).catch(() => {});
      }
    }
    return bad;
  }

  // Presets that take a working directory and an optional conversation to
  // resume -- both run Claude Code (see CWD_PRESETS in aiza-backend). Only
  // "claude-tui" is creatable from the dropdown now; "claude" stays listed
  // so sessions made before it was removed still behave correctly. Never
  // applies to the ssh:<machine> presets (rebuildPresetOptions()) -- those
  // machines share no filesystem with this host, so there is no ~/sandhome
  // for a working directory to mean anything in. A drives-capable machine's
  // own Claude preset (claude-tui-<machine>) gets a *different* cwd picker
  // instead (#ssh-cwd-opts/#ssh-resume, sshCwdMachines below) -- never
  // added to this list, since it's rooted at a drive letter, not
  // ~/sandhome, and (unlike the two members below) has no fixed default
  // directory to resume "the current one" against before a drive/folder is
  // actually chosen (the deployment notes).
  // (CWD_PRESETS: picker "claude" in FORM_PRESETS below.)
  // Working-directory-only pickers (2026-09-27,
  // the deployment notes, user request: "続きから"/screen-log-persist restoring the plain
  // shells needs somewhere stable to key on, same as claude-tui already
  // has). No resume row for any of these (aiza-backend's SHELL_CWD_PRESETS
  // has no notion of resuming a specific past conversation) -- see
  // #shell-cwd-opts, shown instead of #claude-opts/#ssh-cwd-opts.
  // "shell" browses the exact same ~/sandhome tree "claude"/"claude-tui" do
  // (GET /workdirs?scope=sandhome, the default, unchanged); "host-shell"
  // this user's real host filesystem (scope=host); "root-shell" the real
  // root filesystem via the root tmux pane (scope=root, can pop the same
  // passkey prompt opening the session itself already can). "codex-tui"
  // joined this list 2026-09-28 (user request), same scope=sandhome as
  // "shell" -- it just has no resume of its own (aiza-backend's own
  // SHELL_CWD_PRESETS comment), unlike claude-tui/CWD_PRESETS above.
  // claude-host/-root and codex-host/-root (KIND_PLACE): their place's shell,
  // so the same picker and scope as that shell.
  // One row per preset the new-session form can start (2026-11-23: these
  // were five separate lists, each checked in its own place):
  //   picker  "claude" #claude-opts in ~/sandhome (CWD_PRESETS above)
  //           "mail"   #claude-opts in the Email box
  //           "shell"  #shell-cwd-opts, in scope (SHELL_CWD_PRESETS above)
  //           "ssh"    #ssh-cwd-opts (a drives-capable machine's Claude)
  //   resume  offers a conversation to resume
  //   skip    the permission checkbox: "claude" | "codex" (#skip-row).
  //           Not root's: Claude refuses to skip permissions as root, and
  //           root's Codex does not skip either (2026-11-24, the user); the
  //           backend starts them without the flag whatever is asked, and
  //           their prompts come as cards (the deployment notes).
  // claude-host/-root and codex-host/-root (KIND_PLACE) are their place's
  // shell, so the same picker and scope as that shell.
  const FORM_PRESETS = {
    "claude-tui": { picker: "claude", resume: true, skip: "claude" },
    claude: { picker: "claude", resume: true },
    "mail-tui": { picker: "mail", resume: true },
    "mail-shell": { picker: "mail" },
    "codex-mail": { picker: "mail" },
    "codex-tui": { picker: "shell", scope: "sandhome", skip: "codex" },
    shell: { picker: "shell", scope: "sandhome" },
    "host-shell": { picker: "shell", scope: "host" },
    "root-shell": { picker: "shell", scope: "root" },
    "claude-host": { picker: "shell", scope: "host", skip: "claude" },
    "claude-root": { picker: "shell", scope: "root" },
    "codex-host": { picker: "shell", scope: "host", skip: "codex" },
    "codex-root": { picker: "shell", scope: "root" },
  };
  function presetForm(p) {
    const base = { picker: null, scope: null, resume: false, skip: null };
    if (FORM_PRESETS[p]) return { ...base, ...FORM_PRESETS[p] };
    // A machine's Claude (claude-tui-<machine>): the drive/folder picker
    // where the machine has drives. Its permission flag is sent without
    // the checkbox row (as before).
    const m = /^claude-tui-(.+)$/.exec(String(p || ""));
    if (m && sshCwdMachines.includes(m[1])) return { ...base, picker: "ssh", resume: true };
    return base;
  }

  // The Email presets: its own folder tree (#claude-opts with scope "mail").
  const MAIL_PRESETS_UI = ["mail-tui", "mail-shell", "codex-mail"];
  // What a session is, decided once from its meta (2026-11-23, the user:
  // 分岐が早めに合流して組み合わせ爆発が起きないのが良い). The checks were
  // preset-name compares spread over the file, and "root-shell" alone missed
  // the root login panes. Ask this, not the preset name:
  //   place  "dev" | "mail" | "host" | "root" | "ssh" (where it runs)
  //   root   runs as root (any preset there, the login panes too)
  //   ai     "claude" | "codex" | null: the program, its own pane or typed
  //          into a shell (meta.launch)
  //   tui    Claude/Codex in a pane of its own (claude-tui[-<machine>], codex-tui)
  //   localShell  this host's shell, devbox/host/root (the program typed in)
  //   headless, login, machine
  // Sessions only; the new-session form still works on its own choices.
  function sessionKind(meta) {
    meta = meta || {};
    const p = String(meta.preset || ""), loc = meta.tmux_location || "container";
    const login = /^(claude|codex)-login/.test(p);
    const place = MAIL_PRESETS_UI.includes(p) ? "mail" : loc === "root" ? "root" : loc === "host" ? "host"
      : loc.startsWith("ssh:") ? "ssh" : "dev";
    const ai = meta.launch === "codex" || (p.startsWith("codex-") && !login) ? "codex"
      : meta.launch === "claude" || p === "claude" || p === "mail-tui" || p.startsWith("claude-tui") ? "claude" : null;
    return {
      preset: p, place, root: place === "root", ai, login,
      tui: /^(claude|codex)-tui(-|$)/.test(p),
      localShell: ["shell", "host-shell", "root-shell"].includes(p),
      headless: HEADLESS_PRESETS.includes(p),
      launch: meta.launch || null,
      machine: sessionMachine(meta),
    };
  }

  // Preact + htm for the page's components (the to-do page, tree.js).
  const html = window.htm && window.preact ? window.htm.bind(window.preact.h) : null;
  const PH = window.preactHooks || {};
  // Text into HTML (for the pages built from strings): one of the base the
  // other scripts use, with html/PH above (the deployment notes).
  function escapeHtml(s) {
    return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // From app.js (the deployment notes): the history and the login check, whose listeners
  // must come before the other scripts' own, and the page's elements those scripts use while loading.

  // Every internal navigation (openSession/closeSession/openAuthView) writes
  // its state to location.hash so a reload can return to it -- but a plain
  // `location.hash = x` assignment pushes a *new* browser history entry each
  // time, which iOS/Android's own edge-swipe-back gesture then treats as
  // real navigation history to pop, entirely independently of aiza's own
  // JS-driven swipe-back handler (see below).
  // The two fighting over the same swipe was reported 2026-08-16 as "after
  // swiping back, the page I just left reappears" -- the OS gesture was
  // popping a stale hash entry back into view a moment after aiza's own
  // handler had already moved on. history.replaceState never adds an entry,
  // so there is nothing left for a native back gesture to find. See
  // setHash()'s callers for where `location.hash = ...` used to be.
  // Browser Back from a session returns to the list (2026-11-04, at the
  // user's request, with patrol): opening a session from a list view adds
  // one history entry; moving to another session (patrol, links) does not
  // add more; Back pops it and closes the session, and closing it any other
  // way (←, swipe) pops it too, so no stale entry is left for the OS
  // back gesture to find (the 2026-08-16 problem below).
  // The app's own path for any URL that names a session or the list: never
  // /todo (2026-11-08, the user: leaving やること for a session made
  // /todo#<id>, which does not come back to it).
  // (2026-11-25: the tab's own address, the deployment notes.)
  function appPath() { return tabPath(ui.get().tab, ui.get().view); }
  let sessionHistoryPushed = false;
  // Back from a session takes one path (2026-11-24): the popstate below
  // closes the session and shows where it returns to (the list, 設定); the
  // hashchange of that same Back (the session's #<id> to the list's hash)
  // does not do it again. Before, applyHash did it as well, so either one
  // broken went unnoticed (tests/page_mutation.py). backHash: the hash of the
  // entry Back returns to; poppedTo: the hash a Back just landed on, whose
  // hashchange is already handled.
  let backHash = null;
  let poppedTo = null;
  // A layer's own history entry (始める, the deployment notes) that the session
  // it starts takes over: 開始 turns the layer into the chat, so Back from
  // the chat returns to the tab, not to a layer that is gone.
  let spareEntry = false;
  // ---- The page's own dialogs (the deployment notes, 2026-11-27) ------------
  // In place of the browser's alert / confirm / prompt (the user: 置き換えの
  // 方針良いです): ui.ask (fields to fill), ui.confirm (yes or no, red for
  // what deletes or stops) and ui.toast (a few seconds at the bottom; an
  // error's toast opens its detail when tapped). Each is a promise, and a
  // popup is its own element (.aiza-pop), so one can open over another.
  // Nothing written is dropped without a word: cancelling a popup whose
  // text was changed asks first. The desk's popup (app.js) wears the same
  // .aiza-pop look.
  let popDepth = 0;
  function popOpen(kind, title) {
    const el = document.createElement("div");
    el.className = `aiza-pop aiza-pop-${kind}`;
    el.style.zIndex = String(80 + popDepth++);
    el.innerHTML = `<div class="box" role="dialog" aria-modal="true"><div class="pop-head"><span></span>`
      + `<button type="button" class="close" aria-label="close">✕</button></div><div class="pop-body"></div>`
      + `<p class="pop-err" hidden></p><div class="pop-actions"></div></div>`;
    el.querySelector(".pop-head span").textContent = title || "";
    document.body.appendChild(el);
    return el;
  }
  function popClose(el) { if (el.isConnected) { el.remove(); popDepth = Math.max(0, popDepth - 1); } }
  function popButton(text, cls) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = cls;
    b.textContent = text;
    return b;
  }

  // ui.ask({title, text, fields: [{name, label, value, type, options, custom,
  // placeholder}], ok, danger}) -> {name: value} or null (cancelled).
  // type: "text" (default), "textarea", "select" (options [{value, label}]),
  // "choice" (options as buttons, and custom: {type: "number"|"datetime"|"text",
  // label} for a value of one's own; a datetime comes back as epoch ms).
  // ui.ask("title", "value") is one text field: its string, or null.
  ui.ask = (opts, value) => {
    if (typeof opts === "string") {
      return ui.ask({ title: opts, fields: [{ name: "v", value: value == null ? "" : String(value) }] })
        .then((r) => (r ? r.v : null));
    }
    return new Promise((resolve) => {
      const el = popOpen("ask", opts.title);
      const body = el.querySelector(".pop-body"), err = el.querySelector(".pop-err");
      if (opts.text) { const p = document.createElement("p"); p.className = "pop-text"; p.textContent = opts.text; body.appendChild(p); }
      const getters = {}, initial = {};
      for (const f of opts.fields || []) {
        const wrap = document.createElement("label");
        wrap.className = "pop-field";
        if (f.label) { const l = document.createElement("span"); l.textContent = f.label; wrap.appendChild(l); }
        let input;
        if (f.type === "select") {
          input = document.createElement("select");
          for (const o of f.options || []) { const x = document.createElement("option"); x.value = String(o.value); x.textContent = o.label; input.appendChild(x); }
          if (f.value != null) input.value = String(f.value);
          getters[f.name] = () => input.value;
        } else if (f.type === "choice") {
          const row = document.createElement("div");
          row.className = "pop-choices";
          let chosen = f.value != null ? String(f.value) : null;
          const btns = [];
          let custom = null;
          const mark = () => { for (const b of btns) b.classList.toggle("on", b.dataset.value === chosen); };
          for (const o of f.options || []) {
            const b = popButton(o.label, "pop-choice");
            b.dataset.value = String(o.value);
            b.addEventListener("click", (e) => { e.preventDefault(); chosen = b.dataset.value; if (custom) custom.value = ""; mark(); });
            btns.push(b);
            row.appendChild(b);
          }
          wrap.appendChild(row);
          if (f.custom) {
            const cl = document.createElement("span");
            cl.className = "pop-custom-label";
            cl.textContent = f.custom.label || "";
            wrap.appendChild(cl);
            custom = document.createElement("input");
            custom.className = "pop-custom";
            custom.type = f.custom.type === "datetime" ? "datetime-local" : "text";
            if (f.custom.type === "number") custom.inputMode = "numeric";
            custom.addEventListener("input", () => { if (custom.value) { chosen = null; mark(); } });
            wrap.appendChild(custom);
          }
          mark();
          getters[f.name] = () => {
            if (custom && custom.value !== "") {
              if (f.custom.type === "datetime") { const ms = new Date(custom.value).getTime(); return Number.isFinite(ms) ? ms : NaN; }
              return custom.value;
            }
            return chosen;
          };
          input = null;
        } else {
          input = document.createElement(f.type === "textarea" ? "textarea" : "input");
          if (f.type === "textarea") input.rows = 4; else input.type = "text";
          input.value = f.value == null ? "" : String(f.value);
          if (f.placeholder) input.placeholder = f.placeholder;
          getters[f.name] = () => input.value;
        }
        if (input) { input.name = f.name; wrap.appendChild(input); }
        initial[f.name] = getters[f.name]();
        body.appendChild(wrap);
      }
      const done = (v) => { popClose(el); document.removeEventListener("keydown", onKey, true); resolve(v); };
      const values = () => Object.fromEntries(Object.entries(getters).map(([k, g]) => [k, g()]));
      const changed = () => Object.entries(getters).some(([k, g]) => typeof g() === "string" && g().trim() !== "" && g() !== initial[k]);
      function cancel() {
        if (!changed()) return done(null);
        // what was written is not dropped without a word
        const acts = el.querySelector(".pop-actions");
        acts.replaceChildren();
        err.textContent = t("page.discard_what_you_wrote");
        err.hidden = false;
        const back = popButton(t("page.keep_writing"), "pop-ok");
        const drop = popButton(t("page.discard"), "pop-danger");
        back.addEventListener("click", () => { err.hidden = true; buttons(); });
        drop.addEventListener("click", () => done(null));
        acts.append(drop, back);
      }
      function buttons() {
        const acts = el.querySelector(".pop-actions");
        acts.replaceChildren();
        const no = popButton(t("common.cancel"), "pop-cancel");
        const ok = popButton(opts.ok || t("common.ok"), opts.danger ? "pop-danger" : "pop-ok");
        no.addEventListener("click", cancel);
        ok.addEventListener("click", () => done(values()));
        acts.append(no, ok);
      }
      function onKey(e) {
        if (!el.isConnected) return;
        if (e.key === "Escape") { e.preventDefault(); cancel(); }
        else if (e.key === "Enter" && e.target && e.target.tagName === "INPUT" && el.contains(e.target)) { e.preventDefault(); done(values()); }
      }
      document.addEventListener("keydown", onKey, true);
      el.querySelector(".close").addEventListener("click", cancel);
      el.addEventListener("click", (e) => { if (e.target === el) cancel(); });
      buttons();
      const first = el.querySelector(".pop-field input, .pop-field textarea, .pop-field select");
      if (first) setTimeout(() => first.focus(), 0);
    });
  };

  // ui.confirm(text, {title, ok, danger}) -> true / false. danger: a red
  // button, for what deletes, stops or cannot be undone.
  ui.confirm = (text, o = {}) => new Promise((resolve) => {
    const el = popOpen("confirm", o.title || "");
    const p = document.createElement("p");
    p.className = "pop-text";
    p.textContent = text;
    el.querySelector(".pop-body").appendChild(p);
    const done = (v) => { popClose(el); document.removeEventListener("keydown", onKey, true); resolve(v); };
    function onKey(e) {
      if (!el.isConnected) return;
      if (e.key === "Escape") { e.preventDefault(); done(false); }
    }
    document.addEventListener("keydown", onKey, true);
    const no = popButton(o.cancel || t("common.cancel"), "pop-cancel");
    const ok = popButton(o.ok || t("common.ok"), o.danger ? "pop-danger" : "pop-ok");
    no.addEventListener("click", () => done(false));
    ok.addEventListener("click", () => done(true));
    el.querySelector(".pop-actions").append(no, ok);
    el.querySelector(".close").addEventListener("click", () => done(false));
    el.addEventListener("click", (e) => { if (e.target === el) done(false); });
    setTimeout(() => ok.focus(), 0);
  });

  // ui.toast(text, {error, detail, ms}): a few seconds at the bottom (an
  // error longer). An error's toast, tapped, opens it whole with its detail;
  // it stays while open. Several stack.
  let toastBox = null;
  ui.toast = (text, o = {}) => {
    if (!toastBox || !toastBox.isConnected) {
      toastBox = document.createElement("div");
      toastBox.className = "aiza-toasts";
      document.body.appendChild(toastBox);
    }
    const el = document.createElement("div");
    el.className = "aiza-toast" + (o.error ? " error" : "");
    el.setAttribute("role", o.error ? "alert" : "status");
    const span = document.createElement("span");
    span.textContent = String(text);
    el.appendChild(span);
    const ms = o.ms || (o.error ? 8000 : 4000);
    let timer = setTimeout(() => el.remove(), ms);
    el.addEventListener("click", () => {
      if (el.classList.toggle("open")) {
        clearTimeout(timer);
        if (o.detail && !el.querySelector(".detail")) {
          const d = document.createElement("pre");
          d.className = "detail";
          d.textContent = String(o.detail);
          el.appendChild(d);
        }
      } else timer = setTimeout(() => el.remove(), 2000);
    });
    toastBox.appendChild(el);
    return el;
  };

  ui.layer = {
    push: () => history.pushState({ aiza: "layer" }, "", location.pathname + location.search + location.hash),
    handToSession: () => { spareEntry = true; },
  };
  function pushSessionHistory() {
    if (sessionHistoryPushed) return;
    // The entry Back returns to must be the list's own URL. Opened from a
    // URL that already names the session (#<id>: a reload, a notification,
    // a page in the Email box) it would otherwise be that #<id>, and Back's
    // hashchange opened the same session again (2026-11-04, the user:
    // "戻るで一覧に戻れないことがあります。URLに#IDが付いてるから").
    // Opened from 設定 (a login): Back returns there, #auth (2026-11-23: it
    // was the list's URL, and the hashchange of that Back took 設定 away
    // again -- the root of 「設定のまま名前だけ別のホスト」, found by test_page_flow).
    // (2026-11-25: the tab's own address, the deployment notes: /settings for
    // a login opened from 設定, the machine's list on 仕事's tree.)
    const back = ui.get().tab === "work" && ui.get().view === "tree" ? listHash() : "";
    const listUrl = back ? `${appPath()}${location.search}#${back}` : `${appPath()}${location.search}`;
    backHash = back ? `#${back}` : "";
    // Opened from the to-do list (/todo): that entry stays, so Back returns
    // to the list it was opened from (2026-11-09, the user: "タスクリストから
    // セッションに移動してその後またタスクリストに戻るって事ができない").
    if (spareEntry) {   // the layer's entry becomes the session's
      spareEntry = false;
      history.replaceState({ aiza: "session" }, "", listUrl);
      sessionHistoryPushed = true;
      return;
    }
    history.replaceState(null, "", listUrl);
    history.pushState({ aiza: "session" }, "", listUrl);
    sessionHistoryPushed = true;
  }
  function popSessionHistory() {
    if (!sessionHistoryPushed) return false;
    sessionHistoryPushed = false;
    history.back();
    return true;
  }
  window.addEventListener("popstate", () => {
    if (window.aizaExt.back()) return; // an extension's own entry (aizaExt back)
    if (!sessionHistoryPushed) return;
    sessionHistoryPushed = false;
    if (!chatNow.id) return;
    // A Back to the entry pushed for it; any other hash (a notification's
    // #<id>, a link) is still applyHash's to open after the close.
    const back = location.hash === backHash;
    chatNow.close();
    if (back) poppedTo = location.hash;
  });

  // closeSession went back by history.back() (← or a swipe): that Back's
  // hashchange is done by the close already.
  function backPopped() { poppedTo = backHash; }
  // In the hashchange handler (app.js): whether this one was a Back the
  // popstate above (or backPopped) has done already. Clears the mark.
  function takePopped() {
    const handled = poppedTo !== null && location.hash === poppedTo;
    poppedTo = null;
    return handled;
  }

  function setHash(value) {
    poppedTo = null;
    const url = value ? `${appPath()}${location.search}#${value}` : `${appPath()}${location.search}`;
    history.replaceState(null, "", url);
  }

  const whoEl = document.getElementById("who");
  const messagesEl = document.getElementById("messages");
  const chatLabelEl = document.getElementById("chat-label");
  const chatDotEl = document.getElementById("chat-dot");
  const textEl = document.getElementById("text");
  const sendBtn = document.getElementById("send-btn");
  const attachFileInputEl = document.getElementById("attach-file-input");
  const shareBtn = document.getElementById("share-btn");
  const presetEl = document.getElementById("preset");

  // ---- Google login gone (2026-11-19, the user: しばらくしてから開くと、
  // チャットが更新されなくなり、リロードするとGoogleログインが切れてる
  // ことがあります。開いたとき切れてたら再ログインを求めてほしい) ----------
  // The gateway answers 401 "not logged in" once the session cookie is past
  // its absolute lifetime; the chat's stream then only retried quietly. Any
  // such answer, and a check whenever the page is shown again, put up a box
  // asking to log in again. The button keeps the unsent text of the open
  // session in this browser and brings it back after the login's reload.
  const LOGIN_DRAFT_KEY = "aiza-login-draft";
  let loginLostEl = null;
  let loginReady = false;   // set once init() has the user; before that init() goes to the login itself
  function setLoginReady() { loginReady = true; }   // init (app.js)
  const loginUrl = () => `${window.aizaBase}/agents/login?next=${encodeURIComponent(location.pathname + location.search + location.hash)}`;
  function loginLost() {
    if (loginLostEl || !loginReady) return;
    stopSessionEvents();
    loginLostEl = document.createElement("div");
    loginLostEl.id = "login-lost";
    loginLostEl.innerHTML = `<div class="box"><h3>${escapeHtml(t("page.google_login_expired"))}</h3>`
      + `<div class="note">${escapeHtml(t("page.chat_stopped_updating_too_log"))}</div>`
      + `<button type="button">${escapeHtml(t("common.log_in_again"))}</button></div>`;
    loginLostEl.querySelector("button").addEventListener("click", () => {
      try {
        if (chatNow.id && textEl.value.trim()) {
          localStorage.setItem(LOGIN_DRAFT_KEY, JSON.stringify({ sid: chatNow.id, text: textEl.value, at: Date.now() }));
        }
      } catch (e) { /* storage off: the text cannot be kept */ }
      location.href = loginUrl();
    });
    document.body.appendChild(loginLostEl);
  }
  function restoreLoginDraft(sid) {
    try {
      const d = JSON.parse(localStorage.getItem(LOGIN_DRAFT_KEY) || "null");
      if (!d || d.sid !== sid) return;
      localStorage.removeItem(LOGIN_DRAFT_KEY);
      if (Date.now() - (d.at || 0) > 3600e3 || textEl.value.trim()) return;
      textEl.value = d.text;
      autoResizeTextarea();
    } catch (e) { /* nothing kept */ }
  }
  async function checkLogin() {
    if (loginLostEl || !loginReady) return;
    try {
      const r = await fetch(window.aizaBase + "/agents/api/me", { cache: "no-store" });
      if (r.status === 401) loginLost();
    } catch (e) { /* offline: the next showing checks again */ }
  }
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") checkLogin(); });
  window.addEventListener("pageshow", (e) => { if (e.persisted) checkLogin(); });
  window.addEventListener("online", checkLogin);
