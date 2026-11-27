// One session's screen size, and stopping or resuming it (aiza).
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after voice.js and before app.js, in this order:
// form, settings, keys, api, links, search, sessionops, compose. What runs
// here at load uses only this file and the earlier ones. Moved out of
// app.js 2026-11-24 as it was; the indentation is app.js's.
"use strict";

  // This file's own element of the page (only it uses it; from form.js, 2026-11-24).
  const skipPermissionsEl = document.getElementById("skip-permissions");

  // How many monospace columns the screen panel can actually show without
  // horizontal scrolling, measured against its real font/size rather than
  // assumed -- a fixed 220-column pane is what a fullscreen TUI (claude-tui)
  // lays its own borders/menus out against, and none of that fits a phone
  // screen at a readable size.
  //
  // Measured with a real, off-screen <pre> styled exactly like #screen-pane,
  // not Canvas measureText -- Canvas's font shorthand parser does not
  // reliably resolve the "ui-monospace" CSS Fonts 4 generic the same way
  // layout does on every engine, and a silent fallback there measures a
  // different (in practice, narrower) font than #screen-pane actually
  // renders with, which is exactly what produced a pane roughly 2x wider
  // than the phone's real screen.
  function computeScreenCols() {
    const probe = document.createElement("pre");
    probe.style.cssText =
      "position: absolute; visibility: hidden; white-space: pre; margin: 0; padding: 0; " +
      "font-family: ui-monospace, monospace; font-size: 0.7rem; line-height: 1.25;";
    const sample = "0".repeat(100);
    probe.textContent = sample;
    document.body.appendChild(probe);
    const charWidth = probe.getBoundingClientRect().width / sample.length;
    document.body.removeChild(probe);

    const rootPx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const horizontalPadding = 1.6 * rootPx; // #screen-pane's 0.8rem left + right
    const available = document.documentElement.clientWidth - horizontalPadding;
    return Math.max(20, Math.floor(available / charWidth));
  }

  // How many monospace rows the screen panel can actually show at once,
  // sent as the tmux pane's own height (2026-08-31)
  // so a fullscreen TUI (claude-tui, or `claude` run by hand)
  // lays itself out against a *real* terminal size instead of the flat 300
  // rows every session used to get regardless of any screen looking at it
  // -- which left a large dead gap between the actual conversation and a
  // footer/composer a fullscreen program pins to the true bottom of
  // whatever height it is told the terminal has. Unlike computeScreenCols,
  // no off-screen <pre> measurement is needed: line-height is already an
  // exact multiple of font-size by CSS definition, not something a font's
  // metrics can make narrower than assumed the way character width can.
  //
  // Deliberately asks for SCREEN_OVERFLOW_BUFFER_ROWS more than what
  // #screen-pane's own max-height can actually display at once
  // (2026-09-01, at the user's request) -- a
  // pane sized to *exactly* fill the panel never overflows it, so the
  // panel never gets a scrollbar/scroll position to drag on at all, and
  // the gesture meant to reach history mode from there (dragging/wheeling
  // up while already at the top) turned out not to fire reliably on every
  // device/browser. A few rows of permanent, always-present overflow is a
  // far smaller version of the exact defect this whole feature fixed (a
  // fullscreen program padding unused rows with blank lines) -- accepted
  // deliberately this time, in exchange for scrolling to reach history
  // always working through the one, always-reliable native path (the
  // "scroll" listener above, confirmed to work whenever real overflow
  // exists) instead of a gesture that does not.
  const SCREEN_OVERFLOW_BUFFER_ROWS = 5;
  function computeScreenRows() {
    const rootPx = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const lineHeightPx = 0.7 * 1.25 * rootPx; // #screen-pane's font-size * line-height
    const verticalPadding = 1.2 * rootPx; // #screen-pane's 0.6rem top + bottom
    const available = document.documentElement.clientHeight * 0.45 - verticalPadding; // max-height: 45vh
    return Math.max(10, Math.floor(available / lineHeightPx)) + SCREEN_OVERFLOW_BUFFER_ROWS;
  }

  const createBtn = document.getElementById("create-btn");

  createBtn.addEventListener("click", async () => {
    // A cold remote tmux server (first session after it
    // was last idle) can now take up to a
    // few minutes to actually start (aiza-backend polls rather than failing
    // fast), so without this a second tap while the first was still in
    // flight created a second, duplicate session -- confirmed 2026-08-14 as
    // exactly why "the first tap did nothing, the second one worked, then a
    // failure showed up later" was actually two sessions racing, not one
    // session failing. The button text is the only feedback a plain
    // disabled button gives, so it says so explicitly.
    if (createBtn.disabled) return;
    createBtn.disabled = true;
    const originalLabel = createBtn.textContent;
    createBtn.textContent = t("sessionops.starting");
    try {
      let preset = presetEl.value;
      const label = document.getElementById("label").value;
      const body = { preset, label, cols: computeScreenCols(), rows: computeScreenRows() };
      // The backend rejects these outright for the plain shells rather than
      // ignoring them, so only send them for the presets they apply to.
      const form = presetForm(preset);
      if ((form.picker === "claude" || form.picker === "mail") && form.resume) {
        body.cwd = currentCwd;
        body.resume = resumeEl.value;
      } else if (form.picker === "mail") {
        body.cwd = currentCwd;          // the Email shell/Codex: a folder, no resume
      } else if (form.picker === "ssh") {
        // resume is only meaningful once a drive/folder was actually chosen
        // (see create_session's own check) -- an empty currentSshCwd sends
        // resume: "", same as never picking one from #ssh-resume.
        body.cwd = currentSshCwd;
        body.resume = sshResumeEl.value;
      } else if (form.picker === "shell") {
        // No resume for these (FORM_PRESETS) -- just
        // the working directory, already in whatever shape create_session
        // expects for this preset's scope (sandhome-relative for "shell",
        // an absolute path for "host-shell"/"root-shell").
        body.cwd = shellCwdByPreset[preset];
      }
      // 🪟: the same preset on the machine's desktop variant
      // (the deployment notes) -- cwd/resume above stay valid as-is, since the
      // variant is the same machine and filesystem.
      // Only while a toggle is actually on screen (the Claude preset's
      // #ssh-resume row, or #ssh-shell-opts for "Shell"): a 🪟 left on from
      // before must not silently apply to a preset that doesn't show it.
      const variant = sshDesktop[currentMachine];
      const toggleShown = sshCwdOptsEl.classList.contains("visible") || sshShellOptsEl.classList.contains("visible");
      if (desktopMode && variant && toggleShown && preset.endsWith(`-${currentMachine}`)) {
        preset = preset.slice(0, -currentMachine.length) + variant;
        body.preset = preset;
      }
      // Only the claude-tui presets honor this (see aiza-backend's
      // CLAUDE_TUI_PRESETS/create_session) -- the headless "claude" preset
      // hardcodes it unconditionally already, and the plain shells have no
      // such flag at all.
      if (form.skip || preset.startsWith("claude-tui-")) {
        body.skip_permissions = skipPermissionsEl.checked;
      }
      // Made from a folder's ＋ (the deployment notes): the backend picks the
      // directory from the folder, unless a conversation to resume was
      // chosen (that one's own folder stands).
      if (newSessionFolder) {
        body.folder = newSessionFolder;
        if (folderEffectiveWorkdir(newSessionFolder) && !body.resume) delete body.cwd;
      }
      // What the start screen was opened from (the deployment notes 段3): a tree
      // item, an issue, someone's item to take on -- unless 結びつける was cleared.
      const ctx = ui.start.ctx(), linked = ui.start.linked();
      if (linked && ctx.prepare) ctx.prepare(body);
      // withUnlockRetry: picking "host-shell"/"root-shell" (or any other
      // host/root preset) while the 15-minute window is closed pops the
      // passkey prompt right here, then creates this same session once it
      // succeeds -- the user never has to press 開始 a second time.
      const meta = await withUnlockRetry(() => (linked && ctx.create ? ctx.create(body) : api("/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }))).catch((e) => {
        alert(t("common.could_not_create_session_err", { err: e.message }));
        return null;
      });
      if (!meta) return;
      if (linked && ctx.after) await ctx.after(meta);
      ui.start.close(true);   // the chat takes its place (and its history entry)
      document.getElementById("label").value = "";
      resumeEl.value = "";
      sshResumeEl.value = "";
      setNewSessionFolder(null);
      await refreshSessions();
      chatNow.open(meta);
    } finally {
      createBtn.disabled = false;
      createBtn.textContent = originalLabel;
    }
  });

  // ← is a link to the list (its href kept on the selected machine's list);
  // a plain click closes the chat without reloading the page.
  const backLinkEl = document.getElementById("back-btn");
  backLinkEl.addEventListener("click", (e) => {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    chatNow.close();
  });
  const syncBackHref = () => {
    backLinkEl.href = `${appPath()}${location.search}${listHash() ? "#" + listHash() : ""}`;
  };
  backLinkEl.addEventListener("pointerdown", syncBackHref);
  backLinkEl.addEventListener("focus", syncBackHref);
  backLinkEl.addEventListener("contextmenu", syncBackHref);
  // See tapToLeave. Capture phase, so the tap does nothing else on the way.
  viewChat.addEventListener("click", (e) => {
    if (!tapToLeave) return;
    e.preventDefault();
    e.stopPropagation();
    chatNow.close();
  }, true);

  // The chat header's status dot: on one's own ended, resumable session a
  // tap offers to resume it (same as the list row's grey dot); its
  // long-press force-stop does nothing once the session has ended.
  function chatDotResumable() {
    const m = chatNow.meta;
    return !!m && m.alive === false && !chatNow.owner && canResumeEnded(m);
  }
  function updateChatResumeBtn() {
    const m = chatNow.meta;
    const ended = !!m && m.alive === false;
    const resumable = chatDotResumable();
    chatDotEl.classList.toggle("resumable", resumable);
    chatDotEl.title = resumable ? t("common.tap_resume") : ended ? t("sessionops.ended") : t("common.tap_stop");
  }
  chatDotEl.addEventListener("click", () => {
    if (chatDotResumable()) { resumeEndedSession(chatNow.meta); return; }
    if (chatNow.meta && chatNow.meta.alive !== false && currentShareMode !== "read") {
      stopSessionConfirmed(chatNow.id, chatNow.owner, true);
    }
  });

  // Stopping a running session: an ordinary tap on its green status dot and
  // a confirm (2026-10-09, user request -- it used to be a long-press, now
  // that the grey dot's tap resumes, a tap is consistent). The backend first
  // sends Claude Code Ctrl+C twice so it exits with its conversation saved
  // for a later resume, then ends the session (aiza-backend's
  // _graceful_claude_exit).
  async function stopSessionConfirmed(sessionId, owner, fromChat) {
    if (!confirm(t("sessionops.stop_session_if_claude_running"))) return;
    try {
      await withUnlockRetry(() => api(sessionPath(sessionId, "/stop", owner), { method: "POST" }));
    } catch (e) {
      alert(t("sessionops.could_not_stop_err", { err: e.message }));
      return;
    }
    // Close only the chat it was stopped from, not one the user went to meanwhile.
    if (fromChat && chatNow.id === sessionId && chatNow.owner === (owner || null)) chatNow.close();
    else await refreshSessions();
  }

  // Which ended sessions get ↻: the presets create_session accepts `resume`
  // for (aiza-backend: CWD_PRESETS, the Email preset, and a drives-capable
  // ssh machine's Claude once a folder was chosen), and only once the
  // conversation id is known. The backend re-checks all of it (the log must
  // still exist in that folder), so this only decides whether to offer it.
  function canResumeEnded(s) {
    // Codex run in a shell: its own conversation (codex_resume_id).
    const k = sessionKind(s);
    if (k.ai === "codex" && k.localShell) return !!s.codex_resume_id;
    if (!s.claude_session_id) return false;
    if (FORM_PRESETS[s.preset] && FORM_PRESETS[s.preset].resume && FORM_PRESETS[s.preset].picker !== "ssh") return true;
    // A shell (incl. root) where `claude` was run by hand: the backend
    // records the folder that conversation ran in as claude_cwd (null when
    // it never ran), and on ↻ opens the same shell there and types
    // `claude --resume <id>` (the deployment notes).
    if (k.localShell) return !!s.claude_cwd;
    return s.preset.startsWith("claude-tui-") && !!s.cwd;
  }

  let resumingSession = false;
  async function resumeEndedSession(s, confirmed) {
    if (resumingSession) return;
    if (!confirmed && !confirm(t("sessionops.resume_label", { label: s.label }))) return;
    resumingSession = true;
    try {
      const body = resumeBody(s);
      // Same passkey handling as 開始 (Email and host/root presets).
      const meta = await withUnlockRetry(() => api("/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })).catch(async (e) => {
        // Already running elsewhere (e.g. resumed by the server while this
        // page still showed the stopped one): go there instead.
        if (e.runningSession) {
          const list = await refreshSessions().catch(() => lastSessions);
          const other = (list || []).find((x) => x.id === e.runningSession);
          if (other) {
            showUndoToast(t("sessionops.conversation_already_running_in_another"), false);
            chatNow.open(other);
            return null;
          }
        }
        alert(t("sessionops.could_not_resume_err", { err: e.message }));
        return null;
      });
      if (!meta) return;
      await refreshSessions();
      chatNow.open(meta);
    } finally {
      resumingSession = false;
    }
  }

  function resumeBody(s) {
    const body = {
      preset: s.preset,
      label: s.label,
      cwd: s.claude_cwd || s.cwd || "",
      resume: s.launch === "codex" && s.codex_resume_id ? s.codex_resume_id : s.claude_session_id,
      // The backend resumes this same session (same id, its history goes
      // on); only if that cannot be done safely does it copy the history
      // into a new one and delete this (the deployment notes).
      replace_session: s.id,
      cols: computeScreenCols(),
      rows: computeScreenRows(),
    };
    // The same permission option as it started with (2026-11-15, the user:
    // 再開時にももとと同じオプションになるように): Claude/Codex in a TUI preset,
    // or run in a shell by its launcher (claude-root, codex-root, ...).
    const kind = sessionKind(s);
    if (kind.tui || kind.launch) {
      body.skip_permissions = s.skip_permissions !== false;
    }
    return body;
  }

  // Force-stopping a still-*running* session -- aborting a hung shell, or a
  // claude turn the user doesn't want to wait out -- is not something the
  // automatic dead-pane/remain-on-exit detection (aiza-backend) can ever
  // replace: there is nothing to detect until a session already stops on
  // its own. It used to be a dedicated, always-visible 停止 button;
  // replaced 2026-08-16 (at the user's request, now that natural exits are
  // caught automatically) with a long-press on the status dot + a
  // confirm() dialog, so ending a still-running session takes a deliberate
  // gesture rather than an ordinary tap that sits among harmless buttons.
