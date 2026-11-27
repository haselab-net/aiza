// Sharing (the deployment notes): one session's share pane, and a folder's share panel.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after page.js and before app.js. What runs here at
// load uses only this file and the earlier ones. Moved out of app.js
// 2026-11-24; the indentation is app.js's.
"use strict";

  // This file's own elements of the page (only it uses them; from page.js, 2026-11-24).
  const sharePaneEl = document.getElementById("share-pane");

  // ---- sharing --------------------------------------------------------
  //
  // Owner-only panel (shareBtn itself is hidden in openSession() whenever
  // chatNow.owner is set): add/remove usernames from this session's
  // shared_with, kept in currentSharedWith and re-rendered after every
  // change rather than polled, since only this tab's own actions can change
  // it while the panel is open.

  let shareVisible = false;
  let currentSharedWith = [];
  let currentSharedRead = [];
  // "read" when the open session is someone else's shared with me read-only
  // (the deployment notes): the log only -- no composer, keys, screen or stop.
  let currentShareMode = null;
  // The open session's sharing, from its meta (null: closed) -- chat.js's
  // openSession / closeSession. Someone else's: how it is shared with me.
  function setSessionShare(meta) {
    currentShareMode = meta && meta.owner ? (meta.share_mode || "write") : null;
    currentSharedWith = meta && !meta.owner ? (meta.shared_with || []) : [];
    currentSharedRead = meta && !meta.owner ? (meta.shared_read || []) : [];
  }

  // aiza-backend sends Content-Disposition: attachment, but a same-tab
  // navigation to it is not reliable in a standalone PWA on every mobile
  // browser (some just navigate the app itself away from the chat). Fetch
  // + blob + a synthetic <a download> forces a real download regardless of
  // how the platform would otherwise have handled the response.
  async function downloadTranscript() {
    const sid = chatNow.id;
    if (!sid) return;
    // Not api(): that always calls .json() on the response, which would
    // throw on this endpoint's plain-text body.
    const res = await fetch(sessionApiUrl(sid, "/download", chatNow.owner)).catch(() => null);
    if (!res || !res.ok) {
      alert(t("share.download_failed") + (res ? `: ${res.status}` : ""));
      return;
    }
    const disposition = res.headers.get("Content-Disposition") || "";
    const m = /filename="([^"]+)"/.exec(disposition);
    const filename = m ? m[1] : `aiza-${sid}.txt`;
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // Distinct from .active (which just means "panel open right now") --
  // .shared means "this session is currently shared with someone", so the
  // button still tells you that at a glance even with the panel closed.
  // Meaningless for a shared viewer's own copy of this button (they don't
  // control shared_with), so only ever set for one's own session.
  function updateShareBtnColor() {
    shareBtn.classList.toggle("shared", !chatNow.owner && currentSharedWith.length + currentSharedRead.length > 0);
  }

  // The ⋯ panel (2026-11-21, the user: リンクしているセッションに飛ぶ・新たなリンクを
  // 始めるボタンを、共有のアイコンを ⋯ に変えてその中に): the session links
  // (the deployment notes) on top of save and sharing. Own sessions only, like
  // the list's 🔗.
  function renderSharePane() {
    renderSharePaneBody();
    if (chatNow.owner || !chatNow.id) return;
    const me = lastSessions.find((x) => x.id === chatNow.id && !x.owner);
    if (!me) return;
    const box = document.createElement("div");
    box.className = "share-save share-links";
    const head = document.createElement("div");
    head.className = "share-links-head";
    head.textContent = me.link
      ? t("share.linked_left", { left: me.link.expires_ts == null ? t("common.no_time_limit") : linkRemaining(me.link.expires_ts) })
      : t("share.session_link");
    box.appendChild(head);
    const mk = (text, title, onclick) => {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = text;
      if (title) b.title = title;
      b.addEventListener("click", onclick);
      box.appendChild(b);
      return b;
    };
    for (const m of (me.link && me.link.members) || []) {
      mk(`→ ${m.label}${m.stopped ? " " + t("share.stopped") : ""}`, t("share.open_session"), async () => {
        const still = ui.ticket();
        const all = lastSessions.find((x) => x.id === m.id && !x.owner) ? lastSessions : await refreshSessions();
        if (!still()) return;
        const meta = (all || []).find((x) => x.id === m.id && !x.owner);
        if (!meta) { alert(t("common.cannot_see_session_no_longer")); return; }
        setShareVisible(false);
        chatNow.open(meta);
      });
    }
    mk(me.link ? t("share.add_another_session") : t("share.link_another_session"),
      t("share.back_list_tap_on_session"), () => {
        setShareVisible(false);
        armLink(me.id);
        chatNow.close();
        renderLinkArmedBanner();
      });
    if (me.link) {
      mk(t("share.leave_link"), "", async () => {
        disarmLink();
        await onLinkButtonTapped(me);
        if (shareVisible) renderSharePane();
      });
    }
    sharePaneEl.insertBefore(box, sharePaneEl.firstChild);
  }

  function renderSharePaneBody() {
    updateShareBtnColor();
    const save = `
      <div class="share-save">
        <button id="share-download-btn">${t("share.save_conversation_log")}</button>
      </div>`;
    // Sharing *management* stays owner-only -- chatNow.owner set means this
    // session was shared to me, not mine to re-share.
    if (chatNow.owner) {
      sharePaneEl.innerHTML = save;
      sharePaneEl.querySelector("#share-download-btn").addEventListener("click", downloadTranscript);
      return;
    }
    // the deployment notes: everyone, read-only is the default. A root shell is
    // only ever shared read-only; Email only with a named person (read-only,
    // or co-working its Claude or Codex since 2026-11-25), so it gets the
    // name box. Everyone may
    // co-work only a devbox session (2026-11-25; the backend rechecks).
    const kind = sessionKind(chatNow.meta || { preset: chatNow.preset });
    const isRoot = kind.root;
    const isMail = kind.place === "mail";
    const everyoneCowork = kind.place === "dev";
    const modeLabel = (m) => (m === "read" ? t("common.read_only") : t("common.co_work"));
    const entries = [
      ...currentSharedRead.map((u) => ({ u, m: "read" })),
      ...currentSharedWith.map((u) => ({ u, m: isRoot ? "read" : "write" })),
    ];
    const rows = entries.length
      ? entries.map(({ u, m }) => `
          <div class="share-row" data-user="${escapeHtml(u)}">
            <span>${u === "*" ? t("common.everyone") : escapeHtml(u)} &middot; ${modeLabel(m)}</span>
            <button class="unshare-btn">${t("common.remove_2")}</button>
          </div>`).join("")
      : `<div class="share-empty">${t("share.not_shared_anyone_yet")}</div>`;
    const note = isMail
      ? `<div class="share-note">${t("share.mailbox_sessions_can_shared_only")}</div>`
      : `<div class="share-note">${t("share.read_only_they_see_only")}</div>`;
    const warn = kind.place === "host"
      ? `<div class="share-warn">${t("share.sharing_co_work_lets_them")}</div>`
      : "";
    // Move into the Email box (2026-11-15, the user: 移すボタンを作って):
    // Only devbox conversations; the backend rechecks scope and resume identity.
    const codexMove = hasMailboxCodex && (chatNow.preset === "codex-tui" ||
      (chatNow.preset === "shell" && chatNow.meta && chatNow.meta.codex_resume_id));
    const move = hasMailbox && (chatNow.preset === "claude-tui" || codexMove)
      ? `<div class="share-save"><button id="move-mail-btn">${t("share.move_into_box", { box: mailboxLabel })}</button></div>` : "";
    // The desk (the deployment notes): a report with a link to this session.
    const desk = `<div class="share-save"><button id="desk-report-btn">${t("share.send_desk_bug_request")}</button></div>`;
    // To this session's place in the work tree (2026-11-20, the user:
    // セッションから木の該当箇所に飛べると良いです / 共有の中で良い); shown
    // only when a node it took on is one this viewer may see.
    const treeJump = `<div class="share-save" id="tree-jump-row" hidden><button id="tree-jump-btn"></button></div>`;
    sharePaneEl.innerHTML = `
      ${save}
      ${move}
      ${treeJump}
      ${desk}
      ${note}
      ${warn}
      ${rows}
      <div class="share-add">
        <select id="share-target" ${isMail ? "hidden" : ""}>
          <option value="*">${t("common.everyone")}</option>
          <option value="user" ${isMail ? "selected" : ""}>${t("share.specific_user")}</option>
        </select>
        <input type="text" id="share-username" placeholder="${t("common.username")}" autocapitalize="off" autocorrect="off" ${isMail ? "" : "hidden"}>
        <select id="share-mode" ${isRoot ? "hidden" : ""}>
          <option value="read">${t("common.read_only")}</option>
          <option value="write" ${(isMail && (kind.preset === "mail-tui" || kind.launch === "codex")) || everyoneCowork ? "" : "disabled"}>${t("common.co_work")}</option>
        </select>
        <button id="share-add-btn">${t("share.share")}</button>
      </div>`;
    sharePaneEl.querySelector("#share-download-btn").addEventListener("click", downloadTranscript);
    sharePaneEl.querySelector("#desk-report-btn").addEventListener("click", () => deskReport({ session: chatNow.id }));
    sharePaneEl.querySelector("#tree-jump-btn").addEventListener("click", (e) => jumpToTreeNode(e.currentTarget.dataset.node));
    if (!treeData) loadTree();
    updateChatTreeBtn();
    const moveBtn = sharePaneEl.querySelector("#move-mail-btn");
    if (moveBtn) moveBtn.addEventListener("click", async () => {
      if (!confirm(t("share.move_session_into_box_conversation", { box: mailboxLabel }))) return;
      const sid = chatNow.id;
      const still = ui.ticket();
      moveBtn.disabled = true;
      try {
        const meta = await withUnlockRetry(() => api(`/sessions/${sid}/to-mailbox`, { method: "POST" }));
        await refreshSessions();
        if (still()) chatNow.open(meta);   // moved elsewhere meanwhile: it is in the list
      } catch (e) { moveBtn.disabled = false; alert(e.message); }
    });
    const targetEl = sharePaneEl.querySelector("#share-target");
    const userEl = sharePaneEl.querySelector("#share-username");
    const modeEl = sharePaneEl.querySelector("#share-mode");
    targetEl.addEventListener("change", () => {
      const everyone = targetEl.value === "*";
      userEl.hidden = everyone;
      // Co-working with everyone: a devbox session only.
      const off = everyone && !everyoneCowork;
      modeEl.querySelector('option[value="write"]').disabled = off;
      if (off) modeEl.value = "read";
    });
    // The answer is the session's it was asked for: shown only while that
    // one is still open (the deployment notes).
    const applyShareMeta = (meta, still) => {
      if (!still()) return;
      currentSharedWith = meta.shared_with || [];
      currentSharedRead = meta.shared_read || [];
      renderSharePane();
    };
    sharePaneEl.querySelectorAll(".unshare-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const username = btn.closest(".share-row").dataset.user;
        const still = ui.ticket("session");
        try {
          applyShareMeta(await api(`/sessions/${chatNow.id}/unshare`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username }),
          }), still);
        } catch (e) {
          alert(t("share.could_not_stop_sharing_err", { err: e.message }));
        }
      });
    });
    sharePaneEl.querySelector("#share-add-btn").addEventListener("click", async () => {
      const username = targetEl.value === "user" ? userEl.value.trim() : "*";
      if (!username) return;
      const mode = isRoot ? "read" : modeEl.value;
      const still = ui.ticket("session");
      try {
        applyShareMeta(await api(`/sessions/${chatNow.id}/share`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, mode }),
        }), still);
      } catch (e) {
        alert(t("share.could_not_share_err", { err: e.message }));
      }
    });
  }

  function setShareVisible(on) {
    shareVisible = on;
    sharePaneEl.classList.toggle("visible", on);
    shareBtn.classList.toggle("active", on);
    if (on) renderSharePane();
  }

  shareBtn.addEventListener("click", () => setShareVisible(!shareVisible));

  // Sharing a whole folder (the deployment notes): every session in it and
  // in the folders under it, now and later, with the limits sharing one
  // session has (a root shell read-only; Email only to a named person).
  const folderShareEl = document.getElementById("folder-share");
  folderShareEl.addEventListener("click", (e) => { if (e.target === folderShareEl) folderShareEl.hidden = true; });
  function openFolderShare(id) {
    const f = folderById(id);
    if (!f) { folderShareEl.hidden = true; return; }
    const box = folderShareEl.querySelector(".box");
    const modeLabel = (m) => (m === "read" ? t("common.read_only") : t("common.co_work"));
    const entries = [
      ...(f.shared_read || []).map((u) => ({ u, m: "read" })),
      ...(f.shared_with || []).map((u) => ({ u, m: "write" })),
    ];
    box.innerHTML = `
      <h3>🧑‍🤝‍🧑 ${t("share.share_folder_name", { name: escapeHtml(f.name) })}</h3>
      <div class="share-note">${t("share.every_session_in_shared_including")}</div>
      ${entries.length ? entries.map(({ u, m }) => `
        <div class="share-row" data-user="${escapeHtml(u)}">
          <span>${u === "*" ? t("common.everyone") : escapeHtml(u)} &middot; ${modeLabel(m)}</span>
          <button class="unshare-btn">${t("common.remove_2")}</button>
        </div>`).join("") : `<div class="share-empty">${t("share.not_shared_anyone_yet")}</div>`}
      <div class="share-add">
        <select class="target"><option value="*">${t("common.everyone")}</option><option value="user">${t("share.specific_user")}</option></select>
        <input type="text" class="username" placeholder="${t("common.username")}" autocapitalize="off" autocorrect="off" hidden>
        <select class="mode"><option value="read">${t("common.read_only")}</option><option value="write" disabled>${t("common.co_work")}</option></select>
        <button class="add">${t("share.share")}</button>
      </div>
      <button class="close">${t("common.close")}</button>`;
    const targetEl = box.querySelector(".target"), userEl = box.querySelector(".username"), modeEl = box.querySelector(".mode");
    targetEl.addEventListener("change", () => {
      const everyone = targetEl.value === "*";
      userEl.hidden = everyone;
      modeEl.querySelector('option[value="write"]').disabled = everyone;
      if (everyone) modeEl.value = "read";
    });
    const run = async (op) => {
      try { await saveFolders([op]); } catch (e) {}
      openFolderShare(id);
    };
    box.querySelectorAll(".unshare-btn").forEach((b) => b.addEventListener("click", () =>
      run({ op: "unshare", id, username: b.closest(".share-row").dataset.user })));
    box.querySelector(".add").addEventListener("click", () => {
      const username = targetEl.value === "user" ? userEl.value.trim() : "*";
      if (username) run({ op: "share", id, username, mode: modeEl.value });
    });
    box.querySelector(".close").addEventListener("click", () => { folderShareEl.hidden = true; });
    folderShareEl.hidden = false;
  }
