// Session links (the deployment notes): the 🔗 on the list's rows, the armed
// banner, the remaining time.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after voice.js and before app.js, in this order:
// form, settings, keys, api, links, search, sessionops, compose. What runs
// here at load uses only this file and the earlier ones. Moved out of
// app.js 2026-11-24 as it was; the indentation is app.js's.
"use strict";

  // This file's own elements of the page (only it uses them; from page.js, 2026-11-24).
  const linkArmedBannerEl = document.getElementById("link-armed-banner");
  const linkArmedTextEl = document.getElementById("link-armed-text");
  const linkArmedCancelBtn = document.getElementById("link-armed-cancel");

  // ---- session links (the deployment notes) --------------------------------
  //
  // Lets the user pick two of their own sessions (typically one in the
  // sandbox container, one on the host or as root -- but any pair) and have
  // each side's replies relayed to the other automatically, until either
  // side disconnects or the backend's own turn cap kicks in
  // (create_link/_relay_agent_output in aiza-backend). Two taps, no new
  // screen: tap 🔗 on the first session (arms it, shows the banner below),
  // tap 🔗 on a second session to complete the link, or tap the same 🔗
  // again (or the banner's キャンセル) to back out.
  let linkArmedSessionId = null;
  // The 🔗 armed from elsewhere (the share pane, share.js): armLink(id), disarmLink().
  function armLink(id) { linkArmedSessionId = id; }
  function disarmLink() { linkArmedSessionId = null; }

  // Remaining time of a link, as "残り1時間23分" -- links are time-limited
  // (2026-10-04; they used to count turns). Refreshed with every session-list
  // poll, which is also when the backend disconnects an expired one.
  function linkRemaining(expiresTs) {
    const min = Math.max(0, Math.ceil((expiresTs - Date.now() / 1000) / 60));
    const h = Math.floor(min / 60), m = min % 60;
    return h ? (m ? t("links.h_h_m_min_left", { h, m }) : t("links.h_h_left", { h })) : t("links.m_min_left", { m });
  }

  // The GitHub issue a session works on (the deployment notes), and 🤖 when
  // the dispatcher started it rather than a person.
  // After it, the issue's Status in its project (issue_status, refreshed by
  // the backend in the background) -- Blocked and In review are the ones
  // waiting for a person. A closed issue with no Status shows "Closed".
  function issueSuffix(s) {
    if (!s.issue) return "";
    return ` &middot; ${s.auto ? "🤖" : ""}${escapeHtml(s.issue)}${issueStatusBadge(s.issue_status)}`;
  }

  function issueStatusBadge(st) {
    if (!st) return "";
    const name = st.status || (st.state === "CLOSED" ? "Closed" : "");
    if (!name) return "";
    const cls = name.toLowerCase().replace(/[^a-z]+/g, "-");
    return ` <span class="issue-status issue-status-${escapeHtml(cls)}">${escapeHtml(name)}</span>`;
  }

  function linkSuffix(s) {
    if (!s.link) return "";
    const left = s.link.expires_ts == null ? t("common.no_time_limit") : linkRemaining(s.link.expires_ts);
    return ` &middot; 🔗${escapeHtml(s.link.partner_label)}(${left})`;
  }

  function renderLinkArmedBanner() {
    const armed = lastSessions.find((s) => s.id === linkArmedSessionId);
    linkArmedBannerEl.classList.toggle("visible", !!armed);
    document.body.classList.toggle("link-armed", !!armed);   // room under the list for the bar
    if (armed) linkArmedTextEl.textContent = t("links.tap_session_link_label", { label: armed.label });
  }

  linkArmedCancelBtn.addEventListener("click", () => {
    linkArmedSessionId = null;
    renderLinkArmedBanner();
    refreshSessions();
  });

  // "root-shell" is the only preset a root Claude conversation can run in
  // (there is no dedicated "claude-tui-root" -- the deployment notes): whoever is
  // driving it typed `claude` into that shell by hand. Used only to suggest
  // a shorter default time limit below; the backend applies its own default
  // (and the real backstop, the passkey window) regardless of what the
  // client suggests.
  function isRootSession(s) { return sessionKind(s).root; }

  // A link is a group (2026-11-08): with one session armed, tapping 🔗 on a
  // session that is already linked adds the armed one to that link.
  async function onLinkButtonTapped(s) {
    if (s.link && (linkArmedSessionId === null || linkArmedSessionId === s.id)) {
      const many = (s.link.members || []).length > 1;
      const q = many
        ? t("links.remove_link_still_linked_b", { a: s.label, b: s.link.partner_label })
        : t("links.unlink_b", { a: s.label, b: s.link.partner_label });
      if (!confirm(q)) return;
      await api("/sessions/unlink", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: s.id }),
      }).catch((e) => alert(t("links.could_not_unlink_err", { err: e.message })));
      await refreshSessions();
      return;
    }
    if (linkArmedSessionId === s.id) {
      linkArmedSessionId = null;
      renderLinkArmedBanner();
      await refreshSessions();
      return;
    }
    if (linkArmedSessionId === null) {
      linkArmedSessionId = s.id;
      renderLinkArmedBanner();
      await refreshSessions();
      return;
    }
    const other = lastSessions.find((x) => x.id === linkArmedSessionId);
    linkArmedSessionId = null;
    renderLinkArmedBanner();
    if (!other) { await refreshSessions(); return; }
    if (s.link || other.link) {
      // Joining a link: it keeps its own time limit. Both linked: the two
      // links become one (2026-11-25), with the longer limit.
      const joiner = s.link ? other : s;
      const group = s.link ? s : other;
      const q = (s.link && other.link)
        ? t("links.merge_links_b", { a: [other.label, other.link.partner_label].join("・"),
                                     b: [s.label, s.link.partner_label].join("・") })
        : t("links.add_link_b", { a: joiner.label, b: [group.label, group.link.partner_label].join("・") });
      if (!confirm(q)) {
        await refreshSessions();
        return;
      }
      await api("/sessions/link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ a: other.id, b: s.id }),
      }).catch((e) => alert(t("links.could_not_link_err", { err: e.message })));
      await refreshSessions();
      return;
    }
    // Same defaults as the backend's DEFAULT_LINK_DURATION(_ROOT): 30 min
    // when root is involved, 4 hours otherwise. Blank also means "default".
    const suggested = (isRootSession(s) || isRootSession(other)) ? 30 : 240;
    const raw = prompt(
      t("links.link_b", { a: other.label, b: s.label }) + "\n" +
      t("links.unlink_automatically_after_how_many"),
      String(suggested),
    );
    if (raw === null) { await refreshSessions(); return; } // cancelled
    const minutes = raw.trim() === "" ? null : Number(raw);
    const forever = minutes === 0;  // the deployment notes: 0 = never expires
    if (raw.trim() !== "" && !forever && (!Number.isFinite(minutes) || minutes <= 0)) {
      alert(t("links.enter_positive_number_minutes"));
      await refreshSessions();
      return;
    }
    const body = { a: other.id, b: s.id };
    if (forever) body.forever = true;
    else if (minutes !== null) body.duration_minutes = minutes;
    await api("/sessions/link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).catch((e) => alert(t("links.could_not_link_err", { err: e.message })));
    await refreshSessions();
  }

  // Sessions previously placed by a drag keep their
  // saved relative sequence; anything not in `order` (a session created
  // since the last drag) is placed *before* all of them, in the usual
  // alive/ended sort's relative order -- so a brand-new session always
  // shows up at the very top of the list, never buried under whatever was
  // last dragged (2026-09-15: putting it after
  // the saved ones instead defeated "newest first" as soon as anyone had
  // ever dragged the list once).
  function applyCustomOrder(defaultSorted, order) {
    if (!order || order.length === 0) return defaultSorted;
    const byId = new Map(defaultSorted.map((s) => [s.id, s]));
    const orderedIds = order.filter((id) => byId.has(id));
    const orderedSet = new Set(orderedIds);
    const rest = defaultSorted.filter((s) => !orderedSet.has(s.id));
    return [...rest, ...orderedIds.map((id) => byId.get(id))];
  }
  // The Windows machines' blackboard (the deployment notes, 2026-11-06): who
  // (which session) is using which Windows machine, on this host. Sessions
  // on a Windows machine appear by themselves; a session working on one
  // from elsewhere over ssh/scp/sftp/rsync appear by themselves too (the
  // check finds the process); `aiza-board use` / "＋ 使う" are optional notes.
  // The server checks every 3 minutes: ended sessions become 「終了」, a
  // closed ssh 「終了(SSH終了)」, 30 minutes without activity 「30分以上動きなし」.
  const boardModalEl = document.getElementById("board-modal");
  let boardTimer = null;
  boardModalEl.addEventListener("click", (e) => { if (e.target === boardModalEl) closeBoard(); });
  function closeBoard() {
    boardModalEl.hidden = true; clearInterval(boardTimer); boardTimer = null;
    if (ui.get().overlay === "board") ui.set({ overlay: null });
  }
  const BOARD_WHY = { stopped: "common.stopped", fell: "links.fell", deleted: "common.deleted", released: "common.remove_2", disconnected: "links.ssh_closed" };
  async function boardPost(body) {
    try {
      return await api("/board", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    } catch (e) { alert(t("links.could_not_update_board_err", { err: e.message })); return null; }
  }
  async function renderBoard(data) {
    const box = boardModalEl.querySelector(".box");
    if (!data) data = await api("/board").catch((e) => ({ error: e.message }));
    const caps = await api("/capabilities").catch(() => ({}));
    const reachable = new Set([...(caps.ssh_machines || []), ...Object.keys(caps.ssh_desktop || {})]);
    // Asleep (not answering, but wakeable): nobody is using it. Opening its
    // session list or starting a session there wakes it.
    const asleep = new Set(caps.ssh_asleep || []);
    const now = Date.now() / 1000;
    const hm = (ts) => fmtStamp(ts).slice(5);
    // The machines (this host, the other ssh machines) come first:
    // this panel took the place of the machine menu (2026-11-09, the user:
    // "コンボボックスをやめて黒板に統一"). The Windows machines are the
    // blackboard's cards below; their names open their session lists.
    box.innerHTML = `
      <div class="head"><h3>🖥 ${t("common.machines")}</h3><button class="reload">⟳</button><button class="close">✕</button></div>
      <div class="mlist"></div>`;
    const mlist = box.querySelector(".mlist");
    const cur = pageNow() === "auth" ? "auth" : currentMachine;
    for (const o of [...machineSelectEl.options]) {
      // 設定 is a tab of its own now (the deployment notes), not a machine here.
      if (o.dataset.board || o.value === "auth") continue;
      const btn = document.createElement("button");
      btn.className = "mpick" + (o.value === cur ? " cur" : "");
      btn.textContent = o.value === "auth" ? "⚙ " + o.textContent : o.textContent;
      btn.addEventListener("click", () => openBoardMachine(o.value));
      mlist.appendChild(btn);
    }
    box.querySelector(".close").addEventListener("click", closeBoard);
    box.querySelector(".reload").addEventListener("click", () => renderBoard());
    if (data.error) { box.insertAdjacentHTML("beforeend", `<div class="note">${escapeHtml(data.error)}</div>`); return; }
    if (!data.available && !(data.machines || []).length) return;
    box.insertAdjacentHTML("beforeend", `
      <div class="head"><h3>📋 ${t("links.windows_machines_board")}</h3></div>
      <div class="note">${t("links.who_which_session_using_which")}</div>
      ${data.available ? "" : `<div class="note">${t("links.host_no_place_board")}</div>`}
      ${Object.entries(data.feeds || {}).filter(([, f]) => f.stale).map(([h, f]) => `<div class="note">${t("links.nothing_host_since_time", { host: escapeHtml(h), time: hm(f.at) })}</div>`).join("")}`);
    for (const m of data.machines) {
      const rows = data.entries.filter((e) => e.machine === m)
        .sort((a, b) => (a.state === "ended") - (b.state === "ended") || (a.since || 0) - (b.since || 0));
      const live = rows.filter((e) => e.state !== "ended");
      const card = document.createElement("div");
      card.className = "machine";
      const status = !reachable.has(m) ? `<span class="off">${t("common.unreachable")}</span>`
        : asleep.has(m) ? `<span class="sleep" title="${escapeHtml(t("links.opening_or_starting_session_wakes"))}">💤 ${t("links.asleep_free")}</span>`
        : live.length ? `<span class="busy">${t("links.in_use_n", { n: live.length })}</span>` : `<span class="free">${t("links.free")}</span>`;
      card.innerHTML = `<div class="m-head">${reachable.has(m) && boardMachines.has(m)
        ? `<a class="name${m === currentMachine && pageNow() !== "auth" ? " cur" : ""}" href="#" title="${escapeHtml(t("links.machines_sessions"))}">🪟 ${escapeHtml(m)}</a>`
        : `<span class="name">🪟 ${escapeHtml(m)}</span>`}${status}<button class="use">＋ ${t("common.use")}</button></div>`;
      const nameLink = card.querySelector("a.name");
      if (nameLink) nameLink.addEventListener("click", (ev) => { ev.preventDefault(); openBoardMachine(m); });
      card.querySelector(".use").addEventListener("click", async () => {
        const what = prompt(t("links.what_do_on_m_hand", { m }), "");
        if (what === null) return;
        const r = await boardPost({ op: "claim", machine: m, what });
        if (r) renderBoard(r);
      });
      for (const e of rows) {
        const row = document.createElement("div");
        row.className = "entry" + (e.state === "ended" ? " ended" : "");
        let st;
        if (e.state === "ended") st = `<span class="st ended">${t("common.ended")}(${t(BOARD_WHY[e.ended_why] || e.ended_why || "")} ${hm(e.ended_at)})</span>`;
        else if (e.state === "asleep") st = `<span class="st asleep">💤 ${t("links.asleep")}</span>`;
        else if (e.state === "idle") st = `<span class="st idle">${t("links.no_activity_30_min")}(${Math.floor((now - (e.last_activity || now)) / 60)}${t("common.min")})</span>`;
        else st = `<span class="st using">${t("links.in_use")}</span>`;
        const mine = e.user === data.me && !e.host;
        const own = mine && e.session_id ? lastSessions.find((x) => x.id === e.session_id && !x.owner) : null;
        const label = e.label || (e.session_id ? e.session_id : t("links.hand_written"));
        const src = { auto: t("common.auto"), ssh: t("links.ssh_auto"), claim: e.session_id ? t("links.written_session") : t("links.hand_written_2") }[e.source] || e.source;
        row.innerHTML = `
          <div class="body">
            <div>${st} <span class="who">${escapeHtml(e.user)}${e.host ? ` (${escapeHtml(e.host)})` : ""} · ${own ? `<a href="#${escapeHtml(e.session_id)}" class="open">${escapeHtml(label)}</a>` : escapeHtml(label)}</span></div>
            ${e.what ? `<div class="what">${escapeHtml(e.what)}</div>` : ""}
            <div class="sub">${src} · ${hm(e.since)}〜</div>
            ${e.command ? `<div class="sub cmd">${escapeHtml(e.command)}</div>` : ""}
          </div>`;
        const open = row.querySelector(".open");
        if (open) open.addEventListener("click", (ev) => { ev.preventDefault(); closeBoard(); own.locked ? openLockedSession(own) : chatNow.open(own); });
        if (mine && e.state !== "ended") {
          const ed = document.createElement("button");
          ed.textContent = "✏️";
          ed.title = t("links.edit_what_being_done");
          ed.addEventListener("click", async () => {
            const what = prompt(t("links.edit_what_being_done"), e.what || "");
            if (what === null) return;
            const r = await boardPost({ op: "note", key: e.key, what });
            if (r) renderBoard(r);
          });
          row.appendChild(ed);
          if (e.source === "claim") {
            const rel = document.createElement("button");
            rel.textContent = t("common.remove_2");
            rel.title = t("links.remove_entry");
            rel.addEventListener("click", async () => {
              const r = await boardPost({ op: "release", key: e.key });
              if (r) renderBoard(r);
            });
            row.appendChild(rel);
          }
        }
        card.appendChild(row);
      }
      box.appendChild(card);
    }
  }
  async function openBoard() {
    boardModalEl.querySelector(".box").innerHTML = `<div class="note">${t("common.checking")}</div>`;
    ui.set({ overlay: "board" });
    boardModalEl.hidden = false;
    await renderBoard();
    clearInterval(boardTimer);
    boardTimer = setInterval(() => { if (!boardModalEl.hidden) renderBoard(); }, 30000);
  }

  function fmtStamp(ts) {
    const d = new Date(ts * 1000);
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  }

  // Everyone's Claude / Codex logins (the deployment notes): read-only, no
  // buttons. root's own row only while this user's root window is open
  // (the server decides).
  const loginsModalEl = document.getElementById("logins-modal");
  loginsModalEl.addEventListener("click", (e) => { if (e.target === loginsModalEl) loginsModalEl.hidden = true; });
  document.getElementById("login-list-btn").addEventListener("click", async () => {
    const box = loginsModalEl.querySelector(".box");
    box.innerHTML = `<h3>🧑‍🤝‍🧑 ${t("common.everyones_logins")}</h3><div class="note">${t("common.checking")}</div>`;
    loginsModalEl.hidden = false;
    let data;
    try {
      data = await api("/logins");
    } catch (e) {
      box.innerHTML = `<h3>🧑‍🤝‍🧑 ${t("common.everyones_logins")}</h3><div class="note">${escapeHtml(e.message)}</div><button class="close">${t("common.close")}</button>`;
      box.querySelector(".close").addEventListener("click", () => { loginsModalEl.hidden = true; });
      return;
    }
    const cell = (v) => {
      if (!v) return `<td class="off"></td>`;
      if (!v.logged_in) return `<td class="off">${t("common.not_logged_in")}</td>`;
      const who = v.email ? escapeHtml(v.email) : escapeHtml(v.method || t("common.logged_in"));
      const sub = [v.org, v.plan, v.email ? v.method : null].filter(Boolean).map(escapeHtml).join(" · ");
      return `<td>${who}${sub ? `<div class="sub">${sub}</div>` : ""}</td>`;
    };
    const rows = (data.users || []).map((u) => {
      const sc = u.scopes || {};
      return `<tr><td>${escapeHtml(u.user)}</td>${cell(sc.sandbox?.claude)}${cell(sc.host?.claude)}${cell(sc.email?.claude)}${cell(sc.sandbox?.codex)}${cell(sc.host?.codex)}</tr>`;
    }).join("") + (data.root ? `<tr><td>root</td>${cell(data.root.scopes?.root?.claude)}<td class="off"></td><td class="off"></td>${cell(data.root.scopes?.root?.codex)}<td class="off"></td></tr>` : "");
    box.innerHTML = `
      <h3>🧑‍🤝‍🧑 ${t("common.everyones_logins")}</h3>
      <div class="note">${t("links.read_only_list_nothing_can")}</div>
      <table>
        <tr><th>${t("common.user")}</th><th>Claude (devbox)</th><th>Claude (${t("common.host")})</th><th>Claude (mailbox)</th><th>Codex (devbox)</th><th>Codex (${t("common.host")})</th></tr>
        ${rows}
      </table>
      <button class="close">${t("common.close")}</button>`;
    box.querySelector(".close").addEventListener("click", () => { loginsModalEl.hidden = true; });
  });

  // Swipe right to go back, replacing the ← button (2026-08-15, at the
  // user's request). Originally armed only within 24px of the left edge,
  // but that was too thin a target to hit reliably on a real phone
  // (2026-08-16, at the user's request to widen it) -- now it starts
  // anywhere in the chat view EXCEPT the few elements that have their own
  // real meaning for a horizontal drag: the key toolbar's own row of keys,
  // the screen/agents panels (both can scroll horizontally), and the
  // composer (a drag there is far more likely to be selecting/moving the
  // cursor in the still-unsent message than trying to leave the screen).
  // Not preventDefault'd. Same "only a real drag past a threshold, never
  // an ordinary tap" shape as the pull-to-refresh gesture below.
  (function () {
    const EXCLUDED_SELECTOR = "#key-toolbar, #screen-pane, #agents-pane, #composer";
    const SWIPE_THRESHOLD = 80;
    const MAX_VERTICAL_DRIFT = 60;
    let startX = null;
    let startY = null;
    viewChat.addEventListener("touchstart", (e) => {
      if (e.touches.length !== 1) { startX = null; return; }
      const t = e.touches[0];
      if (t.target.closest && t.target.closest(EXCLUDED_SELECTOR)) { startX = null; return; }
      startX = t.clientX;
      startY = t.clientY;
    }, { passive: true });
    viewChat.addEventListener("touchend", (e) => {
      if (startX === null) return;
      const t = e.changedTouches[0];
      const dx = t.clientX - startX;
      const dy = Math.abs(t.clientY - startY);
      startX = null;
      if (dx > SWIPE_THRESHOLD && dy < MAX_VERTICAL_DRIFT) chatNow.close();
    });
  })();

  // The ⟳ reload buttons (list and chat headers) were removed on 2026-11-21
  // at the user's request (リロードのアイコンは不要).
