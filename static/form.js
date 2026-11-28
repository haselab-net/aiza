// The new-session form and the machines (aiza): what to run where (KIND_PLACE),
// the machine looked at and its menu, the presets a machine offers, the
// capabilities, and the working-directory and conversation pickers.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after voice.js and before app.js, in this order:
// form, settings, keys, api, links, search, sessionops, compose. What runs
// here at load uses only this file and the earlier ones. Moved out of
// app.js 2026-11-24 as it was; the indentation is app.js's.
"use strict";

  // If the same index.html/app.js is ever served identically from more than
  // one host, which server a tab/PWA icon (and the machine selector's
  // "local" entry, see MACHINE_LABELS) belongs to has to come from the
  // actual hostname the browser loaded, not a fixed string -- e.g.
  // "example.com" becomes "example", correct on any host with no per-host
  // file diff.
  const SHORT_HOSTNAME = location.hostname.split(".")[0];
  document.title = `${t("common.ai_za")} (${SHORT_HOSTNAME})`;
  // What to run x where (2026-11-14, the user: Claude/Codex/Shell と
  // Email/Dev/ホスト/ルート の全部の組み合わせ). These two pick #preset's value
  // (KIND_PLACE); everything else keeps reading #preset. The combinations
  // with no preset of their own (claude-host, codex-mail, ...) are the place's
  // shell with the program typed in (aiza-backend LAUNCH_PRESETS).
  const kindEl = document.getElementById("kind");
  const placeEl = document.getElementById("place");
  const kindPlaceRowEl = document.getElementById("kind-place-row");
  const KIND_PLACE = {
    claude: { dev: "claude-tui", mail: "mail-tui", host: "claude-host", root: "claude-root" },
    // Mailbox Codex is enabled only after the backend reports its guards ready.
    codex: { dev: "codex-tui", mail: "codex-mail", host: "codex-host", root: "codex-root" },
    shell: { dev: "shell", mail: "mail-shell", host: "host-shell", root: "root-shell" },
  };
  // Who may start a tree's session on the host / as root (applyCapabilities):
  // the same people the new-session form offers those places to.
  let treeCanHost = false, treeCanRoot = false;
  // The presets that take the permission checkbox (#skip-row), and which
  // flag it means there.
  // Not claude-root: Claude refuses to skip permissions as root (the
  // backend starts it without the flag whatever is asked).
  const skipRowEl = document.getElementById("skip-row");
  const skipLabelEl = document.getElementById("skip-label");
  // The preset for 何で × どこで; on an ssh machine (ssh:<m>) Claude or Shell.
  function presetOf(kind, place) {
    if (place.startsWith("ssh:")) return kind === "claude" ? `claude-tui-${place.slice(4)}` : kind === "shell" ? `shell-${place.slice(4)}` : null;
    return (KIND_PLACE[kind] || {})[place] || null;
  }
  function presetFromKindPlace() {
    // The backend must offer the exact combination, including mailbox guards.
    // (An ssh machine other than the one the form is on: its presets are
    // made when it is picked, so only 何で decides there.)
    for (const o of placeEl.options) {
      const p = presetOf(kindEl.value, o.value);
      o.disabled = !p || (!presetEl.querySelector(`option[value="${p}"]`) && !(o.value.startsWith("ssh:") && o.value !== `ssh:${currentMachine}`));
    }
    if (placeEl.selectedOptions[0] && placeEl.selectedOptions[0].disabled) {
      const ok = [...placeEl.options].find((o) => !o.disabled);
      if (ok) placeEl.value = ok.value;
    }
    const p = presetOf(kindEl.value, placeEl.value);
    if (!p || !presetEl.querySelector(`option[value="${p}"]`)) return;
    presetEl.value = p;
    applyPresetOptions();
  }
  const claudeOptsEl = document.getElementById("claude-opts");
  const cwdCrumbEl = document.getElementById("cwd-crumb");
  const cwdUpBtn = document.getElementById("cwd-up");
  const cwdChildEl = document.getElementById("cwd-child");
  const resumeEl = document.getElementById("resume");
  const sshCwdOptsEl = document.getElementById("ssh-cwd-opts");
  const sshCwdCrumbEl = document.getElementById("ssh-cwd-crumb");
  const sshCwdUpBtn = document.getElementById("ssh-cwd-up");
  const sshCwdNewBtn = document.getElementById("ssh-cwd-new");
  const sshCwdChildEl = document.getElementById("ssh-cwd-child");
  const sshResumeEl = document.getElementById("ssh-resume");
  // 🐚/🪟 toggle on the #ssh-resume row (the deployment notes): 🐚 runs the new
  // session in the Windows machine's sshd session 0 (no desktop), 🪟 in the
  // logged-on user's desktop session 1, via that machine's desktop variant
  // (GET /capabilities' ssh_desktop, {base: variant}). One row in the
  // machine picker per machine either way. Two copies of the button: one on
  // the Claude preset's #ssh-resume row, one in #ssh-shell-opts for "Shell"
  // (which has no such row) -- both show and flip the same desktopMode.
  const desktopToggleEls = document.querySelectorAll(".desktop-toggle");
  const sshShellOptsEl = document.getElementById("ssh-shell-opts");
  const shellCwdOptsEl = document.getElementById("shell-cwd-opts");
  const shellCwdCrumbEl = document.getElementById("shell-cwd-crumb");
  const shellCwdUpBtn = document.getElementById("shell-cwd-up");
  const shellCwdChildEl = document.getElementById("shell-cwd-child");
  const shellCwdNewBtn = document.getElementById("shell-cwd-new");

  // Working directory for a new claude session, relative to ~/sandhome
  // ("" = ~/sandhome itself). Walked one level at a time, so it can go as
  // deep as the tree does.
  let currentCwd = "";
  // Which tree #claude-opts is walking: "sandhome" (claude-tui) or "mail"
  // (the Email preset's own MAILBOX dir, the deployment notes, 2026-10-06) --
  // same picker, same resume list, each tree keeping its own position.
  let cwdScope = "sandhome";
  const cwdByScope = { sandhome: "", mail: "" };
  let mailboxLabel = "mailbox";
  let hasMailbox = false;
  let hasMailboxCodex = false;


  // Presets driven headlessly through a request/response API (no real
  // terminal underneath) instead of a raw tmux pane -- see aiza-backend's
  // own HEADLESS_PRESETS. These have no notion of "keys" or intermediate
  // TUI redraws.
  const HEADLESS_PRESETS = ["claude"];

  // Each preset's own current position, independently -- switching the
  // preset dropdown between e.g. "host-shell" and "root-shell" must not
  // carry one's browsed-to path over to the other's picker.
  let shellCwdByPreset = Object.fromEntries(Object.entries(FORM_PRESETS)
    .filter(([, f]) => f.picker === "shell").map(([k]) => [k, ""]));
  // Machines whose Claude preset offers #ssh-cwd-opts (winbox-a/winbox-b,
  // not linuxbox) -- from GET /capabilities' ssh_machines_drives, since
  // which machines exist/support it is a live backend answer, same as
  // ssh_machines itself.
  let sshCwdMachines = [];
  // The drive/folder picker's current position: "" means "no drive chosen
  // yet" (shows the machine's drive letters), otherwise a posix MSYS2 path
  // like "/d/Projects" (see resolve_ssh_workdir in aiza-backend). Reset
  // whenever the machine selector changes (applyMachineFilter) so switching
  // machines never carries over a path from a different one.
  let currentSshCwd = "";
  // {base machine: desktop variant} and its inverse, from GET /capabilities'
  // ssh_desktop; desktopMode is the 🐚(false)/🪟(true) toggle's state, reset
  // to 🐚 whenever the machine changes.
  let sshDesktop = {};
  let desktopBase = {};
  let desktopMode = false;

  // "local" means aiza-backend's own container/host/root locations -- the
  // machine selector's other options are aiza-backend's SSH_MACHINES,
  // reachable only over SSH via a shared key, not
  // per-user like root_shell. Populated from GET /capabilities in
  // applyCapabilities() since which machines exist/are reachable is a live
  // backend answer, not a fixed set.
  let currentMachine = "local";
  // Every change of the machine looked at goes through here (ui.ticket's "machine").
  function setMachine(m) {
    if (m !== currentMachine) ui.moved("machine");
    currentMachine = m;
  }
  // (The session list's own state -- sessionOrder, lastSessions, dragState,
  // the archive and shared sections -- is list.js's; taskSeq is todo.js's.)
  // ✓/💤/⏰ set from this page (the deployment notes): a list refresh that started
  // before the change came back must not put the old state back (2026-11-10,
  // the user: 済みにしたら一度消えて、また出て、その後消えた).
  const taskLocal = new Map();
  // A fixed "このホスト" label was ambiguous whenever more than one host
  // shares this same static file -- the actual hostname (2026-08-17, at
  // the user's request) says which one without guessing.
  const MACHINE_LABELS = { local: SHORT_HOSTNAME };
  const machineSelectEl = document.getElementById("machine-select");
  // Snapshot of the local preset <option>s (including "root-shell" if this
  // user has it), taken once in applyCapabilities() after they're all in
  // place -- restored verbatim by rebuildPresetOptions() when switching back
  // to "local" rather than reconstructing them by hand a second time.
  let localPresetOptionsHtml = null;

  // tmux_location is "container"/"host"/"root" for everything on this host,
  // "ssh:<machine>" for a GPU machine -- so this is the one place that needs
  // to know that scheme to answer "which machine is this session's".
  function sessionMachine(meta) {
    const loc = meta.tmux_location || "";
    if (!loc.startsWith("ssh:")) return "local";
    const m = loc.slice(4);
    // A desktop variant's sessions belong to its base machine's list
    // (the deployment notes) -- screenBadge below tells the two kinds apart.
    return desktopBase[m] || m;
  }


  // The list view's own location.hash: "" for this host, "machine=<name>"
  // for any other, so a reload (or a shared link) comes back to the same
  // machine's list instead of always this host's (2026-10-04, at the
  // user's request: "マシンを選んでもurlのハッシュ部分が変わらない").
  function listHash() {
    return currentMachine === "local" ? "" : `machine=${encodeURIComponent(currentMachine)}`;
  }

  // Makes `m` the selected machine (state + <select> + preset list).
  // Usable before applyCapabilities() has built the <select> (init()'s
  // applyHash() runs first): the <select>/presets are then brought in line
  // by syncMachineSelect() once it has.
  function selectMachine(m) {
    // From the URL (#machine=…, anyone can send a link): only a machine
    // name, and once the capabilities are in, only one of this backend's
    // (2026-11-28); anything else is this host.
    if (m !== "local" && (!MACHINE_NAME_RE.test(m)
        || (knownMachines && !knownMachines.has(m)))) m = "local";
    if (m !== currentMachine) {
      setMachine(m);
      currentSshCwd = "";
      desktopMode = false;
      if (localPresetOptionsHtml !== null) rebuildPresetOptions();
    }
    syncMachineSelect();
  }

  let boardMachines = new Set();
  // The ssh and Windows machines this backend has (null until the capabilities are in).
  let knownMachines = null;
  const MACHINE_NAME_RE = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
  // Exactly the Windows machine being looked at (if any) has an entry in
  // the machine menu, just above 「📋 黒板」.
  function syncBoardMachineOption(m) {
    for (const o of [...machineSelectEl.options]) {
      if (o.dataset.board && o.value !== m) o.remove();
    }
    if (!boardMachines.has(m) || [...machineSelectEl.options].some((o) => o.value === m)) return;
    const opt = document.createElement("option");
    opt.value = m;
    opt.textContent = "🪟 " + m;
    opt.dataset.board = "1";
    machineSelectEl.insertBefore(opt, [...machineSelectEl.options].find((o) => o.value === "auth") || null);
  }
  // From the blackboard: that machine's sessions.
  function openBoardMachine(m) {
    closeBoard();
    if (chatNow.id) chatNow.close();
    if (m !== "auth") syncBoardMachineOption(m);
    machineSelectEl.value = m;
    applyMachineFilter();
  }
  // The header shows the machine being looked at as a button that opens
  // the machine panel (the <select> stays, hidden, as the state).
  const machineBtnEl = document.getElementById("machine-btn");
  function updateMachineBtn() {
    const v = machineSelectEl.value;
    const o = [...machineSelectEl.options].find((x) => x.value === v);
    // The machines' panel (blackboard) at the bottom of 仕事's tree (段4): its name only.
    machineBtnEl.textContent = "🖥 " + t("common.machines");
  }
  machineBtnEl.addEventListener("click", () => openBoard());

  // Shows currentMachine in the <select> once it exists; a machine that is
  // not offered (unreachable right now, or gone) falls back to this host.
  function syncMachineSelect() {
    if (localPresetOptionsHtml === null) return; // capabilities not loaded yet
    syncBoardMachineOption(currentMachine);
    if (![...machineSelectEl.options].some((o) => o.value === currentMachine)) {
      setMachine("local");
      rebuildPresetOptions();
    }
    // The header names the page being shown (2026-11-23, the user: 設定から
    // ログインしたあと、左上が「設定」からこのホストの名前に切り替わるのに画面が設定のまま).
    machineSelectEl.value = pageNow() === "auth" ? "auth" : currentMachine;
    updateMachineBtn();
  }

  // "🪟 " / "🐚 " in front of a session's name on a machine that has a
  // desktop variant (the deployment notes), so desktop and no-desktop sessions
  // are distinguishable at a glance; "" everywhere else.

  // The kind of session as an icon before its name (2026-11-05, the user:
  // "セッションのタイプをセッション名の前にアイコンで。メールボックスは新着一覧の
  // メールと同じ物、devbox:🛠️ root:🔒。文字での表示はなくして"): 📫 the Email box
  // (the mail icon of the Email box's own pages), 🛠️ devbox, 🔒 root, 🏠 the host itself,
  // 💻 an ssh machine.
  const PLACE_ICON = { mail: "📫", root: "🔒", host: "🏠", ssh: "💻", dev: "🛠️" };
  function typeIcon(meta) {
    const k = sessionKind(meta);
    let icon = PLACE_ICON[k.place];
    // 📦: moved out of ~/sandhome when the host-only store came in
    // (the deployment notes); its record was in a tree a container could write.
    if (meta.migrated && !k.root) icon += "📦";
    return icon + " ";
  }
  function screenBadge(meta) {
    const loc = meta.tmux_location || "";
    if (!loc.startsWith("ssh:")) return "";
    const m = loc.slice(4);
    if (desktopBase[m]) return "🪟 ";
    if (sshDesktop[m]) return "🐚 ";
    return "";
  }

  // Rebuilds the new-session preset dropdown for whichever machine is
  // currently selected -- a remote machine only ever offers a plain shell and
  // Claude (see aiza-backend's shell-<machine>/claude-tui-<machine> presets),
  // never host-shell/root-shell/CWD pickers, which are meaningless there.
  // 何で × どこで for every machine (the deployment notes 段3: an ssh machine is
  // a place, ssh:<machine>, where Claude and Shell run).
  function rebuildPresetOptions() {
    const local = currentMachine === "local";
    kindPlaceRowEl.hidden = false;
    presetEl.hidden = true;
    if (local) {
      presetEl.innerHTML = localPresetOptionsHtml;
      if (placeEl.value.startsWith("ssh:")) placeEl.value = "dev";
    } else {
      presetEl.textContent = "";
      for (const [value, label] of [[`claude-tui-${currentMachine}`, "Claude"], [`shell-${currentMachine}`, "Shell"]]) {
        const o = document.createElement("option");
        o.value = value;
        o.textContent = label;
        presetEl.appendChild(o);
      }
      if ([...placeEl.options].some((o) => o.value === `ssh:${currentMachine}`)) placeEl.value = `ssh:${currentMachine}`;
    }
    presetFromKindPlace();
    applyPresetOptions();
  }

  async function applyMachineFilter() {
    if (machineSelectEl.value === "auth") {
      openAuthView();
      return;
    }
    setMachine(machineSelectEl.value);
    syncBoardMachineOption(currentMachine);
    updateMachineBtn();
    currentSshCwd = ""; // a path on the previous machine means nothing on this one
    desktopMode = false; // 🐚 is the default on every machine
    if (pageNow() === "auth") {
      // Was viewing the auth page -- picking any real machine here is now
      // the only way to leave it (no back button there
      // any more, 2026-08-15, at the user's request).
      showPage("list");
    }
    setHash(listHash());
    rebuildPresetOptions();
    await refreshSessions();
    await refreshTmuxSessions();
  }

  // "Claude 認証" is its own page (view-auth) rather than part of the session
  // list -- see index.html's comment on #view-auth for why it moved.
  // location.hash mirrors openSession's own convention (so a reload while
  // here returns here instead of silently dropping back to the session
  // list).
  // 設定's page, for the tabs (page.js showTab): its own to give.
  ui.pages.settings = () => openAuthView();
  function openAuthView() {
    showPage("auth");
    setHash("");   // its address is /settings (the deployment notes)
    machineSelectEl.value = "auth"; // also reached via init()'s hash-restore, where the <select> would otherwise still show its freshly-built default ("local")
    updateMachineBtn();
    refreshAuthStatus();
  }

  // Adds the preset options this particular user is allowed to use, and
  // populates the machine selector. Only "root-shell" is conditional among
  // the local presets: the backend offers it only to users who can already
  // become root, and both aiza-backend's create_session and the
  // aigw-root-tmux sudo wrapper check that independently -- hiding the
  // option here is convenience, not the security boundary. Machines are
  // similarly just hidden when GET /capabilities doesn't list them as
  // reachable -- create_session/start_claude_login re-check reachability
  // themselves regardless.
  async function applyCapabilities() {
    let caps = await api("/capabilities").catch(() => ({}));
    document.getElementById("login-list-row").hidden = !caps.login_list;
    if (caps.demo) {
      // A public demo's room (the deployment notes): only the AI the demo offers,
      // in one's own box (the backend refuses the rest as well). The rest
      // of this function runs as on a deployment, with nothing else in caps.
      const only = (caps.presets || []).filter((p) => typeof p === "string");
      KIND_PLACE.agent = { dev: "agent" };   // the demo's AI: no folder to pick
      const opts = () => only.map((p) => { const o = document.createElement("option"); o.value = p; o.textContent = t("form.demo_ai"); return o; });
      kindEl.replaceChildren(...opts());
      presetEl.replaceChildren(...opts());
      for (const o of [...placeEl.options]) if (o.value !== "dev") o.remove();
      const logins = document.getElementById("auth-rows");
      if (logins && logins.closest(".set-card")) logins.closest(".set-card").hidden = true;
      // Nothing else to offer, whatever the answer said.
      caps = { ...caps, root_shell: false, unlock: null, login_list: false, mailbox: null,
               ssh_machines: [], ssh_machines_drives: [], ssh_desktop: {}, board: false };
      // The room's owner: the door's own page (invite, send someone out).
      fetch(window.aizaBase + "/agents/demo/room").then((r) => (r.ok ? r.json() : null)).then((room) => {
        if (!room || !room.door || document.getElementById("demo-room-card")) return;
        const card = document.createElement("section");
        card.className = "set-card";
        card.id = "demo-room-card";
        const h = document.createElement("h3");
        h.textContent = t("form.demo_room");
        const a = document.createElement("a");
        a.href = room.door;
        a.textContent = t("form.demo_room_invite");
        card.append(h, a);
        const section = document.getElementById("claude-auth-section");
        if (section) section.prepend(card);
      }).catch(() => {});
    }
    // root_shell alone is "the root tmux socket exists right now", which
    // since the passkey unlock landed means "a window is open right now".
    // Keying the menu off only that made the root-shell option invisible
    // while locked -- i.e. exactly when you need to pick it to be prompted
    // for a passkey -- so it could never be reached (seen for real on
    // 2026-08-30). unlock.enrolled_root (two-tier update --
    // NOT plain "enrolled", which is now true for a
    // host-tier-only credential too) is the standing "this person has a
    // ROOT-tier passkey, so they can open a root window" answer; either one
    // means the option is worth offering, and picking it while locked runs
    // withUnlockRetry's WebAuthn flow (requesting tier "root") and then
    // succeeds. Someone enrolled for host only correctly never sees this --
    // begin-assertion(tier=root) would just refuse them with "no root-tier
    // credential registered for this user" every time.
    const canRoot = !!(caps.root_shell || (caps.unlock && caps.unlock.enrolled_root));
    treeCanHost = !!(caps.unlock && caps.unlock.enrolled);
    treeCanRoot = canRoot;
    if (canRoot) {
      const opt = document.createElement("option");
      opt.value = "root-shell";
      opt.textContent = t("form.shell_root");
      presetEl.appendChild(opt);
      for (const [value, label] of [["claude-root", "form.claude_root"], ["codex-root", "form.codex_root"]]) {
        const o = document.createElement("option");
        o.value = value;
        o.textContent = t(label);
        presetEl.appendChild(o);
      }
      const placeOpt = document.createElement("option");
      placeOpt.value = "root";
      placeOpt.textContent = t("common.root");
      placeEl.appendChild(placeOpt);
      // Same gate as the preset option above: the root Claude-auth row is
      // only ever useful to a user who can reach the root tmux server at all.
      setAuth({ root: true });
    }
    // The second-sandbox preset (aiza-backend's MAILBOX): a Claude Code TUI
    // in a sandbox container separate from devbox-<user>, for material that
    // must not sit in ~/sandhome. Added dynamically for the same reason
    // root-shell is -- a host with no such sandbox configured reports
    // caps.mailbox as null and never shows the option. The label comes from
    // that host's own config file, not from here.
    if (caps.mailbox && caps.mailbox.label) {
      mailboxLabel = caps.mailbox.label;
      hasMailbox = true;
      hasMailboxCodex = caps.mailbox.codex === true;
      const opt = document.createElement("option");
      opt.value = "mail-tui";
      opt.textContent = caps.mailbox.label;
      // Before the Shell entries rather than appended: it belongs with the
      // agent presets (Claude/Codex) it sits alongside, not after the
      // shells. Falls back to appending if that anchor ever goes away.
      presetEl.insertBefore(opt, presetEl.querySelector('option[value="shell"]'));
      const boxPrograms = [["mail-shell", "Shell"]];
      if (hasMailboxCodex) boxPrograms.push(["codex-mail", "Codex"]);
      for (const [value, label] of boxPrograms) {
        const o = document.createElement("option");
        o.value = value;
        o.textContent = `${label} (${caps.mailbox.label})`;
        presetEl.appendChild(o);
      }
      // First among the places, as the user listed them (Email, Dev, ホスト, ルート).
      const placeOpt = document.createElement("option");
      placeOpt.value = "mail";
      placeOpt.textContent = caps.mailbox.label;
      placeEl.insertBefore(placeOpt, placeEl.firstChild);
    }
    localPresetOptionsHtml = presetEl.innerHTML;
    presetFromKindPlace();

    sshCwdMachines = caps.ssh_machines_drives || [];
    sshDesktop = caps.ssh_desktop || {};
    desktopBase = {};
    for (const [base, variant] of Object.entries(sshDesktop)) desktopBase[variant] = base;

    // どこで's ssh machines (the deployment notes 段3), after this host's places.
    for (const g of [...placeEl.querySelectorAll("optgroup.ssh")]) g.remove();
    if ((caps.ssh_machines || []).length) {
      const g = document.createElement("optgroup");
      g.className = "ssh";
      g.label = t("form.ssh_machines");
      for (const machine of caps.ssh_machines) {
        const o = document.createElement("option");
        o.value = `ssh:${machine}`;
        o.textContent = machine;
        g.appendChild(o);
      }
      placeEl.appendChild(g);
    }
    machineSelectEl.innerHTML = "";
    const localOpt = document.createElement("option");
    localOpt.value = "local";
    localOpt.textContent = MACHINE_LABELS.local;
    machineSelectEl.appendChild(localOpt);
    // The Windows machines are reached from the blackboard instead of this
    // menu (2026-11-09, the user): only the one being looked at is listed,
    // so the menu shows it and picking this host goes back.
    boardMachines = new Set(caps.board !== false ? (caps.ssh_machines_drives || []) : []);
    knownMachines = new Set([...(caps.ssh_machines || []), ...boardMachines]);
    for (const machine of caps.ssh_machines || []) {
      MACHINE_LABELS[machine] = machine;
      addSshAuthRow(machine);
      if (boardMachines.has(machine)) continue;
      const opt = document.createElement("option");
      opt.value = machine;
      opt.textContent = machine;
      machineSelectEl.appendChild(opt);
    }
    // Not a machine -- a one-shot navigation to view-auth, always last in
    // the list ("ホスト一覧の一番下", 2026-08-15). Renamed "Claude 認証" ->
    // "設定" (2026-08-18) once that page grew a second, unrelated concern
    // (Kill Chrome) -- see index.html's comment on #auth-header.
    // The blackboard of the Windows machines (the deployment notes): an entry
    // here instead of its own 📋 in the header (2026-11-09, the user: the
    // header was full again).
    const authOpt = document.createElement("option");
    authOpt.value = "auth";
    authOpt.textContent = t("common.settings");
    machineSelectEl.appendChild(authOpt);
    machineSelectEl.addEventListener("change", applyMachineFilter);
    updateMachineBtn();
  }

  // ---- working directory + resume, for the headless "claude" preset ------
  //
  // Everything here is a *choice from what already exists* rather than free
  // text: a phone keyboard is a bad place to type a path, and a typo would
  // only surface as a 400 after tapping 開始. The directory is walked one
  // level at a time (breadcrumb + "open a subfolder" + ↑) instead of being
  // picked out of a flattened list of the whole tree -- that keeps every
  // dropdown short while leaving any depth reachable. The conversation list
  // then comes from whichever directory you stopped at.

  function applyPresetOptions() {
    const form = presetForm(presetEl.value);
    const isMail = form.picker === "mail";
    claudeOptsEl.classList.toggle("visible", form.picker === "claude" || isMail);
    // Resume is Claude's own: not for the Email shell or Codex.
    resumeEl.closest(".nsb-row").style.display =
      (form.resume && form.picker !== "ssh") ? "" : "none";
    // The Email Claude always runs with --dangerously-skip-permissions
    // (the sandbox CLI builds that command line), so no checkbox for it.
    const skipCodex = form.skip === "codex";
    skipRowEl.hidden = !form.skip;
    skipLabelEl.textContent = skipCodex
      ? t("form.dont_ask_before_each_ai")
      : t("common.dont_ask_before_each_ai");
    const scope = isMail ? "mail" : "sandhome";
    if (scope !== cwdScope && (isMail || form.picker === "claude")) {
      cwdByScope[cwdScope] = currentCwd;
      cwdScope = scope;
      currentCwd = cwdByScope[scope];
      refreshWorkdirs();
    }
    // #ssh-cwd-opts: only for a drives-capable machine's
    // own Claude preset ("claude-tui-<machine>") -- "Shell" on the same
    // machine gets no picker either, same as the local "shell" preset.
    const showSshCwd = form.picker === "ssh";
    sshCwdOptsEl.classList.toggle("visible", showSshCwd);
    sshShellOptsEl.classList.toggle("visible",
      !!sshDesktop[currentMachine] && presetEl.value === `shell-${currentMachine}`);
    updateDesktopToggle();
    if (showSshCwd) refreshSshWorkdirs();
    const showShellCwd = form.picker === "shell";
    shellCwdOptsEl.classList.toggle("visible", showShellCwd);
    if (showShellCwd) refreshShellCwdWorkdirs();
  }

  function updateDesktopToggle() {
    const available = !!sshDesktop[currentMachine];
    if (!available) desktopMode = false;
    for (const el of desktopToggleEls) {
      el.style.display = available ? "" : "none";
      el.textContent = desktopMode ? "🪟" : "🐚";
      el.title = desktopMode
        ? t("form.screen_runs_in_desktop_session")
        : t("form.no_screen_runs_in_session");
    }
  }
  for (const el of desktopToggleEls) {
    el.addEventListener("click", () => {
      desktopMode = !desktopMode;
      updateDesktopToggle();
    });
  }

  // Re-reads the level `currentCwd` points at. A directory that has since
  // been renamed or deleted answers 400, which drops us back to ~/sandhome
  // rather than leaving the UI pointing at something that isn't there.
  // interactive=false: a background re-read (back from a session, page
  // load) -- for "mail" that must not pop a passkey prompt out of nowhere,
  // so a locked window just leaves the picker as it was.
  async function refreshWorkdirs(interactive = true) {
    const asked = currentCwd;
    const scope = cwdScope;
    // "mail" is host-tier gated (it lists mail-derived folders), so it can
    // ask for the passkey right here, like root-shell's own picker does.
    const fetchIt = () => api(`/workdirs?scope=${scope}&dir=${encodeURIComponent(asked)}`);
    let unlockNeeded = false;
    const r = await (scope === "mail" && interactive ? withUnlockRetry(fetchIt) : fetchIt())
      .catch((e) => { unlockNeeded = !!e.unlockRequired; return null; });
    if (!r && unlockNeeded && !interactive) return;
    if (asked !== currentCwd || scope !== cwdScope) return; // a later navigation already won
    const top = scope === "mail" ? mailboxLabel : "sandhome";
    if (!r) {
      if (currentCwd === "") {
        if (scope === "mail") {
          cwdCrumbEl.textContent = top;
          cwdUpBtn.disabled = true;
          cwdChildEl.innerHTML = `<option value="">${t("form.could_not_get_list")}</option>`;
          cwdChildEl.disabled = true;
          populateConversationSelect(resumeEl, []);
        }
        return;
      }
      currentCwd = "";
      return refreshWorkdirs(interactive);
    }
    currentCwd = r.dir;
    cwdCrumbEl.textContent = currentCwd ? `${top}/${currentCwd}` : top;
    cwdUpBtn.disabled = !currentCwd;

    cwdChildEl.innerHTML = "";
    const head = document.createElement("option");
    head.value = "";
    head.textContent = r.subdirs.length ? t("common.open_subfolder") : t("form.no_subfolders");
    cwdChildEl.appendChild(head);
    cwdChildEl.disabled = !r.subdirs.length;
    for (const name of r.subdirs) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      cwdChildEl.appendChild(opt);
    }
    await refreshConversations(interactive);
  }

  async function navigateTo(rel) {
    currentCwd = rel;
    await refreshWorkdirs();
  }

  cwdChildEl.addEventListener("change", () => {
    const name = cwdChildEl.value;
    if (!name) return;
    navigateTo(currentCwd ? `${currentCwd}/${name}` : name);
  });

  cwdUpBtn.addEventListener("click", () => {
    if (!currentCwd) return;
    const cut = currentCwd.lastIndexOf("/");
    navigateTo(cut === -1 ? "" : currentCwd.slice(0, cut));
  });

  // ＋: a new, empty folder under the one shown, then straight into it
  // (POST /workdirs, the deployment notes). Both trees -- the user asked for it
  // on Email, and the two pickers are meant to behave the same.
  document.getElementById("cwd-new").addEventListener("click", async () => {
    const name = ((await ui.ask(t("form.name_new_folder"), "")) || "").trim();
    if (!name) return;
    const scope = cwdScope;
    const parent = currentCwd;
    const post = () => api("/workdirs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope, dir: parent, name }),
    });
    const r = await (scope === "mail" ? withUnlockRetry(post) : post()).catch((e) => ({ error: e.message }));
    if (r.error) return ui.toast(t("form.could_not_create_folder_err", { err: r.error }), { error: true });
    if (scope === cwdScope) navigateTo(r.dir);
  });

  // ---- drive/folder picker, for a drives-capable ssh machine's Claude
  // preset ------------------------------------------------------------------
  //
  // Same one-level-at-a-time idea as the sandhome picker above, just rooted
  // at "pick a drive" (currentSshCwd === "") instead of always starting
  // somewhere under ~/sandhome. GET /ssh-workdirs answers `drives` (only
  // when `dir` is empty) or `subdirs` (once a drive/folder is chosen) --
  // never both at once.

  // "/d/Projects/foo" -> "D:/Projects/foo" -- purely a display nicety, the
  // posix form is still what is stored in currentSshCwd/sent to the backend.
  function mountPathLabel(path) {
    const m = path.match(/^\/([a-z])(\/.*)?$/);
    return m ? `${m[1].toUpperCase()}:${m[2] || "/"}` : path;
  }

  async function refreshSshWorkdirs() {
    const machine = currentMachine;
    const asked = currentSshCwd;
    const r = await api(`/ssh-workdirs?machine=${encodeURIComponent(machine)}&dir=${encodeURIComponent(asked)}`)
      .catch(() => null);
    // A later navigation, or a machine switch while this was in flight,
    // already won -- same guard as refreshWorkdirs() above.
    if (machine !== currentMachine || asked !== currentSshCwd) return;
    if (!r) {
      if (currentSshCwd === "") return;
      currentSshCwd = "";
      return refreshSshWorkdirs();
    }
    currentSshCwd = r.dir;
    const atRoot = currentSshCwd === "";
    sshCwdCrumbEl.textContent = atRoot ? t("common.choose_drive_2") : mountPathLabel(currentSshCwd);
    sshCwdUpBtn.disabled = atRoot;
    sshCwdNewBtn.disabled = atRoot; // a folder needs a drive to go in

    sshCwdChildEl.innerHTML = "";
    const items = atRoot ? r.drives : r.subdirs;
    const head = document.createElement("option");
    head.value = "";
    head.textContent = items.length
      ? (atRoot ? t("common.choose_drive") : t("common.open_subfolder"))
      : (atRoot ? t("form.no_drives_found") : t("form.no_subfolders"));
    sshCwdChildEl.appendChild(head);
    sshCwdChildEl.disabled = !items.length;
    for (const name of items) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = atRoot ? `${name.toUpperCase()}:` : name;
      sshCwdChildEl.appendChild(opt);
    }
    await refreshSshConversations();
  }

  async function navigateSshTo(path) {
    currentSshCwd = path;
    await refreshSshWorkdirs();
  }

  sshCwdChildEl.addEventListener("change", () => {
    const name = sshCwdChildEl.value;
    if (!name) return;
    // At the root, `name` is a bare drive letter ("d"), not a child of the
    // current path -- everywhere else this is exactly navigateTo()'s own
    // "append below the current directory" move.
    navigateSshTo(currentSshCwd ? `${currentSshCwd}/${name}` : `/${name}`);
  });

  sshCwdUpBtn.addEventListener("click", () => {
    if (!currentSshCwd) return;
    const cut = currentSshCwd.lastIndexOf("/");
    navigateSshTo(cut === -1 ? "" : currentSshCwd.slice(0, cut));
  });

  // ＋ on a Windows machine (2026-10-08, user request): the same new-folder
  // move as #claude-opts' own, created on that machine over ssh.
  sshCwdNewBtn.addEventListener("click", async () => {
    if (!currentSshCwd) return;
    const name = ((await ui.ask(t("form.name_new_folder"), "")) || "").trim();
    if (!name) return;
    const machine = currentMachine;
    const parent = currentSshCwd;
    const r = await api("/workdirs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope: "ssh", machine, dir: parent, name }),
    }).catch((e) => ({ error: e.message }));
    if (r.error) return ui.toast(t("form.could_not_create_folder_err", { err: r.error }), { error: true });
    if (machine === currentMachine && parent === currentSshCwd) navigateSshTo(r.dir);
  });

  // ---- working-directory-only picker, for "shell"/"host-shell"/
  // "root-shell" (2026-09-27, the deployment notes) -----------------
  //
  // One picker, three backend scopes (SHELL_CWD_SCOPE) -- "sandhome" walks
  // one level at a time exactly like #claude-opts' own (`dir` relative to
  // ~/sandhome, "" at the root); "host"/"root" walk the real filesystem
  // instead, so `dir` there is an absolute path throughout, no relative
  // math needed -- see aiza-backend's GET /workdirs.

  async function refreshShellCwdWorkdirs() {
    const preset = presetEl.value;
    const scope = presetForm(preset).scope;
    if (!scope) return;
    const asked = shellCwdByPreset[preset];
    const fetchIt = () => api(`/workdirs?scope=${scope}&dir=${encodeURIComponent(asked)}`);
    // "root": GET /workdirs?scope=root can 403 unlock_required (root-shell's
    // own picker routes through the root tmux pane, gated the same passkey-
    // unlock way opening the session itself already is) -- withUnlockRetry
    // runs that ceremony right here instead of leaving the picker empty
    // until 開始 is pressed and the *session* creation call hits the same
    // gate. "sandhome"/"host" never raise this, so wrapping them too would
    // just be a needless no-op layer.
    const r = await (scope === "root" ? withUnlockRetry(fetchIt) : fetchIt()).catch(() => null);
    // A later navigation, or a preset switch while this was in flight,
    // already won -- same guard as refreshWorkdirs()/refreshSshWorkdirs().
    if (presetEl.value !== preset || shellCwdByPreset[preset] !== asked) return;
    if (!r) {
      if (shellCwdByPreset[preset] === "") {
        // Even the default dir failed (e.g. passkey cancelled): clear the
        // previous preset's options rather than leave them looking current.
        shellCwdCrumbEl.textContent = "";
        shellCwdUpBtn.disabled = true;
        shellCwdChildEl.innerHTML = "";
        const fail = document.createElement("option");
        fail.value = "";
        fail.textContent = t("form.could_not_get_list");
        shellCwdChildEl.appendChild(fail);
        shellCwdChildEl.disabled = true;
        return;
      }
      shellCwdByPreset[preset] = "";
      return refreshShellCwdWorkdirs();
    }
    shellCwdByPreset[preset] = r.dir;
    shellCwdCrumbEl.textContent = scope === "sandhome" ? (r.dir ? `sandhome/${r.dir}` : "sandhome") : r.dir;
    shellCwdUpBtn.disabled = scope === "sandhome" ? !r.dir : r.dir === "/";

    shellCwdChildEl.innerHTML = "";
    const head = document.createElement("option");
    head.value = "";
    head.textContent = r.subdirs.length ? t("common.open_subfolder") : t("form.no_subfolders");
    shellCwdChildEl.appendChild(head);
    shellCwdChildEl.disabled = !r.subdirs.length;
    for (const name of r.subdirs) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      shellCwdChildEl.appendChild(opt);
    }
  }

  async function navigateShellCwdTo(rel) {
    shellCwdByPreset[presetEl.value] = rel;
    await refreshShellCwdWorkdirs();
  }

  shellCwdChildEl.addEventListener("change", () => {
    const name = shellCwdChildEl.value;
    if (!name) return;
    const scope = presetForm(presetEl.value).scope;
    const cur = shellCwdByPreset[presetEl.value];
    navigateShellCwdTo(
      scope === "sandhome"
        ? (cur ? `${cur}/${name}` : name)
        : (cur === "/" ? `/${name}` : `${cur}/${name}`)
    );
  });

  shellCwdUpBtn.addEventListener("click", () => {
    const scope = presetForm(presetEl.value).scope;
    const cur = shellCwdByPreset[presetEl.value];
    if (scope === "sandhome") {
      if (!cur) return;
      const cut = cur.lastIndexOf("/");
      navigateShellCwdTo(cut === -1 ? "" : cur.slice(0, cut));
    } else {
      if (!cur || cur === "/") return;
      const cut = cur.lastIndexOf("/");
      navigateShellCwdTo(cut <= 0 ? "/" : cur.slice(0, cut));
    }
  });

  // ＋ on the shell pickers too (2026-10-13, user request): the same
  // new-folder move as #claude-opts' own. "host"/"root" create on the real
  // filesystem, behind the same unlock window the pane itself needs.
  shellCwdNewBtn.addEventListener("click", async () => {
    const preset = presetEl.value;
    const scope = presetForm(preset).scope;
    if (!scope) return;
    const name = ((await ui.ask(t("form.name_new_folder"), "")) || "").trim();
    if (!name) return;
    const parent = shellCwdByPreset[preset];
    const post = () => api("/workdirs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ scope, dir: parent, name }),
    });
    const r = await (scope === "sandhome" ? post() : withUnlockRetry(post)).catch((e) => ({ error: e.message }));
    if (r.error) return ui.toast(t("form.could_not_create_folder_err", { err: r.error }), { error: true });
    if (presetEl.value === preset && shellCwdByPreset[preset] === parent) navigateShellCwdTo(r.dir);
  });

  // Shared option-building behind refreshConversations (local) and
  // refreshSshConversations (a drives-capable ssh machine,
  // the deployment notes) -- both fetch the same {id, mtime, aiza_label, summary} shape
  // from GET /claude-conversations, just against a different cwd/machine.
  function populateConversationSelect(selectEl, conversations) {
    selectEl.innerHTML = "";
    const fresh = document.createElement("option");
    fresh.value = "";
    fresh.textContent = t("common.new_2");
    selectEl.appendChild(fresh);
    for (const c of conversations) {
      const opt = document.createElement("option");
      opt.value = c.id;
      const when = fmtDateTime(c.mtime);
      const rest = c.summary ? c.summary : `(${c.id.slice(0, 8)})`;
      // c.aiza_label is the name *this app* gave the
      // session that last used this conversation, if any -- shown ahead of
      // Claude Code's own auto-generated summary since it's what the user
      // actually chose to call it (2026-08-29, at the user's request).
      opt.textContent = c.aiza_label ? `${when} [${c.aiza_label}] ${rest}` : `${when} ${rest}`;
      // Read back by wireResumeLabelPrefill below -- aiza-backend's own
      // create_session() already falls back to this same label server-side
      // when the field is left blank, so this prefill is purely so the name
      // is visible/editable *before* tapping 開始, not what actually makes
      // it carry over (the deployment notes, 2026-09-24).
      if (c.aiza_label) opt.dataset.aizaLabel = c.aiza_label;
      // ssh list only (the deployment notes): how an aiza session last ran this
      // conversation, read back by the 🐚/🪟 restore below.
      if (typeof c.aiza_desktop === "boolean") opt.dataset.desktop = c.aiza_desktop ? "1" : "0";
      selectEl.appendChild(opt);
    }
  }

  // Conversations are per-directory (Claude Code files them under the cwd
  // they ran in), so this reruns on every navigation.
  async function refreshConversations(interactive = true) {
    const cwd = currentCwd;
    const scope = cwdScope;
    const fetchIt = () => api(`/claude-conversations?scope=${scope}&cwd=${encodeURIComponent(cwd)}`);
    const { conversations } = await (scope === "mail" && interactive ? withUnlockRetry(fetchIt) : fetchIt())
      .catch(() => ({ conversations: [] }));
    // A slow directory read could land after the user has already picked
    // another directory; that answer belongs to the old one, so drop it.
    if (currentCwd !== cwd || cwdScope !== scope) return;
    populateConversationSelect(resumeEl, conversations);
  }

  // ssh: counterpart of refreshConversations, for a drives-capable ssh
  // machine's own Claude preset (the deployment notes). currentSshCwd ===
  // "" means no drive/folder has been chosen yet -- list_ssh_claude_
  // conversations has no fixed directory to fall back to there (unlike
  // ~/sandhome locally), so this just shows "新規" with nothing else,
  // same as passing an empty `dir` to GET /claude-conversations does
  // server-side.
  async function refreshSshConversations() {
    const machine = currentMachine;
    const cwd = currentSshCwd;
    if (!cwd) {
      populateConversationSelect(sshResumeEl, []);
      return;
    }
    const { conversations } = await api(
      `/claude-conversations?machine=${encodeURIComponent(machine)}&dir=${encodeURIComponent(cwd)}`
    ).catch(() => ({ conversations: [] }));
    // Same "a later navigation already won" guard as refreshConversations.
    if (machine !== currentMachine || currentSshCwd !== cwd) return;
    populateConversationSelect(sshResumeEl, conversations);
  }

  // Picking a conversation to resume prefills its own past name into the
  // label field, same "carry the name over" request the backend default
  // above already covers -- this just makes the carried-over name visible
  // and still editable before creating, instead of a silent default the
  // user only discovers afterward.
  //
  // lastAutoLabel tracks what this listener itself last wrote, so it can
  // tell "the user typed their own text" (never touched again, even across
  // switching candidates) apart from "still showing whatever we filled in
  // last time" (safe to replace when a *different* candidate is picked --
  // without this, picking conversation A then B would leave A's name
  // behind because the field was no longer literally empty). One closure
  // per select (local/ssh are independent pickers, never shown at once, but
  // switching machine/preset between them should not leak one's state into
  // the other's).
  function wireResumeLabelPrefill(selectEl) {
    let lastAutoLabel = null;
    selectEl.addEventListener("change", () => {
      const labelEl = document.getElementById("label");
      if (labelEl.value !== "" && labelEl.value !== lastAutoLabel) return;
      const wanted = selectEl.selectedOptions[0]?.dataset.aizaLabel || "";
      labelEl.value = wanted;
      lastAutoLabel = wanted || null;
    });
  }
  wireResumeLabelPrefill(resumeEl);
  wireResumeLabelPrefill(sshResumeEl);
  // Picking a conversation to resume also puts the 🐚/🪟 toggle back to how
  // it last ran (2026-10-05, at the user's request) -- only when aiza knows
  // (it ran there before) and this machine has a desktop variant at all.
  // Still just a default: the toggle can be flipped again before 開始.
  sshResumeEl.addEventListener("change", () => {
    const d = sshResumeEl.selectedOptions[0]?.dataset.desktop;
    if (d === undefined || !sshDesktop[currentMachine]) return;
    desktopMode = d === "1";
    updateDesktopToggle();
  });

  presetEl.addEventListener("change", applyPresetOptions);
  kindEl.addEventListener("change", () => { presetFromKindPlace(); suggestName(); });
  // どこで holds the ssh machines too (the deployment notes 段3: ssh:<machine>):
  // picking one makes it the machine the form starts on.
  placeEl.addEventListener("change", () => {
    const v = placeEl.value;
    const m = v.startsWith("ssh:") ? v.slice(4) : "local";
    if (m !== currentMachine) selectMachine(m);
    presetFromKindPlace();
    suggestName();
  });

  // ---- セッションを始める (the deployment notes 段3) ------------------------------
  // The one screen for starting a session, whatever it is started from. The
  // opener says what it knows (ctx); every field stays changeable:
  //   folder   a session folder's id (a folder's ＋)
  //   title    the name to start with (a tree item's, an issue's)
  //   kind, place  what to run where ("claude"/"codex"/"shell", "dev"/"mail"/
  //            "host"/"root"/"ssh:<m>")
  //   note     what it will be linked to ("🔗 …"), with a checkbox to leave it out
  //   prepare(body, linked)  adds to the POST /sessions body (the tree's first message, an issue)
  //   create(body, linked)   instead of POST /sessions (🤛 引き取る: POST /tree take)
  //   after(meta, linked)    once it exists (the tree's link to the item)
  const startModalEl = document.getElementById("start-modal");
  const startNoteEl = document.getElementById("start-note");
  const startLinkEl = document.getElementById("start-link");
  const labelEl = document.getElementById("label");
  let startCtx = {};
  let startPushed = false;
  let labelTouched = false;
  labelEl.addEventListener("input", () => { labelTouched = true; });
  // The name to start with when nothing else gives one (2026-11-25, the
  // user): the AI first, then where -- claudeD (devbox), claudeH (host),
  // claudeR (root), claudeM (Email), claude@<machine> -- and a number when
  // that name is taken already (claudeD2, claudeD3, ...).
  const PLACE_LETTER = { dev: "D", host: "H", root: "R", mail: "M" };
  function suggestName() {
    if (labelTouched || startCtx.title) return;
    const v = placeEl.value || "dev";
    const base = (kindEl.value || "claude") + (v.startsWith("ssh:") ? "@" + v.slice(4) : PLACE_LETTER[v] || "");
    const taken = new Set(ui.start.names());
    let name = base;
    for (let i = 2; taken.has(name); i++) name = base + i;
    labelEl.value = name;
  }
  // 置く場所 (the deployment notes 段4): the folders with their trees and open
  // items (tree.js). An item makes the session that item's (its title, its
  // link, its tree's folder); a folder only files it there. Opened for an
  // issue or someone's item to take on, only the folder can change.
  const startPlaceEl = document.getElementById("start-place");
  let startBase = {};
  function fillStartPlace() {
    startPlaceEl.innerHTML = "";
    startPlaceEl.add(new Option(t("form.in_no_folder"), ""));
    const nodesOk = !startBase.note || !!startBase.node;
    for (const o of ui.trees.placeOptions()) {
      const opt = new Option("\u3000".repeat(o.depth) + o.label, o.value);
      if (o.node && !nodesOk) opt.disabled = true;
      startPlaceEl.add(opt);
    }
    const want = startCtx.node ? "n:" + startCtx.node : startCtx.folder ? "f:" + startCtx.folder : "";
    startPlaceEl.value = [...startPlaceEl.options].some((o) => o.value === want) ? want : "";
  }
  function showStartNote() {
    startNoteEl.hidden = !startCtx.note;
    startNoteEl.querySelector(".what").textContent = startCtx.note || "";
  }
  startPlaceEl.addEventListener("change", () => {
    const v = startPlaceEl.value;
    if (v.startsWith("n:")) {
      const nc = ui.trees.startCtx(v.slice(2));
      if (!nc) return;
      startCtx = nc;
      if (!labelTouched) labelEl.value = nc.title;
      ui.start.setFolder(nc.folder || null);
    } else {
      // A folder (or none): what the opener gave, without a tree item of its own.
      startCtx = startBase.node ? { folder: v.slice(2) || null } : Object.assign({}, startBase, { folder: v.slice(2) || null });
      ui.start.setFolder(v.slice(2) || null);
      if (!labelTouched && !startCtx.title) { labelEl.value = ""; suggestName(); }
    }
    startLinkEl.checked = true;
    showStartNote();
  });
  // Where the form lives when it is over the page (its place in index.html);
  // ＋ 🤖 AI opens it inline instead, in the top row's panel (opts.inline,
  // list.js ui.tool, 2026-11-27): no layer, no Back entry of its own.
  const startHome = { parent: startModalEl.parentNode, next: startModalEl.nextSibling };
  let startInline = false;
  function placeStart(slot) {
    if (slot) { if (startModalEl.parentNode !== slot) slot.appendChild(startModalEl); }
    else if (startModalEl.parentNode !== startHome.parent) startHome.parent.insertBefore(startModalEl, startHome.next);
    startModalEl.classList.toggle("inline", !!slot);
    startInline = !!slot;
  }
  function openStart(ctx = {}, opts = {}) {
    // Opened over the page while it was open inline: the panel lets it go.
    if (!opts.inline && startInline && !startModalEl.hidden) {
      startModalEl.hidden = true;
      if (ui.tool) ui.tool.startClosed();
    }
    if (startModalEl.hidden) placeStart(opts.inline || null);
    startCtx = ctx || {};
    startBase = startCtx;
    labelTouched = false;
    if (startCtx.place) {
      const m = startCtx.place.startsWith("ssh:") ? startCtx.place.slice(4) : "local";
      if (m !== currentMachine) selectMachine(m);
    }
    if (startCtx.kind) kindEl.value = startCtx.kind;
    if (startCtx.place && [...placeEl.options].some((o) => o.value === startCtx.place)) placeEl.value = startCtx.place;
    presetFromKindPlace();
    ui.start.setFolder(startCtx.folder || null);
    labelEl.value = startCtx.title || "";
    suggestName();
    showStartNote();
    startLinkEl.checked = true;
    ui.trees.load();
    fillStartPlace();
    if (startInline) {
      startModalEl.hidden = false;
      const first = labelEl.offsetParent ? labelEl : startModalEl.querySelector("input, select, textarea");
      if (first) first.focus();
      return;
    }
    if (startModalEl.hidden) { ui.layer.push(); startPushed = true; }
    startModalEl.hidden = false;
    ui.set({ overlay: "start" });
  }
  // keep: 開始 -- the chat takes the layer's history entry over.
  function closeStart(keep) {
    if (startModalEl.hidden) return;
    startModalEl.hidden = true;
    if (startInline) {
      startCtx = {};
      if (ui.tool) ui.tool.startClosed();
      return;
    }
    if (ui.get().overlay === "start") ui.set({ overlay: null });
    const pushed = startPushed;
    startPushed = false;
    startCtx = {};
    if (keep && pushed) ui.layer.handToSession();
    else if (pushed) history.back();
  }
  // Back while it is open closes it (its own entry).
  window.addEventListener("popstate", () => {
    if (startModalEl.hidden || !startPushed) return;
    startPushed = false;
    closeStart(false);
  });
  startModalEl.addEventListener("click", (e) => {
    if (e.target === startModalEl || e.target.closest(".start-head .close")) closeStart(false);
  });
  // With a folder or a tree item selected (list.js ui.sel): in it / on it.
  // ＋ 🤖 AI: in the top row's panel (list.js ui.tool opens it with opts.inline).
  document.getElementById("start-btn").addEventListener("click", () => {
    if (ui.tool) ui.tool.open("start");
    else openStart(ui.sel ? ui.sel.startCtx() : {});
  });
  ui.start = Object.assign(ui.start || {}, {
    open: (ctx, opts) => openStart(ctx, opts),
    close: (keep) => closeStart(keep),
    ctx: () => startCtx,
    linked: () => !!startCtx.note && startLinkEl.checked,
  });
