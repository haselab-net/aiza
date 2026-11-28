// The settings page (aiza): Claude's and Codex's logins in each place, and
// stopping the headful Chrome.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after voice.js and before app.js, in this order:
// form, settings, keys, api, links, search, sessionops, compose. What runs
// here at load uses only this file and the earlier ones. Moved out of
// app.js 2026-11-24 as it was; the indentation is app.js's.
"use strict";

  // ---- Claude Code auth inside the container -----------------------------
  //
  // `claude auth status`/`logout` are one-shot commands and answer inline.
  // Login is not: it prints a URL and waits for the code, so it opens as an
  // ordinary chat session (POST /claude-auth/login -> the "claude-login"
  // tmux preset) where the soft keyboard and composer already work.

  // The sign-in rows of 設定 (2026-11-23, moved to Preact: the deployment notes).
  // One table of the tools and the places; the rows are drawn from authState
  // alone (each place's answer, whether a tool's buttons are busy, root, the
  // ssh machines), so no row can show one tool's answer with another's
  // buttons, or stay "確認中…". A place's status is one of GET /claude-auth's
  // or /codex-auth's per-scope values: null (no access), {"error"}, or
  // {loggedIn, ...}; "checking" while asked. Login opens a chat session
  // (POST …/login -> the "claude-login"/"codex-login" preset) where the soft
  // keyboard and composer already work; status and logout answer inline.
  const AUTH_PLACES = [["container", "devbox"], ["host", "common.host"], ["root", "common.root"]];
  const AUTH_TOOLS = {
    claude: { api: "/claude-auth", cls: "auth", name: "Claude Code",
      text: (st) => {
        const detail = [st.authMethod, st.orgName, st.subscriptionType].filter(Boolean).join(" / ");
        return `${st.email || t("common.logged_in")}${detail ? ` (${detail})` : ""}`;
      } },
    codex: { api: "/codex-auth", cls: "codex-auth", name: "Codex", text: (st) => st.text || t("common.logged_in"),
      outText: (st) => st.text || t("common.not_logged_in") },
  };
  // Where each row acts, and what to call it when asking to confirm a logout
  // -- "ログアウトしますか" is not a safe question without saying whose.
  const AUTH_SCOPE_LABELS = {
    container: t("settings.devbox_container"),
    host: t("settings.host_outside_sandbox"),
    root: t("settings.root_on_host"),
  };
  let authState = { claude: {}, codex: {}, busy: { claude: false, codex: false }, root: false, machines: [] };
  const authRefreshBtn = document.getElementById("auth-refresh");
  const authHost = document.getElementById("auth-rows");
  const authHtml = window.htm && window.preact ? window.htm.bind(window.preact.h) : null;
  function setAuth(patch) {
    authState = { ...authState, ...patch };
    authRefreshBtn.disabled = authState.busy.claude;
    if (authHost && authHtml) window.preact.render(authHtml`<${AuthRows} s=${authState} />`, authHost);
  }
  function authStatusView(tool, st) {
    if (st === "checking" || st === undefined) return ["", t("common.checking")];
    if (st == null) return ["", t("settings.no_access")];
    if (st.error) return ["err", st.error];
    if (st.loggedIn) return ["in", AUTH_TOOLS[tool].text(st)];
    return ["out", AUTH_TOOLS[tool].outText ? AUTH_TOOLS[tool].outText(st) : t("common.not_logged_in")];
  }
  function AuthRow({ tool, scope, label, s }) {
    const all = s[tool].__all;   // "checking", or the request's own failure, for every row
    const [cls, text] = authStatusView(tool, all !== undefined ? all : s[tool][scope]);
    const c = AUTH_TOOLS[tool].cls, busy = s.busy[tool];
    return authHtml`<div class="auth-row">
      <div class="auth-line">
        <span class="auth-label">${label}</span>
        <span class=${"auth-status-text" + (cls ? " " + cls : "")}>${text}</span>
      </div>
      <div class="auth-actions">
        <button class=${c + "-login"} data-scope=${scope} disabled=${busy} onClick=${() => authLogin(tool, scope)}>${t("common.log_in")}</button>
        <button class=${c + "-logout"} data-scope=${scope} disabled=${busy} onClick=${() => authLogout(tool, scope)}>${t("common.log_out")}</button>
      </div>
    </div>`;
  }
  const authHead = (text) => authHtml`<h2 class="auth-section">${text}</h2>`;
  function AuthRows({ s }) {
    const places = AUTH_PLACES.filter(([scope]) => scope !== "root" || s.root);
    const rows = (tool) => places.map(([scope, label]) => authHtml`<${AuthRow} key=${scope} tool=${tool} scope=${scope} label=${t(label)} s=${s} />`);
    return authHtml`
      ${authHead("Claude")}${rows("claude")}
      ${authHead("Codex")}${rows("codex")}
      ${s.machines.length ? authHtml`${authHead("Other hosts")}${s.machines.map((m) =>
        authHtml`<${AuthRow} key=${m} tool="claude" scope=${`ssh:${m}`} label=${m} s=${s} />`)}` : null}`;
  }
  async function refreshToolStatus(tool) {
    setAuth({ [tool]: { __all: "checking" } });
    const st = await api(AUTH_TOOLS[tool].api).catch((e) => ({ error: e.message }));
    // The whole answer, so a row added later (an ssh machine) has its own.
    // The request itself failed: one shared failure for every row; a
    // per-scope {"error"} only affects that row.
    setAuth({ [tool]: st.error ? { __all: st } : st });
  }
  // Every moment the Claude rows want a refresh (設定 opening, ⟳, a login or
  // logout ending) the Codex rows want one too.
  async function refreshAuthStatus() {
    await Promise.all([refreshToolStatus("claude"), refreshToolStatus("codex")]);
  }
  // These commands can take a few seconds; a second tap would queue another
  // `sandbox exec` (or root pane) behind the first, so a tool's buttons are
  // off while one of its commands runs.
  async function withAuthBusy(tool, fn) {
    setAuth({ busy: { ...authState.busy, [tool]: true } });
    try {
      await fn();
    } finally {
      setAuth({ busy: { ...authState.busy, [tool]: false } });
    }
  }
  authRefreshBtn.addEventListener("click", () => withAuthBusy("claude", refreshAuthStatus));
  function authLogout(tool, scope) {
    return withAuthBusy(tool, async () => {
      const where = AUTH_SCOPE_LABELS[scope] || scope.replace(/^ssh:/, "");
      if (!(await ui.confirm(t(tool === "claude" ? "settings.log_claude_code_out_where" : "settings.log_codex_out_where", { where }), { danger: true }))) return;
      const r = await withUnlockRetry(() => api(`${AUTH_TOOLS[tool].api}/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope }),
      })).catch((e) => ({ error: e.message }));
      if (r.error) ui.toast(t("settings.logout_failed_err", { err: r.error }), { error: true });
      await refreshToolStatus(tool);
    });
  }
  function authLogin(tool, scope) {
    return withAuthBusy(tool, async () => {
      const meta = await withUnlockRetry(() => api(`${AUTH_TOOLS[tool].api}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope }),
      })).catch((e) => {
        ui.toast(t("common.could_not_start_login_err", { err: e.message }), { error: true });
        return null;
      });
      if (!meta) return;
      await refreshSessions();
      openSessionFromAuth(meta);
    });
  }
  // One more Claude row per reachable ssh machine (applyCapabilities: which
  // machines exist is a live backend answer).
  function addSshAuthRow(machine) {
    if (!authState.machines.includes(machine)) setAuth({ machines: [...authState.machines, machine] });
  }
  setAuth({});

  // (Kill Chrome left 設定 on 2026-11-26, the user: 設定ーKill Chromeはなくして.
  // POST /chrome/kill stays in the backend.)
