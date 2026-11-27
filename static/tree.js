// The work tree's view (the deployment notes): the tree and its ⋯ menu and
// panels (Preact components TreeView / TreeRow / TreeMenu), dragging (⠿),
// the 人と AI / 週のまとめ / 利用 / ⛓ views, and the tree's own state.
//
// One of the page's plain scripts (no build step): index.html loads them in
// order, and they share one global scope, so a function or a top-level
// let/const here is seen by name from the others. Loaded before app.js;
// nothing here runs app.js's code while loading (only when called), so the
// order among the page's files does not matter for it. Split out of app.js
// 2026-11-24 (the deployment notes).
"use strict";
const treeClosed = new Set();
let treeMenuScrollHooked = false;
let treeArrange = false; // ↕: rows carry ⠿ to drag them among their siblings or under another
let treeFocus = null;   // the node to scroll to and mark once (from a session's 🌳)
// A link to one node, /agents/#tree=<id> (2026-11-21, the user: Discord の
// 知らせから木に直接飛べるように): jumped to once the tree is loaded.
let treePendingJump = null;
// The tree's data, its filter and the 週のまとめ / 利用 views' (declared here,
// where they change; the to-do page reads them).
let treeData = null, treeFilter = "all", treeLoading = false, treeAt = 0;
let weekData = null, weekAt = 0;
let usageData = null, usageAt = 0, usageSpan = 4;
// /agents/#tree=<id>: to that node once the tree is read again (app.js's applyHash).
function jumpToTree(id) {
  treePendingJump = id;
  treeAt = 0;
  loadTree();
}
try { for (const id of JSON.parse(localStorage.getItem("aiza-tree-closed") || "[]")) treeClosed.add(id); } catch (e) {}
// Open items whose finished branches are shown too (▾); an open item
// without it (▿) hides them behind one 「✓ 済みの枝 n 件」 row (2026-11-20,
// the user: 灰色の終わった枝が多く、見づらい … ▶ ▽ ▼ に切り替わる).
const treeShowDone = new Set();
try { for (const id of JSON.parse(localStorage.getItem("aiza-tree-show-done") || "[]")) treeShowDone.add(id); } catch (e) {}
// Lead items in a closed item whose helpers are shown under the lead's row
// (its title, 2026-11-27, the user: 協力セッションを見るために、担当セッション
// を押して開けるようにしたい).
const treePeekOpen = new Set();
try { for (const id of JSON.parse(localStorage.getItem("aiza-tree-peek-open") || "[]")) treePeekOpen.add(id); } catch (e) {}
function treePeekFlip(id) {
  treePeekOpen.has(id) ? treePeekOpen.delete(id) : treePeekOpen.add(id);
  treeSaveOpen(); treeRerender();
}
function treeSaveOpen() {
  try {
    localStorage.setItem("aiza-tree-closed", JSON.stringify([...treeClosed]));
    localStorage.setItem("aiza-tree-show-done", JSON.stringify([...treeShowDone]));
    localStorage.setItem("aiza-tree-peek-open", JSON.stringify([...treePeekOpen]));
  } catch (e) {}
}
// Parents whose finished handoff branches are shown (folded by default,
// 2026-11-18, the user: talkto のたびに枝が増えて木が読みにくい).
const treeHandoffsShown = new Set();
let treeDoneShown = false;
try { treeDoneShown = localStorage.getItem("aiza-tree-done-shown") === "1"; } catch (e) {}
let treeTrRetries = 0;
function loadTree() {
  if (treeLoading) return;
  treeLoading = true;
  treeAt = Date.now();
  api("/tree").then((r) => {
    treeData = r;
    // Translations being made (plan stage 13): read again shortly.
    if (r.tr_pending && treeTrRetries++ < 6) setTimeout(() => { treeAt = 0; if (todoOn()) loadTree(); }, 10000);
    else if (!r.tr_pending) treeTrRetries = 0;
  }).catch((e) => { treeData = { unavailable: e.message, nodes: [] }; })
    .finally(() => {
      treeLoading = false; updateChatTreeBtn();
      const jump = treePendingJump;
      treePendingJump = null;
      if (jump && ((treeData && treeData.nodes) || []).some((n) => n.id === jump)) jumpToTreeNode(jump);
      else {
        if (jump) alert(t("tree.cannot_see_branch_no_longer"));
        if (todoOn()) renderTodo();   // 番ごと shows the tree's items too (段5)
      }
      // 仕事's tree: where each root goes may have changed (the list's folders).
      if (ui.trees.loaded) ui.trees.loaded();
    });
}
// From a session to its place in the tree (2026-11-20, the user:
// セッションから木の該当箇所に飛べると良いです): the node the session took
// on last, among those this viewer may see.
function treeNodeOfSession(sid, whose) {
  if (!treeData || !treeData.nodes || !sid) return null;
  let best = null;
  for (const n of treeData.nodes) {
    if (!n.links || n.links.session !== sid || (n.session_owner || n.owner) !== whose) continue;
    if (!best || (n.linked_ts || n.created_ts || 0) > (best.linked_ts || best.created_ts || 0)) best = n;
  }
  return best;
}
// In the share pane (the user: 共有の中で良いと思います); filled in when
// the tree arrives.
function updateChatTreeBtn() {
  const row = document.getElementById("tree-jump-row");
  if (!row) return;
  const n = chatNow.id && treeData ? treeNodeOfSession(chatNow.id, chatNow.owner || treeData.user) : null;
  row.hidden = !n;
  const btn = row.querySelector("button");
  if (n) { btn.dataset.node = n.id; btn.textContent = "🌳 " + t("tree.show_in_tree") + ": " + n.title; }
}
function jumpToTreeNode(id) {
  const byId = new Map(((treeData && treeData.nodes) || []).map((n) => [n.id, n]));
  let n = byId.get(id), root = n;
  if (!n) return;
  // Open every fold on the way: its ancestors, their finished branches,
  // a finished handoff row, and 終了済み.
  for (let p = byId.get(n.parent), i = 0; p && i < 1000; p = byId.get(p.parent), i++) {
    treeClosed.delete(p.id); treeShowDone.add(p.id); root = p;
  }
  if (n.links && n.links.handoff) treeHandoffsShown.add(n.parent || "");
  if (root.state === "done") treeDoneShown = true;
  treeSaveOpen();
  try { localStorage.setItem("aiza-tree-mode", "tree"); } catch (e) {}
  treeFilter = "all"; treeFocus = id;
  // 仕事's tree (the deployment notes 段5): its folder opened, the node in sight.
  if (chatNow.id) chatNow.close();   // from a session's 🌳
  if (ui.trees.reveal) ui.trees.reveal(treePlaceOf(root));
  ui.tabs.show("work", "tree");
  treeRerender();
}
// The session a node is linked to, when this viewer can open it: their
// own, or one shared with them (a devbox session of a tree they may see
// is shared read-only, plan stage 14).
function treeSessionHref(n, me) {
  const sid = n.links && n.links.session;
  if (!sid) return null;
  const whose = n.session_owner || n.owner;
  if (whose === me) return n.session_gone ? null : `/agents/#${encodeURIComponent(sid)}`;
  return lastSessions.some((s) => s.id === sid && s.owner === whose) ? `/agents/#${encodeURIComponent(sid)}` : null;
}
// Plan stage 13: a shared node's title or status line in another language
// comes translated (n.tr); 「訳」 next to it shows the original instead.
const treeShowOrig = new Set();
function treeTitleEl(n, tag) {
  const el = document.createElement(tag);
  el.textContent = treeTitleText(n);
  return el;
}
function treeRestSession(n) {
  const sid = n.links && n.links.session;
  return sid ? lastSessions.find((s) => s.id === sid) || null : null;
}
// Where that session is now, so whether the leftover is finished can be
// told (the user: 終わったかどうかもわかりません).
function treeRestState(n) {
  const s = treeRestSession(n);
  if (!s) return { text: t("tree.session_gone"), finished: false };
  const where = s.archived ? t("tree.archived") : s.alive ? t("common.running") : t("common.stopped_2");
  const tk = s.task || {};
  const st = { you: t("common.turn"), done: t("common.done"), snooze: t("common.snoozed"), working: t("common.working") }[tk.state] || "";
  const text = [where, st && st + (tk.text ? `: ${tk.text}` : "")].filter(Boolean).join(" · ");
  return { text, finished: tk.state === "done" && !s.alive };
}
function treeTrBadge(n) {
  if (!(n.tr && (n.tr.title || n.tr.ball))) return null;
  const b = document.createElement("button");
  b.type = "button"; b.className = "ttr";
  b.textContent = treeShowOrig.has(n.id) ? t("tree.orig") : t("tree.translation_short");
  b.title = treeShowOrig.has(n.id) ? t("tree.show_translation") : t("tree.show_original");
  b.addEventListener("click", (e) => {
    e.preventDefault(); e.stopPropagation();
    treeShowOrig.has(n.id) ? treeShowOrig.delete(n.id) : treeShowOrig.add(n.id);
    renderTodo();
  });
  return b;
}
function ballText(n) {
  const b = n.ball || {};
  return n.tr && n.tr.ball && !treeShowOrig.has(n.id) ? n.tr.ball : b.text;
}
// To a session the tree just made, took or joined: as its links open one
// (openSessionOverTodo), not by loading the page again (2026-11-24: that lost
// voice mode, and the page's state).
async function treeGoSession(id, whose) {
  const find = () => lastSessions.find((s) => s.id === id && (s.owner || null) === (whose || null));
  const meta = find() || (await refreshSessions().catch(() => null), find());
  if (meta) openSessionOverTodo(meta);
  else location.href = `/agents/#${encodeURIComponent(id)}`;
}
async function treeOp(body) {
  try {
    await api("/tree", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  } catch (e) { alert(e.message); }
  loadTree();
}
// 🤝 The sessions helping an item's 🧭 担当 (the deployment notes; the store
// hands them on the item its 担当 holds now). Gone ones are left out.
function treeHelpers(n) {
  return (n.helpers || []).filter((h) => !h.gone);
}
const BALL = { person: "🙋", ai: "🤖", sleep: "💤", ext: "✉", done: "✓" };
// ▶ (A): a node no running session holds is taken by the new session itself
// (an issue's node starts the issue's session, in its worktree, so the
// GitHub sync keeps the link); a node already held gets a child instead.
// Either way the title offered is the node's own.
function treeHeldBy(n) {
  // A split-up node's own work is its その他 child.
  const rest = ((treeData && treeData.nodes) || []).find((x) => x.parent === n.id && x.rest);
  const sid = ((rest || n).links || {}).session;
  return sid ? lastSessions.find((s) => s.id === sid && s.alive && !s.archived) : null;
}
// The pieces the ⋯ items that open under themselves are made of.
function treeSelect(box, label, options) {
  const el = document.createElement("select");
  el.setAttribute("aria-label", label);
  for (const [value, text] of options) {
    const o = document.createElement("option");
    o.value = value; o.textContent = text; el.appendChild(o);
  }
  box.appendChild(el);
  return el;
}
function treeInput(box, label, value) {
  const el = document.createElement("input");
  el.type = "text"; el.value = value || "";
  if (label) { el.placeholder = label; el.setAttribute("aria-label", label); }
  el.autocomplete = "off";
  box.appendChild(el);
  return el;
}
function treeNote(box, text) {
  const el = document.createElement("span");
  el.textContent = text;
  box.appendChild(el);
  return el;
}
// The panel's button; Enter in `field` presses it too.
function treeAct(box, label, fn, field) {
  const b = document.createElement("button");
  b.textContent = label;
  b.addEventListener("click", (e) => { e.stopPropagation(); fn(); });
  box.appendChild(b);
  if (field) field.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.isComposing) { e.preventDefault(); fn(); } });
  return b;
}
// The session folders a session can go in (not archived, not built-in), by path.
function treeFolderChoices() {
  const by = new Map(folderDoc.folders.map((f) => [f.id, f]));
  const hidden = (f) => { for (let x = f, i = 0; x && i < 1000; x = by.get(x.parent), i++) if (x.archived) return true; return false; };
  const pathOf = (f) => { const out = []; for (let x = f, i = 0; x && i < 1000; x = by.get(x.parent), i++) out.unshift(x.name); return out.join(" / "); };
  return folderDoc.folders.filter((f) => !hidden(f) && !(window.aizaExt && window.aizaExt.folder(f.id)))
    .map((f) => ({ f, p: pathOf(f) })).sort((a, b) => a.p.localeCompare(b.p));
}
// 📁 on a root: which session folder its ▶ sessions start in -- one there
// is, a new one (often a subfolder of a top-level one), or none (guess).
function treeFolderPanel(n, box, close) {
  const by = new Map(folderDoc.folders.map((f) => [f.id, f]));
  const list = treeFolderChoices();
  const cur = n.folder ? n.folder.path + (n.folder.how === "guess" ? t("tree.guessed") : "") : t("common.none");
  treeNote(box, t("tree.now_c", { c: cur }));
  const pick = treeSelect(box, t("common.folder"), [["", t("tree.none_back_guessing")]]
    .concat(list.map((x) => [x.f.id, x.p])).concat([["+new", "＋ " + t("common.make_new_folder")]]));
  if (n.folder && n.folder.how !== "guess" && by.has(n.folder.id)) pick.value = n.folder.id;
  const par = treeSelect(box, t("tree.which_folder_make_under"), [["", t("tree.make_at_top")]]
    .concat(list.map((x) => [x.f.id, t("tree.make_under_p", { p: x.p })])));
  const name = treeInput(box, t("common.folder_name"), n.title);
  const sync = () => { par.hidden = name.hidden = pick.value !== "+new"; };
  pick.addEventListener("change", sync);
  sync();
  treeAct(box, t("common.set"), async () => {
    let ops;
    if (pick.value === "+new") {
      const nm = name.value.trim();
      if (!nm) return;
      const f = { id: newFolderId(), name: nm.slice(0, 100), parent: par.value || null, archived: false, last_stopped: [] };
      ops = [{ op: "put", folder: f }, { op: "tree_root", node: n.id, folder: f.id }];
    } else ops = [{ op: "tree_root", node: n.id, folder: pick.value }];
    close();
    await saveFolders(ops);
    loadTree();
  }, name);
}
// What a tree item gives the start screen (the deployment notes 段3, 2026-11-25):
// its title, its tree's session folder (and so the 作業フォルダ), and, on
// 開始, the first message and the link. A node no running session holds is
// taken by the new session itself (an issue's node starts the issue's
// session, in its worktree, so the GitHub sync keeps the link); a node
// already held gets a child named after the session instead.
function treeStartCtx(n) {
  const own = !treeHeldBy(n);
  // The session folder this tree's sessions go in (chosen on its root's ⋯,
  // else guessed from where its sessions are).
  const fo = n.folder && folderDoc.folders.some((f) => f.id === n.folder.id) ? n.folder : null;
  const parentOf = (x) => x && x.parent ? ((treeData && treeData.nodes) || []).find((y) => y.id === x.parent) : null;
  const up = parentOf(n);
  const path = (up ? up.title + " / " : "") + n.title;
  let label = n.title;
  return {
    node: n.id,
    title: n.title,
    folder: fo ? fo.id : null,
    note: own ? t("tree.start_links_item", { path }) : t("tree.start_under_item", { path }),
    prepare(body) {
      label = (String(body.label || "").trim() || n.title).slice(0, 80);
      body.label = label;
      // The first message names where the job sits (the node's parent too, so
      // a node whose title is no job, 「その他」, still says whose rest it is),
      // and carries no task: the AI waits for the user (2026-11-18: one
      // started from 「その他」 made up a task of its own). One short line
      // (2026-11-25, the user: 最初のメッセージがながい).
      body.initial_message = t("tree.first_message", { path: own ? path : `${path} / ${label}` });
      // The issue's own session (its worktree): Claude in the devbox only.
      const issue = own && body.preset === "claude-tui" ? (n.links || {}).issue : null;
      if (issue) body.issue = issue;
    },
    async after(meta) {
      try {
        const req = own
          ? { op: "update", id: n.id, links: Object.assign({}, n.links || {}, { session: meta.id }) }
          : { op: "add", parent: n.id, title: label, visibility: n.visibility, links: { session: meta.id } };
        await api("/tree", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req) });
      } catch (e) { alert(e.message); }
    },
  };
}
// 🤛 Someone's item taken on in a new session of one's own (plan stage 14):
// the start screen too, the session made by the tree's take (POST /tree
// {op: "take"}, which links it and tells it what it takes on).
function treeTakeCtx(n) {
  return {
    title: n.title,
    note: t("tree.take_note", { title: n.title, who: n.session_owner || n.owner }),
    async create(body) {
      const r = await api("/tree", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ op: "take", id: n.id, preset: body.preset, label: body.label, cwd: body.cwd,
                               skip_permissions: body.skip_permissions }) });
      const all = await refreshSessions().catch(() => lastSessions);
      return (all || lastSessions).find((x) => x.id === r.session) || { id: r.session };
    },
  };
}
// 🔗 (B): one of this user's sessions goes under this node -- its own node
// moves there, or a child named after it is made.
// 🧭 Every open item a session of the viewer's holds lets it go, and it
// helps no one: it is back in its folder (a drag out of the tree, or before
// it helps someone, 2026-11-27, the user: 樹からドラッグで外すと外せる).
async function treeRelease(sid) {
  const me = treeData && treeData.user;
  const c = treeContext(treeData);
  for (const n of (treeData.nodes || [])) {
    if (!(n.links && n.links.session === sid) || (n.session_owner || n.owner) !== me || c.isDone(n)) continue;
    const links = Object.assign({}, n.links);
    delete links.session;
    try {
      await api("/tree", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "update", id: n.id, links, ball: null }) });
    } catch (e) { alert(e.message); return false; }
  }
  if ((treeData.nodes || []).some((n) => treeHelpers(n).some((h) => h.session === sid && h.owner === me))) {
    try {
      await api("/tree", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "unhelp", session: sid }) });
    } catch (e) { alert(e.message); return false; }
  }
  return true;
}
// 🤝 Session s helps the 担当 of item n (dropped onto the item or onto the
// 担当's own row, 2026-11-27, the user: 担当セッションの上に落としても協力に).
// One that is a 担当 itself lets its items go first, when the user says so.
async function treeHelpLead(n, s) {
  const me = treeData.user;
  if ((n.session_owner || n.owner) !== me) { alert(t("tree.helping_others_lead_not_yet")); return; }
  if (n.links.session === s.id || treeHelpers(n).some((h) => h.session === s.id && h.owner === me)) return;
  const c = treeContext(treeData);
  const holds = (treeData.nodes || []).filter((x) => x.links && x.links.session === s.id && (x.session_owner || x.owner) === me && !c.isDone(x));
  if (holds.length) {
    if (!confirm(t("tree.lead_lets_go_to_help", { s: s.label, items: holds.map((x) => x.title).join("・") }))) return;
    if (!(await treeRelease(s.id))) return;
  } else if (!confirm(t("tree.help_lead_confirm", { s: s.label, lead: n.session_label || n.title }))) return;
  try {
    await api("/tree", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "help", id: n.id, session: s.id }) });
  } catch (e) { alert(e.message); }
  if (typeof refreshSessions === "function") refreshSessions();
}
// What a session let go on a tree's item (or on a 担当's row, lead=true)
// would do, for the drag to show before the drop (2026-11-27, the user:
// ドロップ先に移動できない場合があるので区別がわかりやすいと良い).
// {ok, label}; the same rules as treeLinkSession / treeHelpLead.
function treeDropVerdict(n, s, lead) {
  const no = (k) => ({ ok: false, label: "✕ " + t(k) });
  if (!n || !s || !treeData) return no("tree.drop_no_here");
  const me = treeData.user, c = treeContext(treeData);
  const writable = n.owner === me || (n.members || []).includes(me);
  if (c.isDone(n)) return no("tree.drop_no_done");
  if (!writable) return no("tree.drop_no_write");
  if (lead) {
    if (!(n.links && n.links.session)) return no("tree.drop_no_here");
    if ((n.session_owner || n.owner) !== me) return no("tree.drop_no_others_lead");
    if (n.links.session === s.id || treeHelpers(n).some((h) => h.session === s.id && h.owner === me)) return no("tree.drop_no_already");
    return { ok: true, label: "🤝 " + t("tree.helper") };
  }
  let own = (treeData.nodes || []).filter((x) => x.owner === me && x.links && x.links.session === s.id
      && x.state !== "done" && !(x.ball && x.ball.kind === "done"))
    .sort((a, b) => a.created_ts - b.created_ts)[0];
  if (own && own.rest) own = (treeData.nodes || []).find((x) => x.id === own.parent);
  const leadSid = n.links && n.links.session;
  if (!own && leadSid && leadSid !== s.id && !n.rest) {
    if ((n.session_owner || n.owner) !== me) return no("tree.drop_no_others_lead");
    if (treeHelpers(n).some((h) => h.session === s.id && h.owner === me)) return no("tree.drop_no_already");
    return { ok: true, label: "🤝 " + t("tree.helper") };
  }
  if (own) {
    if (own.id === n.id) return no("tree.drop_no_already");
    for (let x = n, i = 0; x && i < 1000; x = x.parent && c.byId.get(x.parent), i++) if (x.id === own.id) return no("tree.drop_no_under_itself");
    return { ok: true, label: "↳ " + t("tree.drop_move_here") };
  }
  return { ok: true, label: "🧭 " + t("tree.lead") };
}
async function treeLinkSession(n, s) {
  if (!s) return;
  // Only an item the session still has open (2026-11-27: the oldest one,
  // long done, was moved under the drop target, which then counted as
  // done and vanished).
  let own = (treeData.nodes || []).filter((x) => x.owner === treeData.user && x.links && x.links.session === s.id
      && x.state !== "done" && !(x.ball && x.ball.kind === "done"))
    .sort((a, b) => a.created_ts - b.created_ts)[0];
  if (own && own.rest) own = (treeData.nodes || []).find((x) => x.id === own.parent);
  // 🤝 Onto an item with a 担当: a session holding no item of its own helps
  // that 担当 (the deployment notes; linked to it by talkto). One that holds an
  // item is a 担当 itself: its item moves under this one, as before.
  const lead = n.links && n.links.session;
  if (!own && lead && lead !== s.id && !n.rest && (n.owner === treeData.user || (n.members || []).includes(treeData.user))) {
    await treeHelpLead(n, s);
    return;
  }
  if (own) {
    if (own.id === n.id) return;
    await treeOp({ op: "update", id: own.id, parent: n.id });
  } else if (!(n.links && n.links.session) && !n.rest && !(treeData.nodes || []).some((x) => x.parent === n.id && x.rest)
      && (n.owner === treeData.user || (n.members || []).includes(treeData.user))) {
    // ▶ セッションで作業 → 既存 on a node no session works on: that session works on it.
    // Asked first, as everything but a plain move (2026-11-27, the user:
    // 確認は単純な移動以外で全て出してください).
    if (!confirm(t("tree.make_lead_confirm", { s: s.label, item: n.title }))) return;
    await treeOp({ op: "update", id: n.id, links: Object.assign({}, n.links || {}, { session: s.id }) });
  } else {
    if (!confirm(t("tree.make_child_lead_confirm", { s: s.label, item: n.title }))) return;
    await treeOp({ op: "add", parent: n.id, title: s.label, visibility: n.visibility, links: { session: s.id } });
  }
}
// 🧑‍🤝‍🧑 Who sees a tree and who changes it, in one panel (2026-11-23, the
// user: 木を見られる人を全体、書ける人を数人などにしたい。利用者名は一覧と
// 候補がほしい). Seeing: the owner and the writers, or the whole lab.
// Writers (who also see it): picked from the lab's users (the list comes
// with the tree); the box narrows the list and Enter adds the one it names.
function treeSharePanel(n, box, closeMenu) {
  const users = (treeData && treeData.lab_users) || [];
  const me = treeData.user;
  let vis = n.visibility === "lab" ? "lab" : "self";
  const sel = new Set(n.members || []);
  // In the ⋯ menu, under its item (2026-11-23: first an overlay, which
  // the to-do view's body.todo-page hid; then all inputs into the menu).
  const ov = document.createElement("div");
  ov.className = "tshare";
  const rname = "tsv-" + n.id;
  ov.innerHTML = `
    <div class="tshare-sec"><b>${escapeHtml(t("tree.who_can_see"))}</b>
      <label><input type="radio" name="${rname}" value="self"> ${escapeHtml(t("tree.those_who_can_edit"))}</label>
      <label><input type="radio" name="${rname}" value="lab"> ${escapeHtml(t("tree.everyone_in_ai_za"))}</label></div>
    <div class="tshare-sec"><b>${escapeHtml(t("tree.who_can_edit_they_can"))}</b>
      <div class="tshare-chosen"></div>
      <input type="search" class="tshare-q" placeholder="${escapeHtml(t("tree.filter_name_enter_adds"))}" autocapitalize="off" autocorrect="off" autocomplete="off">
      <div class="tshare-list"></div></div>
    <div class="tshare-btns"><button class="tshare-cancel">${escapeHtml(t("common.cancel"))}</button><button class="tshare-save on">${escapeHtml(t("common.save"))}</button></div>`;
  const $ = (q) => ov.querySelector(q);
  for (const r of ov.querySelectorAll('input[type="radio"]')) {
    r.checked = r.value === vis;
    r.addEventListener("change", () => { vis = r.value; });
  }
  const label = (u) => { const x = users.find((y) => y.user === u); return x && x.name ? `${u}(${x.name})` : u; };
  const draw = () => {
    const chosen = $(".tshare-chosen");
    chosen.innerHTML = sel.size ? "" : `<span class="tshare-none">${escapeHtml(t("tree.no_one_yet"))}</span>`;
    for (const u of [...sel].sort()) {
      const b = document.createElement("button");
      b.className = "tchip on"; b.textContent = label(u) + " ×"; b.title = t("common.remove");
      b.addEventListener("click", () => { sel.delete(u); draw(); });
      chosen.appendChild(b);
    }
    const q = $(".tshare-q").value.trim().toLowerCase();
    const list = $(".tshare-list");
    list.innerHTML = "";
    for (const x of users) {
      if (x.user === n.owner || x.user === me || sel.has(x.user)) continue;
      if (q && !(x.user.toLowerCase().includes(q) || (x.name || "").toLowerCase().includes(q))) continue;
      const b = document.createElement("button");
      b.className = "tchip"; b.textContent = "＋ " + label(x.user);
      b.addEventListener("click", () => { sel.add(x.user); $(".tshare-q").value = ""; draw(); });
      list.appendChild(b);
    }
    if (!list.children.length) list.innerHTML = `<span class="tshare-none">${escapeHtml(q ? t("tree.no_one_matches") : t("tree.no_one_else_add"))}</span>`;
  };
  $(".tshare-q").addEventListener("input", draw);
  $(".tshare-q").addEventListener("keydown", (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const q = e.target.value.trim().toLowerCase();
    const hits = users.filter((x) => x.user !== n.owner && !sel.has(x.user)
      && (x.user.toLowerCase().includes(q) || (x.name || "").toLowerCase().includes(q)));
    const exact = hits.find((x) => x.user.toLowerCase() === q);
    const pick = exact || (hits.length === 1 ? hits[0] : null);
    if (pick) { sel.add(pick.user); e.target.value = ""; draw(); }
  });
  const close = () => closeMenu();
  $(".tshare-cancel").addEventListener("click", close);
  $(".tshare-save").addEventListener("click", () => {
    const body = { op: "update", id: n.id };
    if (vis !== (n.visibility === "lab" ? "lab" : "self")) body.visibility = vis;
    const members = [...sel].sort();
    if (members.join(",") !== [...(n.members || [])].sort().join(",")) body.members = members;
    close();
    if (Object.keys(body).length > 2) treeOp(body);
  });
  draw();
  box.appendChild(ov);
}
// ↕ Arranging the tree (2026-11-23, the user: 兄弟の順番も変えたくなる。
// ドラッグアンドドロップで編集できるモード). Each of one's own rows has ⠿;
// dragged (mouse, finger or pen), it carries its branches along:
//  - onto the top or bottom part of a row: just before / after it, among
//    its siblings (after an open row with its children showing: its
//    first child);
//  - onto the middle of a row that can take it: its last child.
// Siblings sort by `order` (a number between its neighbours'), else by
// when made; その他 stays last.
function treeKey(n) { return n.order != null ? n.order : n.created_ts; }
let treeDrag = null;
function wireTreeDrag(grip) {
  grip.addEventListener("pointerdown", (e) => {
    if (e.button !== 0 || treeDrag || !treeArrange) return;
    e.preventDefault();
    const row = grip.parentNode, out = row.closest(".tree");
    const nodes = (treeData && treeData.nodes) || [];
    const byId = new Map(nodes.map((x) => [x.id, x]));
    const id = row.dataset.id;
    const below = (x) => { for (let p = x, i = 0; p && i < 1000; p = byId.get(p.parent), i++) if (p.id === id) return true; return false; };
    // The list draws each folder's trees in its own .tree box: any of them
    // can take it (2026-11-27, the user: 安全性をサーバー管理に落とせません).
    const list = row.closest("#sessions");
    const rows = Array.from((list || out).querySelectorAll(list ? ".tree .tnode[data-id]" : ".tnode[data-id]"));
    const carried = rows.filter((r) => r !== row && below(byId.get(r.dataset.id)));
    for (const r of carried) r.style.display = "none";
    const scroller = (() => { for (let el = out.parentElement; el; el = el.parentElement) { const o = getComputedStyle(el).overflowY; if ((o === "auto" || o === "scroll") && el.scrollHeight > el.clientHeight) return el; } return document.scrollingElement; })();
    // A root can also go onto a folder row of 仕事's tree (the deployment notes 段4,
    // 2026-11-26, the user: 並べ替えで木をフォルダに入れられない): its folder.
    const node0 = byId.get(id);
    const folderRows = node0 && !(node0.parent && byId.has(node0.parent))
      ? Array.from(document.querySelectorAll("#sessions > .session-row[data-folder-id], #archived-list .session-row[data-folder-id]")) : [];
    treeDrag = { pointerId: e.pointerId, row, id, byId, below, rows: rows.filter((r) => r !== row && !carried.includes(r)), carried, folderRows,
                 startY: e.clientY + scroller.scrollTop, lastY: e.clientY, scroller, drop: null, moved: false, timer: null };
    row.classList.add("dragging");
    grip.setPointerCapture(e.pointerId);
  });
  grip.addEventListener("pointermove", (e) => {
    const st = treeDrag;
    if (!st || st.pointerId !== e.pointerId) return;
    st.lastY = e.clientY;
    treeDragMoved();
    const box = st.scroller === document.scrollingElement ? { top: 0, bottom: innerHeight } : st.scroller.getBoundingClientRect();
    const speed = e.clientY < box.top + 48 ? -20 : e.clientY > box.bottom - 48 ? 20 : 0;
    clearInterval(st.timer);
    st.timer = speed ? setInterval(() => { if (treeDrag !== st) return clearInterval(st.timer); st.scroller.scrollTop += speed; treeDragMoved(); }, 30) : null;
  });
  const stop = (e) => { if (treeDrag && treeDrag.pointerId === e.pointerId) endTreeDrag(); };
  grip.addEventListener("pointerup", stop);
  grip.addEventListener("pointercancel", stop);
  grip.addEventListener("lostpointercapture", stop);
  grip.addEventListener("click", (e) => e.stopPropagation());
}
function treeCanTake(x, st) {
  const me = treeData.user;
  return !x.rest && !st.below(x) && (x.owner === me || (x.members || []).includes(me));
}
function treeDragMoved() {
  const st = treeDrag;
  const dy = st.lastY + st.scroller.scrollTop - st.startY;
  if (Math.abs(dy) > 4) st.moved = true;
  st.row.style.transform = `translateY(${dy}px)`;
  let drop = null;
  for (const r of st.rows) {
    const b = r.getBoundingClientRect();
    if (!b.height || st.lastY < b.top || st.lastY >= b.bottom) continue;
    const x = st.byId.get(r.dataset.id), f = (st.lastY - b.top) / b.height;
    drop = f > 0.3 && f < 0.7 && treeCanTake(x, st) ? { row: r, how: "into" } : { row: r, how: f < 0.5 ? "before" : "after" };
    break;
  }
  if (!drop) {
    for (const r of st.folderRows) {
      const b = r.getBoundingClientRect();
      if (b.height && st.lastY >= b.top && st.lastY < b.bottom && !window.aizaExt.folder(r.dataset.folderId)) { drop = { row: r, how: "into", folder: r.dataset.folderId }; break; }
    }
  }
  for (const r of st.rows.concat(st.folderRows)) r.classList.remove("drop-before", "drop-after", "drop-into");
  if (drop) drop.row.classList.add("drop-" + drop.how);
  st.drop = drop;
}
function endTreeDrag() {
  const st = treeDrag;
  treeDrag = null;
  clearInterval(st.timer);
  st.row.style.transform = "";
  st.row.classList.remove("dragging");
  for (const r of st.carried) r.style.display = "";
  for (const r of st.rows.concat(st.folderRows)) r.classList.remove("drop-before", "drop-after", "drop-into");
  if (!st.moved || !st.drop) return;
  if (st.drop.folder) {   // a root onto a folder: that folder is where it goes
    saveFolders([{ op: "tree_root", node: st.id, folder: st.drop.folder }]).then(() => loadTree());
    return;
  }
  const me0 = treeData.user, n0 = st.byId.get(st.id);
  if (!(n0.owner === me0 || (n0.members || []).includes(me0))) return;   // someone else's tree: only its folder
  const n = st.byId.get(st.id);
  const target = st.byId.get(st.drop.row.dataset.id);
  const kidsOf = (p) => ((treeData && treeData.nodes) || [])
    .filter((x) => (x.parent && st.byId.has(x.parent) ? x.parent : null) === p && x.id !== st.id && !x.rest)
    .sort((a, b) => treeKey(a) - treeKey(b));
  let parent, prev, next;
  const open = st.drop.how === "after" && st.rows.some((r) => r.dataset.id !== st.id && st.byId.get(r.dataset.id).parent === target.id && r.style.display !== "none");
  if (st.drop.how === "into") {
    parent = target.id; const k = kidsOf(parent); prev = k[k.length - 1]; next = null;
  } else if (open) {
    if (target.id !== n.parent && !treeCanTake(target, st)) return;
    parent = target.id; const k = kidsOf(parent); prev = null; next = k[0];
  } else {
    parent = target.parent && st.byId.has(target.parent) ? target.parent : null;
    const cur0 = n.parent && st.byId.has(n.parent) ? n.parent : null;
    if (parent && parent !== cur0 && !treeCanTake(st.byId.get(parent), st)) return;
    if (target.rest) return;
    const k = kidsOf(parent), i = k.findIndex((x) => x.id === target.id);
    if (st.drop.how === "before") { prev = k[i - 1]; next = target; } else { prev = target; next = k[i + 1]; }
  }
  const order = prev && next ? (treeKey(prev) + treeKey(next)) / 2
    : prev ? treeKey(prev) + 1 : next ? treeKey(next) - 1 : Date.now() / 1000;
  const cur = n.parent && st.byId.has(n.parent) ? n.parent : null;
  const body = { op: "update", id: st.id, order };
  if (parent !== cur) body.parent = parent;
  // A whole tree into another: asked first, and out of its folder after.
  if (!cur && parent) {
    if (!confirm(t("tree.root_into_confirm", { a: treeTitleText(n), b: treeTitleText(st.byId.get(parent)) }))) return;
    api("/tree", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(() => saveFolders([{ op: "tree_root", node: st.id, folder: "" }]))
      .catch((e) => alert(e.message)).then(() => loadTree());
    return;
  }
  treeOp(body);
}
function treeIndex() {
  const nodes = treeData.nodes || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const kids = new Map();
  for (const n of nodes) {
    const p = n.parent && byId.has(n.parent) ? n.parent : null;
    if (!kids.has(p)) kids.set(p, []);
    kids.get(p).push(n);
  }
  return { nodes, byId, kids };
}
function treeLeafRow(n, me, extra) {
  const row = document.createElement("div");
  row.className = "tnode";
  row.style.setProperty("--d", 0);
  row.appendChild(document.createElement("span"));
  const main = document.createElement("div");
  main.className = "tmain";
  const href = treeSessionHref(n, me);
  const title = treeTitleEl(n, href ? "a" : "span");
  title.className = "tt" + (href ? " tlink" : "");
  if (href) title.href = href;
  main.appendChild(title);
  const trb = treeTrBadge(n);
  if (trb) main.appendChild(trb);
  if (extra) main.insertAdjacentHTML("beforeend", extra);
  row.appendChild(main);
  // 🌳 to this node in the tree (2026-11-20, the user: 止めてるもの一覧から、
  // 枝にジャンプできるように).
  const end = document.createElement("span");
  if (treeData && (treeData.nodes || []).some((x) => x.id === n.id)) {
    const go = document.createElement("button");
    go.className = "tmore"; go.textContent = "🌳"; go.title = t("tree.show_in_tree");
    go.addEventListener("click", (e) => { e.stopPropagation(); jumpToTreeNode(n.id); });
    end.className = "tbtns";
    end.appendChild(go);
  }
  row.appendChild(end);
  return row;
}
const holderOf = (n, me) => {
  const b = n.ball || {};
  if (n.left && n.state !== "done") return "⏸ " + t("tree.left_behind_session_moved_on");
  if (b.kind === "person") return b.who === me ? "🙋 " + t("common.you") : "🙋 " + (b.who || "?");
  return { ai: "🤖 AI", sleep: "💤 " + t("common.waiting_snoozed"), ext: "✉ " + t("tree.waiting_on_others") }[b.kind] || t("tree.nobody_holds_yet");
};
// A parent's own open work, with no その他 child for it (2026-11-22: その他
// is made only when the parent's session goes on working on it): it counts
// as one more open item, like a leaf.
const ownOpen = (n, k) => !!(k && k.length && !k.some((c) => c.rest) && n.links && n.links.session
  && n.state !== "done" && n.ball && n.ball.kind !== "done");
const stuckDays = (n) => (n.ball && n.ball.since && n.state !== "done" && n.ball.kind !== "done" ? Math.floor((Date.now() / 1000 - n.ball.since) / 86400) : 0);
const pathOf = (n, byId, stop) => {
  const out = [];
  for (let p = byId.get(n.parent); p && p.id !== stop; p = byId.get(p.parent)) out.unshift(p.title);
  return out;
};
// 🙋 番ごと's part from the work tree (the deployment notes 段5, 2026-11-25:
// the to-do list and 人と AI as one): the open leaves no session of this
// user holds (those are in the list already), by whose turn it is --
// mine, waiting on others outside, someone else's, nobody's yet. A DOM
// box per group, made by todo.js's list.
function treeTurns() {
  if (!treeData || treeData.unavailable) return null;
  const me = treeData.user;
  const { nodes, byId, kids } = treeIndex();
  const out = { you: [], ext: [], others: [], none: [] };
  for (const n of nodes) {
    const nk = kids.get(n.id) || [];
    if (nk.length ? !ownOpen(n, nk) : (n.state === "done" || (n.ball && n.ball.kind === "done"))) continue;
    if (n.links && n.links.session && (n.session_owner || n.owner) === me) continue;   // its session is in the list
    const b = n.ball || {};
    const k = b.kind === "person" ? (b.who === me ? "you" : "others") : b.kind === "ext" ? "ext"
      : b.kind === "ai" || b.kind === "sleep" ? null : "none";
    if (k) out[k].push(n);
  }
  for (const k of Object.keys(out)) out[k].sort((a, b) => stuckDays(b) - stuckDays(a));
  return { out, byId, me };
}
function treeTurnRows(list, byId, me, withWho) {
  const box = document.createElement("div");
  box.className = "tree";
  for (const n of list) {
    const path = pathOf(n, byId, null);
    const d = stuckDays(n);
    const b = n.ball || {};
    box.appendChild(treeLeafRow(n, me, (withWho && b.who ? `<span class="tsum">🙋 ${escapeHtml(b.who)}</span>` : "")
      + (path.length ? `<span class="tsum">🌳 ${escapeHtml(path.join(" / "))}</span>` : "")
      + (d >= 3 ? `<span class="tstale">${escapeHtml(t("tree.stuck_n_days", { n: d }))}</span>` : "")));
  }
  return box;
}
// C: what holds a job up -- each open leaf below it, with the way down.
function renderChain(box) {
  const me = treeData.user;
  const { byId, kids } = treeIndex();
  const top = byId.get(todoNow().chain);
  const back = document.createElement("button");
  back.className = "tree-back"; back.textContent = "← " + t("tree.back_tree");
  // Back to 仕事's tree, where ⛓ was opened (the deployment notes 段5).
  back.addEventListener("click", () => { setTodo({ chain: null }); ui.tabs.show("work", "tree"); });
  box.appendChild(back);
  if (!top) { setTimeout(() => setTodo({ chain: null }), 0); return; }   // not during this draw
  box.insertAdjacentHTML("beforeend", `<div class="group">⛓ ${escapeHtml(t("tree.what_holds_up_p", { p: top.title }))}</div>`);
  const leaves = [];
  (function walk(n) {
    const k = kids.get(n.id) || [];
    if (!k.length) { if (n.id !== top.id && n.state !== "done" && !(n.ball && n.ball.kind === "done")) leaves.push(n); return; }
    if (ownOpen(n, k)) leaves.push(n);
    for (const c of k) if (c.state !== "done") walk(c);
  })(top);
  if (!leaves.length) { box.insertAdjacentHTML("beforeend", `<div class="empty">${escapeHtml(t("tree.nothing_holds_up"))}</div>`); return; }
  const out = document.createElement("div"); out.className = "tree";
  for (const n of leaves.sort((a, b) => stuckDays(b) - stuckDays(a))) {
    const chain = [top.title, ...pathOf(n, byId, top.id)].join(" ← ");
    const d = stuckDays(n);
    out.appendChild(treeLeafRow(n, me, `<span class="tball k-${escapeHtml((n.ball || {}).kind || "none")}">${escapeHtml(holderOf(n, me))}</span>`
      + `<span class="tsum">${escapeHtml(chain)} ←</span>`
      + (d >= 3 ? `<span class="tstale">${escapeHtml(t("tree.stuck_n_days", { n: d }))}</span>` : "")));
  }
  box.appendChild(out);
}
function renderWeek(box) {
  if (!weekData || Date.now() - weekAt > 60000) {
    weekAt = Date.now();
    api("/tree/week").then((r) => { weekData = r; if (todoIs("tree", "week")) renderTodo(); })
      .catch((e) => { weekData = { unavailable: e.message }; });
    if (!weekData) { box.insertAdjacentHTML("beforeend", `<div class="empty">${t("common.loading")}</div>`); return; }
  }
  if (weekData.unavailable) { box.insertAdjacentHTML("beforeend", `<div class="empty">${escapeHtml(t("common.host_no_work_tree"))}</div>`); return; }
  const me = treeData ? treeData.user : null;
  const sec = (title, list, extra) => {
    box.insertAdjacentHTML("beforeend", `<div class="group">${escapeHtml(title)} (${list.length})</div>`);
    if (!list.length) return;
    const out = document.createElement("div"); out.className = "tree";
    for (const x of list) out.appendChild(treeLeafRow({ ...x, links: { session: x.session } }, me, extra(x)));
    box.appendChild(out);
  };
  box.insertAdjacentHTML("beforeend", `<div class="note">${escapeHtml(t("tree.last_7_days_since_d", { d: fmtUntil(weekData.since) }))}</div>`);
  sec("✓ " + t("tree.done"), weekData.done, () => "");
  sec("⚙️ " + t("tree.moved"), weekData.moving, (x) => `<span class="tsum">${escapeHtml(holderOf(x, me))}</span>`);
  sec("⏳ " + t("tree.stuck_3_days_2"), weekData.stuck, (x) => `<span class="tstale">${escapeHtml(t("tree.stuck_n_days", { n: x.days }))}</span> <span class="tsum">${escapeHtml(holderOf(x, me))}</span>`);
  sec("🔁 " + t("tree.went_back_forth"), weekData.pingpong, (x) => `<span class="tsum">${escapeHtml(t("tree.handed_over_n_times", { n: x.changes }))}</span>`);
}

// Who used aiza how much (the deployment notes, 2026-11-23, the user: 研究室の全員が
// 全員分。時間帯までは出さない、プライバシーなので。人々がどの仕事にどの
// くらいかかわっているかも、タスクの木ごとに). aiza-usage-collect counts
// per week; nodes are named from the viewer's own tree, and one the viewer
// cannot see is only "not shown".
function renderUsage(box) {
  if (!usageData || Date.now() - usageAt > 60000) {
    usageAt = Date.now();
    api("/usage").then((r) => { usageData = r; if (todoIs("tree", "usage")) renderTodo(); })
      .catch((e) => { usageData = { unavailable: e.message }; if (todoIs("tree", "usage")) renderTodo(); });
    if (!usageData) { box.insertAdjacentHTML("beforeend", `<div class="empty">${t("common.loading")}</div>`); return; }
  }
  if (usageData.unavailable) { box.insertAdjacentHTML("beforeend", `<div class="empty">${escapeHtml(t("tree.not_counted_yet"))}</div>`); return; }
  const names = usageData.names || {};
  const nameOf = (u) => names[u] || u;
  const weeks = [...new Set((usageData.rows || []).map((r) => r.week).filter((w) => w !== "before"))].sort();
  const from = usageSpan ? weeks.slice(-usageSpan)[0] : null;
  const rows = (usageData.rows || []).filter((r) => (usageSpan ? r.week !== "before" && r.week >= from : true));
  const fmtTok = (n) => (n >= 1e9 ? (n / 1e9).toFixed(1) + "G" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? Math.round(n / 1e3) + "k" : String(Math.round(n || 0)));
  const fmtCost = (c) => "$" + (c >= 100 ? Math.round(c) : (c || 0).toFixed(1));
  const sum = (list) => list.reduce((a, r) => { for (const k of ["msgs", "sessions", "tokens", "cost"]) a[k] += r[k] || 0; return a; },
    { msgs: 0, sessions: 0, tokens: 0, cost: 0 });
  const groupBy = (list, key) => { const m = new Map(); for (const r of list) { const k = key(r); if (!m.has(k)) m.set(k, []); m.get(k).push(r); } return m; };

  const bar = document.createElement("div");
  bar.className = "tree-bar";
  for (const [n, label] of [[1, t("tree.1_week")], [4, t("tree.4_weeks")], [12, t("tree.12_weeks")], [0, t("common.all_2")]]) {
    const b = document.createElement("button");
    b.textContent = label; b.className = usageSpan === n ? "on" : "";
    b.addEventListener("click", () => { usageSpan = n; renderTodo(); });
    bar.appendChild(b);
  }
  box.appendChild(bar);
  box.insertAdjacentHTML("beforeend", `<div class="note">${escapeHtml(t("tree.counted_per_week_sent_messages",
    { d: fmtUntil(usageData.since) }))}</div>`);

  // People
  const people = [...groupBy(rows, (r) => r.who)].map(([u, list]) => ({ u, ...sum(list) })).sort((a, b) => b.msgs - a.msgs || b.tokens - a.tokens);
  const maxMsgs = Math.max(1, ...people.map((p) => p.msgs));
  box.insertAdjacentHTML("beforeend", `<div class="group">🧑‍🤝‍🧑 ${escapeHtml(t("tree.person"))}</div>`);
  const tbl = document.createElement("div"); tbl.className = "usage-people";
  tbl.insertAdjacentHTML("beforeend", `<div class="uh"><span>${escapeHtml(t("common.person"))}</span><span>${escapeHtml(t("tree.sent"))}</span><span>${escapeHtml(t("common.new_sessions"))}</span><span>${escapeHtml(t("tree.tokens"))}</span><span>${escapeHtml(t("tree.estimate"))}</span></div>`);
  for (const p of people) {
    tbl.insertAdjacentHTML("beforeend", `<div class="ur"><span class="un">${escapeHtml(nameOf(p.u))}<i style="width:${Math.round(100 * p.msgs / maxMsgs)}%"></i></span>`
      + `<span>${p.msgs}</span><span>${p.sessions}</span><span>${fmtTok(p.tokens)}</span><span>${fmtCost(p.cost)}</span></div>`);
  }
  box.appendChild(tbl);

  // Weeks
  const shown = usageSpan ? weeks.slice(-usageSpan) : weeks;
  if (shown.length) {
    box.insertAdjacentHTML("beforeend", `<div class="group">📅 ${escapeHtml(t("tree.messages_sent_per_week"))}</div>`);
    const byWeek = groupBy(rows.filter((r) => r.week !== "before"), (r) => r.week);
    const maxW = Math.max(1, ...shown.map((w) => sum(byWeek.get(w) || []).msgs));
    const wl = document.createElement("div"); wl.className = "usage-weeks";
    for (const w of shown.slice().reverse()) {
      const list = byWeek.get(w) || [];
      const top = [...groupBy(list, (r) => r.who)].map(([u, l]) => [u, sum(l).msgs]).filter((x) => x[1]).sort((a, b) => b[1] - a[1]);
      const tot = sum(list).msgs;
      wl.insertAdjacentHTML("beforeend", `<div class="uw"><span class="wd">${escapeHtml(w.slice(5).replace("-", "/"))}〜</span>`
        + `<span class="wb"><i style="width:${Math.round(100 * tot / maxW)}%"></i><b>${tot}</b></span>`
        + `<span class="wp">${top.slice(0, 4).map(([u, n]) => `${escapeHtml(nameOf(u))} ${n}`).join("・")}${top.length > 4 ? "…" : ""}</span></div>`);
    }
    box.appendChild(wl);
  }

  // Per tree: each node under its root (and the root's own children)
  const byId = new Map(((treeData && treeData.nodes) || []).map((n) => [n.id, n]));
  const chainOf = (id) => { const c = []; let n = byId.get(id), guard = 0; while (n && guard++ < 200) { c.unshift(n); n = n.parent && byId.get(n.parent); } return c; };
  const placed = rows.map((r) => {
    if (!r.node) return { ...r, top: "_none", branch: null };
    const c = r.node !== "private" && byId.has(r.node) ? chainOf(r.node) : null;
    if (!c) return { ...r, top: "_hidden", branch: null };
    return { ...r, top: c[0].id, branch: c[1] ? c[1].id : null };
  });
  const who = (list) => [...groupBy(list, (r) => r.who)].map(([u, l]) => ({ u, ...sum(l) })).sort((a, b) => b.tokens - a.tokens || b.msgs - a.msgs)
    .map((p) => `<span class="up">${escapeHtml(nameOf(p.u))} <small>${escapeHtml(t("tree.m_sent_k", { m: p.msgs, k: fmtTok(p.tokens) }))}</small></span>`).join("");
  const head = (title, s) => `<span class="ut">${escapeHtml(title)}</span><span class="us">${escapeHtml(t("tree.m_sent_k_c", { m: s.msgs, k: fmtTok(s.tokens), c: fmtCost(s.cost) }))}</span>`;
  box.insertAdjacentHTML("beforeend", `<div class="group">🌳 ${escapeHtml(t("tree.work_tree"))}</div>`);
  const tops = [...groupBy(placed, (r) => r.top)].map(([k, list]) => ({ k, list, s: sum(list) }))
    .sort((a, b) => (a.k.startsWith("_") - b.k.startsWith("_")) || b.s.tokens - a.s.tokens || b.s.msgs - a.s.msgs);
  const tl = document.createElement("div"); tl.className = "usage-trees";
  for (const g of tops) {
    const title = g.k === "_none" ? t("tree.sessions_not_in_tree") : g.k === "_hidden" ? "🔒 " + t("tree.work_cannot_see") : (byId.get(g.k) || {}).title || g.k;
    const d = document.createElement("details");
    d.innerHTML = `<summary>${head(title, g.s)}</summary><div class="uw2">${who(g.list)}</div>`;
    if (!g.k.startsWith("_")) {
      const br = [...groupBy(g.list.filter((r) => r.branch), (r) => r.branch)].map(([k, list]) => ({ k, list, s: sum(list) }))
        .sort((a, b) => b.s.tokens - a.s.tokens || b.s.msgs - a.s.msgs);
      for (const b of br) {
        d.insertAdjacentHTML("beforeend", `<div class="ub">${head((byId.get(b.k) || {}).title || b.k, b.s)}<div class="uw2">${who(b.list)}</div></div>`);
      }
    }
    tl.appendChild(d);
  }
  box.appendChild(tl);
}

// ---- The tree view in Preact (2026-11-23, the user chose it: the 30 s
// refresh rebuilt the page and closed an open ⋯ → 「React と同じやり方に」).
// The view is drawn from the data each time, but rows are keyed by the
// node's id, so Preact changes only what changed; the open ⋯, its open
// panel (its inputs, the ▶ 既存 list and their scroll) live on through a
// refresh. Preact 10.29.8 + htm 3.1.1, vendored in static/vendor/ (no build
// step, no CDN). Dragging (⠿), the menu's placement and the keyboard
// handling stay plain DOM code; the panels' insides are built by the
// tree* helpers above, once, when a panel opens (DomPanel).
// Every TreeView's open ⋯ (the to-do page's, and one per folder of 仕事's
// tree, the deployment notes 段4): closing closes them all.
const treeMenuClosers = new Set();
function treeMenuClose() { for (const f of treeMenuClosers) f(); }
// The tree is part of the to-do page's one Preact root (TodoPage), and of
// 仕事's tree (the session list's folders, ui.trees.mount): its own redraws
// (open/close, filter...) draw those again, which only changes what differs.
function treeRerender() { if (todoOn()) renderTodo(); treeRedrawMounted(); }
// ---- 仕事's tree (the deployment notes 段4, 2026-11-25) -------------------------
// The work tree's roots drawn inside the session list's folders: a root goes
// in the session folder its tree's sessions go in (n.folder: picked on its
// ⋯, else guessed), none -- 「フォルダに入れていない木」 at the end -- when
// it has none. Each folder's roots are one bare TreeView in a box the list
// keeps across its redraws (so an open ⋯ stays open).
const treeMounts = new Map();   // box -> the roots it draws
function treePlaceOf(n) {
  const f = n.folder && n.folder.id;
  return f && folderDoc.folders.some((x) => x.id === f && !x.archived) ? f : null;
}
function treeRootsIn(folder, done) {
  if (!treeData || treeData.unavailable) return [];
  const c = treeContext(treeData);
  return (c.kids.get(null) || []).filter((n) => treePlaceOf(n) === folder && !!c.isDone(n) === !!done && c.match(n)).map((n) => n.id);
}
function treeDoneRoots() {
  if (!treeData || treeData.unavailable) return [];
  const c = treeContext(treeData);
  // (A finished tree may be in an archived folder: the archive's.)
  return (c.kids.get(null) || []).filter((n) => c.isDone(n)).map((n) => ({
    id: n.id, folder: n.folder && folderDoc.folders.some((x) => x.id === n.folder.id) ? n.folder.id : null }));
}
// This user's sessions an item of the tree holds: drawn on the item, not again as a row.
// Only an open item (not done, in a tree not done) holds its session there: a
// session whose items are all finished (a long-lived session that handed
// many jobs on, 2026-11-26, the user: このセッションが一覧から探せません)
// stays in its folder.
function treeLinkedSessions() {
  const out = new Set();
  if (!treeData || !treeData.nodes || treeData.unavailable) return out;
  const c = treeContext(treeData);
  const rootOf = (n) => { let x = n; for (let i = 0; x && x.parent && c.byId.has(x.parent) && i < 1000; i++) x = c.byId.get(x.parent); return x; };
  for (const n of treeData.nodes) {
    const sid = n.links && n.links.session;
    if (sid && (n.session_owner || n.owner) === treeData.user && !c.isDone(n) && !c.isDone(rootOf(n))) out.add(sid);
    // 🤝 A helper is with its 担当's item, not in its folder.
    if (!c.isDone(n) && !c.isDone(rootOf(n))) for (const h of treeHelpers(n)) if (h.owner === treeData.user) out.add(h.session);
  }
  return out;
}
function treeMount(box, roots) {
  treeMenuHooks();
  treeMounts.set(box, roots);
  if (html && treeData) window.preact.render(html`<${TreeView} data=${treeData} roots=${roots} bare=${true} />`, box);
}
function treeRedrawMounted() {
  for (const [box, roots] of treeMounts) {
    if (!box.isConnected) { treeMounts.delete(box); continue; }
    if (html && treeData) window.preact.render(html`<${TreeView} data=${treeData} roots=${roots} bare=${true} />`, box);
  }
}
// The start screen's 置く場所 (the deployment notes 段4): the folders, each
// with the trees put in it and their open items, then the trees in no
// folder -- {value: "f:<folder>" | "n:<node>", label, depth}.
function treePlaceOptions() {
  const out = [];
  const c = treeData && !treeData.unavailable ? treeContext(treeData) : null;
  const items = (n, depth) => {
    if (c.isDone(n)) return;
    out.push({ value: "n:" + n.id, label: "• " + treeTitleText(n), depth, node: true });
    for (const k of c.kids.get(n.id) || []) items(k, depth + 1);
  };
  const roots = (folder, depth) => {
    if (!c) return;
    for (const n of c.kids.get(null) || []) {
      if (treePlaceOf(n) !== folder || c.isDone(n)) continue;
      out.push({ value: "n:" + n.id, label: "🌳 " + treeTitleText(n), depth, node: true });
      for (const k of c.kids.get(n.id) || []) items(k, depth + 1);
    }
  };
  const folders = (pid, depth) => {
    for (const f of folderDoc.folders.filter((x) => (x.parent || null) === pid && !x.archived && !window.aizaExt.folder(x.id))) {
      out.push({ value: "f:" + f.id, label: "📁 " + f.name, depth });
      folders(f.id, depth + 1);
      roots(f.id, depth + 1);
    }
  };
  folders(null, 0);
  roots(null, 0);
  return out;
}
function treeNodeById(id) { return treeData && treeData.nodes ? treeData.nodes.find((n) => n.id === id) || null : null; }
ui.trees = Object.assign(ui.trees || {}, {
  ready: () => !!treeData && !treeData.unavailable,
  load: () => { if (!treeData || Date.now() - treeAt > 20000) loadTree(); },
  rootsIn: treeRootsIn, doneRoots: treeDoneRoots, linked: treeLinkedSessions, mount: treeMount,
  filter: () => treeFilter, setFilter: (f) => { treeFilter = f; treeRerender(); },
  // A new tree, in a folder when one is given (＋ 🌳 with a folder selected).
  add: async (title, folder) => {
    try {
      const r = await api("/tree", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "add", title }) });
      if (folder && r && r.node && r.node.id) await saveFolders([{ op: "tree_root", node: r.node.id, folder }]);
    } catch (e) { alert(e.message); }
    loadTree();
  },
  node: (id) => treeNodeById(id),
  title: (id) => { const n = treeNodeById(id); return n ? treeTitleText(n) : ""; },
  isRoot: (id) => { const n = treeNodeById(id); return !!n && !(n.parent && treeNodeById(n.parent)); },
  selStartCtx: (id) => { const n = treeNodeById(id); return n ? treeSelStartCtx(n) : null; },
  childPanel: (id, box, close) => { const n = treeNodeById(id); if (n && treeData) treeChildPanel(n, treeData.user, box, close); },
  setArrange: (on) => { treeArrange = !!on; treeRerender(); },
  linkSession: async (id, sess) => { const n = treeNodeById(id); if (n) { await treeLinkSession(n, sess); loadTree(); } },
  dropVerdict: (id, sess, lead) => treeDropVerdict(treeNodeById(id), sess, lead),
  helpLead: async (id, sess) => { const n = treeNodeById(id); if (n && n.links && n.links.session) { await treeHelpLead(n, sess); loadTree(); } },
  release: async (sid) => {
    const me = treeData && treeData.user, c = treeContext(treeData);
    const items = (treeData.nodes || []).filter((n) => n.links && n.links.session === sid && (n.session_owner || n.owner) === me && !c.isDone(n));
    const helping = (treeData.nodes || []).some((n) => treeHelpers(n).some((h) => h.session === sid && h.owner === me));
    if (!items.length && !helping) { ui.trees.loaded(); return; }
    const s = lastSessions.find((x) => x.id === sid);
    const q = items.length ? t("tree.release_lead_confirm", { s: s ? s.label : sid, items: items.map((n) => n.title).join("・") })
      : t("tree.release_helper_confirm", { s: s ? s.label : sid });
    if (!confirm(q)) { ui.trees.loaded(); return; }
    if (await treeRelease(sid)) { loadTree(); if (typeof refreshSessions === "function") refreshSessions(); }
  },
  turns: () => treeTurns(), turnRows: (list, byId, me, withWho) => treeTurnRows(list, byId, me, withWho),
  placeOptions: treePlaceOptions,
  startCtx: (id) => { const n = treeNodeById(id); return n ? treeStartCtx(n) : null; },
});
// Everything the rows need, from the data as it is now.
function treeContext(data) {
  const me = data.user;
  const nodes = data.nodes || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const kids = new Map();
  for (const n of nodes) {
    const p = n.parent && byId.has(n.parent) ? n.parent : null;
    if (!kids.has(p)) kids.set(p, []);
    kids.get(p).push(n);
  }
  // その他 (a split-up node's own work) comes last among its siblings.
  // Otherwise by order (set by dragging in ↕), else by when made.
  for (const list of kids.values()) list.sort((a, b) => (!!a.rest - !!b.rest) || treeKey(a) - treeKey(b));
  const now = Date.now() / 1000;
  // A node with children is done only by its state: a done ball from the
  // session on it says nothing of the work under it (2026-11-20, the user:
  // 〈ある木〉は子が開いてるのに、トップが閉じてるように見えます).
  const isDone = (n) => n.state === "done" || (!(kids.get(n.id) || []).length && !!n.ball && n.ball.kind === "done");
  const staleDays = (n) => (!isDone(n) && n.ball && n.ball.since ? Math.floor((now - n.ball.since) / 86400) : 0);
  const leaves = (n) => { const k = kids.get(n.id) || []; return k.length ? (ownOpen(n, k) ? [n] : []).concat(k.flatMap(leaves)) : [n]; };
  const match = (n) => {
    if (treeFilter === "all") return true;
    const L = (kids.get(n.id) || []).length ? leaves(n) : [n];
    if (treeFilter === "you") return L.some((x) => !isDone(x) && x.ball && x.ball.kind === "person" && x.ball.who === me);
    return L.some((x) => staleDays(x) >= 3);
  };
  return { me, nodes, byId, kids, isDone, staleDays, leaves, match };
}
// The rows in the order shown, each top-level item and everything under it
// in a frame of its own (2026-11-20, the user: 一番上の項目ごとに枠で囲まれるように).
function treeLayout(c, roots) {
  const { kids, isDone, match } = c;
  const only = roots ? new Set(roots) : null;
  const groups = [];
  let sink = null;
  const frame = (key, cls) => { sink = { key, cls, items: [] }; groups.push(sink); };
  const walk = (parent, depth) => {
    const all = kids.get(parent) || [];
    // ▿: the finished branches under an open item stay folded.
    const hiddenDone = parent && !treeShowDone.has(parent) ? all.filter((n) => isDone(n) && match(n)) : [];
    // Finished handoff branches (leaves) fold into one row per parent.
    const doneHand = all.filter((n) => n.links && n.links.handoff && isDone(n) && !(kids.get(n.id) || []).length);
    const pkey = parent || "";
    const showHand = treeHandoffsShown.has(pkey);
    // Finished trees (a root that is done) go under one foldable
    // "終了済み" row at the end, closed at first (2026-11-20, the user:
    // 終了した木は、開閉できる 終了済み の項目の下に移動するように).
    // (仕事's tree: one folder's roots, the finished ones kept with them --
    // the list's 🗄 アーカイブ holds those.)
    const doneRoots = parent || only ? [] : all.filter((n) => isDone(n) && match(n));
    const one = (n) => {
      if (!parent && only && !only.has(n.id)) return;
      if (!match(n)) return;
      if (hiddenDone.includes(n)) return;
      if (!showHand && doneHand.includes(n)) return;
      if (depth === 0) frame(n.id, isDone(n) ? "done" : "");
      const has = (kids.get(n.id) || []).length > 0;
      const open = !treeClosed.has(n.id);
      // ▸ closed → ▿ open, finished branches folded → ▾ everything → ▸.
      // Without finished branches the middle step is skipped.
      const doneKids = (kids.get(n.id) || []).filter((k) => isDone(k) && match(k)).length;
      const mode = !open ? "closed" : doneKids && !treeShowDone.has(n.id) ? "part" : "full";
      sink.items.push({ kind: "node", key: n.id, n, depth, has, mode });
      if (has && open) walk(n.id, depth + 1);
    };
    for (const n of all) if (!doneRoots.includes(n)) one(n);
    if (hiddenDone.length) sink.items.push({ kind: "doneBranches", key: "db:" + parent, depth, parent, count: hiddenDone.length });
    const shownHand = doneHand.filter((n) => match(n) && !hiddenDone.includes(n));
    if (shownHand.length) {
      if (depth === 0) frame("hand:", "");
      sink.items.push({ kind: "hand", key: "h:" + pkey, depth, pkey, show: showHand, count: shownHand.length });
    }
    if (doneRoots.length) {
      frame("done-fold", "done-fold-group");
      sink.items.push({ kind: "doneFold", key: "df", depth, count: doneRoots.length });
      if (treeDoneShown) for (const n of doneRoots) one(n);
    }
  };
  walk(null, 0);
  return groups;
}
function treeTitleText(n) {
  if (n.rest && n.title === "その他") {
    // Whose leftover work it is (2026-11-20, the user: その他に何が入ってるか
    // わかりません): the session that held the node before it was split.
    const s = treeRestSession(n);
    return s ? t("tree.other_work_label", { label: s.label || s.id }) : t("tree.other_what_left_before_split");
  }
  const tr = n.tr && n.tr.title;
  return tr && !treeShowOrig.has(n.id) ? tr : n.title;
}
// A box a tree* helper builds into, once, when it is first drawn; Preact
// leaves what the helper put in it alone afterwards.
function DomPanel({ cls, build, after }) {
  const ref = PH.useRef(null);
  PH.useLayoutEffect(() => {
    const box = ref.current;
    build(box);
    if (after) after(box);
  }, []);
  return html`<div class=${cls} ref=${ref} onClick=${(e) => e.stopPropagation()}></div>`;
}
// roots: only these top-level items (仕事's tree: one folder's, the deployment notes
// 段4), drawn bare (no bar: 仕事's tree has its own at its top).
function TreeView({ data, roots, bare }) {
  const [menu, setMenu] = PH.useState(null);     // the node whose ⋯ is open
  const [adding, setAdding] = PH.useState(false); // ＋ 新しい仕事's line
  PH.useEffect(() => {
    const close = () => setMenu(null);
    treeMenuClosers.add(close);
    return () => treeMenuClosers.delete(close);
  });
  // From a session's 🌳: scroll to the node and mark it, once.
  PH.useLayoutEffect(() => {
    if (!treeFocus) return;
    const el = document.querySelector(".tnode.tfocus");
    if (el) { treeFocus = null; setTimeout(() => el.scrollIntoView({ block: "center" }), 0); }
  });
  const c = treeContext(data);
  const groups = treeLayout(c, roots);
  // 仕事's tree: an item's own session as a row right under it (2026-11-26,
  // the user: 木の中にはセッションははいれないのですか) -- the list's row
  // (list.js, ui.trees.sessionRow), not in its folder any more.
  if (bare && ui.trees.sessionRow) {
    // Each of the viewer's sessions once, under the item it holds now (the
    // one it took on last); under the nearest item shown when a closed
    // branch hides that one (2026-11-27, the user: このセッションが木の
    // どこにあるか行方不明 -- out of its folder and in no row either).
    const shown = new Set();
    for (const g of groups) for (const it of g.items) if (it.kind === "node") shown.add(it.n.id);
    const cur = new Map();   // sid -> its open item taken on last
    for (const n of (data.nodes || [])) {
      const sid = n.links && n.links.session;
      if (!sid || (n.session_owner || n.owner) !== c.me || c.isDone(n)) continue;
      const o = cur.get(sid);
      const at = (x) => [x.linked_ts || x.created_ts || 0, x.created_ts || 0];
      if (!o || at(n)[0] > at(o)[0] || (at(n)[0] === at(o)[0] && at(n)[1] > at(o)[1])) cur.set(sid, n);
    }
    // Hidden in a closed item: its title alone, one deeper than the closed
    // item (not the items between), and the lead session under it with a
    // 🤝 count instead of the helpers' rows; opening it shows them as before
    // (2026-11-27, the user: 木を閉じてても、担当セッションは表示する方が
    // 良かった。担当の枝と担当セッションだけを表示し、開くと協力も見える).
    const under = new Map();   // shown item id -> [held item]
    const peek = new Map();    // shown (closed) item id -> [held item inside it]
    for (const n of cur.values()) {
      let x = n;
      for (let i = 0; x && !shown.has(x.id) && i < 1000; i++) x = x.parent ? c.byId.get(x.parent) : null;
      if (!x) continue;
      const m = x === n ? under : peek;
      if (!m.has(x.id)) m.set(x.id, []);
      m.get(x.id).push(n);
    }
    for (const g of groups) {
      g.items = g.items.flatMap((it) => {
        if (it.kind !== "node" || !(under.has(it.n.id) || peek.has(it.n.id))) return [it];
        const out = [it];
        for (const n of under.get(it.n.id) || []) {
          const hs = treeHelpers(n).filter((h) => h.owner === c.me);
          out.push({ kind: "session", key: "s:" + n.id, sid: n.links.session, depth: it.depth + 1, role: hs.length ? "lead" : null, node: n.id },
            ...hs.map((h) => ({ kind: "session", key: "h:" + n.id + ":" + h.session, sid: h.session, depth: it.depth + 1, role: "helper", node: n.id })));
        }
        for (const n of peek.get(it.n.id) || []) {
          const hs = treeHelpers(n).filter((h) => h.owner === c.me);
          const unfold = hs.length && treePeekOpen.has(n.id);
          out.push({ kind: "peek", key: "p:" + n.id, n, fold: hs.length ? (unfold ? "open" : "closed") : null, depth: it.depth + 1 },
            { kind: "session", key: "s:" + n.id, sid: n.links.session, depth: it.depth + 2, role: hs.length ? "lead" : null, helpers: hs.length, fold: hs.length ? (unfold ? "open" : "closed") : null, node: n.id },
            ...(unfold ? hs.map((h) => ({ kind: "session", key: "h:" + n.id + ":" + h.session, sid: h.session, depth: it.depth + 2, role: "helper", node: n.id })) : []));
        }
        return out;
      });
    }
  }
  if (menu && !c.byId.has(menu)) setTimeout(() => setMenu(null), 0);
  const filters = [["all", t("common.all")], ["you", "🙋 " + t("common.turn")], ["stale", t("tree.stuck_3_days")]];
  const item = (it) => {
    if (it.kind === "node") return html`<${TreeRow} key=${it.key} it=${it} c=${c} open=${menu === it.n.id} setMenu=${setMenu} list=${!!bare} />`;
    if (it.kind === "session") return html`<${TreeSessionRow} key=${it.key} sid=${it.sid} depth=${it.depth} role=${it.role} helpers=${it.helpers} fold=${it.fold} node=${it.node} />`;
    if (it.kind === "peek") {
      // Its title shows and hides its lead's helpers right there, the tree
      // staying closed (2026-11-27, the user: 担当セッションの開きはセッション
      // 直上の枝の名前のところで良い。今そこをクリックすると木が全部開きますが
      // それはない方が良い); with no helpers it does nothing. The mark is on
      // the lead's 🧭 担当 line below, not ▶ here (the user: 木を開くのと区別
      // するため、タスクの行に移して).
      return html`<div key=${it.key} class=${"tnode tpeek" + (it.fold ? " tcan" : "")} style=${{ "--d": it.depth }} data-node=${it.n.id}
        aria-expanded=${it.fold ? it.fold === "open" : null} onClick=${() => { if (it.fold) treePeekFlip(it.n.id); }}>
        <span class="tt">${treeTitleText(it.n)}</span></div>`;
    }
    const st = { "--d": it.depth };
    if (it.kind === "doneBranches") return html`
      <div key=${it.key} class="tnode done done-branches tcan" style=${st} title=${t("tree.show_finished_branches_too")}
        onClick=${() => { treeShowDone.add(it.parent); treeSaveOpen(); treeRerender(); }}>
        <button class="tog">▶</button><span class="tvis">${"✓ " + t("tree.n_finished_branches", { n: it.count })}</span>
      </div>`;
    if (it.kind === "hand") {
      const flip = () => { it.show ? treeHandoffsShown.delete(it.pkey) : treeHandoffsShown.add(it.pkey); treeRerender(); };
      return html`
        <div key=${it.key} class="tnode done handoff-fold" style=${st}>
          <button class="tog" onClick=${flip}>${it.show ? "▼" : "▶"}</button>
          <span class="tvis" style="cursor: pointer" onClick=${flip}>${(it.show ? "" : "🔁 ") + t("tree.n_finished_handoffs", { n: it.count }) + (it.show ? t("tree.fold") : "")}</span>
        </div>`;
    }
    const flip = () => {
      treeDoneShown = !treeDoneShown;
      try { localStorage.setItem("aiza-tree-done-shown", treeDoneShown ? "1" : ""); } catch (e) {}
      treeRerender();
    };
    return html`
      <div key=${it.key} class="tnode done done-fold" style=${st}>
        <button class="tog" onClick=${flip}>${treeDoneShown ? "▼" : "▶"}</button>
        <span class="tt" style="cursor: pointer" onClick=${flip}>${"✓ " + t("tree.finished_n", { n: it.count })}</span>
      </div>`;
  };
  // An item with what is under it in a frame (2026-11-27, the user:
  // インデントが場所を取ってて見にくい。枠で囲って示す。左は少しだけ
  // インデント、右は枠を重ねる): the frames nest a little to the left and
  // share the right edge. The group's own frame is the outermost one.
  const selBox = (it) => it.kind === "node" && !!(ui.sel && ui.sel.is("node", it.n.id));
  const nest = (items) => {
    let i = 0;
    const walk = (d, top) => {
      const out = [];
      while (i < items.length && items[i].depth >= d) {
        const it = items[i++];
        const kids = i < items.length && items[i].depth > it.depth ? walk(it.depth + 1, false) : null;
        if (!kids) out.push(item(it));
        else if (top) out.push(item(it), ...kids);
        else out.push(html`<div key=${"box:" + it.key} class=${"tbox" + (selBox(it) ? " tsel-box" : "")}>${item(it)}${kids}</div>`);
      }
      return out;
    };
    return walk(Math.min(...items.map((it) => it.depth)), true);
  };
  // The selected item's whole frame is lit, not its row only: a root's
  // group, an open branch's box (2026-11-27, the user: 木を選択しても選択の
  // 枠が木全体でなく1行だけになりますが、枠全体にしたほうがわかりやすいです).
  const group = (g) => {
    const root = g.items.find((x) => x.kind === "node");
    const lit = root && g.items.length > 1 && selBox(root);
    return html`<div key=${g.key} class=${"tgroup" + (g.cls ? " " + g.cls : "") + (lit ? " tsel-box" : "")}>${nest(g.items)}</div>`;
  };
  if (bare) return html`
    <div class=${"tree grouped" + (treeArrange ? " arrange" : "")}>
      ${groups.map(group)}
    </div>`;
  return html`
    <div class="tree-bar">
      ${filters.map(([f, label]) => html`<button key=${f} class=${treeFilter === f ? "on" : ""} onClick=${() => { treeFilter = f; treeRerender(); }}>${label}</button>`)}
      <button aria-expanded=${adding ? "true" : "false"} onClick=${() => setAdding(!adding)}>${"＋ " + t("common.new_job")}</button>
      <button class=${treeArrange ? "on" : ""} title=${t("tree.drag_change_order_siblings_or")}
        onClick=${() => { treeArrange = !treeArrange; treeRerender(); }}>${"↕ " + t("common.arrange")}</button>
    </div>
    ${adding ? html`<${DomPanel} key="tadd" cls="tadd" build=${(box) => {
      // A line under the bar (not the browser's prompt, 2026-11-23).
      const v = treeInput(box, t("tree.title_job"), "");
      treeAct(box, t("tree.add"), () => { if (v.value.trim()) { treeOp({ op: "add", title: v.value.trim() }); v.value = ""; } }, v);
      v.focus();
    }} />` : null}
    <div class=${"tree grouped" + (treeArrange ? " arrange" : "")}>
      ${groups.length
        ? groups.map(group)
        : html`<div class="empty">${t("tree.no_tree_yet_start_one")}</div>`}
    </div>`;
}
// The list's own row for a session (its dot, its ⋯, its drag), made again
// only when what it shows changes; nothing when it is not shown (stopped,
// archived, filtered out).
function TreeSessionRow({ sid, depth, role, helpers, fold, node }) {
  const ref = PH.useRef(null);
  const sig = ui.trees.sessionSig(sid);
  PH.useLayoutEffect(() => {
    const el = ref.current;
    el.textContent = "";
    const row = ui.trees.sessionRow(sid);
    if (row) el.appendChild(row);
  }, [sig]);
  // A team's sessions say which is which (🧭 担当 / 🤝 協力).
  return html`<div class="tsession-wrap" data-node=${node} data-sid=${sid}>
    ${!role ? null : fold ? html`<div class="trole tcan" aria-expanded=${fold === "open"} onClick=${(e) => { e.stopPropagation(); treePeekFlip(node); }}>
        ${"🧭 " + t("tree.lead") + " · 🤝" + helpers + (fold === "open" ? " ⌄" : " ›")}</div>`
      : html`<div class="trole">${role === "lead" ? "🧭 " + t("tree.lead") + (helpers ? " · 🤝" + helpers : "") : "🤝 " + t("tree.helper")}</div>`}
    <div class="tsession" style=${{ "--d": depth }} ref=${ref}></div></div>`;
}
function TreeRow({ it, c, open, setMenu, list }) {
  const { n, depth, has, mode } = it;
  // A tree's root shows 🌳, its ▶ small at the lower right as a folder's
  // (2026-11-27, the user: 木の根には木のアイコンを出す。フォルダの中なので
  // なんだか分かるように).
  const root = !n.parent || !c.byId.has(n.parent);
  // ▼ the open ones, ▽ everything (2026-11-27, the user: ▼と▽を入れ替えて).
  const sym = { closed: "▶", part: "▼", full: "▽" }[mode];
  // A root shared with no one: 🔒 at its 🌳's lower left, instead of saying
  // 座の中 on the shared ones (2026-11-27, the user).
  const unshared = root && n.visibility !== "lab" && !(n.members || []).length;
  const { me, kids, isDone, leaves, staleDays } = c;
  const done = isDone(n);
  // The whole row opens and closes it, but not its links and buttons
  // (the user: ▶だけでなく行全体がクリックできると良い); ▽ → ▼ (finished
  // branches) only from the mark itself (2026-11-20, the user: ▽から▼は、
  // ▽自体をタップしたときだけ).
  const cycle = (e) => {
    if (e) e.stopPropagation();
    if (mode === "closed") { treeClosed.delete(n.id); treeShowDone.delete(n.id); }
    else if (mode === "part") treeShowDone.add(n.id);
    else { treeClosed.add(n.id); treeShowDone.delete(n.id); }
    treeSaveOpen(); treeRerender();
  };
  // A tap selects the row (the bar above the tree then works on it); a tap
  // on the selected one, or on ▶/▼, opens and closes it (2026-11-27,
  // the deployment notes: 選んだものに働く固定の道具の段).
  const selected = !!(ui.sel && ui.sel.is("node", n.id));
  const rowClick = (e) => {
    if (e.target.closest("a, button, input, select, textarea, .tmenu, .tbtns")) return;
    // In 仕事's list only (the to-do page's tree has no bar): there it opens at once.
    const inList = !!e.currentTarget.closest(".wtree");
    if (inList && !selected) { if (ui.sel) ui.sel.set({ kind: "node", id: n.id }); return; }
    if (!has) return;
    if (mode === "closed") treeClosed.delete(n.id);
    else { treeClosed.add(n.id); treeShowDone.delete(n.id); }
    treeSaveOpen(); treeRerender();
  };
  // A root anyone may put in a folder of their own (its place is per user, 段4).
  const mine = n.owner === me || (n.members || []).includes(me);
  const movable = treeArrange && !n.rest && (mine || !(n.parent && c.byId.has(n.parent)));
  // A node one of this user's sessions works on: its title and its ball
  // both open that session (2026-11-15, the user: AI が担当している項目は
  // そのセッションに飛べると良い). An item with branches: its title opens
  // and closes it; a leaf's title opens its session (or its issue).
  const href = treeSessionHref(n, me);
  const im = n.links && n.links.issue && /^([\w.-]+)\/([\w.-]+)#(\d+)$/.exec(n.links.issue);
  const ghref = im ? `https://github.com/${im[1]}/${im[2]}/issues/${im[3]}` : null;
  const tlink = !has && (href || ghref);
  const titleText = treeTitleText(n);
  const title = tlink && href ? html`<a class="tt tlink" href=${href}>${titleText}</a>`
    : tlink ? html`<a class="tt" href=${ghref} target="_blank" rel="noopener">${titleText}</a>`
    : html`<span class="tt">${titleText}</span>`;
  const bits = [];
  if (has && ghref) bits.push(html`<a class="tvis" href=${ghref} target="_blank" rel="noopener">${n.links.issue} ↗</a>`);
  if (n.rest && !done) {
    const rs = treeRestState(n);
    bits.push(html`<span class="tvis" title=${t("tree.where_session_holding_work_now")}>${rs.text}</span>`);
    if (rs.finished) bits.push(html`<span class="tstale">${t("tree.session_said_done_stopped_check")}</span>`);
  }
  if (n.tr && (n.tr.title || n.tr.ball)) {
    const orig = treeShowOrig.has(n.id);
    bits.push(html`<button type="button" class="ttr" title=${orig ? t("tree.show_translation") : t("tree.show_original")}
      onClick=${(e) => { e.preventDefault(); e.stopPropagation(); orig ? treeShowOrig.delete(n.id) : treeShowOrig.add(n.id); treeRerender(); }}>${orig ? t("tree.orig") : t("tree.translation_short")}</button>`);
  }
  if (n.links && n.links.repo) bits.push(html`<span class="tvis">GitHub ${n.links.repo}</span>`);
  // A shared root's Discord channel / its branch's thread (the deployment notes):
  // the store hands only a checked link, to who sees the node; checked again here.
  // Beside the ⋯ (2026-11-27, the user: ディスコードのアイコンは…のすぐ左に).
  const discord = n.discord && /^https:\/\/discord\.com\/channels\/\d+\/\d+$/.test(n.discord)
    ? html`<a class="tdiscord" href=${n.discord} target="_blank" rel="noopener" title=${t("tree.talk_on_discord")} aria-label=${t("tree.talk_on_discord")} onClick=${(e) => e.stopPropagation()}>💬</a>`
    : null;
  // A handoff branch's title is what it is about; to whom, beside it (2026-11-22).
  if (n.links && n.links.handoff && n.session_label && n.session_label !== n.title) bits.push(html`<span class="tvis">→ ${n.session_label}</span>`);
  // A desk report's session: where it is, as a link only (the deployment notes).
  if (n.links && n.links.ref) {
    const p = n.report_pos || {};
    const at = p.at ? new Date(p.at * 1000).toLocaleString() : "";
    const where = [at, p.events != null ? t("tree.chat_line_n", { n: p.events }) : "", p.conv_line != null ? t("tree.claude_log_line_n", { n: p.conv_line }) : ""].filter(Boolean).join(" · ");
    bits.push(html`<span class="tvis" title=${n.links.ref + (where ? "\n" + where : "")}>📮 ${n.links.ref.split("/").slice(0, 3).join(" · ")}${at ? " · " + at : ""}</span>`);
  }
  if (has) {
    const L = leaves(n);
    const cnt = (k) => L.filter((x) => !isDone(x) && x.ball && x.ball.kind === k).length;
    const parts = [t("tree.d_n_done", { d: L.filter(isDone).length, n: L.length })];
    for (const k of ["person", "ai", "sleep", "ext"]) if (cnt(k)) parts.push(`${BALL[k]}${cnt(k)}`);
    const sub = [];
    (function all(x) { sub.push(x); for (const k of kids.get(x.id) || []) all(k); })(n);
    const seen = new Set();
    let cost = 0, any = false;
    for (const x of sub) {
      const sid = x.links && x.links.session;
      if (!x.usage || x.usage.cost == null || seen.has(sid)) continue;
      seen.add(sid); cost += x.usage.cost; any = true;
    }
    if (any) parts.push("≈" + fmtCost(cost));
    bits.push(html`<span class="tsum">${parts.join("  ")}</span>`);
  }
  // A parent shows its own ball too when a session works on it.
  if ((!has && (n.ball || done)) || (has && n.ball && n.links && n.links.session && !done)) {
    const b = n.ball || { kind: "done" };
    let txt = BALL[done ? "done" : b.kind] || "";
    if (!done && n.left) txt = "⏸ " + t("tree.left_behind_session_moved_on") + " · " + txt;
    if (!done && b.kind === "person") txt += " " + (b.who === me ? t("common.you") : b.who || "");
    if (!done && b.kind === "sleep" && b.until) txt += " " + fmtUntil(b.until);
    if (!done && ballText(n)) txt += " · " + ballText(n);
    const cls = `tball k-${done ? "done" : b.kind}`;
    bits.push(href ? html`<a class=${cls} href=${href}>${txt} ›</a>` : html`<span class=${cls}>${txt}</span>`);
  }
  if (!has && n.usage && n.usage.cost != null) bits.push(html`<span class="tsum" title=${t("tree.estimate_at_api_list_prices")}>≈${fmtCost(n.usage.cost)}</span>`);
  const days = staleDays(n);
  if (days >= 3) bits.push(html`<span class="tstale">${t("tree.stuck_n_days", { n: days })}</span>`);
  // 🧭 担当 and 🤝 協力 (the deployment notes): who leads it and who helps.
  // A session by its name when it is the viewer's, else by whose it is.
  const helpers = done ? [] : treeHelpers(n);
  if (helpers.length) {
    const lead = (n.session_owner || n.owner) === me ? (n.session_label || n.title) : t("tree.someones_session", { who: n.session_owner || n.owner });
    const names = helpers.map((h) => h.owner === me ? (h.label || h.session) : t("tree.someones_session", { who: h.owner }));
    bits.push(html`<span class="tvis tteam" title=${t("tree.lead_and_helpers")}>${"🧭 " + lead + " · 🤝 " + names.join("・")}</span>`);
  }
  if (n.owner !== me) bits.push(html`<span class="tvis">${n.owner}</span>`);
  // ⠿ is wired once per row element (the drag itself is plain DOM code).
  const gripRef = (el) => { if (el && !el._treeDrag) { el._treeDrag = true; wireTreeDrag(el); } };
  return html`
    <div class=${"tnode" + (done ? " done" : "") + (n.id === treeFocus ? " tfocus" : "") + (has ? " tcan" : "") + (selected ? " tsel" : "")}
      data-id=${n.id} style=${{ "--d": depth }} onClick=${rowClick}>
      ${treeArrange ? (movable
        ? html`<span class="tgrip" title=${t("common.drag_move")} ref=${gripRef}>⠿</span>`
        : html`<span class="tgrip"></span>`) : null}
      <button class="tog" disabled=${!has} title=${has ? { closed: t("common.open"), part: t("tree.show_finished_branches_too"), full: t("common.close") }[mode] : ""}
        onClick=${has ? cycle : undefined}>${root
          ? html`<span class="ficon">🌳${unshared ? html`<span class="flock" title=${t("tree.shared_with_no_one")}>🔒</span>` : null}${has ? html`<span class="ftog">${sym}</span>` : null}</span>`
          : has ? sym : ""}</button>
      <div class="tmain">${title}${bits}</div>
      <span class="tbtns">
        ${discord}
        <button class="tmore" title=${t("common.actions")} onClick=${(e) => { e.stopPropagation(); setMenu(open ? null : n.id); }}>⋯</button>
        ${open ? html`<${TreeMenu} n=${n} c=${c} has=${has} list=${list} close=${() => setMenu(null)} />` : null}
      </span>
    </div>`;
}
// One ⋯ per row; its actions open in a balloon (2026-11-15, the user:
// アイコンが幅を取りすぎ。操作のアイコンは一つにまとめてバルーンが出るのが良い).
// An item that needs input opens under itself, in place of the browser's
// own prompt/confirm (2026-11-23, the user: ブラウザ標準のポップアップで
// 入力するのではなく、メニューの項目が開くUIに統一); one open at a time.
function TreeMenu({ n, c, has, close, list }) {
  const [panel, setPanel] = PH.useState(null);
  const ref = PH.useRef(null);
  // Placed on the screen itself (position: fixed) from the ⋯'s place:
  // below it, or above when that has more room, as high as the screen
  // leaves room for, scrolling inside when longer (2026-11-20 / 11-23, the
  // user: 一番下の枝だと画面からはみ出して押せません; 画面に入らなければ
  // スクロールするように). Once, when it opens.
  PH.useLayoutEffect(() => {
    const menu = ref.current, more = menu.previousElementSibling;
    const r = more.getBoundingClientRect();
    const vh = window.visualViewport ? window.visualViewport.height : window.innerHeight;
    const bar = document.getElementById("voice-bar");
    const foot = bar && bar.offsetParent ? bar.getBoundingClientRect().height : 0;
    const below = vh - foot - r.bottom - 8, above = r.top - 8;
    const up = menu.scrollHeight + 8 > below && above > below;
    menu.classList.toggle("up", up);
    const right = Math.max(8, document.documentElement.clientWidth - r.right);
    menu.style.right = right + "px";
    menu.style.maxWidth = (document.documentElement.clientWidth - right - 8) + "px";
    if (up) menu.style.bottom = (window.innerHeight - r.top + 6) + "px";
    else menu.style.top = (r.bottom + 6) + "px";
    menu.style.maxHeight = Math.max(up ? above : below, 120) - 6 + "px";
  }, []);
  const items = treeMenuItems(n, c, has, close, panel, setPanel, () => ref.current, list);
  return html`<div class="tmenu" ref=${ref} onClick=${(e) => e.stopPropagation()}>${items}</div>`;
}
// ⋯'s items (its balloon). scroller(): the element a panel opening is
// scrolled into view in.
// list: in 仕事's list, whose top row's ＋ 🤖 AI and ＋ 🌳 work on the
// selected item -- ▶ / 🤛 and ＋ 子を足す are left to them there (2026-11-27,
// the user: 枝やフォルダの…から4つのボタンでできる機能を外してください). The
// to-do page's tree has no such row: they stay in its ⋯.
function treeMenuItems(n, c, has, close, panel, setPanel, scroller, list) {
  const me = c.me;
  const items = [];
  const mk = (key, label, fn) => items.push(html`<button key=${key} onClick=${(e) => { e.stopPropagation(); close(); fn(); }}>${label}</button>`);
  const mkPanel = (key, label, build) => {
    const on = panel === key;
    items.push(html`<button key=${key} aria-expanded=${on ? "true" : "false"} onClick=${(e) => { e.stopPropagation(); setPanel(on ? null : key); }}>${label}</button>`);
    if (on) items.push(html`<${DomPanel} key=${key + ":panel"} build=${(box) => build(box, close)} after=${(box) => {
      const f = box.querySelector("input:not([type=radio]), select");
      if (f) f.focus({ preventScroll: true });
      // Into view inside the menu only: a scroll of the tree would close it.
      const menu = scroller && scroller();
      if (!menu) return;
      const over = box.getBoundingClientRect().bottom - menu.getBoundingClientRect().bottom;
      if (over > 0) menu.scrollTop += over + 8;
    }} />`);
  };
  // ⛓ opens over 仕事's views (the to-do page shows it; the deployment notes 段5).
  if (has) mk("chain", "⛓ " + t("tree.see_what_holds_up"), () => {
    if (!todoOn()) ui.tabs.show("work", "ball");
    setTodo({ view: "tree", chain: n.id });
  });
  // ▶ one item for a new session or one there is (2026-11-23, the user:
  // 「今あるセッションをこの下につなぐ」は「これをセッションで始める」を
  // 「セッションで作業」に変えてこれに含め、「新規」がいまのメニュー＋
  // フォルダの選択、「既存」はセッション一覧のツリーから選ぶ).
  const startLabel = treeHeldBy(n) ? t("tree.work_under_in_session") : t("common.work_on_in_session");
  // ▶: the start screen with this item filled in (the deployment notes 段3). A
  // session there is already is dragged onto the item instead (2026-11-26,
  // the user: セッションがドラッグできれば、既存を繋ぐは不要).
  if (!list) mk("start", "▶ " + startLabel, () => ui.start.open(treeStartCtx(n)));
  const whoseS = n.links && n.links.session ? (n.session_owner || n.owner) : null;
  if (whoseS && whoseS !== me && treeSessionHref(n, me)) {
    // Plan stage 14: take someone's work on -- co-work in their
    // session, or a new session of one's own (undoable).
    mk("join", "✍ " + t("tree.co_work_type_into_session"), async () => {
      try {
        await api(sessionPath(n.links.session, "/join", whoseS), { method: "POST" });
        await refreshSessions();
        await treeGoSession(n.links.session, whoseS);
      } catch (e) { alert(e.message); }
    });
    if (!list) mk("take", "🤛 " + t("tree.take_on_new_session_own"), () => ui.start.open(treeTakeCtx(n)));
  }
  if (n.taken && n.taken.by === me && n.taken.state === "taken") {
    mkPanel("untake", "↩ " + t("tree.undo_taking_on"), (box, close) => {
      treeNote(box, t("tree.session_made_stopped_archived_item"));
      treeAct(box, t("tree.undo"), () => { close(); treeOp({ op: "untake", id: n.id }); });
    });
  }
  if (treeSessionHref(n, me)) {
    mkPanel("ref", "💬 " + t("tree.reference_session_copy"), (box) => {
      const whose = n.session_owner || n.owner;
      const s = { id: n.links.session, owner: whose === me ? null : whose, label: n.session_label || n.title };
      const token = sessionRefToken(s).trim();
      const field = treeInput(box, "", token);
      field.readOnly = true;
      const note = treeNote(box, t("tree.paste_into_chat_ai_can"));
      treeAct(box, t("tree.copy"), () => {
        (navigator.clipboard ? navigator.clipboard.writeText(token) : Promise.reject())
          .then(() => { note.textContent = t("tree.reference_copied_paste_into_chat"); })
          .catch(() => { field.select(); note.textContent = t("tree.paste_reference_into_chat"); });
      });
    });
  }
  // 🧭 Take the 担当 off the item (2026-11-27, the user: 担当を剥がせる
  // ように): the item stays as it is, the session goes back to its folder.
  if (n.links && n.links.session && (n.owner === me || (n.members || []).includes(me) || (n.session_owner || n.owner) === me)) {
    mk("unlead", "🧭 " + t("tree.take_lead_off"), () => {
      if (!confirm(t("tree.release_lead_confirm", { s: n.session_label || t("tree.someones_session", { who: n.session_owner || n.owner }), items: n.title }))) return;
      const links = Object.assign({}, n.links);
      delete links.session;
      treeOp({ op: "update", id: n.id, links, ball: null });
    });
  }
  // 🤝 Stop one of the viewer's sessions helping here (its talkto link stays).
  for (const h of treeHelpers(n)) {
    if (h.owner !== me && (n.session_owner || n.owner) !== me) continue;
    const name = h.owner === me ? (h.label || h.session) : t("tree.someones_session", { who: h.owner });
    mk("unhelp:" + h.session, "🤝 " + t("tree.stop_helping", { s: name }), () => {
      if (confirm(t("tree.release_helper_confirm", { s: name }))) treeOp({ op: "unhelp", session: h.session, owner: h.owner });
    });
  }
  if (!n.parent) mkPanel("folder", "📁 " + t("tree.session_folder_2"), (box, close) => treeFolderPanel(n, box, close));
  // ＋ 子を足す: by a title, or from a GitHub repository (2026-11-23, the
  // user: 子を足すのメニューに Githubにつなぐを増やして統合).
  if (!list) mkPanel("child", "＋ " + t("tree.add_child"), (box, close) => treeChildPanel(n, me, box, close));
  mk("done", c.isDone(n) ? "↺ " + t("tree.reopen") : "✓ " + t("common.mark_done"),
     () => treeOp({ op: "update", id: n.id, state: c.isDone(n) ? "open" : "done" }));
  if (n.owner === me && n.links && n.links.repo) {
    mk("resync", "↻ " + t("tree.read_again_github"), async () => {
      try {
        const r = await api("/tree", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "sync", id: n.id }) });
        showUndoToast(t("tree.updated_n", { n: r.changed }), false);
      } catch (e) { alert(e.message); }
      loadTree();
    });
  }
  // 🧑‍🤝‍🧑 共有, or 共有(根で設定) below a shared root: that opens the
  // root's own settings (2026-11-23, the user: 根で設定をクリックした
  // 場合も根の共有設定が開くように).
  if (n.owner === me && n.follows) {
    let root = n;
    for (let i = 0; root && root.parent && i < 1000; i++) root = c.byId.get(root.parent) || null;
    mkPanel("share", "🧑‍🤝‍🧑 " + t("tree.sharing_set_at_root"), (box, close) => {
      if (!root || root === n) { treeNote(box, t("tree.root_not_found")); return; }
      treeNote(box, t("tree.settings_p_every_branch_below", { p: root.title }));
      if (root.owner === me) treeSharePanel(root, box, close);
      else treeNote(box, t("tree.only_roots_creator_u_can", { u: root.owner }));
    });
  } else if (n.owner === me) {
    mkPanel("share", "🧑‍🤝‍🧑 " + t("common.share"), (box, close) => treeSharePanel(n, box, close));
  }
  // Rename (2026-11-20, the user: 枝の名前を変えられるように), at the bottom
  // (2026-11-23). Not その他 (named by the tree) nor a GitHub issue.
  if (!n.rest && !(n.links && n.links.issue) && (n.owner === me || (n.members || []).includes(me))) {
    mkPanel("rename", "✏️ " + t("tree.rename"), (box, close) => {
      const v = treeInput(box, t("tree.new_title"), n.title);
      treeAct(box, t("common.rename_2"), () => {
        if (!v.value.trim() || v.value.trim() === n.title) return;
        close(); treeOp({ op: "update", id: n.id, title: v.value.trim() });
      }, v);
    });
  }
  return items;
}
// ＋ 🤖 AI on a selected item: 🤛 take on someone's work, else ▶ work on it.
function treeSelStartCtx(n) {
  const me = treeData && treeData.user;
  const whoseS = n.links && n.links.session ? (n.session_owner || n.owner) : null;
  return whoseS && whoseS !== me && treeSessionHref(n, me) ? treeTakeCtx(n) : treeStartCtx(n);
}
// ＋ 子を足す: 題で足す | GitHub につなぐ (the latter while the node is
// one's own and tied to no repository or issue yet).
function treeChildPanel(n, me, box, close) {
  const canGh = n.owner === me && !(n.links && (n.links.repo || n.links.issue));
  const paneT = document.createElement("div"); paneT.className = "tpane";
  const paneG = document.createElement("div"); paneG.className = "tpane";
  let tT, tG;
  if (canGh) {
    const tabs = document.createElement("div");
    tabs.className = "ttabs";
    tT = document.createElement("button"); tT.textContent = t("tree.title");
    tG = document.createElement("button"); tG.textContent = t("tree.link_github");
    tabs.append(tT, tG);
    box.appendChild(tabs);
  }
  box.append(paneT, paneG);
  const v = treeInput(paneT, t("tree.title_child"), "");
  treeAct(paneT, t("tree.add"), () => {
    if (!v.value.trim()) return;
    close(); treeOp({ op: "add", parent: n.id, title: v.value.trim(), visibility: n.visibility });
  }, v);
  paneG.hidden = true;
  if (!canGh) return;
  const r = treeInput(paneG, t("tree.repository_owner_name"), "");
  const note = treeNote(paneG, t("tree.issues_become_branches_under_parent"));
  treeAct(paneG, t("tree.link"), () => {
    const repo = r.value.trim();
    if (!/^[\w.-]+\/[\w.-]+$/.test(repo)) { note.textContent = t("tree.write_owner_name"); return; }
    close();
    treeOp({ op: "update", id: n.id, links: Object.assign({}, n.links || {}, { repo }) })
      .then(() => api("/tree", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ op: "sync", id: n.id }) }))
      .catch((e) => alert(e.message)).finally(loadTree);
  }, r);
  const show = (g) => {
    tT.classList.toggle("on", !g); tG.classList.toggle("on", g);
    paneT.hidden = g; paneG.hidden = !g;
  };
  tT.addEventListener("click", (e) => { e.stopPropagation(); show(false); });
  tG.addEventListener("click", (e) => { e.stopPropagation(); show(true); });
  show(false);
}
// The balloon stays where it was put on the screen: a click outside it, a
// scroll under it (not inside it), or a change of the width closes it.
// Hooked once.
function treeMenuHooks() {
  if (treeMenuScrollHooked) return;
  treeMenuScrollHooked = true;
  document.addEventListener("click", (e) => {
    if (e.target && e.target.closest && e.target.closest(".tmenu, .tmore")) return;
    treeMenuClose();
  });
  // Not while typing in it (2026-11-23, the user: githubの文字入力が閉じて
  // しまってできません): on a phone the keyboard coming up resizes the
  // window and scrolls the field into view.
  const typingInMenu = () => { const a = document.activeElement; return !!(a && a.closest && a.closest(".tmenu") && a.matches("input, textarea, select")); };
  document.addEventListener("scroll", (e) => {
    if (e.target && e.target.closest && e.target.closest(".tmenu")) return;
    if (typingInMenu()) return;
    treeMenuClose();
  }, true);
  // ...and moved into what the keyboard leaves of the screen (2026-11-23,
  // the user: 閉じはしないのですが、見えないので困ります): when the open
  // balloon with the field being typed in reaches outside the visible
  // part, it goes to the top of that part, as tall as it, and the field
  // is scrolled into sight inside it.
  const fitTyping = () => {
    if (!typingInMenu()) return;
    const a = document.activeElement, m = a.closest(".tmenu");
    const vv = window.visualViewport;
    const vt = vv ? vv.offsetTop : 0, vh = vv ? vv.height : window.innerHeight;
    const r = m.getBoundingClientRect();
    if (r.top >= vt && r.bottom <= vt + vh) return a.scrollIntoView({ block: "nearest" });
    m.classList.remove("up");
    m.style.bottom = "";
    m.style.top = (vt + 6) + "px";
    m.style.maxHeight = Math.max(vh - 12, 80) + "px";
    a.scrollIntoView({ block: "nearest" });
  };
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", fitTyping);
    window.visualViewport.addEventListener("scroll", fitTyping);
  }
  document.addEventListener("focusin", (e) => {
    if (e.target && e.target.closest && e.target.closest(".tmenu")) setTimeout(fitTyping, 350);
  });
  let menuWidth = window.innerWidth;
  window.addEventListener("resize", () => {
    const w = window.innerWidth;
    if (w === menuWidth || typingInMenu()) { menuWidth = w; return; }
    menuWidth = w;
    treeMenuClose();
  });
}
