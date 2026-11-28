// The chat search (aiza): the 🔍 on the list, the hits, opening one.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after voice.js and before app.js, in this order:
// form, settings, keys, api, links, search, sessionops, compose. What runs
// here at load uses only this file and the earlier ones. Moved out of
// app.js 2026-11-24 as it was; the indentation is app.js's.
"use strict";

  // ---- chat search (2026-10-11, at the user's request) ----------------------
  //
  // GET /search scans this user's own sessions' chat logs (aiza-backend's
  // search_events), and GET /shared/<owner>/search, once per owner who
  // shares something with this user, the sessions shared with them -- the
  // owner's backend applies the same shared_with check as opening one.
  // host/root/Email sessions only while this browser has their passkey
  // window (the reply counts the skipped ones). Tapping a hit opens that
  // session and jumps to the message (openSession's jumpSeq).
  const searchPanelEl = document.getElementById("search-panel");
  const searchInputEl = document.getElementById("search-input");
  const searchStatusEl = document.getElementById("search-status");
  const searchResultsEl = document.getElementById("search-results");
  const SEARCH_TYPE_LABEL = { user_message: t("common.me"), agent_output: "AI", agent_thinking: t("search.ai_thinking"), system: t("search.system") };

  document.getElementById("search-toggle-btn").addEventListener("click", () => {
    searchPanelEl.hidden = !searchPanelEl.hidden;
    if (!searchPanelEl.hidden) searchInputEl.focus();
  });

  function appendHighlighted(el, text, terms) {
    const lower = text.toLowerCase();
    let i = 0;
    while (i < text.length) {
      let best = -1, bestLen = 0;
      for (const t of terms) {
        const j = lower.indexOf(t, i);
        if (j !== -1 && (best === -1 || j < best)) { best = j; bestLen = t.length; }
      }
      if (best === -1) break;
      if (best > i) el.appendChild(document.createTextNode(text.slice(i, best)));
      const m = document.createElement("mark");
      m.textContent = text.slice(best, best + bestLen);
      el.appendChild(m);
      i = best + bestLen;
    }
    if (i < text.length) el.appendChild(document.createTextNode(text.slice(i)));
  }

  async function openSearchHit(hit, terms) {
    const match = (s) => s.id === hit.session_id && (s.owner || null) === (hit.owner || null);
    let meta = lastSessions.find(match);
    if (!meta) {
      const still = ui.ticket();
      const sessions = await refreshSessions();
      if (!still()) return;
      meta = sessions.find(match);
    }
    if (!meta) {
      searchStatusEl.textContent = t("search.session_no_longer_exists");
      return;
    }
    chatNow.open(meta, hit.seq, terms);
  }

  async function runSearch(q) {
    const terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    searchResultsEl.innerHTML = "";
    if (!terms.length) { searchStatusEl.textContent = ""; return; }
    searchStatusEl.textContent = t("search.searching");
    const still = ui.ticket("search");   // a newer search wins over a slower older one
    const qp = `/search?q=${encodeURIComponent(q)}`;
    const owners = [...new Set(lastSessions.filter((s) => s.owner).map((s) => s.owner))];
    let r;
    try {
      const [own, ...shared] = await Promise.all([
        api(qp),
        ...owners.map((o) => api(`/shared/${encodeURIComponent(o)}${qp}`)
          .then((x) => ({ ...x, hits: x.hits.map((h) => ({ ...h, owner: o })) }))
          .catch(() => ({ hits: [], locked: 0, truncated: false }))),
      ]);
      const all = [own, ...shared];
      const hits = all.flatMap((x) => x.hits).sort((a, b) => (b.ts || 0) - (a.ts || 0));
      r = {
        hits: hits.slice(0, 200),
        locked: all.reduce((n, x) => n + (x.locked || 0), 0),
        truncated: hits.length > 200 || all.some((x) => x.truncated),
      };
    } catch (e) {
      if (still()) searchStatusEl.textContent = t("search.search_failed_err", { err: e.message });
      return;
    }
    if (!still()) return;
    const notes = [r.hits.length ? t("common.n_hits", { n: r.hits.length }) + (r.truncated ? t("search.newest_first_older_ones_omitted") : "") : t("common.nothing_found")];
    if (r.locked) notes.push(t("search.n_sessions_host_root_mailbox", { n: r.locked }));
    searchStatusEl.textContent = notes.join(t("common.period"));
    for (const hit of r.hits) {
      const row = document.createElement("div");
      row.className = "search-hit-row";
      row.dataset.sessionId = hit.session_id;
      if (hit.owner) row.dataset.owner = hit.owner;
      row.dataset.seq = hit.seq;
      const metaEl = document.createElement("div");
      metaEl.className = "meta";
      metaEl.textContent = `${hit.archived ? "🗄 " : ""}${hit.owner ? t("search.owner", { owner: hit.owner }) : ""}${hit.label} · ${hit.ts ? fmtDateTime(hit.ts) : ""} · ${SEARCH_TYPE_LABEL[hit.type] || hit.type}`;
      const snip = document.createElement("div");
      snip.className = "snippet";
      appendHighlighted(snip, hit.snippet, terms);
      row.appendChild(metaEl);
      row.appendChild(snip);
      row.addEventListener("click", () => openSearchHit(hit, terms));
      searchResultsEl.appendChild(row);
    }
  }

  document.getElementById("search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    searchInputEl.blur(); // closes the phone keyboard so the results are visible
    runSearch(searchInputEl.value.trim());
  });

  // Logging out moved from its own always-visible header link to a
  // tap-to-confirm on the username itself (2026-08-28, at the user's
  // request, to free up header space) -- whoEl.textContent is read at click
  // time, not registration time, since applyCapabilities() only fills it in
  // once GET /api/me answers.
  // POST, not a plain `location.href = "/agents/logout"` navigation: logging
  // out changes server state now that there is a real session store (Phase 3),
  // and SameSite=Lax still attaches the session cookie to a top-level GET
  // navigation any other site can trigger -- so a GET logout route is a
  // logout-CSRF anyone can fire at you. The gateway now answers this only on
  // POST and returns {"ok": true} rather than a 302, so the redirect happens
  // here afterwards instead. Failure is ignored on purpose: the server-side
  // revoke either happened or the session was already invalid, and either way
  // sending the user back to /agents/ is the right next step.
  // 設定's アカウント card (the deployment notes): its ログアウト button.
  document.getElementById("logout-btn").addEventListener("click", async () => {
    if ((await ui.confirm(t("search.log_out_who", { who: whoEl.textContent }), { danger: true }))) {
      try {
        await fetch(window.aizaBase + "/agents/logout", { method: "POST", credentials: "same-origin" });
      } catch (e) { /* fall through to the redirect regardless */ }
      location.href = window.aizaBase + "/agents/";
    }
  });

  // A hand-rolled approximation of the same gesture, scoped to the header:
  // native pull-to-refresh needs the document itself to be at scroll
  // position 0 and dragged down, which never applies here, so this just
  // watches for a downward drag starting on the (always-visible, never
  // scrolling) header and reloads past a threshold. Not preventDefault'd
  // anywhere, so an ordinary tap on 再読み込み/ログアウト still behaves as a
  // plain click -- only a real drag past PULL_THRESHOLD does anything.
  // Both bars: the list's and, since 2026-11-21 (the user: セッションのトップの
  // バーも下スワイプでリロード, with the ⟳ buttons gone), the chat's.
  for (const header of [document.getElementById("top-header"), document.getElementById("chat-header")]) {
    const PULL_THRESHOLD = 70;
    let startY = null;
    let pulling = false;
    header.addEventListener("touchstart", (e) => {
      if (e.touches.length !== 1) return;
      startY = e.touches[0].clientY;
      pulling = false;
    }, { passive: true });
    header.addEventListener("touchmove", (e) => {
      if (startY === null || e.touches.length !== 1) return;
      pulling = e.touches[0].clientY - startY > PULL_THRESHOLD;
    }, { passive: true });
    header.addEventListener("touchend", () => {
      if (pulling) location.reload();
      startY = null;
      pulling = false;
    });
  }
