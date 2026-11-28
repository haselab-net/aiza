// The session list (the list page): folders, rows, the archive and the shared
// sections, the patrol bar, dragging rows, archive / undo, tmux sessions to adopt.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after page.js and before app.js. What runs here at
// load uses only this file and the earlier ones. Moved out of app.js
// 2026-11-24; the indentation is app.js's.
"use strict";

  // The list's own state and badge (only it uses them; from form.js, 2026-11-24).
  // A built-in folder's own archive list (ownArchive): folder id -> its
  // archived sessions, and which of those lists are open.
  const extArchived = new Map();
  const extArchivedOpen = new Set();
  const openSharedOwners = new Set();
  // "確認待ち" (the deployment notes): the backend saw a Claude Code dialog (a
  // permission prompt or a choice) on this session's screen.
  function waitingBadge(meta) {
    if (meta.waiting) return `<span class="waiting-badge">${t("common.waiting")}</span>`;
    // the deployment notes: the state Claude declared, as a small mark on the row.
    const tk = !meta.owner && !meta.archived && meta.task;
    if (!tk) return "";
    if (tk.state === "you") return `<span class="waiting-badge">${t("common.needs")}</span>`;
    if (tk.state === "snooze") {
      const d = new Date((tk.until || 0) * 1000);
      return `<span class="task-badge${d <= new Date() ? " due" : ""}">💤${d.getMonth() + 1}/${d.getDate()}</span>`;
    }
    if (tk.state === "done" && !tk.seen) return `<span class="task-badge">${t("common.done")}</span>`;
    return "";
  }

  // This file's own elements of the page (only it uses them; from page.js, 2026-11-24).
  const sessionsEl = document.getElementById("sessions");
  const archiveToggleBtn = document.getElementById("archive-toggle-btn");
  const archivedListEl = document.getElementById("archived-list");
  // Built-in folders with an archive list of their own (aizaExt folders,
  // ownArchive): folded under the archive.
  const extArchivesEl = document.getElementById("ext-archives");
  // Sessions others shared with me, folded like the archive and grouped by
  // owner (the deployment notes).
  const sharedToggleBtn = document.getElementById("shared-toggle-btn");
  const sharedListEl = document.getElementById("shared-list");
  const tmuxSessionsEl = document.getElementById("tmux-sessions");

  // Manual drag order of the session list: an array of
  // session ids, persisted server-side (GET/POST /session-order) so it
  // survives reloads and other devices. Sessions not in it (new, or from
  // before this feature existed) fall back to the usual alive/ended sort --
  // see applyCustomOrder(). Kept alongside the last full sessions array
  // (own + shared, unfiltered by machine) so a drag on the filtered view can
  // be merged back into a full order without losing hidden sessions' spots.
  // (Declared here, where they change; read from the other files too.)
  let sessionOrder = [];
  let lastSessions = [];
  let dragState = null;
  // Archived sessions are display-only: hidden
  // from the main list, shown instead in #archived-list once the toggle
  // button is pressed. Recomputed on every refreshSessions(); archivedVisible
  // survives across refreshes (a manual toggle) but resets to closed on
  // reload, same as sessionMachine/currentMachine.
  let archivedVisible = false;
  let lastArchivedSessions = [];
  let sharedVisible = false;
  let lastSharedSessions = [];

  // Rows a browser without the needed passkey window gets back from
  // GET /sessions with label "🔒" and locked: true (aiza-backend's
  // redact_locked_sessions). This bar above it (not inside #sessions, whose
  // children the drag-reorder code counts) asks for the passkey by itself
  // once (autoAskPasskey, 2026-11-17) and keeps the button for a browser
  // that wants a tap first; a tap on a locked row asks first and then opens
  // the row with its real name (2026-10-09, at the user's request).
  const lockedListBarEl = document.createElement("div");
  lockedListBarEl.hidden = true;
  lockedListBarEl.className = "locked-bar";   // style.css
  const lockedListTextEl = document.createElement("span");
  lockedListTextEl.className = "locked-text";
  const lockedListBtnEl = document.createElement("button");
  lockedListBtnEl.type = "button";
  lockedListBtnEl.textContent = t("list.unlock_show");
  lockedListBtnEl.className = "locked-unlock";
  lockedListBarEl.append(lockedListTextEl, lockedListBtnEl);
  // Above the list and its folders, not under them (2026-11-03, the user:
  // with many sessions in a folder the bar was pushed out of sight).
  const listToolsEl = document.getElementById("tree-tools");
  listToolsEl.parentNode.insertBefore(lockedListBarEl, listToolsEl);
  let lockedListTier = "host";

  function lockedTierFor(list) {
    return list.some((s) => sessionKind(s).root) ? "root" : "host";
  }

  async function unlockAndRefresh(tier) {
    await ensureUnlocked(tier);
    return refreshSessions();
  }

  lockedListBtnEl.addEventListener("click", async () => {
    lockedListBtnEl.disabled = true;
    try {
      await unlockAndRefresh(lockedListTier);
    } catch (e) {
      ui.toast(e.message, { error: true });
    } finally {
      lockedListBtnEl.disabled = false;
    }
  });

  async function openLockedSession(s) {
    try {
      const all = await unlockAndRefresh(sessionKind(s).root ? "root" : "host");
      chatNow.open((all || []).find((x) => x.id === s.id && x.owner === s.owner) || s);
    } catch (e) {
      ui.toast(e.message, { error: true });
    }
  }

  // ---- Session folders (the deployment notes, 2026-11-04, user request) ----
  //
  // The list is a tree: folders (unlimited depth, "入れ子の段数は制限したく
  // ない") hold sessions and other folders. An extension may add built-in
  // ones (aizaExt folders; the server's own list has them first), and a
  // default folder for a session no folder was chosen for (aizaExt
  // folderOf). Stored per user as GET/POST /folders ({folders, assign}); a
  // session's place is assign[id] ("" = top), else that default, else the top.
  // A folder's 🗄 and stop cover everything under it; its grey dot resumes
  // what its last stop stopped (last_stopped). Rows and folders move by
  // dragging ⠿: onto the middle of a folder row puts the item in it,
  // between rows puts it where it was dropped.
  let folderDoc = { folders: [], assign: {} };
  let folderSaving = 0;
  let orderSaving = 0;
  // Bumped by every local change to the order or the folders, so a list
  // refresh that started before it does not put the old state back.
  let listEditSeq = 0;
  let lastVisibleSessions = [];
  let listLoaded = false;  // the first GET /sessions answered (no hint before it)
  const FOLDERS_OPEN_KEY = "aiza-folders-open";
  const openFolders = new Set();
  try { for (const id of JSON.parse(localStorage.getItem(FOLDERS_OPEN_KEY) || "[]")) openFolders.add(id); } catch (e) {}
  // A built-in folder may keep its open state under a key of its own too
  // (aizaExt folders, openKey): read when it registers.
  function readExtOpenKeys() {
    for (const f of window.aizaExt.folders()) {
      if (!f.openKey) continue;
      try { if (localStorage.getItem(f.openKey) === "1") openFolders.add(f.id); } catch (e) {}
    }
  }
  const openArchivedFolders = new Set();
  function saveOpenFolders() {
    try { localStorage.setItem(FOLDERS_OPEN_KEY, JSON.stringify([...openFolders])); } catch (e) {}
    for (const f of window.aizaExt.folders()) {
      if (!f.openKey) continue;
      try { localStorage.setItem(f.openKey, openFolders.has(f.id) ? "1" : "0"); } catch (e) {}
    }
  }
  function folderById(id) {
    return folderDoc.folders.find((f) => f.id === id) || null;
  }
  function folderOfSession(s) {
    const a = folderDoc.assign[s.id];
    if (a !== undefined) return a && folderById(a) ? a : null;
    const d = window.aizaExt.folderOf(s);
    return d && folderById(d) ? d : null;
  }
  function childFolders(parentId) {
    return folderDoc.folders.filter((f) => (f.parent || null) === parentId);
  }
  // The folder itself or any folder above it is archived.
  function folderHidden(id) {
    for (let f = id && folderById(id); f; f = f.parent && folderById(f.parent)) {
      if (f.archived) return true;
    }
    return false;
  }
  function folderAncestors(id) {
    const out = [];
    for (let f = id && folderById(id); f; f = f.parent && folderById(f.parent)) out.push(f.id);
    return out;
  }
  function folderSubtree(id) {
    const out = new Set([id]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const f of folderDoc.folders) {
        if (f.parent && out.has(f.parent) && !out.has(f.id)) { out.add(f.id); grew = true; }
      }
    }
    return out;
  }
  function sessionsInSubtree(id, list) {
    const ids = folderSubtree(id);
    return list.filter((s) => ids.has(folderOfSession(s)));
  }
  function openFolderPath(id) {
    const path = folderAncestors(id);
    if (path.every((x) => openFolders.has(x))) return;
    for (const x of path) openFolders.add(x);
    saveOpenFolders();
    renderSessionList();
  }
  // Sessions in the order the tree shows them, every folder open.
  function treeOrder(list) {
    const out = [];
    const walk = (pid) => {
      for (const f of childFolders(pid)) if (!f.archived) walk(f.id);
      for (const s of list) if (folderOfSession(s) === pid) out.push(s);
    };
    walk(null);
    return out;
  }
  // Sends only the change (POST /folders/ops), applied by the backend to
  // the tree as it is then: another tab's moves are not overwritten. The
  // change is already made here too, so the list shows it at once.
  async function saveFolders(ops) {
    listEditSeq++;
    folderSaving++;
    try {
      folderDoc = await api("/folders/ops", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ops }),
      });
    } catch (e) {
      ui.toast(t("list.could_not_save_folders_err", { err: e.message }), { error: true });
      folderDoc = await api("/folders").catch(() => folderDoc);
    } finally {
      folderSaving--;
    }
    renderSessionList();
  }
  function newFolderId() {
    return "f" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  }
  async function createFolder(parentId, given) {
    const name = (given !== undefined ? given : (await ui.ask(t("list.folder_name"), "")) || "").trim();
    if (!name) return;
    const f = { id: newFolderId(), name, parent: parentId, archived: false, last_stopped: [] };
    folderDoc.folders.push(f);
    if (parentId) { for (const x of folderAncestors(parentId)) openFolders.add(x); saveOpenFolders(); }
    await saveFolders([{ op: "put", folder: f }]);
  }
  async function renameFolder(f) {
    const name = ((await ui.ask(t("list.new_name"), f.name)) || "").trim();
    if (!name || name === f.name) return;
    f.name = name;
    await saveFolders([{ op: "put", folder: { id: f.id, name } }]);
  }
  // A folder's 作業フォルダ (the deployment notes): relative to ~/sandhome
  // for the sandbox, to $HOME for host-shell and to /root for root-shell;
  // a folder without one uses the nearest folder above's.
  async function setFolderWorkdir(f) {
    const raw = await ui.ask(t("list.working_folder_relative_sandhome_in"), f.workdir || "");
    if (raw === null) return;
    const workdir = raw.trim().replace(/^~\//, "").replace(/^\/+|\/+$/g, "");
    if (workdir.split("/").includes("..")) { ui.toast(t("list.not_allowed"), { error: true }); return; }
    f.workdir = workdir;
    await saveFolders([{ op: "put", folder: { id: f.id, workdir } }]);
  }
  function folderEffectiveWorkdir(id) {
    for (let f = id && folderById(id); f; f = f.parent && folderById(f.parent)) {
      if (f.workdir) return f.workdir;
    }
    return "";
  }
  // ＋ → このフォルダで新しいセッション: the bar above the list says where
  // it goes; 開始 sends the folder, and the backend starts it in the
  // folder's 作業フォルダ (made if missing) and files it there.
  let newSessionFolder = null;
  const nsbFolderEl = document.getElementById("nsb-folder");
  // For the start screen (form.js, the deployment notes 段3): its folder, and the
  // names already taken (its name suggestion).
  ui.start = Object.assign(ui.start || {}, {
    setFolder: (id) => setNewSessionFolder(id),
    names: () => lastSessions.filter((s) => !s.owner).map((s) => s.label),
  });
  function setNewSessionFolder(id) {
    newSessionFolder = id && folderById(id) ? id : null;
    nsbFolderEl.hidden = !newSessionFolder;
    nsbFolderEl.innerHTML = "";
    if (!newSessionFolder) return;
    const wd = folderEffectiveWorkdir(id);
    const span = document.createElement("span");
    span.textContent = "📁 " + folderById(id).name + (wd ? " · " + t("list.working_folder_dir", { dir: wd }) : "");
    const x = document.createElement("button");
    x.textContent = "✕";
    x.title = t("list.do_not_put_in_folder");
    x.addEventListener("click", () => setNewSessionFolder(null));
    nsbFolderEl.append(span, x);
  }
  async function deleteFolder(f) {
    const subs = childFolders(f.id).length;
    const inside = lastSessions.filter((s) => !s.owner && folderOfSession(s) === f.id).length;
    if (subs || inside) {
      ui.toast(t("list.name_not_empty_so_cannot", { name: f.name, f: subs, n: inside }), { error: true });
      return;
    }
    if (!(await ui.confirm(t("list.delete_folder_name", { name: f.name }), { danger: true }))) return;
    folderDoc.folders = folderDoc.folders.filter((x) => x.id !== f.id);
    openFolders.delete(f.id);
    saveOpenFolders();
    await saveFolders([{ op: "delete", id: f.id }]);
  }
  async function archiveFolder(f, archived) {
    f.archived = archived;
    await saveFolders([{ op: "put", folder: { id: f.id, archived } }]);
    if (archived) {
      archiveUndoStack.push({ id: f.id, label: f.name, folder: true });
      if (archiveUndoStack.length > 50) archiveUndoStack.shift();
      showUndoToast(t("list.archived_folder_label", { label: f.name }), true);
    }
  }
  // Stop: every running own session under it (this machine's, not archived).
  async function stopFolder(f) {
    const list = sessionsInSubtree(f.id, lastVisibleSessions.filter((s) => !s.owner && !s.archived && s.alive));
    if (!list.length) return;
    if (!(await ui.confirm(t("list.stop_n_sessions_in_name", { name: f.name, n: list.length }), { danger: true }))) return;
    const stopped = [];
    const failed = [];
    await runLimited(list, 3, async (s) => {
      try {
        await withUnlockRetry(() => api(sessionPath(s.id, "/stop", null), { method: "POST" }));
        stopped.push(s.id);
      } catch (e) {
        failed.push(`${s.label}: ${e.message}`);
      }
    });
    f.last_stopped = stopped;
    await saveFolders([{ op: "put", folder: { id: f.id, last_stopped: stopped } }]);
    if (failed.length) ui.toast(t("list.could_not_stop") + "\n" + failed.join("\n"), { error: true });
    await refreshSessions();
  }
  function folderResumable(f) {
    const ids = new Set(f.last_stopped || []);
    return lastVisibleSessions.filter((s) => ids.has(s.id) && !s.owner && !s.alive);
  }
  // Resume: only what this folder's last stop stopped, two at a time.
  async function resumeFolder(f) {
    let list = folderResumable(f);
    if (!list.length) return;
    if (!(await ui.confirm(t("list.resume_n_sessions_last_stop", { name: f.name, n: list.length })))) return;
    if (list.some((s) => s.locked)) {
      try {
        await unlockAndRefresh(lockedTierFor(list.filter((s) => s.locked)));
      } catch (e) {
        ui.toast(e.message, { error: true });
        return;
      }
      list = folderResumable(f);
    }
    const failed = [];
    await runLimited(list, 2, async (s) => {
      if (!canResumeEnded(s)) { failed.push(`${s.label}: ${t("list.kind_cannot_resumed")}`); return; }
      try {
        await withUnlockRetry(() => api("/sessions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(resumeBody(s)),
        }));
      } catch (e) {
        failed.push(`${s.label}: ${e.message}`);
      }
    });
    f.last_stopped = [];
    await saveFolders([{ op: "put", folder: { id: f.id, last_stopped: [] } }]);
    if (failed.length) ui.toast(t("list.could_not_resume") + "\n" + failed.join("\n"), { error: true });
    await refreshSessions();
  }
  async function runLimited(items, n, fn) {
    const queue = [...items];
    await Promise.all(Array.from({ length: Math.min(n, queue.length) }, async () => {
      while (queue.length) await fn(queue.shift());
    }));
  }

  // A folder's rows a little to the right, and the open folder with what
  // it holds in a frame (2026-11-27, the user: フォルダもネストにして
  // インデントを今の半分にして -- as the work tree's frames): the rows stay
  // one flat list (the drag counts on it), so the frames are drawn over it.
  const INDENT_REM = 0.45;
  function indentRow(row, depth) {
    row.dataset.depth = depth;
    if (depth) row.style.marginLeft = `${Math.min(depth, 8) * INDENT_REM}rem`;
  }
  function drawFolderFrames(listEl) {
    let layer = listEl._frames;
    if (!layer) {
      layer = listEl._frames = document.createElement("div");
      layer.className = "folder-frames";
      listEl.after(layer);
      const host = listEl.parentElement;
      if (getComputedStyle(host).position === "static") host.style.position = "relative";
      let queued = false;
      new ResizeObserver(() => {
        if (queued) return;
        queued = true;
        requestAnimationFrame(() => { queued = false; drawFolderFrames(listEl); });
      }).observe(listEl);
    }
    layer.textContent = "";
    if (listEl.hidden) return;
    const host = listEl.parentElement, hb = host.getBoundingClientRect();
    const dx = host.scrollLeft - hb.left - host.clientLeft, dy = host.scrollTop - hb.top - host.clientTop;
    const rows = Array.from(listEl.children);
    rows.forEach((r, i) => {
      if (!r.classList.contains("folder-row") || r.dataset.open !== "1") return;
      const d = +r.dataset.depth || 0;
      let last = null;
      for (let j = i + 1; j < rows.length; j++) {
        const x = rows[j];
        if (x.dataset.depth === undefined || +x.dataset.depth <= d) break;
        last = x;
      }
      if (!last) return;
      const a = r.getBoundingClientRect(), b = last.getBoundingClientRect();
      const f = document.createElement("div");
      // The selected folder's frame is lit (2026-11-27, the user: 枠全体にしたほうがわかりやすい).
      f.className = "folder-frame" + (sel && sel.kind === "folder" && sel.id === r.dataset.folderId ? " sel" : "");
      f.style.cssText = `left:${a.left + dx}px;top:${a.top + dy}px;width:${a.width}px;height:${b.bottom + 4 - a.top}px`;
      layer.appendChild(f);
    });
  }
  // A folder's icon with its ▸/▾ small at its lower right (2026-11-27, the
  // user: フォルダや木の開閉の▶をフォルダや木のアイコンの右下に小さく出す).
  // A built-in folder's label starts with its own icon.
  function folderLabelHtml(open, label, icon) {
    if (!icon) {
      const m = /^(\p{Extended_Pictographic}(?:\uFE0F|\u200D\p{Extended_Pictographic})*)\s*/u.exec(label);
      icon = m ? m[1] : "📁";
      if (m) label = label.slice(m[0].length);
    }
    return `<span class="ficon">${escapeHtml(icon)}<span class="ftog">${open ? "▼" : "▶"}</span></span> ${escapeHtml(label)}`;
  }
  function makeFolderRow(f, depth, list) {
    const inside = sessionsInSubtree(f.id, list);
    const alive = inside.filter((s) => s.alive).length;
    const waiting = inside.filter((s) => s.waiting).length;
    const open = openFolders.has(f.id);
    // A built-in folder (aizaExt folders): its own label, a drag handle only
    // if it says so, and only ＋ for a folder inside it.
    const builtin = window.aizaExt.folder(f.id);
    const row = document.createElement("div");
    row.className = "session-row folder-row";
    row.dataset.folderId = f.id;
    if (open) row.dataset.open = "1";
    const selected = !!(sel && sel.kind === "folder" && sel.id === f.id);
    if (selected) row.classList.add("sel");
    if (f.workdir) row.title = t("list.working_folder_dir", { dir: f.workdir });
    row.innerHTML = `
      <div class="folder-main">
        ${builtin && !builtin.draggable ? "" : `<span class="drag-handle" title="${t("common.drag_move")}">⠿</span>`}
        <span class="dot ${alive ? "alive" : "stopped"}"></span>
        <span class="label">${builtin ? folderLabelHtml(open, builtin.label || f.name) : folderLabelHtml(open, f.name, "📁")}</span>
        <span class="meta">${inside.length}</span>${waiting ? `<span class="waiting-badge">${t("common.waiting")}${waiting}</span>` : ""}${(f.shared_with || []).length || (f.shared_read || []).length ? `<span class="meta" title="${t("list.shared_folder")}">🧑‍🤝‍🧑</span>` : ""}${f.workdir ? `<span class="workdir">~/${escapeHtml(f.workdir)}</span>` : ""}
      </div>`;
    indentRow(row, depth);
    // A tap selects it (the bar above works on it); a tap on the selected
    // one, or on its ▶/▼, opens and closes it (2026-11-27, the deployment notes).
    row.addEventListener("click", (e) => {
      if (!selected && !e.target.closest(".ficon")) { setSel({ kind: "folder", id: f.id }); return; }
      if (open) openFolders.delete(f.id); else openFolders.add(f.id);
      saveOpenFolders();
      renderSessionList();
    });
    const handle = row.querySelector(".drag-handle");
    if (handle) wireSessionDrag(handle, row);
    const dot = row.querySelector(".dot");
    if (alive) {
      dot.classList.add("stoppable");
      dot.title = t("list.tap_stop_every_session_in");
      dot.addEventListener("click", (e) => { e.stopPropagation(); stopFolder(f); });
    } else if (folderResumable(f).length) {
      dot.classList.add("resumable");
      dot.title = t("list.tap_resume_what_last_stop");
      dot.addEventListener("click", (e) => { e.stopPropagation(); resumeFolder(f); });
    }
    // A session, a folder or a tree in it: select it and use the top row's
    // ＋ (2026-11-27, the user: 枝やフォルダの…から4つのボタンでできる機能を外して).
    // Its own actions in one ⋯, as a session's (2026-11-27, the user:
    // フォルダだけボタンが直接置かれてるのを…に変えてください).
    if (!builtin) {
      const acts = document.createElement("div");
      acts.className = "row-acts";
      acts.hidden = true;
      const item = (cls, icon, label, title, fn) => {
        const b = document.createElement("button");
        b.className = cls;
        if (icon === "dir") { const i = document.createElement("i"); i.className = "dir-icon"; b.appendChild(i); } else b.textContent = icon;
        if (title) b.title = title;
        const l = document.createElement("span");
        l.textContent = label;
        b.appendChild(l);
        b.addEventListener("click", (e) => { e.stopPropagation(); acts.hidden = true; fn(); });
        acts.appendChild(b);
      };
      item("edit-btn", "✏️", t("common.rename"), "", () => renameFolder(f));
      item("workdir-btn", "dir", t("list.set_working_folder"), "", () => setFolderWorkdir(f));
      item("share-btn", "🧑‍🤝‍🧑", t("list.share_folder"), "", () => openFolderShare(f.id));
      item("archive-btn", "🗄", t("list.archive"), t("list.archive_folder_everything_in"), () => archiveFolder(f, true));
      if (!childFolders(f.id).length && !lastSessions.some((s) => !s.owner && folderOfSession(s) === f.id)) {
        item("delete-btn", "🗑", t("common.delete"), t("list.delete_empty_folder"), () => deleteFolder(f));
      }
      const more = document.createElement("button");
      more.className = "row-more";
      more.textContent = "⋯";
      more.title = t("list.row_actions");
      more.setAttribute("aria-haspopup", "menu");
      more.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = acts.hidden;
        for (const m of document.querySelectorAll(".row-acts")) m.hidden = true;
        acts.hidden = !open;
      });
      row.append(more, acts);
    }
    return row;
  }

  // ---- The selected row: the toolbar's ＋ work on it (2026-11-27,
  // the deployment notes, 選んだものに働く固定の道具の段) ----
  // One folder or one tree item at a time ({kind: "folder"|"node", id}),
  // its row lit. ＋ 🤖 AI starts in it / on it, ＋ 📁 makes a folder in it,
  // ＋ 🌳 a tree in it or a branch under it; their titles say where. No bar
  // naming it (2026-11-27, the user: 選択すると４つのボタンの下に出ますが
  // 不要です。+で作るようにしてください); its actions stay in its ⋯.
  let sel = null;
  const newFolderBtnEl = document.getElementById("new-folder-btn");
  const plusBtns = ["start-btn", "new-folder-btn", "new-tree-btn"].map((id) => document.getElementById(id));
  const plusTitles = plusBtns.map((b) => b.getAttribute("title"));
  function setSel(v) {
    sel = v;
    if (ui.tool && ["child", "tree", "folder"].includes(ui.tool.current())) ui.tool.close();
    renderSessionList();
  }
  ui.sel = {
    get: () => sel,
    is: (kind, id) => !!sel && sel.kind === kind && sel.id === id,
    set: (v) => setSel(v),
    // What ＋ 🤖 AI opens the start screen with.
    startCtx: () => {
      if (sel && sel.kind === "folder") return { folder: sel.id };
      if (sel && sel.kind === "node") return ui.trees.selStartCtx(sel.id) || {};
      return {};
    },
  };
  function selName() {
    if (!sel) return "";
    if (sel.kind === "node") return (ui.trees.isRoot(sel.id) ? "🌳 " : "") + ui.trees.title(sel.id);
    const f = folderById(sel.id), b = window.aizaExt.folder(sel.id);
    return b ? b.label || f.name : "📁 " + f.name;
  }
  function renderSelTools() {
    // Gone (deleted, archived, out of the tree): nothing selected.
    if (sel && sel.kind === "folder" && (!folderById(sel.id) || folderById(sel.id).archived)) sel = null;
    if (sel && sel.kind === "node" && ui.trees.ready() && !ui.trees.node(sel.id)) sel = null;
    const name = selName();
    plusBtns.forEach((b, i) => {
      const title = sel ? t("list.make_in", { name }) : plusTitles[i];
      if (title) b.title = title; else b.removeAttribute("title");
    });
    newFolderBtnEl.disabled = !!sel && sel.kind === "node";
    if (newFolderBtnEl.disabled) newFolderBtnEl.title = t("list.no_folder_under_item");
  }

  // 仕事's tree (the deployment notes 段4): the work tree's roots in their
  // folders (tree.js ui.trees), each folder's in a box kept across redraws
  // so the tree's own state (an open ⋯) lives on.
  const treeBoxes = new Map();
  function treeBox(key, roots, depth) {
    let box = treeBoxes.get(key);
    if (!box) { box = document.createElement("div"); box.className = "wtree"; treeBoxes.set(key, box); }
    box.style.setProperty("--wd", depth);
    box.dataset.depth = depth;
    ui.trees.mount(box, roots);
    return box;
  }
  // ---- 仕事's tree: what to show (the deployment notes 段4, the user's mock) ----
  // 全部 / 🙋 あなたの番 / ⏳ 3日止まり: the work tree's own filter (its
  // items, tree.js) and the same for the sessions; and the stopped sessions,
  // hidden unless 止まったセッションも (kept in this browser).
  const treeFilterEl = document.getElementById("tree-filter");
  const showStoppedEl = document.getElementById("show-stopped");
  try { showStoppedEl.checked = localStorage.getItem("aiza-show-stopped") === "1"; } catch (e) {}
  showStoppedEl.addEventListener("change", () => {
    try { localStorage.setItem("aiza-show-stopped", showStoppedEl.checked ? "1" : ""); } catch (e) {}
    renderSessionList();
  });
  function syncTreeFilter() {
    for (const b of treeFilterEl.querySelectorAll("[data-f]")) b.classList.toggle("on", b.dataset.f === ui.trees.filter());
  }
  treeFilterEl.addEventListener("click", (e) => {
    const b = e.target.closest("[data-f]");
    if (!b) return;
    ui.trees.setFilter(b.dataset.f);
    syncTreeFilter();
    renderSessionList();
  });
  syncTreeFilter();
  const STALE_S = 3 * 86400;
  function sessionShown(s) {
    if (!showStoppedEl.checked && !s.alive && !s.waiting) return false;
    const f = ui.trees.filter();
    if (f === "you") return ["you", "due"].includes(taskGroup(s));
    if (f === "stale") return !!taskGroup(s) && s.task && s.task.ts && Date.now() / 1000 - s.task.ts >= STALE_S;
    return true;
  }
  // 🔍 探す: the chat search (search.js), from the toolbar's own box.
  const treeSearchEl = document.getElementById("tree-search");
  treeSearchEl.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing) return;
    e.preventDefault();
    const panel = document.getElementById("search-panel");
    document.getElementById("search-input").value = treeSearchEl.value;
    if (panel.hidden) document.getElementById("search-toggle-btn").click();
    document.getElementById("search-input").value = treeSearchEl.value;
    document.getElementById("search-form").requestSubmit();
  });
  // The top row's forms (2026-11-27, the user: ４つのボタンを押したときの
  // 追加のフォームの出方が違います。木と検索のやり方にあわせてほしい): ＋ 🤖 AI,
  // ＋ 📁, ＋ 🌳 and ↕ each open their form in #tool-panel, right under the
  // buttons (＋ 🌳 on a selected branch: its ＋ 子を足す, #child-slot).
  // One at a time; the same button again, or Esc, closes it.
  const toolPanelEl = document.getElementById("tool-panel");
  const newTreeRowEl = document.getElementById("new-tree-row");
  const newTreeTitleEl = document.getElementById("new-tree-title");
  const newFolderRowEl = document.getElementById("new-folder-row");
  const newFolderNameEl = document.getElementById("new-folder-name");
  const arrangeRowEl = document.getElementById("arrange-row");
  const childSlotEl = document.getElementById("child-slot");
  let toolOpen = null;        // "tree" | "folder" | "arrange" | "start" | "child"
  const toolRows = { tree: newTreeRowEl, folder: newFolderRowEl, arrange: arrangeRowEl };
  const toolBtnOf = { tree: "new-tree-btn", child: "new-tree-btn", folder: "new-folder-btn", arrange: "list-arrange-btn", start: "start-btn" };
  const markTool = (name, on) => { const b = name && document.getElementById(toolBtnOf[name]); if (b) b.classList.toggle("on", on); };
  function closeTool() {
    const was = toolOpen;
    if (!was) return;
    toolOpen = null;
    markTool(was, false);
    for (const el of Object.values(toolRows)) el.hidden = true;
    if (was === "child") { childSlotEl.hidden = true; childSlotEl.textContent = ""; }
    if (was === "arrange") setArrange(false);
    if (was === "start") ui.start.close(false);
    toolPanelEl.hidden = true;
  }
  function openTool(name) {
    if (toolOpen === name) { closeTool(); return; }   // the same button again
    closeTool();
    toolOpen = name;
    markTool(name, true);
    toolPanelEl.hidden = false;
    if (name === "child") {     // ＋ 子を足す for the selected branch
      childSlotEl.textContent = "";
      childSlotEl.hidden = false;
      ui.trees.childPanel(sel.id, childSlotEl, () => { if (toolOpen === "child") closeTool(); });
      const field = childSlotEl.querySelector("input:not([type=radio])");
      if (field) field.focus();
      return;
    }
    if (name === "start") { ui.start.open(ui.sel.startCtx(), { inline: document.getElementById("start-slot") }); return; }
    toolRows[name].hidden = false;
    if (name === "arrange") { setArrange(true); return; }
    const field = name === "tree" ? newTreeTitleEl : newFolderNameEl;
    const inFolder = sel && sel.kind === "folder" ? (folderById(sel.id) || {}).name || "" : null;
    if (name === "tree") newTreeTitleEl.placeholder = inFolder !== null ? t("list.new_tree_in_folder", { name: inFolder }) : t("tree.title_job");
    if (name === "folder") newFolderNameEl.placeholder = inFolder !== null ? t("list.new_folder_in_folder", { name: inFolder }) : t("list.new_folder_name");
    field.focus();
  }
  ui.tool = {
    open: openTool,
    close: closeTool,
    current: () => toolOpen,
    // The start form closed by itself (✕, 開始, Back).
    startClosed: () => { if (toolOpen === "start") { toolOpen = null; markTool("start", false); toolPanelEl.hidden = true; } },
  };
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || e.isComposing || !toolOpen) return;
    e.preventDefault();
    closeTool();
  });
  // ＋ 🌳: a new tree (a work-tree root; in the selected folder), or a branch under the selected item.
  document.getElementById("new-tree-btn").addEventListener("click", () => openTool(sel && sel.kind === "node" ? "child" : "tree"));
  const addTree = () => {
    const v = newTreeTitleEl.value.trim();
    if (!v) return;
    newTreeTitleEl.value = "";
    const folder = sel && sel.kind === "folder" ? sel.id : null;
    closeTool();
    if (folder) { openFolders.add(folder); saveOpenFolders(); }
    ui.trees.add(v, folder);
  };
  document.getElementById("new-tree-add").addEventListener("click", addTree);
  newTreeTitleEl.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); addTree(); } });
  // A tree's folder opened (🌳 from a session, the deployment notes 段5), with the folders above it.
  ui.trees.reveal = (fid) => {
    for (let f = fid && folderById(fid), i = 0; f && i < 100; f = f.parent && folderById(f.parent), i++) openFolders.add(f.id);
    saveOpenFolders();
    renderSessionList();
  };
  // A tree's item's session, as the list draws it (tree.js TreeSessionRow).
  ui.trees.sessionRow = (sid) => {
    const s = lastSessions.find((x) => x.id === sid && !x.owner);
    return s && !s.archived && sessionShown(s) ? makeSessionRow(s) : null;
  };
  ui.trees.sessionSig = (sid) => {
    const s = lastSessions.find((x) => x.id === sid && !x.owner);
    return s ? JSON.stringify([s.label, s.alive, s.waiting, s.archived, s.task, s.link, s.preset, sessionShown(s), linkArmedSessionId === s.id]) : "";
  };
  // The tree came (or came again): its roots' places may have changed.
  ui.trees.loaded = () => renderSessionList();
  function renderSessionList() {
    if (dragState) return;
    renderSelTools();
    const visible = lastVisibleSessions;
    ui.trees.load();
    // A session an item of a tree holds is in that tree, under the item
    // (tree.js TreeSessionRow), not again in its folder (2026-11-26, the user).
    const held = ui.trees.linked();
    const main = visible.filter((s) => !s.archived && !s.owner && !folderHidden(folderOfSession(s)) && sessionShown(s) && !held.has(s.id));
    // What the list shows, in order; put in place at the end without taking
    // the trees' boxes out (an input typed in a tree's ⋯ keeps its focus).
    const nodes = [];
    const put = (...x) => nodes.push(...x);
    const walk = (pid, depth, path) => {
      for (const f of childFolders(pid)) {
        if (f.archived) continue;
        // A built-in folder that says so is shown only once it has
        // something in it (aizaExt folders, hideWhenEmpty).
        const spec = window.aizaExt.folder(f.id);
        if (spec && spec.hideWhenEmpty && !childFolders(f.id).length
            && !lastSessions.some((s) => !s.owner && folderOfSession(s) === f.id)) continue;
        const row = makeFolderRow(f, depth, main);
        row.dataset.path = path.join("/");
        put(row);
        if (openFolders.has(f.id)) walk(f.id, depth + 1, [...path, f.id]);
      }
      // The folder's trees, after its folders and before its sessions.
      const roots = pid ? ui.trees.rootsIn(pid, false) : [];
      if (roots.length) put(treeBox("f:" + pid, roots, depth));
      for (const s of main) {
        if (folderOfSession(s) !== pid) continue;
        const row = makeSessionRow(s);
        row.dataset.path = path.join("/");
        indentRow(row, depth);
        put(row);
      }
    };
    walk(null, 0, []);
    // The trees in no folder (each one's place is its own to arrange).
    const loose = ui.trees.rootsIn(null, false);
    if (loose.length) {
      const h = document.createElement("div");
      h.className = "list-section";
      h.textContent = t("list.trees_in_no_folder");
      put(h, treeBox("f:", loose, 0));
    }
    // A new account (no session of its own, no folder in sight): say how to
    // begin, instead of an empty list (2026-11-24, the user: 初めて使う人の
    // 画面を分かりやすく).
    if (listLoaded && !nodes.length && !lastSessions.some((s) => !s.owner)) {
      const hint = document.createElement("div");
      hint.className = "list-empty";
      hint.textContent = t("list.no_sessions_yet_choose_ai");
      put(hint);
    }
    for (const x of [...sessionsEl.childNodes]) if (!nodes.includes(x)) x.remove();
    let at = sessionsEl.firstChild;
    for (const x of nodes) {
      if (x === at) { at = at.nextSibling; continue; }
      sessionsEl.insertBefore(x, at);
    }
    drawFolderFrames(sessionsEl);
    // Archive: the same folder tree (fillArchivedFolders), with archived
    // sessions in no folder at its top level; those in a built-in folder
    // with an archive of its own (ownArchive) in that list.
    const archivedOwn = visible.filter((s) => s.archived && !s.owner && !folderHidden(folderOfSession(s)));
    extArchived.clear();
    for (const f of window.aizaExt.folders()) {
      if (f.ownArchive && folderById(f.id)) extArchived.set(f.id, archivedOwn.filter((s) => folderOfSession(s) === f.id));
    }
    lastArchivedSessions = archivedOwn.filter((s) => !extArchived.has(folderOfSession(s)));
    lastArchivedFolders = folderDoc.folders.filter((f) => f.archived && !folderHidden(f.parent));
    renderArchivedSection();
  }
  let lastArchivedFolders = [];
  // ＋ 📁: a folder (in the selected one), named in the panel's row.
  document.getElementById("new-folder-btn").addEventListener("click", () => openTool("folder"));
  const addFolder = () => {
    const v = newFolderNameEl.value.trim();
    if (!v) return;
    newFolderNameEl.value = "";
    const parent = sel && sel.kind === "folder" ? sel.id : null;
    closeTool();
    createFolder(parent, v);
  };
  document.getElementById("new-folder-add").addEventListener("click", addFolder);
  newFolderNameEl.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); addFolder(); } });
  // ↕ The list's order is locked by default (2026-11-23, the user: 誤って
  // ドラッグしてセッションを動かしてしまう。普段はロックしておいて、解除して
  // 動かす): the ⠿ handles show, and drag, only while this is on. Not kept:
  // every load starts locked.
  function updateSpeakBgBtn() {
    if (audioMenuEl) audioMenuEl.refresh();
  }
  const listArrangeBtnEl = document.getElementById("list-arrange-btn");
  listArrangeBtnEl.textContent = "↕";
  listArrangeBtnEl.title = t("list.show_drag_sessions_folders_into");
  function setArrange(on) {
    document.body.classList.toggle("list-arrange", on);
    listArrangeBtnEl.classList.toggle("on", on);
    ui.trees.setArrange(on);   // the trees in the folders too (仕事's tree, the deployment notes 段4)
  }
  // On while its row (what to do, 終わる) is open in the panel.
  listArrangeBtnEl.addEventListener("click", () => openTool("arrange"));
  document.getElementById("arrange-done").addEventListener("click", () => closeTool());

  // The archive as a tree (the deployment notes; 2026-11-04, at the user's
  // request: a session archived out of a folder goes "into the same folder
  // structure inside the archive"). Nothing is stored for this: an archived
  // session keeps its folder, so the archive shows, under the same folders,
  //  - every archived session, and
  //  - every archived folder with all it holds (📤 brings it back).
  // A folder appears only when something archived is under it; a folder that
  // is not itself archived has no 📤 (it is only the way to its contents).
  function fillArchivedFolders(listEl) {
    const all = lastVisibleSessions.filter((s) => !s.owner);
    // What a folder shows directly: everything in an archived folder, only
    // the archived sessions in one that is not.
    const shownIn = (f) => all.filter((s) => folderOfSession(s) === f.id && (s.archived || folderHidden(f.id)));
    const count = new Map();
    const countOf = (f) => {
      if (count.has(f.id)) return count.get(f.id);
      let n = shownIn(f).length;
      for (const sub of childFolders(f.id)) n += countOf(sub);
      count.set(f.id, n);
      return n;
    };
    const anyArchived = (f) => folderHidden(f.id) || childFolders(f.id).some(anyArchived);
    const walk = (pid, depth) => {
      for (const f of childFolders(pid)) {
        if (extArchived.has(f.id)) continue; // it has its own archive list
        const n = countOf(f);
        if (!n && !anyArchived(f)) continue;
        const open = openArchivedFolders.has(f.id);
        const row = document.createElement("div");
        row.className = "session-row folder-row";
        row.dataset.folderId = f.id;
        if (open) row.dataset.open = "1";
        row.innerHTML = `
        <div class="folder-main">
          <span class="label">${folderLabelHtml(open, f.name, "📁")}</span>
          <span class="meta">${n}</span>
        </div>`;
        indentRow(row, depth);
        row.addEventListener("click", () => {
          if (open) openArchivedFolders.delete(f.id); else openArchivedFolders.add(f.id);
          renderArchivedSection();
        });
        if (f.archived && !folderHidden(f.parent)) {
          const btn = document.createElement("button");
          btn.className = "archive-btn";
          btn.textContent = "📤";
          btn.title = t("list.restore_folder_everything_in");
          btn.addEventListener("click", (e) => { e.stopPropagation(); archiveFolder(f, false); });
          row.appendChild(btn);
        }
        listEl.appendChild(row);
        if (!open) continue;
        walk(f.id, depth + 1);
        const sub = document.createElement("div");
        fillArchivedList(sub, shownIn(f));
        for (const r of [...sub.children]) { indentRow(r, depth + 1); listEl.appendChild(r); }
      }
    };
    walk(null, 0);
  }

  // The machine a row runs on, when not this host (the list holds every
  // machine's since the deployment notes 段4).
  function machinePrefix(s) {
    const m = sessionMachine(s);
    return m && m !== "local" ? `🖥 ${escapeHtml(m)} &middot; ` : "";
  }
  function makeSessionRow(s) {
    const row = document.createElement("div");
    row.className = "session-row";
    row.dataset.sessionId = s.id;
    // s.owner is only ever present on a /shared-with-me
    // entry -- shown as a badge so a shared session is never mistaken for
    // one's own, since it can be co-worked (messages/keys/stop) but not
    // renamed/deleted/archived from here (owner-only, see aiza-backend).
    const ownerBadge = s.owner ? ` &middot; ${t("common.shared_owner", { owner: escapeHtml(s.owner) })}` : "";
    row.innerHTML = `
      <div>
        <span class="drag-handle" title="${t("list.drag_reorder")}">⠿</span>
        <span class="dot ${s.alive ? "alive" : "stopped"}"></span>
        <span class="label">${typeIcon(s)}${screenBadge(s)}${escapeHtml(s.label)}${waitingBadge(s)}</span>
        <div class="meta">${machinePrefix(s)}${cwdPrefix(s)}${fmtTime(s.created_ts)}${ownerBadge}${issueSuffix(s)}${linkSuffix(s)}</div>
      </div>`;
    // While choosing the other side of a link (the banner is up), a tap on
    // one's own session adds it to the link rather than opening it, the same
    // as its 🔗 (2026-11-27, the user: リンク先を選ぶとき、セッションをタップ
    // したら開いてしまいました。リンクに加えるようにしてください).
    // The armed one itself still opens (backing out is the banner's キャンセル).
    row.addEventListener("click", () => {
      if (linkArmedSessionId !== null && linkArmedSessionId !== s.id && !s.owner) { onLinkButtonTapped(s); return; }
      s.locked ? openLockedSession(s) : chatNow.open(s);
    });
    wireSessionDrag(row.querySelector(".drag-handle"), row);
    // Tapping an ended session's grey dot offers to resume it (2026-10-09,
    // user request: "灰色のスイッチを押したら、再開するか確認して、OKなら再開") --
    // instead of a separate ↻ button. Only one's own, resumable sessions
    // (a locked row carries no conversation id, so never qualifies).
    if (!s.alive && !s.owner && canResumeEnded(s)) {
      const dot = row.querySelector(".dot");
      dot.classList.add("resumable");
      dot.title = t("common.tap_resume");
      dot.addEventListener("click", (e) => {
        e.stopPropagation(); // don't also open the ended session
        resumeEndedSession(s);
      });
    } else if (s.alive && !s.owner && !s.locked) {
      // ...and a running one's green dot offers to stop it, the same as
      // the chat header's dot.
      const dot = row.querySelector(".dot");
      dot.classList.add("stoppable");
      dot.title = t("common.tap_stop");
      dot.addEventListener("click", (e) => {
        e.stopPropagation();
        stopSessionConfirmed(s.id, null, false);
      });
    }

    if (!s.owner) {
      const editBtn = document.createElement("button");
      editBtn.className = "edit-btn";
      editBtn.textContent = "✏️";
      editBtn.title = t("common.rename");
      editBtn.addEventListener("click", (e) => {
        e.stopPropagation(); // don't also open the session
        renameSession(s);
      });
      row.appendChild(editBtn);

      const linkBtn = document.createElement("button");
      linkBtn.className = "link-btn" + (linkArmedSessionId === s.id ? " armed" : "");
      linkBtn.textContent = "🔗";
      linkBtn.title = s.link ? t("list.linked_label_tap_unlink", { label: s.link.partner_label }) : t("list.link_another_session");
      linkBtn.addEventListener("click", (e) => {
        e.stopPropagation(); // don't also open the session
        onLinkButtonTapped(s);
      });
      row.appendChild(linkBtn);

      const archiveBtn = document.createElement("button");
      archiveBtn.className = "archive-btn";
      archiveBtn.textContent = "🗄";
      archiveBtn.title = t("list.archive");
      archiveBtn.addEventListener("click", (e) => {
        e.stopPropagation(); // don't also open the session
        archiveSession(s);
      });
      row.appendChild(archiveBtn);

      const delBtn = document.createElement("button");
      delBtn.className = "delete-btn";
      delBtn.textContent = "🗑";
      delBtn.addEventListener("click", (e) => {
        e.stopPropagation(); // don't also open the session
        deleteSession(s);
      });
      row.appendChild(delBtn);
      // One ⋯ for them (the deployment notes 段4, the user's mock: rows easier to
      // tap): the four open as a small menu of their own under it.
      const acts = document.createElement("div");
      acts.className = "row-acts";
      acts.hidden = true;
      for (const [b, label] of [[editBtn, t("common.rename")], [linkBtn, linkBtn.title], [archiveBtn, t("list.archive")], [delBtn, t("common.delete")]]) {
        const l = document.createElement("span");
        l.textContent = label;
        b.appendChild(l);
        acts.appendChild(b);
      }
      const more = document.createElement("button");
      more.className = "row-more";
      more.textContent = "⋯";
      more.title = t("list.row_actions");
      more.setAttribute("aria-haspopup", "menu");
      more.addEventListener("click", (e) => {
        e.stopPropagation();
        const open = acts.hidden;
        for (const m of document.querySelectorAll(".row-acts")) m.hidden = true;
        acts.hidden = !open;
      });
      acts.addEventListener("click", () => { acts.hidden = true; });
      row.append(more, acts);
    }

    return row;
  }
  // A ⋯ menu of a row closes with a tap anywhere else.
  document.addEventListener("click", (e) => {
    if (e.target.closest && e.target.closest(".row-more, .row-acts")) return;
    for (const m of document.querySelectorAll(".row-acts:not([hidden])")) m.hidden = true;
  });

  // The periodic refreshes (the list every 20 s, やること every 30 s) ask
  // for the sessions without the archived ones (2026-11-10, the deployment notes:
  // they were ~80% of the list's bytes) and reuse the archived ones of the
  // last full answer. Every other refresh -- after archiving, unarchiving,
  // opening, any action -- is a full one, and so is a periodic one when the
  // full copy is older than ARCHIVED_REUSE_MS.
  const ARCHIVED_REUSE_MS = 5 * 60 * 1000;
  let archivedCopy = null;
  let archivedCopyAt = 0;
  // A light refresh while another refresh is still on its way rides on that
  // one instead of asking again (2026-11-10, the deployment notes: going from a
  // session to やること asked for the whole list three times in 4 s). A full
  // one -- after an action, whose result it must show -- always asks anew.
  let refreshInFlight = null;
  function refreshSessions(opts) {
    if (opts && opts.light && refreshInFlight) return refreshInFlight;
    const p = refreshSessionsNow(opts);
    refreshInFlight = p;
    const clear = () => { if (refreshInFlight === p) refreshInFlight = null; };
    p.then(clear, clear);
    return p;
  }
  async function refreshSessionsNow(opts) {
    const editSeq = listEditSeq;
    const tseq = taskSeq;
    const light = !!(opts && opts.light) && archivedCopy !== null && Date.now() - archivedCopyAt < ARCHIVED_REUSE_MS;
    const fetchedAt = Date.now();
    const [{ sessions: fetched }, sharedSessions, order, folders] = await Promise.all([
      api(light ? "/sessions?archived=0" : "/sessions"),
      api("/shared-with-me").then((r) => r.sessions).catch(() => []),
      api("/session-order").then((r) => r.order).catch(() => sessionOrder),
      api("/folders").catch(() => folderDoc),
    ]);
    // A drag saved while this was in flight: what came back is older than
    // what this page already has (2026-11-04, the user: drags sometimes
    // "did not take" -- a list refresh racing the save put them back).
    if (editSeq === listEditSeq && !folderSaving && !orderSaving) {
      sessionOrder = order;
      folderDoc = folders;
    }
    // owner is absent (falsy) on every entry from /sessions (one's own) and
    // set to the owning username on every /shared-with-me entry -- the same
    // field openSession() reads into chatNow.owner.
    let ownSessions = fetched;
    if (light) {
      // Unarchived since (another tab, another device): it came back in
      // the answer, so its archived copy is dropped.
      const ids = new Set(fetched.map((x) => x.id));
      ownSessions = fetched.concat(archivedCopy.filter((x) => !ids.has(x.id)));
    } else {
      archivedCopy = fetched.filter((x) => x.archived);
      archivedCopyAt = fetchedAt;
    }
    const merged = [...ownSessions, ...sharedSessions];
    for (const x of merged) {
      const o = taskLocal.get(x.id);
      if (o && o.seq > tseq) x.task = o.task;
    }
    // Currently-running sessions first (2026-08-15, at the user's request);
    // among those, newest-started first, since "which one is still going"
    // matters more than when it started. Among the rest, most-recently-
    // *ended* first (aiza-backend's ended_ts, set wherever meta["stopped"]
    // becomes true) rather than created_ts -- a session started long ago
    // but finished a minute ago belongs near the top, not buried under
    // everything created more recently but finished earlier. ended_ts can be
    // missing on older sessions from before this field existed; created_ts
    // is the closest fallback. This is only the fallback baseline now --
    // applyCustomOrder() below layers the user's own drag order on top.
    merged.sort((a, b) => {
      if (a.alive !== b.alive) return a.alive ? -1 : 1;
      // sort_ts: a resumed session keeps the place of the one it replaced
      // (aiza-backend create_session, 2026-11-01).
      if (a.alive) return (b.sort_ts ?? b.created_ts) - (a.sort_ts ?? a.created_ts);
      return (b.ended_ts ?? b.created_ts) - (a.ended_ts ?? a.created_ts);
    });
    const sessions = applyCustomOrder(merged, sessionOrder);
    // Kept unfiltered so a drag's saveSessionOrder() can merge the visible
    // (machine-filtered) subset's new order back without losing the
    // relative position of sessions the filter is currently hiding.
    lastSessions = sessions;
    listLoaded = true;
    try { bgCheck(merged); } catch (e) {}  // the deployment notes
    try { updateTodoBadge(); } catch (e) {}  // the deployment notes (not yet set up on the very first list)
    // Filtered by the header's machine selector -- the full unfiltered list
    // is still returned below so init()'s hash-restore can find a session
    // that belongs to a machine other than the one currently selected.
    // Archived sessions are excluded from this
    // main list -- they still count towards the drag-order/machine-filter
    // bookkeeping via `sessions`/`lastSessions` above, only the rendering
    // splits them out into #archived-list below.
    // Every machine's (the deployment notes 段4, 2026-11-25: no machine filter
    // any more; a row says its machine, and the start screen's どこで picks one).
    const visible = sessions;
    const lockedRows = visible.filter((s) => s.locked && !s.archived);
    lockedListTier = lockedTierFor(lockedRows);
    lockedListTextEl.textContent =
      t("list.n_sessions_hidden_until_unlock", { n: lockedRows.length });
    lockedListBarEl.hidden = lockedRows.length === 0;
    lockedListBarEl.style.display = lockedRows.length === 0 ? "none" : "flex";
    if (lockedRows.length) {
      autoAskPasskey(`list:${lockedListTier}`, () => unlockAndRefresh(lockedListTier),
        lockedListBtnEl, () => !lockedListBarEl.hidden);
    }
    lastVisibleSessions = visible;
    // The main list as a folder tree, and the archive (the deployment notes).
    renderSessionList();
    // Not filtered by the machine selector: a shared log is found by its
    // owner, not by where it ran.
    lastSharedSessions = sessions.filter((s) => s.owner);
    renderSharedSection();
    updatePatrolBar();
    return sessions;
  }

  // Patrol (the deployment notes, 2026-11-04, at the user's request): ◀ ▶ under the
  // chat header go to the previous/next session without the list -- every
  // non-archived own session of the selected machine in list order (the
  // folder tree's order, open or not), folders ignored, wrapping around. The
  // filter narrows it to running or "確認待ち" ones. Locked rows are left
  // out (a passkey prompt would stop the round). Moving does not add browser
  // history: Back still returns to the list (see sessionHistoryPushed).
  const patrolBarEl = document.getElementById("patrol-bar");
  const patrolPosEl = document.getElementById("patrol-pos");
  const patrolFilterEl = document.getElementById("patrol-filter");
  const PATROL_FILTER_KEY = "aiza-patrol-filter";
  try { patrolFilterEl.value = localStorage.getItem(PATROL_FILTER_KEY) || "all"; } catch (e) {}
  if (!patrolFilterEl.value) patrolFilterEl.value = "all";
  function patrolBase() {
    const own = lastSessions.filter((s) => !s.archived && !s.owner && !s.locked
      && !folderHidden(folderOfSession(s)));
    return treeOrder(own);
  }
  function patrolPasses(s) {
    const f = patrolFilterEl.value;
    return f === "alive" ? !!s.alive : f === "waiting" ? !!s.waiting
      : f === "you" ? ["you", "due"].includes(taskGroup(s)) : true;
  }
  // A tap on the chat title opens and closes the bar (2026-11-04, user
  // request); kept in this browser, open at first.
  const PATROL_OPEN_KEY = "aiza-patrol-open";
  let patrolOpen = true;
  try { patrolOpen = localStorage.getItem(PATROL_OPEN_KEY) !== "0"; } catch (e) {}
  chatLabelEl.title = t("list.tap_show_or_hide_patrol");
  chatLabelEl.addEventListener("click", () => {
    if (!chatNow.id) return;
    patrolOpen = !patrolOpen;
    try { localStorage.setItem(PATROL_OPEN_KEY, patrolOpen ? "1" : "0"); } catch (e) {}
    updatePatrolBar();
  });
  const patrolFolderEl = document.getElementById("patrol-folder");
  function updatePatrolBar() {
    if (!patrolBarEl) return;
    const show = !!chatNow.id && !chatNow.owner && !isLoginPreset(chatNow.preset) && patrolOpen;
    patrolBarEl.hidden = !show;
    if (!show) return;
    const list = patrolBase().filter(patrolPasses);
    const i = list.findIndex((s) => s.id === chatNow.id);
    patrolPosEl.textContent = `${i >= 0 ? i + 1 : "–"}/${list.length}`;
    // Where it sits in the list's folders (2026-11-05, at the user's request).
    const cur = lastSessions.find((s) => s.id === chatNow.id && !s.owner);
    const fid = cur ? folderOfSession(cur) : null;
    const path = fid ? folderAncestors(fid).reverse().map((x) => folderById(x)?.name || "").filter(Boolean) : [];
    patrolFolderEl.textContent = "📁 " + (path.length ? path.join(" / ") : t("list.no_folder"));
  }
  function patrolTarget(dir) {
    const base = patrolBase();
    const n = base.length;
    let at = base.findIndex((s) => s.id === chatNow.id);
    if (at < 0) at = dir > 0 ? -1 : 0;
    for (let k = 1; k <= n; k++) {
      const s = base[(((at + dir * k) % n) + n) % n];
      if (s.id !== chatNow.id && patrolPasses(s)) return s;
    }
    return null;
  }
  async function patrolGo(dir) {
    if (!chatNow.id) return;
    const still = ui.ticket();
    await refreshSessions().catch(() => null);
    if (!still()) return;   // moved elsewhere meanwhile (the deployment notes)
    const s = patrolTarget(dir);
    if (s) { chatNow.open(s); return; }
    showUndoToast(t("list.no_other_session_matches"), false);
  }
  // 🗄 / 🗑 in the patrol bar (2026-11-05, at the user's request): act on the
  // session being shown, then go on to the next one (back to the list when
  // there is none). The undo toast/Ctrl+Z still covers the archive.
  async function patrolAct(kind) {
    const id = chatNow.id;
    if (!id || chatNow.owner) return;
    await refreshSessions().catch(() => null);
    const meta = lastSessions.find((s) => s.id === id && !s.owner);
    if (!meta) return;
    if (kind === "delete" && !(await ui.confirm(t("list.delete_conversation_log_label_cannot", { label: meta.label }), { danger: true }))) return;
    const next = patrolTarget(1);
    if (kind === "archive") {
      await archiveSession(meta);
    } else {
      const ok = await api(`/sessions/${id}/delete`, { method: "POST" }).then(() => true, (e) => {
        ui.toast(t("list.could_not_delete_err", { err: e.message }), { error: true });
        return false;
      });
      if (!ok) return;
      await refreshSessions().catch(() => null);
    }
    if (chatNow.id !== id) return; // moved elsewhere meanwhile
    const fresh = next && lastSessions.find((s) => s.id === next.id && !s.archived);
    if (fresh) chatNow.open(fresh);
    else chatNow.close();
  }
  // ✏️ in the patrol bar (2026-11-16, at the user's request): rename the
  // session being shown without going back to the list.
  document.getElementById("patrol-rename").addEventListener("click", async () => {
    const id = chatNow.id;
    if (!id || chatNow.owner) return;
    await refreshSessions().catch(() => null);
    const meta = lastSessions.find((s) => s.id === id && !s.owner);
    if (meta && chatNow.id === id) await renameSession(meta);
  });
  document.getElementById("patrol-archive").addEventListener("click", () => patrolAct("archive"));
  document.getElementById("patrol-delete").addEventListener("click", () => patrolAct("delete"));
  // The list keeps "確認待ち" current on its own while it is on screen (the
  // list otherwise refreshes only on navigation): every 20 s while visible.
  setInterval(() => {
    if (!chatNow.id && !dragState && document.visibilityState === "visible" && pageNow() === "list") {
      refreshSessions({ light: true }).catch(() => null);
    }
  }, 20000);
  document.getElementById("patrol-prev").addEventListener("click", () => patrolGo(-1));
  document.getElementById("patrol-next").addEventListener("click", () => patrolGo(1));
  patrolFilterEl.addEventListener("change", () => {
    try { localStorage.setItem(PATROL_FILTER_KEY, patrolFilterEl.value); } catch (e) {}
    updatePatrolBar();
  });

  // The bottom-of-list "🗄 アーカイブを開く" button and the (initially
  // hidden) archived-sessions panel it reveals.
  // Re-run on every refreshSessions() so counts/rows stay current; the open
  // state itself (archivedVisible) is only ever flipped by the button click
  // below.
  function renderArchivedSection() {
    archiveToggleBtn.textContent = archivedVisible
      ? t("list.close_archive")
      : t("list.open_archive_n", { n: lastArchivedSessions.length + lastArchivedFolders.length });
    archivedListEl.hidden = !archivedVisible;
    archivedListEl.innerHTML = "";
    if (archivedVisible) {
      // The finished trees (a root that is done), as the tree kept them at its end.
      // By folder: a finished tree can be dragged (↕) onto a folder row,
      // an archived one too, and is then shown under its name here.
      const done = ui.trees.doneRoots();
      if (done.length) {
        const h = document.createElement("div");
        h.className = "list-section";
        h.textContent = t("list.finished_trees_n", { n: done.length });
        archivedListEl.append(h);
        const by = new Map();
        for (const d of done) { if (!by.has(d.folder || "")) by.set(d.folder || "", []); by.get(d.folder || "").push(d.id); }
        for (const [fid, ids] of by) {
          if (fid) {
            const names = [];
            for (let f = folderById(fid), i = 0; f && i < 100; f = f.parent && folderById(f.parent), i++) names.unshift(f.name);
            const fh = document.createElement("div");
            fh.className = "list-section sub";
            fh.textContent = "📁 " + names.join(" / ");
            archivedListEl.append(fh);
          }
          archivedListEl.append(treeBox("done:" + fid, ids, 0));
        }
      }
      fillArchivedFolders(archivedListEl);
      // Top level: archived sessions that are in no folder.
      fillArchivedList(archivedListEl, lastArchivedSessions.filter((s) => !folderOfSession(s)));
    }
    drawFolderFrames(archivedListEl);
    // A built-in folder's own archive (aizaExt folders, ownArchive), with
    // its own open/close words.
    extArchivesEl.innerHTML = "";
    for (const [fid, list] of extArchived) {
      const spec = window.aizaExt.folder(fid) || {};
      const shown = extArchivedOpen.has(fid);
      if (!list.length && !shown) continue;
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "ext-archive-toggle-btn";
      toggle.textContent = shown
        ? t(spec.archiveClose || "list.close_archive")
        : t(spec.archiveOpen || "list.open_archive_n", { n: list.length });
      toggle.addEventListener("click", () => {
        if (shown) extArchivedOpen.delete(fid); else extArchivedOpen.add(fid);
        renderArchivedSection();
      });
      extArchivesEl.appendChild(toggle);
      if (!shown) continue;
      const listEl = document.createElement("div");
      listEl.className = "ext-archived-list";
      fillArchivedList(listEl, list);
      extArchivesEl.appendChild(listEl);
    }
  }

  function fillArchivedList(listEl, list) {
    for (const s of list) {
      const row = document.createElement("div");
      row.className = "session-row";
      row.dataset.sessionId = s.id;
      const ownerBadge = s.owner ? ` &middot; ${t("common.shared_owner", { owner: escapeHtml(s.owner) })}` : "";
      row.innerHTML = `
        <div>
          <span class="dot ${s.alive ? "alive" : "stopped"}"></span>
          <span class="label">${typeIcon(s)}${screenBadge(s)}${escapeHtml(s.label)}</span>
          <div class="meta">${machinePrefix(s)}${cwdPrefix(s)}${fmtTime(s.created_ts)}${ownerBadge}</div>
        </div>`;
      row.addEventListener("click", () => (s.locked ? openLockedSession(s) : chatNow.open(s)));

      if (!s.owner) {
        const restoreBtn = document.createElement("button");
        restoreBtn.className = "archive-btn";
        restoreBtn.textContent = "📤";
        restoreBtn.title = t("list.restore_archive");
        restoreBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          unarchiveSession(s);
        });
        row.appendChild(restoreBtn);

        const delBtn = document.createElement("button");
        delBtn.className = "delete-btn";
        delBtn.textContent = "🗑";
        delBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          deleteSession(s);
        });
        row.appendChild(delBtn);
      }

      listEl.appendChild(row);
    }
  }

  // "🧑‍🤝‍🧑 共有ログ" (the deployment notes): folded like the archive; open, one
  // folder per owner, each opened on its own.
  function renderSharedSection() {
    sharedToggleBtn.hidden = lastSharedSessions.length === 0 && !sharedVisible;
    sharedToggleBtn.textContent = sharedVisible
      ? t("list.close_shared_logs")
      : t("list.open_shared_logs_n", { n: lastSharedSessions.length });
    sharedListEl.hidden = !sharedVisible;
    sharedListEl.innerHTML = "";
    if (!sharedVisible) return;
    const byOwner = new Map();
    for (const s of lastSharedSessions) {
      if (!byOwner.has(s.owner)) byOwner.set(s.owner, []);
      byOwner.get(s.owner).push(s);
    }
    for (const owner of [...byOwner.keys()].sort()) {
      const list = byOwner.get(owner);
      const open = openSharedOwners.has(owner);
      const folder = document.createElement("button");
      folder.type = "button";
      folder.className = "shared-folder";
      folder.textContent = `📁 ${owner} (${list.length})`;
      folder.addEventListener("click", () => {
        if (open) openSharedOwners.delete(owner); else openSharedOwners.add(owner);
        renderSharedSection();
      });
      sharedListEl.appendChild(folder);
      if (!open) continue;
      for (const s of list) {
        const row = document.createElement("div");
        row.className = "session-row shared-row";
        row.dataset.sessionId = s.id;
        const mode = s.share_mode === "read" ? t("common.read_only") : t("common.co_work");
        row.innerHTML = `
          <div>
            <span class="dot ${s.alive ? "alive" : "stopped"}"></span>
            <span class="label">${typeIcon(s)}${screenBadge(s)}${escapeHtml(s.label)}</span>
            <div class="meta">${fmtTime(s.created_ts)} &middot; ${mode}</div>
          </div>`;
        row.addEventListener("click", () => (s.locked ? openLockedSession(s) : chatNow.open(s)));
        sharedListEl.appendChild(row);
      }
    }
  }

  sharedToggleBtn.addEventListener("click", () => {
    sharedVisible = !sharedVisible;
    renderSharedSection();
  });

  archiveToggleBtn.addEventListener("click", () => {
    archivedVisible = !archivedVisible;
    renderArchivedSection();
  });

  // Undo for 🗄 (2026-11-04, at the user's request): the sessions archived
  // from this page, newest last. A notice with "元に戻す" shows for a few
  // seconds after each archive, and Ctrl+Z (⌘Z) on the list -- not inside a
  // session, where the key belongs to the terminal, nor in a text field --
  // takes back the latest one, again and again down this list.
  const archiveUndoStack = [];
  let undoToastEl = null;
  let undoToastTimer = null;
  function hideUndoToast() {
    clearTimeout(undoToastTimer);
    if (undoToastEl) undoToastEl.remove();
    undoToastEl = null;
  }
  function showUndoToast(text, withButton) {
    hideUndoToast();
    const el = document.createElement("div");
    el.className = "undo-toast";
    const span = document.createElement("span");
    span.textContent = text;
    el.appendChild(span);
    if (withButton) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = t("common.undo");
      // withButton: true = the archive undo; a function = its own undo (✓ on /todo).
      btn.addEventListener("click", () => {
        if (typeof withButton === "function") { hideUndoToast(); withButton(); } else undoArchive();
      });
      el.appendChild(btn);
    }
    document.body.appendChild(el);
    undoToastEl = el;
    undoToastTimer = setTimeout(hideUndoToast, 8000);
  }
  async function undoArchive() {
    const meta = archiveUndoStack.pop();
    if (!meta) {
      showUndoToast(t("list.nothing_undo"), false);
      return;
    }
    hideUndoToast();
    if (meta.folder) {
      const f = folderById(meta.id);
      if (f) {
        await archiveFolder(f, false);
        showUndoToast(t("list.restored_folder_label_archive", { label: meta.label }), false);
      }
      return;
    }
    if (await unarchiveSession(meta)) showUndoToast(t("list.restored_label_archive", { label: meta.label }), false);
  }
  document.addEventListener("keydown", (e) => {
    if (!(e.ctrlKey || e.metaKey) || e.shiftKey || e.altKey || e.key.toLowerCase() !== "z") return;
    if (chatNow.id) return;
    const tgt = e.target;
    if (tgt && (tgt.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(tgt.tagName))) return;
    e.preventDefault();
    undoArchive();
  });

  async function archiveSession(meta) {
    const ok = await api(`/sessions/${meta.id}/archive`, { method: "POST" }).then(() => true, (e) => {
      ui.toast(t("list.could_not_archive_err", { err: e.message }), { error: true });
      return false;
    });
    if (ok) {
      archiveUndoStack.push({ id: meta.id, label: meta.label });
      if (archiveUndoStack.length > 50) archiveUndoStack.shift();
      showUndoToast(t("list.archived_label", { label: meta.label }), true);
    }
    await refreshSessions();
  }

  async function unarchiveSession(meta) {
    const ok = await api(`/sessions/${meta.id}/unarchive`, { method: "POST" }).then(() => true, (e) => {
      ui.toast(t("list.could_not_restore_err", { err: e.message }), { error: true });
      return false;
    });
    await refreshSessions();
    return ok;
  }

  // Drag (⠿) for session and folder rows alike (the deployment notes):
  // pointer events cover mouse and touch. Each row's place is taken once,
  // at pointerdown; the dragged row follows the pointer, and either
  //  - the pointer is over the middle half of a folder row: the item goes
  //    into that folder (the row lights up), or
  //  - it is between rows: the others slide apart and the item goes there,
  //    into whatever the row above it is in (an open folder's row: into
  //    that folder).
  // A folder carries its open contents along (hidden while dragging) and
  // can never go into itself. The list is redrawn from the saved state.
  function wireSessionDrag(handle, row) {
    handle.addEventListener("pointerdown", (e) => {
      // Left button / touch / pen only: a right click opens the context menu,
      // which swallows the pointerup -- the drag never ended and, with it
      // never ending, the list stopped redrawing (2026-11-04, the user: a
      // folder's new name "did not show" on Windows).
      if (e.button !== 0 || dragState || !document.body.classList.contains("list-arrange")) return;
      e.preventDefault(); // no text selection / native drag while dragging
      const folderId = row.dataset.folderId || null;
      // A session in a tree (under its item): it can go onto another item, not among the list's rows.
      const inTree = !sessionsEl.contains(row) || row.parentElement !== sessionsEl;
      const all = inTree ? [row] : Array.from(sessionsEl.children);
      const carried = folderId
        ? all.filter((r) => r !== row && (r.dataset.path || "").split("/").includes(folderId))
        : [];
      for (const r of carried) r.style.display = "none";
      const rows = all.filter((r) => !carried.includes(r));
      // Places relative to the list's own top, so a scroll (or the header
      // above the list changing height while it scrolls) moves nothing.
      const base = sessionsEl.getBoundingClientRect().top;
      const rects = new Map(rows.map((r) => {
        const b = r.getBoundingClientRect();
        return [r, { top: b.top - base, bottom: b.bottom - base, height: b.height }];
      }));
      dragState = {
        pointerId: e.pointerId,
        row,
        rows,
        rects,
        carried,
        folderId,
        forbidden: folderId ? folderSubtree(folderId) : new Set(),
        originalIndex: rows.indexOf(row),
        targetIndex: rows.indexOf(row),
        into: null,
        inTree,
        moved: false,
        // The trees' items where they were at the start, like the rows: the
        // rows shift while dragging and the trees with them, and measured
        // where they are now an item came under the pointer and went away
        // again by turns (2026-11-27, the user: 点滅して落とせません).
        // A 担当's own row (and its team's) in the tree, measured the same way:
        // a session dropped there helps that 担当 (2026-11-27, the user).
        leadRects: new Map(Array.from(sessionsEl.querySelectorAll(".wtree .tsession-wrap[data-node]"), (n) => {
          const b = n.getBoundingClientRect();
          return [n, { top: b.top - base, bottom: b.bottom - base, height: b.height }];
        })),
        treeBox: inTree ? row.closest(".wtree") : null,
        nodeRects: new Map(Array.from(sessionsEl.querySelectorAll(".wtree .tnode[data-id]"), (n) => {
          const b = n.getBoundingClientRect();
          return [n, { top: b.top - base, bottom: b.bottom - base, height: b.height }];
        })),
        // An open folder's frame (its row down to the last row inside it,
        // as drawFolderFrames draws it): a drop anywhere in it goes into
        // that folder, the innermost one (2026-11-27, the user: フォルダの
        // 名前でなく、フォルダの中にもドロップできるように).
        frames: inTree ? [] : rows.flatMap((r, i) => {
          if (!r.dataset.folderId || r.dataset.open !== "1" || r === row) return [];
          const d = +r.dataset.depth || 0;
          let last = null;
          for (let j = i + 1; j < rows.length; j++) {
            const x = rows[j];
            if (x.dataset.depth === undefined || +x.dataset.depth <= d) break;
            last = x;
          }
          return last ? [{ row: r, depth: d, top: rects.get(r).top, bottom: rects.get(last).bottom }] : [];
        }),
        // A tree's boxes (an item with its branches) and groups (a root's):
        // a drop between two items goes under the box around them.
        boxRects: Array.from(sessionsEl.querySelectorAll(".wtree .tbox, .wtree .tgroup"), (n) => {
          const b = n.getBoundingClientRect();
          let depth = n.classList.contains("tgroup") ? -1 : 0;
          for (let p = n.parentElement && n.parentElement.closest(".tbox"); p; p = p.parentElement && p.parentElement.closest(".tbox")) depth++;
          return { el: n, top: b.top - base, bottom: b.bottom - base, depth };
        }),
        rowHeight: rects.get(row).height + 8,
        startY: e.clientY - base,
        lastY: e.clientY,
        scrollTimer: null,
      };
      row.classList.add("dragging");
      handle.setPointerCapture(e.pointerId);
    });
    handle.addEventListener("pointermove", (e) => {
      if (!dragState || dragState.pointerId !== e.pointerId) return;
      dragState.lastY = e.clientY;
      dragMoved();
      // Near the top or bottom edge of the list, scroll it (a long list's
      // target can be off screen).
      const st = dragState;
      const box = viewList.getBoundingClientRect();
      const speed = e.clientY < box.top + 48 ? -24 : e.clientY > box.bottom - 48 ? 24 : 0;
      clearInterval(st.scrollTimer);
      st.scrollTimer = speed ? setInterval(() => {
        if (dragState !== st) return clearInterval(st.scrollTimer);
        const before = viewList.scrollTop;
        viewList.scrollTop += speed;
        if (viewList.scrollTop !== before) dragMoved();
      }, 30) : null;
    });
    const stop = (e) => {
      if (!dragState || dragState.pointerId !== e.pointerId) return;
      clearInterval(dragState.scrollTimer);
      endSessionDrag();
    };
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
    // Capture lost without a pointerup (the window lost focus, the pointer
    // was taken by the browser): the drag ends there too.
    handle.addEventListener("lostpointercapture", stop);
    // A plain tap on the handle must not open the session / fold the folder.
    handle.addEventListener("click", (e) => e.stopPropagation());
  }

  // Lays out the drag for the pointer's last position. The rows' places
  // were taken at pointerdown, relative to the list's top; the pointer is
  // compared the same way.
  function dragMoved() {
    const st = dragState;
    {
      const y = st.lastY - sessionsEl.getBoundingClientRect().top;
      const dy = y - st.startY;
      if (Math.abs(dy) > 4) st.moved = true;
      st.row.style.transform = `translateY(${dy}px)`;
      // Into a folder?
      let into = null;
      for (const r of st.inTree ? [] : st.rows) {
        if (r === st.row || !r.dataset.folderId || st.forbidden.has(r.dataset.folderId)) continue;
        const b = st.rects.get(r);
        if (y > b.top + b.height * 0.25 && y < b.bottom - b.height * 0.25) { into = r; break; }
      }
      // A session onto an item of a tree (仕事's tree, 2026-11-26, the user:
      // セッションをツリーにドラッグしてもツリーに入らない): that item's.
      let intoNode = null;
      if (!into && !st.folderId) {
        for (const r of sessionsEl.querySelectorAll(".wtree .tnode[data-id]")) {
          if (st.inTree && r === st.row.closest(".tsession")?.previousElementSibling) continue;   // its own item
          let b = st.nodeRects.get(r);
          if (!b) {   // drawn after the start (the tree refreshed): where it is now
            const n = r.getBoundingClientRect(), top = sessionsEl.getBoundingClientRect().top;
            b = { top: n.top - top, bottom: n.bottom - top, height: n.height };
          }
          if (b.height && y > b.top + b.height * 0.2 && y < b.bottom - b.height * 0.2) { intoNode = r; break; }
        }
      }
      let intoLead = null;
      if (!into && !intoNode && !st.folderId) {
        const mine = st.row.closest(".tsession-wrap");
        for (const [r, b] of st.leadRects) {
          if (r === mine || !r.isConnected) continue;
          if (b.height && y > b.top + b.height * 0.15 && y < b.bottom - b.height * 0.15) { intoLead = r; break; }
        }
      }
      // Between two items of a tree: the item whose box holds them (the
      // innermost, else its root), 2026-11-27 (the user: アイテムの上と
      // 隙間の両方にドロップできるように).
      if (!into && !intoNode && !intoLead && !st.folderId) {
        let best = null;
        for (const b of st.boxRects) {
          if (!b.el.isConnected || y <= b.top || y >= b.bottom) continue;
          if (!best || b.depth > best.depth) best = b;   // the innermost
        }
        const n = best && best.el.querySelector(".tnode[data-id]");
        if (n && !(st.inTree && n === st.row.closest(".tsession")?.previousElementSibling)) intoNode = n;
      }
      for (const r of sessionsEl.querySelectorAll(".wtree .tsession-wrap.drop-into")) if (r !== intoLead) r.classList.remove("drop-into");
      if (intoLead) intoLead.classList.add("drop-into");
      st.intoLead = intoLead;
      if (intoLead) into = null;
      for (const r of sessionsEl.querySelectorAll(".wtree .tnode.drop-into")) if (r !== intoNode) r.classList.remove("drop-into");
      if (intoNode) intoNode.classList.add("drop-into");
      st.intoNode = intoNode;
      if (intoNode) into = null;
      // Inside an open folder's frame (not on its name, nor on a tree): on
      // a row, into that folder; between rows, placed there, in it.
      st.gapFolder = null;
      if (!into && !intoNode && !intoLead && !st.inTree) {
        let fr = null;
        for (const f of st.frames) {
          if (y <= f.top || y >= f.bottom || st.forbidden.has(f.row.dataset.folderId)) continue;
          if (!fr || f.depth > fr.depth) fr = f;
        }
        const onTree = st.rows.some((r) => r.classList.contains("wtree") && y > st.rects.get(r).top && y < st.rects.get(r).bottom);
        if (fr && !onTree) {
          const on = st.rows.find((r) => {
            if (r === st.row || r.classList.contains("wtree")) return false;
            const b = st.rects.get(r);
            return y > b.top + b.height * 0.2 && y < b.bottom - b.height * 0.2;
          });
          if (on) into = fr.row; else st.gapFolder = fr.row;
        }
      }
      for (const r of st.rows) r.classList.toggle("drop-into", r === into);
      st.into = into;
      // On the folder: 「📁 〈名前〉へ」, as the tree's items say theirs.
      const fTgt = into || st.gapFolder;
      for (const r of st.rows) if (r !== fTgt && r.dataset.drop !== undefined && r.dataset.folderId) r.removeAttribute("data-drop");
      if (fTgt) {
        const f = folderById(fTgt.dataset.folderId), b = window.aizaExt.folder(fTgt.dataset.folderId);
        fTgt.dataset.drop = t("list.drop_into_folder", { name: (b && b.label) || (f && f.name) || "" });
      }
      // What letting go there does, or ✕ why not, on the target itself
      // (2026-11-27, the user: 移動できない場合があるので区別がわかりやすいと良い).
      const tgt = intoLead || intoNode;
      st.verdict = null;
      if (tgt) {
        const s = lastSessions.find((x) => x.id === st.row.dataset.sessionId);
        st.verdict = ui.trees.dropVerdict(intoLead ? tgt.dataset.node : tgt.dataset.id, s, !!intoLead);
      }
      for (const r of sessionsEl.querySelectorAll(".wtree [data-drop]")) if (r !== tgt) { r.removeAttribute("data-drop"); r.classList.remove("drop-no"); }
      if (tgt) {
        tgt.dataset.drop = st.verdict.label;
        tgt.classList.toggle("drop-no", !st.verdict.ok);
      }
      // Otherwise: how many of the other rows are above the pointer.
      const others = st.rows.filter((r) => r !== st.row);
      let idx = 0;
      for (const r of others) {
        const b = st.rects.get(r);
        if (b.top + b.height / 2 < y) idx++;
      }
      st.targetIndex = idx;
      const orig = st.originalIndex;
      // Over a tree's box (where it was at the start), the rows stay put: the
      // box shifting under the pointer moved its items to and fro.
      const overTree = others.some((r) => {
        if (!r.classList.contains("wtree")) return false;
        const b = st.rects.get(r);
        return y > b.top && y < b.bottom;
      });
      if (overTree && !intoNode && !intoLead) st.targetIndex = orig;   // let go there: stays where it was
      for (const r of others) {
        const j = st.rows.indexOf(r);
        let shift = 0;
        if (!into && !intoNode && !intoLead && !overTree) {   // between rows (in a frame too): they make room
          if (j > orig && j <= idx) shift = -st.rowHeight;
          else if (j < orig && j >= idx) shift = st.rowHeight;
        }
        r.style.transform = shift ? `translateY(${shift}px)` : "";
      }
    }
  }

  function rowParent(r) {
    if (r.dataset.folderId) return folderById(r.dataset.folderId)?.parent || null;
    const s = lastSessions.find((x) => x.id === r.dataset.sessionId);
    return s ? folderOfSession(s) : null;
  }

  function endSessionDrag() {
    const st = dragState;
    dragState = null;
    for (const r of st.rows) {
      r.style.transform = "";
      r.classList.remove("dragging", "drop-into");
    }
    for (const r of st.carried) r.style.display = "";
    for (const r of sessionsEl.querySelectorAll(".wtree .tnode.drop-into, .wtree .tsession-wrap.drop-into")) r.classList.remove("drop-into");
    for (const r of sessionsEl.querySelectorAll(".wtree [data-drop]")) { r.removeAttribute("data-drop"); r.classList.remove("drop-no"); }
    for (const r of st.rows) r.removeAttribute("data-drop");
    if (!st.moved) return;
    if ((st.intoLead || st.intoNode) && st.verdict && !st.verdict.ok) { renderSessionList(); return; }   // ✕: nothing happens
    if (st.intoLead) {   // onto a 担当's row: it helps that 担当 (🤝)
      const s = lastSessions.find((x) => x.id === st.row.dataset.sessionId);
      if (s) ui.trees.helpLead(st.intoLead.dataset.node, s);
      return;
    }
    if (st.inTree && !st.intoNode) {
      // Out of its tree's box: it lets its item go (or stops helping) and is
      // back in its folder (2026-11-27, the user: 樹からドラッグで外すと外せる).
      const b = st.treeBox && st.treeBox.getBoundingClientRect();
      if (b && (st.lastY < b.top || st.lastY > b.bottom)) ui.trees.release(st.row.dataset.sessionId);
      else renderSessionList();
      return;
    }
    if (st.intoNode) {   // onto a tree's item: the session goes under it (▶'s 既存)
      const s = lastSessions.find((x) => x.id === st.row.dataset.sessionId);
      if (s) ui.trees.linkSession(st.intoNode.dataset.id, s);
      return;
    }
    const others = st.rows.filter((r) => r !== st.row);
    let parent;
    if (st.into) {
      parent = st.into.dataset.folderId;
    } else if (st.gapFolder) {
      parent = st.gapFolder.dataset.folderId;
    } else {
      const above = others[st.targetIndex - 1];
      if (!above) parent = null;
      else if (above.dataset.folderId && openFolders.has(above.dataset.folderId)) parent = above.dataset.folderId;
      else parent = rowParent(above);
    }
    if (parent && st.forbidden.has(parent)) { renderSessionList(); return; }
    if (st.folderId) {
      const f = folderById(st.folderId);
      f.parent = parent;
      folderDoc.folders = folderDoc.folders.filter((x) => x !== f);
      // Before the next folder with the same parent below the drop point,
      // else after the last of them.
      let before = null;
      if (!st.into) {
        for (const r of others.slice(st.targetIndex)) {
          const g = r.dataset.folderId && folderById(r.dataset.folderId);
          if (g && (g.parent || null) === parent) { before = g; break; }
        }
      }
      const at = before ? folderDoc.folders.indexOf(before) : folderDoc.folders.length;
      folderDoc.folders.splice(at, 0, f);
      // The folder it went into stays as it was, open or closed (2026-11-04,
      // the user: "ドロップしてもそのまま開かないように").
      saveFolders([{ op: "put", folder: { id: f.id, parent }, before: before ? before.id : "end" }]);
      return;
    }
    const id = st.row.dataset.sessionId;
    const s = lastSessions.find((x) => x.id === id);
    const ops = [];
    if (s && folderOfSession(s) !== parent) {
      folderDoc.assign[id] = parent || "";
      ops.push({ op: "assign", session: id, folder: parent || "" });
    }
    if (!st.into) {
      const ids = others.filter((r) => r.dataset.sessionId).map((r) => r.dataset.sessionId);
      const k = others.slice(0, st.targetIndex).filter((r) => r.dataset.sessionId).length;
      ids.splice(k, 0, id);
      saveSessionOrder(ids);
    }
    if (ops.length) saveFolders(ops);
    else renderSessionList();
  }

  // Merges the just-dragged, machine-filtered subset's new relative order
  // back into the full (unfiltered) saved order, leaving any session the
  // machine filter is currently hiding at its existing relative position --
  // same idea as a stable merge: walk the previous full order, and every
  // time a visible id comes up, take the next one off the new sequence
  // instead of the old one.
  function saveSessionOrder(visibleIdsNewOrder) {
    const visibleSet = new Set(visibleIdsNewOrder);
    const base = sessionOrder.length ? sessionOrder : lastSessions.map((s) => s.id);
    const full = base.filter((id) => lastSessions.some((s) => s.id === id)); // drop stale/deleted ids
    for (const s of lastSessions) {
      if (!full.includes(s.id)) full.push(s.id); // sessions never placed yet (new, or first drag ever)
    }
    const queue = [...visibleIdsNewOrder];
    sessionOrder = full.map((id) => (visibleSet.has(id) ? queue.shift() : id));
    // Drawn in the new order now, not only after the next list refresh
    // (2026-11-24: the row went back to where it was for up to 20 s).
    lastSessions = applyCustomOrder(lastSessions, sessionOrder);
    lastVisibleSessions = applyCustomOrder(lastVisibleSessions, sessionOrder);
    listEditSeq++;
    orderSaving++;
    api("/session-order", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ order: sessionOrder }),
    }).catch(() => {}).finally(() => { orderSaving--; });
  }

  async function deleteSession(meta) {
    if (!(await ui.confirm(t("list.delete_conversation_log_label_cannot", { label: meta.label }), { danger: true }))) return;
    await api(`/sessions/${meta.id}/delete`, { method: "POST" });
    await refreshSessions();
  }

  async function renameSession(meta) {
    const next = await ui.ask(t("list.new_name"), meta.label);
    if (next === null) return; // cancelled
    const trimmed = next.trim();
    if (!trimmed || trimmed === meta.label) return;
    await api(`/sessions/${meta.id}/rename`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: trimmed }),
    }).catch((e) => ui.toast(t("list.could_not_rename_err", { err: e.message }), { error: true }));
    await refreshSessions();
    // The chat header's own label is a separate DOM element (set once in
    // openSession(), not re-read from the session list) -- keep it in sync
    // if the session being renamed is the one currently open.
    if (chatNow.id === meta.id) chatLabelEl.textContent = typeIcon(meta) + screenBadge(meta) + trimmed;
  }

  // tmux sessions the user started by hand (outside aiza) that aren't
  // already tracked by a live aiza session -- see list_untracked_tmux_sessions
  // in aiza-backend. Covers BOTH sessions inside the user's own devbox
  // container and ones running directly on the host as that same user
  // (aiza-backend@<user> already runs as that literal Unix account, so it
  // has the same access to that user's host-level tmux server a normal
  // shell for them would -- discovered as a real gap when a user's actual
  // long-running sessions turned out to live there, not in the container).
  // Each entry is {name, location}, not a bare name, since a container
  // session and a host session could plausibly share a name (tmux's
  // default auto-numbered names especially). "接続" adopts one via
  // POST /sessions/adopt and opens it in the same chat view as any other
  // tmux-based (shell) session; output arrives via live_tail/agent_output
  // events from _watch_attached_session instead of a raw pipe-pane tail.
  function locationLabel(location) {
    if (location.startsWith("ssh:")) return location.slice(4);
    return location === "host" ? "host" : "container";
  }

  async function refreshTmuxSessions() {
    const { sessions } = await api("/tmux-sessions").catch(() => ({ sessions: [] }));
    tmuxSessionsEl.innerHTML = "";
    const machineOf = (location) => (location.startsWith("ssh:") ? location.slice(4) : "local");
    for (const { name, location, owner, read_only: readOnly } of sessions.filter((s) => machineOf(s.location) === currentMachine)) {
      const row = document.createElement("div");
      row.className = "tmux-row";
      const nameEl = document.createElement("span");
      nameEl.className = "name";
      // Whose it is on a machine every aiza user shares (the deployment notes);
      // someone else's can only be watched.
      const who = owner ? ` · ${t("common.owner", { owner })}` : "";
      nameEl.textContent = `${name} (${locationLabel(location)})${who}`;
      row.appendChild(nameEl);

      const btn = document.createElement("button");
      btn.textContent = readOnly ? t("common.watch") : t("common.connect");
      btn.addEventListener("click", () => adoptSession(name, location));
      row.appendChild(btn);

      tmuxSessionsEl.appendChild(row);
    }
  }

  async function adoptSession(tmuxName, location) {
    // An adopted pane was never sized for this phone -- it may have been
    // created by hand, or by aiza itself on some other, wider device --
    // so this resizes it to the current screen the same way create_session
    // already does for a brand-new pane.
    const meta = await withUnlockRetry(() => api("/sessions/adopt", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        tmux_name: tmuxName, location, label: tmuxName,
        cols: computeScreenCols(), rows: computeScreenRows(),
      }),
    })).catch((e) => {
      ui.toast(t("list.could_not_connect_err", { err: e.message }), { error: true });
      return null;
    });
    if (!meta) return;
    await refreshSessions();
    chatNow.open(meta);
  }

