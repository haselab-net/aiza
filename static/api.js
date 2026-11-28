// Asking the backend (aiza): api(), and the passkey unlock -- asking for it,
// the unlocked badge, the notice in a locked session.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after voice.js and before app.js, in this order:
// form, settings, keys, api, links, search, sessionops, compose. What runs
// here at load uses only this file and the earlier ones. Moved out of
// app.js 2026-11-24 as it was; the indentation is app.js's.
"use strict";

  // This file's own elements of the page (only it uses them; from page.js, 2026-11-24).
  const unlockNoticeEl = document.getElementById("unlock-notice");
  const unlockNoticeBtnEl = document.getElementById("unlock-notice-btn");

  // On failure, surfaces the backend's own {"error": "..."} message (e.g.
  // create_session's "failed to start tmux session: ...") rather than just
  // the bare HTTP status -- callers that alert(e.message) would otherwise
  // show a bare "400" with no indication of what actually went wrong.
  //
  // aiza-backend's require_unlock_if_outside_
  // sandbox() gate answers every denial as 403 {"error": "...",
  // "unlock_required": true, "tier": "host"|"root"} (see aiza-backend's
  // UnlockRequired / Handler._unlock_required). unlock_required is copied
  // onto the thrown Error as e.unlockRequired so withUnlockRetry() below
  // can tell "this needs a passkey" apart from any other 403 (e.g.
  // sharing's "sharing does not include this", which must NOT pop a
  // WebAuthn prompt) using something more specific than the bare HTTP
  // status. "tier" is copied alongside it as
  // e.unlockTier, so ensureUnlocked() knows which tier to ask
  // aiza-unlockd's begin-assertion for instead of guessing.
  function api(path, opts) {
    return fetch(`${window.aizaBase}/agents/api${path}`, opts).then(async (r) => {
      if (!r.ok) {
        const body = await r.json().catch(() => null);
        const err = new Error(body && body.error ? body.error : `${r.status}`);
        if (r.status === 401 && body && body.error === "not logged in") {
          err.loginLost = true;
          loginLost();
        }
        if (body && body.unlock_required) {
          err.unlockRequired = true;
          err.unlockTier = body.tier;
        }
        if (body && body.running_session) err.runningSession = body.running_session;
        // POST /messages: stopped (nothing written or sent; the page resumes
        // it and sends again), or just resumed but not up to take it in time.
        if (body && body.stopped) err.stopped = true;
        if (body && body.not_ready) err.notReadyWait = body.wait;
        throw err;
      }
      return r.json();
    });
  }

  // ---- Passkey unlock (the design notes, the design notes, the design notes) ------------
  //
  // host/root actions (a host-shell/root-shell session, sending into one,
  // Claude-auth login/logout at scope host/root, "全員" Kill Chrome) are
  // gated behind a 15-minute passkey-authenticated window that aiza-unlockd
  // (root) owns. aiza-backend only relays the WebAuthn ceremony over
  // /unlock/* and never itself decides whether an assertion is valid (see
  // aiza-backend's _unlockd_call/require_unlock_if_outside_sandbox) -- so
  // neither does this file: every response from those routes is examined
  // only for its own "ok" field, never trusted beyond that.

  // WebAuthn's binary fields (challenge, credential ids, signatures, ...)
  // travel over JSON as base64url text (fido2's own `dict(options)`
  // encoding), but navigator.
  // credentials.{create,get}() need real ArrayBuffers, and their result
  // needs to go back the other way. Both conversions are notoriously easy
  // to get subtly wrong (padding, +/ vs -_, sign confusion between which
  // direction is "url" and which is "standard") -- silent WebAuthn failures
  // trace back to exactly this more often than to anything cryptographic.
  function b64urlToBuf(s) {
    const pad = "=".repeat((4 - (s.length % 4)) % 4);
    const base64 = (s + pad).replace(/-/g, "+").replace(/_/g, "/");
    const raw = atob(base64);
    const buf = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
    return buf.buffer;
  }

  function bufToB64url(buf) {
    const bytes = new Uint8Array(buf);
    let str = "";
    for (const b of bytes) str += String.fromCharCode(b);
    return btoa(str).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  }

  // begin-assertion's wire "options" -> PublicKeyCredentialRequestOptions.
  // Only `challenge` and each allowCredentials[].id are binary; everything
  // else (rpId, userVerification, timeout, ...) is already the right JS
  // shape (fido2's dict() uses the same camelCase field names the Web
  // Authentication API does) and is spread through unchanged.
  //
  // NOTE the unwrap below: fido2 2.2.1's authenticate_begin() returns a
  // *CredentialRequestOptions*, so dict() of it is the outer
  // {"publicKey": {...}} wrapper, NOT the inner
  // PublicKeyCredentialRequestOptions. Unwrapping here (rather than at the
  // call site) keeps `credentials.get({publicKey: requestOptionsFromWire(
  // ...)})` from double-wrapping it. Getting this wrong stays silent until
  // b64urlToBuf(undefined) reaches atob and throws "Cannot read properties
  // of undefined (reading 'length')" -- which is what the registration side
  // of this same pair actually hit on the first real attempt (2026-08-30).
  // The `|| wire` fallback keeps this working if some future fido2 hands
  // back the inner object instead.
  function requestOptionsFromWire(wire) {
    const o = wire.publicKey || wire;
    return {
      ...o,
      challenge: b64urlToBuf(o.challenge),
      allowCredentials: (o.allowCredentials || []).map((c) => ({ ...c, id: b64urlToBuf(c.id) })),
    };
  }

  // The reverse direction: a PublicKeyCredential (assertion) -> the JSON
  // shape aiza-unlockd's fido2 2.2.1 AuthenticationResponse.from_dict()
  // expects, which is WebAuthn L3's own PublicKeyCredential.toJSON() shape
  // (aiza-unlockd's finish-assertion parsing was built
  // against exactly that shape). Preferring the browser's own .toJSON() when it
  // exists means this never has to guess at a field this browser adds later
  // (extension outputs, authenticatorAttachment); the manual fallback below
  // is only for a browser old enough not to have it yet (Safari added it
  // late).
  function credentialToJSON(cred) {
    if (typeof cred.toJSON === "function") return cred.toJSON();
    const r = cred.response;
    return {
      id: cred.id,
      rawId: bufToB64url(cred.rawId),
      type: cred.type,
      authenticatorAttachment: cred.authenticatorAttachment || undefined,
      response: {
        clientDataJSON: bufToB64url(r.clientDataJSON),
        authenticatorData: bufToB64url(r.authenticatorData),
        signature: bufToB64url(r.signature),
        userHandle: r.userHandle ? bufToB64url(r.userHandle) : undefined,
      },
      clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {},
    };
  }

  // Runs the WebAuthn assertion ceremony end to end: ask aiza-backend (which
  // asks aiza-unlockd) for a challenge, ask the platform authenticator for a
  // signature, hand that back for verification. Throws a user-showable
  // Error on any failure -- an unsupported browser, no registered
  // credential, a cancelled/failed biometric prompt, or a rejected
  // assertion (bad origin/RP ID/UV/signCount, all checked server-side only
  // -- see aiza-unlockd's verb_finish_assertion).
  //
  // `tier` ("for root, root-tier credentials
  // only; for host, all of them") is passed straight through to
  // begin-assertion, unexamined -- this file does not decide which
  // credentials are eligible for which tier, aiza-unlockd does, both when
  // building allowCredentials (so the right key gets prompted for) and
  // again, authoritatively, when verifying the assertion (see that
  // program's own module docstring for why the second check is the one
  // that actually matters). Defaults to "root" when no caller supplies one
  // (e.g. a future direct call to this function): asking for the stronger
  // tier when unsure is the fail-closed choice, matching aiza-backend's own
  // _tier_for_location() default for an unrecognized location.
  // navigator.credentials.get()/create() only ever allow ONE outstanding
  // call per browsing context -- a second call while the first is still
  // pending throws "OperationError: A request is already pending" instead
  // of anything user-showable. Reported live 2026-09-17: the unlock
  // banner's own click handler already disables its button while in
  // flight, but nothing stopped a *different* concurrent caller (e.g.
  // withUnlockRetry() reacting to some other action's 403 at the same
  // moment) from starting a second ceremony. _unlockInFlight tracks the
  // one actually running so a second caller piggybacks on it instead of
  // racing it -- unless that one is host-tier and this caller needs root
  // (host-tier succeeding would not actually satisfy a root request), in
  // which case this waits for it to settle first, then runs its own.
  let _unlockInFlight = null; // {tier, promise} | null

  async function ensureUnlocked(tier) {
    tier = tier === "host" ? "host" : "root";
    if (_unlockInFlight) {
      if (_unlockInFlight.tier === "root" || _unlockInFlight.tier === tier) {
        return _unlockInFlight.promise;
      }
      try {
        await _unlockInFlight.promise;
      } catch (e) {
        // Its own caller already surfaces this failure; this caller still
        // needs root, so fall through and try its own ceremony below.
      }
    }
    const promise = (async () => {
      if (!window.PublicKeyCredential) {
        throw new Error(t("api.browser_does_not_support_passkeys"));
      }
      const begin = await api("/unlock/begin-assertion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tier }),
      });
      if (!begin.ok) throw new Error(begin.error || t("common.could_not_start_authentication"));
      let cred;
      try {
        cred = await navigator.credentials.get({ publicKey: requestOptionsFromWire(begin.options) });
      } catch (e) {
        throw new Error(t("api.biometric_authentication_cancelled_or", { err: e.message }));
      }
      const finish = await api("/unlock/finish-assertion", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: credentialToJSON(cred) }),
      });
      if (!finish.ok) throw new Error(finish.error || t("common.authentication_failed"));
      updateUnlockBadge({ unlocked: true, expires_at: finish.expires_at, tier: finish.tier });
      return finish.expires_at;
    })();
    _unlockInFlight = { tier, promise };
    try {
      return await promise;
    } finally {
      if (_unlockInFlight && _unlockInFlight.promise === promise) _unlockInFlight = null;
    }
  }

  // Wraps any api() call that might hit aiza-backend's require_unlock_if_
  // outside_sandbox() gate: on a 403 carrying unlock_required, runs the
  // passkey ceremony -- for the tier the 403 itself named (e.unlockTier,
  // see api()'s own comment) -- and retries the
  // *same* action exactly once. Any other failure (including a second
  // unlock_required -- shouldn't happen right after a fresh unlock, but not
  // specially looped on if it does) is rethrown to the caller exactly as if
  // this wrapper weren't there.
  async function withUnlockRetry(fn) {
    try {
      return await fn();
    } catch (e) {
      if (!e.unlockRequired) throw e;
      await ensureUnlocked(e.unlockTier);
      return await fn();
    }
  }

  // ---- persistent "unlocked" indicator ------------------------------------
  //
  // Built entirely here rather than in index.html: this task's working copy
  // is app.js alone, so the badge/lock control is a plain DOM node created
  // and appended at load time instead of a pre-existing element looked up
  // by id, the same way e.g. addSshAuthRow()'s rows are built. Appended
  // into #top-header specifically because that element is already shown on
  // the session list and hidden in the full-screen chat view as a matched
  // pair (see the topHeaderEl.style.display toggles in openSession/
  // closeSession) -- this rides along with that existing visibility
  // instead of needing its own.
  const unlockBadgeEl = document.createElement("button");
  unlockBadgeEl.type = "button";
  unlockBadgeEl.hidden = true;
  // font-size is up from the 0.75rem this used while it rendered a text
  // countdown: the label is now a single glyph, and it is also the tap
  // target for locking, so it needs to stay comfortably tappable on a
  // phone rather than shrinking to the size of the text it replaced.
  unlockBadgeEl.className = "unlock-badge";   // style.css
  // align-self: #top-header stretches its children to the tabs' height
  // (align-items: stretch, 2026-11-25), which made this badge as tall as the
  // header (2026-11-27, the user: 鍵のアイコンが縦に大き過ぎる).
  topHeaderEl.appendChild(unlockBadgeEl);

  let unlockExpiresAt = null; // epoch seconds while unlocked, else null
  let unlockTier = null; // "host"/"root" while unlocked, else null
  let pendingUnlockTier = null; // tier #unlock-notice-btn should ask for, set by updateUnlockNotice()
  // False until the first /unlock/status answer (2026-11-21, the user: リロードの
  // たびに鍵認証が出ます). A reload opens the session from the URL before that
  // answer arrives, and an unknown window must not count as a closed one.
  let unlockStatusKnown = false;

  // 2026-09-11, at the user's request (see #unlock-notice's own comment in
  // index.html for the full story): reading a session's history/live events
  // was never gated on the unlock window (aiza-backend's
  // require_unlock_if_outside_sandbox is only in the write-side action
  // list), so a host/root session whose window closed just went quiet with
  // no explanation -- the small header badge disappearing was the only
  // sign, easy to miss, and nothing ever prompted a re-unlock. This runs
  // from the same places updateUnlockBadge() already runs (the 5s poll, and
  // immediately after a fresh unlock) so the banner and the badge are
  // always in sync with each other and appear/disappear together.
  function updateUnlockNotice() {
    const location = chatNow.meta && chatNow.meta.tmux_location;
    const tier = location === "root" ? "root" : location === "host" ? "host" : null;
    // No tier needed (container/ssh:/no session open), or the session has
    // already ended -- nothing further can arrive for it either way, so a
    // closed window has nothing to catch up on.
    // A read-only share needs no window (the deployment notes).
    if (!tier || !chatNow.meta.alive || currentShareMode === "read" || !unlockStatusKnown) {
      unlockNoticeEl.hidden = true;
      return;
    }
    const satisfied = tier === "root" ? unlockTier === "root" : !!unlockTier;
    pendingUnlockTier = tier;
    unlockNoticeEl.hidden = satisfied;
    if (satisfied) return;
    autoAskPasskey(`notice:${chatNow.id}:${tier}`, () => ensureUnlocked(tier),
      unlockNoticeBtnEl, () => !unlockNoticeEl.hidden);
  }

  // Ask for the passkey without waiting for a button (2026-11-17, the user:
  // "必要なら操作無しでパスキー要求を出す"), wherever a screen needs the window
  // and would otherwise only offer a button: the 🔒 banner in the chat, the
  // locked rows' bar above the list, a locked history. Once per `key` until
  // the window opens again (updateUnlockBadge clears them), and only while
  // this page is the one in front -- a hidden tab asking would pop a prompt
  // over whatever the user is doing; not in front yet, the next call (the 5s
  // poll, the next list refresh) tries again.
  // A browser may refuse a request no tap started, at once and without a
  // prompt (Safari can; seen on Edge for Windows too): then nothing is shown
  // as an error, `btn` says a tap anywhere will do, and the next tap anywhere
  // on the page asks -- once, and a tap, not a key, so typing is never cut
  // off by a prompt. A prompt the user saw and cancelled takes longer than
  // that and is left alone.
  const autoAskedKeys = new Set();
  let autoAskTap = null; // {run, btn, stillNeeded} waiting for the next tap

  function autoAskPasskey(key, run, btn, stillNeeded) {
    if (autoAskedKeys.has(key)) return;
    if (document.visibilityState !== "visible" || !document.hasFocus()) return;
    autoAskedKeys.add(key);
    const started = Date.now();
    run().catch((e) => {
      if (Date.now() - started >= 3000 || !stillNeeded()) return;
      if (btn) {
        if (!btn.dataset.label) btn.dataset.label = btn.textContent;
        btn.textContent = t("api.unlock_tap_anywhere_ask");
        btn.title = t("api.browser_did_not_show_passkey", { err: (e && e.message) || "" });
      }
      autoAskTap = { run, btn, stillNeeded };
    });
  }

  function clearAutoAskTap() {
    const w = autoAskTap;
    autoAskTap = null;
    if (w && w.btn && w.btn.dataset.label) {
      w.btn.textContent = w.btn.dataset.label;
      w.btn.title = "";
      delete w.btn.dataset.label;
    }
    return w;
  }

  document.addEventListener("pointerup", (ev) => {
    if (!autoAskTap) return;
    const w = clearAutoAskTap();
    // A tap on the button itself runs the button's own handler instead.
    if ((w.btn && w.btn.contains(ev.target)) || !w.stillNeeded()) return;
    w.run().catch(() => {});
  }, true);

  async function runUnlockNotice() {
    if (unlockNoticeBtnEl.disabled) return;
    unlockNoticeBtnEl.disabled = true;
    try {
      await ensureUnlocked(pendingUnlockTier || "root");
      // ensureUnlocked() already calls updateUnlockBadge() -> updateUnlockNotice()
      // on success, so the banner hides itself; nothing further to do here.
    } catch (e) {
      ui.toast(e.message, { error: true });
    } finally {
      unlockNoticeBtnEl.disabled = false;
    }
  }

  unlockNoticeBtnEl.addEventListener("click", () => runUnlockNotice());

  function renderUnlockBadge() {
    if (unlockExpiresAt == null) {
      unlockBadgeEl.hidden = true;
      return;
    }
    unlockBadgeEl.hidden = false;
    // Icon only (2026-08-31, at the user's request). The remaining-time
    // countdown this used to render stopped carrying information once
    // _sweeper() began auto-extending every open window:
    // a window that is open at all is simply pushed
    // back to the full UNLOCK_TTL on every 5s sweep, so the number sat at
    // ~15:00 and only ever moved in the last moments before the 2-hour
    // absolute cap. What still matters -- and all this badge now says --
    // is the binary "a window is open, tap to close it".
    //
    // The tier is now the icon itself (2026-08-31, follow-up to the
    // icon-only change above), not just the tooltip: a host-tier window
    // does NOT authorise root, and that distinction is
    // exactly the kind of thing a glance at the header should convey
    // without requiring a tap or a hover a touchscreen doesn't have.
    // 🔓 (open padlock) for root -- the strongest tier, authorises host
    // too. 🔑 (key) for host-only -- open, but not the same as 🔓.
    const label = unlockTier === "root" ? "root/host" : "host";
    unlockBadgeEl.title = t("api.label_unlocked_tap_lock_now", { label });
    unlockBadgeEl.textContent = unlockTier === "root" ? "🔓" : "🔑";
  }

  // status is either GET /unlock/status's own reply ({"ok", "unlocked",
  // "expires_at", "tier"}) or null/anything falsy -- both "ok:false"
  // (locked, or aiza-unlockd unreachable) and "no answer at all" render the
  // same way: no badge. Called both by the poll below and by
  // ensureUnlocked() right after a fresh unlock, so the badge appears
  // immediately rather than waiting for the next 5s tick.
  function updateUnlockBadge(status) {
    unlockStatusKnown = true;
    const wasOpen = !!unlockTier;
    unlockExpiresAt = status && status.unlocked ? status.expires_at : null;
    unlockTier = status && status.unlocked ? status.tier : null;
    // Closed again: each screen may ask once more. Not on opening (it used
    // to be): a screen still locked after a passkey that worked -- another
    // tier, or the server not yet agreeing -- then asked again at once, and
    // again after that, without end (2026-11-24, seen in the page tests).
    if (wasOpen && !unlockTier) {
      autoAskedKeys.clear();
      clearAutoAskTap();
    }
    renderUnlockBadge();
    updateUnlockNotice();
  }

  // GET, and always the read-only `status` verb all the way down to
  // aiza-unlockd -- never `touch` -- so that this badge's own polling can
  // never be the thing keeping a window open (a persistent *display* of the
  // remaining time is wanted, not an extension every time someone looks at it).
  async function pollUnlockStatus() {
    const r = await api("/unlock/status").catch(() => null);
    updateUnlockBadge(r && r.ok ? r : null);
  }

  unlockBadgeEl.addEventListener("click", async () => {
    if (!(await ui.confirm(t("api.lock_root_host_now")))) return;
    await api("/unlock/lock", { method: "POST" }).catch(() => {});
    await pollUnlockStatus();
  });

  function initUnlockUI() {
    pollUnlockStatus();
    // 5s: frequent enough that the badge disappears promptly when the
    // window closes from elsewhere (another tab, `aiza-passkey lock`, the
    // absolute cap), cheap enough to run forever while locked -- `status` is one local
    // Unix-socket round trip inside aiza-backend, no WebAuthn or network of
    // its own involved.
    setInterval(pollUnlockStatus, 5000);
    // No second, faster timer any more: with the countdown gone (see
    // renderUnlockBadge) there is nothing to tick between polls -- the
    // badge only ever changes when the window itself opens or closes, and
    // this poll is what learns that.
  }

  // /sessions/<id><suffix> for one's own session, or
  // /shared/<owner>/sessions/<id><suffix> when viewing someone else's --
  // every per-session call goes through one of these two so opening a
  // shared session doesn't need its own copy of each action.
  function sessionPath(sessionId, suffix, owner) {
    return owner
      ? `/shared/${encodeURIComponent(owner)}/sessions/${sessionId}${suffix}`
      : `/sessions/${sessionId}${suffix}`;
  }

  function sessionApiUrl(sessionId, suffix, owner) {
    return `${window.aizaBase}/agents/api${sessionPath(sessionId, suffix, owner)}`;
  }

  function fmtTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  // Resumable conversations can be weeks old, so unlike fmtTime the date
  // matters -- it's often the only thing distinguishing two of them.
  function fmtDateTime(ts) {
    const d = new Date(ts * 1000);
    return d.toLocaleString([], { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  }

  // Where a claude session was started, shown in the list because two
  // conversations with the same preset and label are otherwise
  // indistinguishable. meta.cwd is an absolute path; the part under
  // ~/sandhome is the part that carries information -- or, for a
  // drives-capable ssh machine's Claude preset, a posix
  // MSYS2 path ("/d/Projects"), shown Windows-style via mountPathLabel().
  function cwdSuffix(s) {
    if (!s.cwd) return "";
    if (/^\/[a-z](\/.*)?$/.test(s.cwd)) return ` &middot; ${escapeHtml(mountPathLabel(s.cwd))}`;
    const rel = s.cwd.replace(/^.*\/sandhome(\/|$)/, "");
    return rel ? ` &middot; ${escapeHtml(rel)}` : "";
  }
  // The same, leading the meta line now that the preset's name is gone.
  function cwdPrefix(s) {
    const x = cwdSuffix(s);
    return x ? x.replace(/^ &middot; /, "") + " &middot; " : "";
  }
