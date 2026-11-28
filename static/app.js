// The page (aiza): start-up (init), the hash (applyHash), push, the extensions.
//
// One of the page's plain scripts (no build step), loaded last by
// index.html. They share one global scope, so the other files (tree.js ...)
// see this file's functions and top-level let/const by name, and it sees
// theirs (the deployment notes). Until 2026-11-24 all of it was one
// closure; the old indentation is kept.
"use strict";
  function urlBase64ToUint8Array(base64) {
    const padding = "=".repeat((4 - (base64.length % 4)) % 4);
    const base64safe = (base64 + padding).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64safe);
    return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
  }

  async function setupPush() {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    // The whole site (the tabs' /work, /inbox, /settings; the gateway sends
    // Service-Worker-Allowed: /), the deployment notes.
    const reg = await navigator.serviceWorker.register(window.aizaBase + "/agents/sw.js", { scope: window.aizaBase + "/" });
    // The one registered for /agents/ before: gone, with its push
    // subscription (the server drops a subscription the push service answers
    // 410 for), so a notification does not come twice.
    try {
      for (const r of await navigator.serviceWorker.getRegistrations()) {
        if (new URL(r.scope).pathname === window.aizaBase + "/agents/") await r.unregister();
      }
    } catch (e) { /* not this browser's: nothing to remove */ }
    const perm = await Notification.requestPermission();
    if (perm !== "granted") return;
    const { key } = await api("/vapid-public-key").catch(() => ({ key: null }));
    if (!key) return;
    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: urlBase64ToUint8Array(key),
      });
    }
    await api("/push/subscribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sub.toJSON()),
    });
  }

  // 設定's 通知 card (the deployment notes): whether this device gets the
  // notifications -- its push subscription, on or off (2026-11-26, the user:
  // 通知が何も選べないのはどういうこと) -- and what the browser allows.
  // Off unsubscribes here; the server drops a subscription the push service
  // then answers 410 for.
  const notifyOnEl = document.getElementById("notify-on");
  async function showNotifyState() {
    const st = document.getElementById("notify-status");
    if (!("Notification" in window) || !("serviceWorker" in navigator) || !("PushManager" in window)) {
      notifyOnEl.checked = false; notifyOnEl.disabled = true;
      st.textContent = t("app.notify_unavailable");
      return;
    }
    const reg = await navigator.serviceWorker.getRegistration(window.aizaBase + "/work").catch(() => null);
    const sub = reg && await reg.pushManager.getSubscription().catch(() => null);
    notifyOnEl.disabled = Notification.permission === "denied";
    notifyOnEl.checked = Notification.permission === "granted" && !!sub;
    st.textContent = Notification.permission === "denied" ? t("app.notify_blocked")
      : notifyOnEl.checked ? t("app.notify_on") : t("app.notify_off");
  }
  notifyOnEl.addEventListener("change", async () => {
    try {
      if (notifyOnEl.checked) await setupPush();
      else {
        const reg = await navigator.serviceWorker.getRegistration(window.aizaBase + "/work");
        const sub = reg && await reg.pushManager.getSubscription();
        if (sub) await sub.unsubscribe();
        try { localStorage.setItem("aiza-notify-off", "1"); } catch (e) {}
      }
      if (notifyOnEl.checked) { try { localStorage.removeItem("aiza-notify-off"); } catch (e) {} }
    } catch (e) { console.warn("notify:", e); }
    showNotifyState();
  });
  ui.subscribe((st, prev) => { if (st.page === "auth" && prev.page !== "auth") showNotifyState(); });

  // Keeps the page pinned to the *actual* visible area (CSS's own 100dvh
  // already handles the browser's own chrome collapsing/expanding, but not
  // the on-screen keyboard reliably across iOS/Android) by tracking
  // window.visualViewport, which is what actually shrinks when the keyboard
  // opens. Sets --app-height, which index.html's `body` rule reads via
  // `var(--app-height, 100dvh)` -- see that file for the full fallback
  // chain. Falls back to window.innerHeight (won't react to the keyboard,
  // but still better than a hardcoded 100vh) on browsers with no
  // VisualViewport support at all.
  function setupViewportHeight() {
    const vv = window.visualViewport;
    const update = () => {
      const h = vv ? vv.height : window.innerHeight;
      document.documentElement.style.setProperty("--app-height", `${h}px`);
    };
    (vv || window).addEventListener("resize", update);
    update();
  }
  setupViewportHeight();

  // ---- extensions (ext/README.md) ------------------------------------------
  //
  // /config's "ext" lists each extension's page files; they are loaded from
  // /agents/ext/<name>/<file> and register themselves with window.aizaExt
  // (static/ext.js), which this file asks at each extension point. What an
  // extension may use of this page is aizaExt.app. None at all is the
  // published core's normal case; one that fails to load is left out.
  window.aizaExt.app = {
    // An extension's view over the page is shown (name) or gone (null):
    // ui.overlay "ext:<name>" (the deployment notes).
    overlay: (name) => ui.set({ overlay: name ? `ext:${name}` : null }),
    api,
    t,
    escapeHtml,
    plainClick: (e) => plainClick(e),
    sessions: () => lastSessions,
    refreshSessions: () => refreshSessions(),
    // Opens one of this user's sessions by id (refreshing the list first);
    // false when there is no such session.
    async openSessionById(id) {
      const all = await refreshSessions().catch(() => lastSessions);
      const meta = (all || lastSessions).find((x) => x.id === id);
      if (meta) chatNow.open(meta);
      return !!meta;
    },
    findSession: (id) => lastSessions.find((x) => x.id === id) || null,
    openSession: (meta) => chatNow.open(meta),
    // To a tab (the deployment notes): "work", "settings" or an extension's own.
    showTab: (tab, view) => ui.tabs.show(tab, view),
    // Runs fn and, when the server asks for the passkey, asks for it and runs fn once more.
    withUnlockRetry: (fn) => withUnlockRetry(fn),
    // Redraws what extensions add to (the list, the to-do list).
    render() {
      renderSessionList();
      if (todoOn()) renderTodo();
    },
  };
  function loadExtFile(name, file, kind) {
    return new Promise((resolve) => {
      const url = `${window.aizaBase}/agents/ext/${encodeURIComponent(name)}/${encodeURIComponent(file)}`;
      const el = kind === "css" ? document.createElement("link") : document.createElement("script");
      if (kind === "css") { el.rel = "stylesheet"; el.href = url; } else { el.src = url; el.async = false; }
      el.onload = () => resolve(true);
      el.onerror = () => { console.error(`extension ${name}: could not load ${file}`); resolve(false); };
      document.head.appendChild(el);
    });
  }
  // Waits for the files (a few seconds at most), so the first paint
  // already has the extensions' folders and words.
  let extLoaded = null;
  async function loadExtensions() {
    let conf;
    try { conf = await api("/config"); } catch (e) { return; }
    const loads = [];
    for (const x of Array.isArray(conf && conf.ext) ? conf.ext : []) {
      for (const f of x.css || []) loads.push(loadExtFile(x.name, f, "css"));
      for (const f of x.js || []) loads.push(loadExtFile(x.name, f, "js"));
    }
    await Promise.race([Promise.all(loads), new Promise((r) => setTimeout(r, 4000))]);
  }
  window.aizaExt.onRegister(() => {
    readExtOpenKeys();
    if (lastVisibleSessions.length) renderSessionList();
  });
  // The page's insertion points (aizaExt slots): the header's links and a
  // row of the settings page.
  function fillExtSlots() {
    window.aizaExt.fillSlot("header-links", document.getElementById("ext-slot-header-links"), window.aizaExt.app);
    // 設定's card of the extensions' own (the deployment notes): shown once one puts something in it.
    const setSlot = document.getElementById("ext-slot-settings");
    new MutationObserver(() => { setSlot.hidden = !setSlot.children.length; }).observe(setSlot, { childList: true });
    window.aizaExt.fillSlot("settings", setSlot, window.aizaExt.app);
  }

  async function init() {
    const extReady = extLoaded = loadExtensions();
    const me = await api("/me").catch((e) => (e && e.loginLost ? "lost" : null));
    if (me === "lost") {
      // Logged out already when opened: straight to the login, back to this
      // very place (session hash included) afterwards.
      location.href = loginUrl();
      return;
    }
    if (!me) {
      location.href = window.aizaBase + "/agents/";
      return;
    }
    setLoginReady();
    whoEl.textContent = me.username;
    buildKeyToolbar();
    // Display language (the deployment notes): the picker on the settings page, and the
    // choice saved on the server (another device may have changed it).
    const langSelectEl = document.getElementById("lang-select");
    for (const [code, name] of Object.entries(window.aizaI18n.LANGS)) {
      const opt = document.createElement("option");
      opt.value = code;
      opt.textContent = name;
      langSelectEl.appendChild(opt);
    }
    langSelectEl.value = window.aizaI18n.lang();
    langSelectEl.addEventListener("change", () => window.aizaI18n.setLang(langSelectEl.value));
    window.aizaI18n.syncFromServer();

    // A session (or auth) deep link -- typically a push notification's
    // click, see sw.js -- gets in as fast as possible: applyHash()'s own
    // refreshSessions() call is all it needs. Everything below is state
    // only the *list* view's own controls need (capabilities for the
    // preset dropdown, workdirs for new sessions, tmux-sessions for
    // "attach" candidates) and none of it should hold up a notification tap
    // that already knows exactly which session it wants -- each of those
    // calls is a real network/SSH round trip, and ssh_reachable() alone can
    // cost several seconds per GPU machine that's asleep or off
    // (2026-08-23). This used to run last, so a
    // notification tap paid for all of them before showing anything.
    // The extensions first (one quick call): their folders decide where a
    // session is listed.
    await extReady;
    ui.tabs.addExt();   // their tabs (aizaExt tabs) before the page's own tab is shown
    await applyHash();

    await applyCapabilities();
    // applyHash() above may have picked a machine (a "machine=" hash, or an
    // opened session's own) before the <select> existed -- and, for a
    // session, before ssh_desktop was known, so a desktop variant's session
    // was attributed to the variant itself rather than its base machine,
    // and shown without its 🐚/🪟 badge. Redo both now.
    if (chatNow.meta) {
      setMachine(sessionMachine(chatNow.meta));
      chatLabelEl.textContent = typeIcon(chatNow.meta) + screenBadge(chatNow.meta) + chatNow.meta.label;
    }
    const wanted = currentMachine;
    syncMachineSelect();
    if (currentMachine !== "local") rebuildPresetOptions();
    if (wanted !== currentMachine && !chatNow.id) setHash(listHash());
    // Same for the settings page opened by its hash (a reload there):
    // openAuthView() ran before the "auth" option existed.
    if (pageNow() === "auth") machineSelectEl.value = "auth";
    updateMachineBtn();
    initUnlockUI();
    fillExtSlots();
    applyPresetOptions();
    await refreshWorkdirs(false);
    await refreshSessions();
    await refreshTmuxSessions();
    // Not awaited: it shells into the container, which is slower than
    // everything else here and shouldn't hold up the first paint.
    refreshAuthStatus();
    let notifyOff = false;
    try { notifyOff = localStorage.getItem("aiza-notify-off") === "1"; } catch (e) {}
    if (!notifyOff) setupPush().catch((e) => console.warn("push setup skipped:", e));   // off on this device: 設定's 通知
  }

  // openSession()/openAuthView() write their state to location.hash
  // precisely so a reload (browser's own, or aiza's #reload-btn/header-
  // swipe) can return here instead of always landing back on the session
  // list -- this reads it back, both right after init() and on every
  // later "hashchange" (below). The hashchange case is what a push
  // notification's click needs: sw.js's client.navigate() changes an
  // already-open client's hash without reloading the page (a same-
  // document, fragment-only navigation), so nothing short of a listener
  // here would ever notice and actually open the session (2026-08-16, at
  // the user's request -- before this, clicking the notification moved
  // the address bar but left whatever view was already on screen alone).
  // #issue=owner/repo%23n (the deployment notes): the link a GitHub issue
  // carries. Asks before starting anything -- the link sits in an issue
  // anyone can read, and what it starts is Claude in this viewer's own devbox.
  async function startIssueSession(ref) {
    let info;
    try {
      info = await api(`/issue?ref=${encodeURIComponent(ref)}`);
    } catch (e) {
      ui.toast(t("app.could_not_read_issue_err", { err: e.message }), { error: true });
      return;
    }
    if (info.sessions.length) {
      if (!(await ui.confirm(t("app.session_issue_already_running_open")))) return;
      const meta = (await refreshSessions()).find((s) => s.id === info.sessions[0]);
      if (meta) chatNow.open(meta);
      return;
    }
    const repo = info.ref.split("/")[1].split("#")[0];
    if (!info.cloned) {
      ui.toast(t("app.sandhome_repo_does_not_exist", { repo }), { error: true });
      return;
    }
    const lines = [
      `#${info.number} ${info.title}`,
      `Status: ${info.status || "-"} / Worker: ${info.worker || "-"} / ${t("common.assignees")}: ${info.assignees.join(", ") || "-"}`,
    ];
    if (info.state !== "OPEN") lines.push(t("app.issue_closed"));
    else if (info.status !== "Ready" && info.status !== "In progress") lines.push(t("app.status_not_ready"));
    lines.push(t("app.start_claude_in_issues_worktree", { repo, n: info.number }));
    // The start screen (the deployment notes 段3): Claude in the devbox, named
    // after the issue, linked to it -- nothing starts until 開始. The issue's
    // own session (its worktree) is Claude in the devbox only.
    ui.start.open({
      title: `#${info.number} ${info.title}`.slice(0, 80), kind: "claude", place: "dev",
      note: "🔗 " + lines.join("\n"),
      prepare(body) { if (body.preset === "claude-tui") body.issue = info.ref; },
    });
  }

  // The desk (the deployment notes): a popup with two ways in (2026-11-27, the
  // user: 報告とデプロイ依頼は分けて…ポップアップに2つの口…コミットは番号で
  // なくブランチ・プルリクを選ぶ) -- 📮 a report, 🚀 a deploy request naming
  // a branch or an open pull request of the session's repository, which the
  // backend resolves as this user (GET /desk/choices, POST /desk/report
  // {kind, pick}). From the other host the report comes here as
  // #desk&t=<text>&ref=<host/user/kind/session>[&pos][&c=<{repo, sha}>&l=<what>]
  // (that host resolved the commit) and is sent from this popup.
  // Nothing written is dropped without a word: closing keeps a draft (this
  // browser), a refused send keeps the popup open with why.
  const DESK_DRAFTS = "aiza-desk-drafts";
  function deskDrafts() {
    try { return JSON.parse(localStorage.getItem(DESK_DRAFTS) || "{}") || {}; } catch (e) { return {}; }
  }
  function deskDraftSet(key, v) {
    const d = deskDrafts();
    if (v && v.text && v.text.trim()) d[key] = v; else delete d[key];
    try { localStorage.setItem(DESK_DRAFTS, JSON.stringify(d)); } catch (e) { /* storage blocked: the popup keeps it while open */ }
  }
  let deskEl = null;
  function deskBuild() {
    if (deskEl) return deskEl;
    deskEl = document.createElement("div");
    deskEl.id = "desk-modal";
    deskEl.className = "aiza-pop";
    deskEl.hidden = true;
    deskEl.innerHTML = `<div class="box" role="dialog" aria-modal="true">
      <div class="desk-head"><span>📮 ${escapeHtml(t("app.desk_title"))}</span><button type="button" class="close" aria-label="close">✕</button></div>
      <div class="desk-tabs"><button type="button" data-kind="report">📮 ${escapeHtml(t("app.desk_report_tab"))}</button><button type="button" data-kind="deploy">🚀 ${escapeHtml(t("app.desk_deploy_tab"))}</button></div>
      <p class="desk-hint"></p>
      <textarea class="desk-text" rows="5"></textarea>
      <div class="desk-deploy"><label class="desk-pick-label"></label><select class="desk-pick"></select><p class="desk-pick-note"></p></div>
      <p class="desk-err" hidden></p>
      <div class="desk-actions"><span class="desk-keep">${escapeHtml(t("app.desk_closing_keeps_draft"))}</span><button type="button" class="desk-send">${escapeHtml(t("app.desk_send"))}</button></div>
    </div>`;
    document.body.appendChild(deskEl);
    return deskEl;
  }

  function deskReport({ session, ref, pos, text, commit, label } = {}) {
    const el = deskBuild();
    const $ = (q) => el.querySelector(q);
    let c = null;
    try { c = commit ? JSON.parse(commit) : null; } catch (e) { c = null; }
    const key = session ? `s:${session}` : `r:${ref || ""}`;
    const draft = deskDrafts()[key];
    let kind = draft && draft.kind ? draft.kind : c ? "deploy" : "report";
    let choices = null;   // GET /desk/choices, once, for a session
    const textEl2 = $(".desk-text"), pickEl = $(".desk-pick"), errEl = $(".desk-err");
    textEl2.value = draft ? draft.text : (text || "");
    errEl.hidden = true;
    const keep = () => deskDraftSet(key, { text: textEl2.value, kind });
    function close() { keep(); el.hidden = true; el.onclick = null; }
    function showKind() {
      for (const b of el.querySelectorAll(".desk-tabs button")) b.classList.toggle("on", b.dataset.kind === kind);
      $(".desk-hint").textContent = t(kind === "deploy" ? "app.desk_deploy_hint" : "app.desk_report_hint");
      textEl2.placeholder = t(kind === "deploy" ? "app.desk_deploy_placeholder" : "app.desk_report_placeholder");
      $(".desk-deploy").hidden = kind !== "deploy";
      if (kind === "deploy") fillPick();
    }
    function fillPick() {
      const note = $(".desk-pick-note"), lab = $(".desk-pick-label");
      pickEl.replaceChildren();
      if (c) {   // from the other host: that host resolved it
        lab.textContent = t("app.desk_commit_from_other_host");
        const o = document.createElement("option");
        o.value = "c";
        o.textContent = `${label ? label + " — " : ""}${c.repo || ""} ${String(c.sha || "").slice(0, 10)}`;
        pickEl.appendChild(o);
        pickEl.disabled = true;
        note.textContent = "";
        return;
      }
      pickEl.disabled = false;
      lab.textContent = t("app.desk_pick_what");
      if (!session) { note.textContent = t("app.desk_deploy_needs_session"); return; }
      if (!choices) {
        note.textContent = t("app.desk_reading_branches");
        api(`/desk/choices?session=${encodeURIComponent(session)}`).then((r) => { choices = r; if (kind === "deploy" && !el.hidden) fillPick(); })
          .catch((e) => { choices = { branches: [], pulls: [], note: e.message }; if (kind === "deploy" && !el.hidden) fillPick(); });
        return;
      }
      const ph = document.createElement("option");
      ph.value = ""; ph.textContent = t("app.desk_choose");
      pickEl.appendChild(ph);
      const group = (name, rows, mk) => {
        if (!rows.length) return;
        const g = document.createElement("optgroup");
        g.label = name;
        for (const r of rows) { const o = document.createElement("option"); [o.value, o.textContent] = mk(r); g.appendChild(o); }
        pickEl.appendChild(g);
      };
      group(t("app.desk_pulls"), choices.pulls || [], (p) => [`pull:${p.number}`, `#${p.number} ${p.title} (${p.branch})`]);
      group(t("app.desk_branches"), choices.branches || [], (b) => [`branch:${b.name}`,
        `${b.name}${b.current ? " ★" : ""} — ${b.subject} (${b.sha.slice(0, 7)})`]);
      note.textContent = [choices.note, choices.pulls_note].filter(Boolean).join(" ") || (choices.repo ? choices.repo : "");
    }
    async function send() {
      const v = textEl2.value.trim();
      errEl.hidden = true;
      if (!v) { errEl.textContent = t("app.desk_write_something"); errEl.hidden = false; return; }
      const body = { text: v, kind };
      let what = "";
      if (session) {
        body.session = session;
        if (kind === "deploy") {
          const p = pickEl.value;
          if (!p) { errEl.textContent = t("app.desk_choose_first"); errEl.hidden = false; return; }
          body.pick = p.startsWith("pull:") ? { pull: Number(p.slice(5)) } : { branch: p.slice(7) };
          what = pickEl.selectedOptions[0] ? pickEl.selectedOptions[0].textContent : "";
          body.label = p.startsWith("pull:") ? `#${p.slice(5)}` : p.slice(7);
        }
      } else if (ref) {
        body.ref = ref;
        if (pos) body.pos = pos;
        if (kind === "deploy") {
          if (!c) { errEl.textContent = t("app.desk_deploy_needs_session"); errEl.hidden = false; return; }
          body.commit = commit;
        }
      } else if (kind === "deploy") {
        errEl.textContent = t("app.desk_deploy_needs_session"); errEl.hidden = false; return;
      }
      const btn = $(".desk-send");
      btn.disabled = true;
      const r = await api("/desk/report", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).catch((e) => ({ error: e.message }));
      btn.disabled = false;
      if (r.error) { errEl.textContent = t("app.could_not_send_desk_err", { err: r.error }); errEl.hidden = false; return; }
      deskDraftSet(key, null);
      el.hidden = true; el.onclick = null;
      if (r.desk_url) { location.href = r.desk_url; return; }
      ui.toast(kind === "deploy" ? t("app.desk_deploy_sent", { what }) : t("app.sent_desk_follow_under_ai"));
    }
    for (const b of el.querySelectorAll(".desk-tabs button")) b.onclick = () => { kind = b.dataset.kind; errEl.hidden = true; keep(); showKind(); };
    $(".close").onclick = close;
    $(".desk-send").onclick = send;
    el.onclick = (e) => { if (e.target === el) close(); };
    el.hidden = false;
    showKind();
    textEl2.focus();
  }

  async function applyHash() {
    const hashId = location.hash.slice(1);
    if (hashId === "desk" || hashId.startsWith("desk&")) {
      setHash(""); // one-shot
      const q = new URLSearchParams(hashId.slice(5));
      deskReport({ ref: q.get("ref") || undefined, pos: q.get("pos") || undefined, text: q.get("t") || "",
                   commit: q.get("c") || undefined, label: q.get("l") || undefined });
      return;
    }
    if (hashId.startsWith("issue=")) {
      setHash(""); // one-shot: a reload must not offer to start it again
      await refreshSessions();
      await startIssueSession(decodeURIComponent(hashId.slice("issue=".length)));
      return;
    }
    if (hashId.startsWith("tree=")) {
      setHash(""); // one-shot, like issue=
      jumpToTree(decodeURIComponent(hashId.slice("tree=".length)));
      return;
    }
    if (hashId === "auth") {
      // Unconditional, not "only if not already showing": openAuthView()
      // is idempotent (setHash() inside it uses replaceState, so it can't
      // re-trigger this same listener), and this path only ever runs from
      // init() or an externally-driven hashchange in the first place.
      openAuthView();
      return;
    }
    // No hash on 設定 or an extension's tab: that tab (the deployment notes).
    if (!hashId && ui.get().tab === "settings") { openAuthView(); return; }
    if (!hashId && ui.get().tab !== "work") { ui.tabs.show(ui.get().tab); return; }
    if (!hashId || hashId.startsWith("machine=")) {
      // A machine's list: leave 設定 if it was showing, as picking a
      // machine in the menu does (applyMachineFilter).
      // An open session is closed by then: every hash move is a popstate
      // first, and that one closes it (pushSessionHistory).
      if (pageNow() === "auth") showPage("list");
      selectMachine(hashId ? decodeURIComponent(hashId.slice("machine=".length)) : "local");
      await refreshSessions();
      return;
    }
    if (hashId === chatNow.id) return; // already there
    // Not when the user has gone elsewhere (or a newer hash came) while the list loaded.
    const still = ui.ticket(), newest = ui.ticket("hash");
    const sessions = await refreshSessions();
    if (!still() || !newest()) return;
    const meta = sessions.find((s) => s.id === hashId);
    if (meta) chatNow.open(meta);
    else {
      // A link to a session this list does not have (deleted, no longer
      // shared, or on the other host): say so rather than show the list as
      // if that was where the link led.
      setHash("");
      ui.toast(t("common.cannot_see_session_no_longer"), { error: true });
    }
  }

  // A plain click on a link an extension handles (aizaExt links): its own
  // way of opening it, not the browser's.
  document.addEventListener("click", (e) => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a || !plainClick(e)) return;
    const open = window.aizaExt.linkHandler(a.getAttribute("href"), a);
    if (!open) return;
    e.preventDefault();
    open(a.getAttribute("href"));
  });

  window.addEventListener("hashchange", () => {
    // The hashchange of a Back from a session: its popstate did it all.
    if (!takePopped()) applyHash();
  });
  // sw.js's notificationclick posts {type: "open-session"} to an already-open
  // window rather than relying on WindowClient.navigate(), which not every
  // browser has (iOS Safari) -- 2026-10-04, at the user's request
  // ("通知を開いたときに、当該セッションが開きません").
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.addEventListener("message", (e) => {
      const d = e.data || {};
      if (d.type === "open-session" && typeof d.session_id === "string") {
        setHash(d.session_id);
        applyHash();
      }
    });
  }

  init();
