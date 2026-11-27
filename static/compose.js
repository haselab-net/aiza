// Writing to a session (aiza): sending, the text kept for its own session
// (unsentFor), the box, the @ reference, attachments.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after voice.js and before app.js, in this order:
// form, settings, keys, api, links, search, sessionops, compose. What runs
// here at load uses only this file and the earlier ones. Moved out of
// app.js 2026-11-24 as it was; the indentation is app.js's.
"use strict";

  // This file's own elements of the page (only it uses them; from page.js, 2026-11-24).
  const runBtn = document.getElementById("run-btn");

  // submit=false is the 送信 button: the characters, no Enter. The box is
  // still cleared -- the text has left for the pane either way, and what it
  // looks like there is the screen panel's job, not the composer's.
  // submit=true with an empty box is a bare Enter, which is how 実行 answers
  // a selection menu or a "press Enter to continue" without the soft keyboard.
  // What the user made for a session but could not land there because the
  // answer came after they had moved to another session: a failed send's text, an
  // attached file's path. Kept for that session in this page and put back
  // into the box when it is opened again -- never into another session's
  // box, from where the next send would go to the wrong session.
  const unsent = new Map();
  const unsentKey = (sid, owner) => `${owner || ""}/${sid}`;
  function unsentFor(sid, owner, text, before) {
    const k = unsentKey(sid, owner);
    const had = unsent.get(k);
    unsent.set(k, !had ? text : before ? `${text}\n${had}` : `${had}${/\s$/.test(had) ? "" : " "}${text}`);
  }
  function restoreUnsent(meta) {
    const k = unsentKey(meta.id, meta.owner);
    const text = unsent.get(k);
    if (text === undefined) return;
    unsent.delete(k);
    textEl.value = textEl.value ? `${text}\n${textEl.value}` : text;
    autoResizeTextarea();
  }

  async function send(submit) {
    const text = textEl.value;
    if (!chatNow.id) return;
    if (!text.trim() && !submit) return;
    const sid = chatNow.id, owner = chatNow.owner;
    const label = (chatNow.meta && chatNow.meta.label) || sid;
    const here = () => chatNow.id === sid && chatNow.owner === owner;   // the box is still that session's
    textEl.value = "";
    autoResizeTextarea();
    // Immediate feedback: a headless turn can take several seconds and
    // produces no output at all until it's fully done, which otherwise
    // looks exactly like nothing is happening.
    if (HEADLESS_PRESETS.includes(chatNow.preset)) {
      if (!text.trim()) return;
      addThinkingIndicator();
    }
    try {
      // withUnlockRetry: a host/root session's first message after the
      // 15-minute window has closed pops the passkey prompt right here,
      // then re-sends this same text automatically once it succeeds
      // (the design notes).
      await withUnlockRetry(() => api(sessionPath(sid, "/messages", owner), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // typed: from this page's own box (the send gate counts only these).
        body: JSON.stringify({ text, submit: !!submit, typed: true }),
      }));
    } catch (e) {
      // The box was already cleared above (so a *successful* send doesn't
      // flash the old text back before the reply arrives) -- without this,
      // a POST failure (a network blip on the phone, aiza-backend-proxy's
      // socket-activation cold start, a transient 502/504) silently
      // dropped the message with zero indication: the box looked like it
      // had sent, nothing ever reached claude, and there was nothing to
      // retry because the text was already gone. Reported 2026-08-17 as
      // "たまにclaudeにメッセージが届かない" (occasionally, since it only
      // shows up on that one unlucky request). Restoring the text and
      // re-growing the box puts the user back exactly where they were
      // before pressing send/実行, instead of just losing the message.
      //
      // Prepended rather than overwriting (2026-08-29, at the user's
      // request): the failure only surfaces after the request round-trips,
      // by which point the user may have already started typing something
      // new into the now-empty box -- a plain overwrite would silently
      // discard *that* instead.
      if (!here()) {
        // Moved to another session meanwhile: the text waits for its own.
        unsentFor(sid, owner, text, true);
        alert(t("compose.sending_label_failed_err", { label, err: e.message }) + "\n"
          + t("compose.open_session_unsent_text_back"));
        return;
      }
      textEl.value = textEl.value ? `${text}\n${textEl.value}` : text;
      autoResizeTextarea();
      alert(t("compose.sending_failed_err", { err: e.message }) + "\n" + t("common.try_again"));
    }
  }

  // Grows the composer with its content instead of scrolling a long draft
  // inside a fixed-height box (2026-08-16, at the user's request) -- CSS's
  // own max-height still caps it (see #composer textarea), past which this
  // just leaves the browser's normal internal scrollbar to take over.
  // Resetting to "auto" before reading scrollHeight is required, not just
  // stylistic: scrollHeight otherwise reports the *current* (possibly
  // still-large, from before text was deleted) height's content, so a
  // shrinking edit would never shrink the box back down.
  function autoResizeTextarea() {
    textEl.style.height = "auto";
    textEl.style.height = `${textEl.scrollHeight}px`;
  }
  textEl.addEventListener("input", autoResizeTextarea);
  // "@" in the box (plan stage 14): pick a session to point the agent at.
  // What goes in is a reference the agent reads with `aiza-session show`;
  // what it may read is decided by the backend, not here.
  const refPick = document.createElement("div");
  refPick.id = "ref-pick"; refPick.hidden = true;

  document.getElementById("composer").appendChild(refPick);
  function sessionRefToken(s) {
    const ref = s.owner ? `${s.owner}/${s.id}` : s.id;
    return `[AI座参照 s:${ref} 「${s.label || s.id}」 — aiza-session show ${ref} で読める] `;
  }
  function refCandidates(q) {
    const mail = (p) => /^mail-/.test(p || "");
    const hereMail = mail(chatNow.preset);
    q = q.toLowerCase();
    return lastSessions.filter((s) => !s.archived && !(s.id === chatNow.id && (s.owner || null) === (chatNow.owner || null))
      && !(mail(s.preset) && (s.owner || !hereMail))
      && (!q || (s.label || "").toLowerCase().includes(q) || (s.owner || "").toLowerCase().includes(q)))
      .slice(0, 8);
  }
  function refPickUpdate() {
    const caret = textEl.selectionStart;
    const m = /(?:^|\s)@([^\s@]*)$/.exec(textEl.value.slice(0, caret));
    if (!m) { refPick.hidden = true; return; }
    const list = refCandidates(m[1]);
    if (!list.length) { refPick.hidden = true; return; }
    refPick.replaceChildren();
    for (const s of list) {
      const b = document.createElement("button");
      b.type = "button";
      b.textContent = (s.owner ? `${s.owner}: ` : "") + (s.label || s.id);
      b.addEventListener("mousedown", (e) => e.preventDefault());
      b.addEventListener("click", () => {
        const start = caret - m[1].length - 1;
        textEl.value = textEl.value.slice(0, start) + sessionRefToken(s) + textEl.value.slice(caret);
        const at = start + sessionRefToken(s).length;
        textEl.setSelectionRange(at, at);
        refPick.hidden = true;
        textEl.focus();
        autoResizeTextarea();
      });
      refPick.appendChild(b);
    }
    refPick.hidden = false;
  }
  textEl.addEventListener("input", refPickUpdate);
  textEl.addEventListener("blur", () => setTimeout(() => { refPick.hidden = true; }, 150));

  // ---- Image attachments (2026-09-08) -------------------------------------
  //
  // Claude Code (or whatever else is in the pane) has no notion of "a chat
  // attachment" -- only file paths in its prompt. So this uploads the file,
  // then inserts the path POST /attach hands back as literal text into the
  // composer: sending it from there on is just an ordinary message, same as
  // if the user had typed that path themselves.
  //
  // Kept in sync with aiza-backend's MAX_INBOX_BYTES -- this is only a fast
  // client-side rejection so a large pick fails immediately instead of after
  // a slow upload; the backend enforces the real limit regardless.
  const MAX_ATTACH_BYTES = 100 * 1024 * 1024;

  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.slice(reader.result.indexOf(",") + 1));
      reader.onerror = () => reject(reader.error || new Error("failed to read the file"));
      reader.readAsDataURL(file);
    });
  }

  // Any file type since 2026-10-07 (user request) -- the session only ever
  // gets a path, so what the file is doesn't matter to anything here.
  async function attachFile(file) {
    if (!chatNow.id) return;
    if (file.size > MAX_ATTACH_BYTES) {
      alert(t("compose.file_too_large_limit_mb", { mb: Math.floor(MAX_ATTACH_BYTES / (1024 * 1024)) }));
      return;
    }
    let path;
    const sid = chatNow.id, owner = chatNow.owner;
    const here = () => chatNow.id === sid && chatNow.owner === owner;
    try {
      const data_base64 = await fileToBase64(file);
      // withUnlockRetry: same as send() below -- a host/root session's
      // window can have closed since it was opened, and this action is
      // gated exactly like a message into that same session.
      ({ path } = await withUnlockRetry(() => api(sessionPath(sid, "/attach", owner), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name || (file.type.startsWith("image/") ? "image.png" : "upload"), data_base64 }),
      })));
    } catch (e) {
      alert(t("compose.could_not_attach_file_err", { err: e.message }));
      return;
    }
    if (!here()) { unsentFor(sid, owner, `${path} `, false); return; }   // its path waits for its own session
    const sep = textEl.value && !/[\s]$/.test(textEl.value) ? " " : "";
    textEl.value = `${textEl.value}${sep}${path} `;
    autoResizeTextarea();
    textEl.focus();
  }

  attachFileInputEl.addEventListener("change", () => {
    const file = attachFileInputEl.files[0];
    attachFileInputEl.value = ""; // so picking the same file again still fires "change"
    if (file) attachFile(file);
  });

  // Clipboard-paste is the other half of "両方で" (2026-09-08): works in
  // every preset, headless "claude" chat included, since the composer
  // itself (unlike #key-toolbar) is never hidden.
  textEl.addEventListener("paste", (e) => {
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    for (const item of items) {
      // Any pasted file (not just images, 2026-10-07); plain text pastes
      // have kind "string" and fall through to the normal paste.
      if (item.kind === "file") {
        const file = item.getAsFile();
        if (!file) continue;
        e.preventDefault();
        attachFile(file);
        break; // one file per paste, same as the file picker's one-file flow
      }
    }
  });

  sendBtn.addEventListener("click", () => send(false));
  runBtn.addEventListener("click", () => send(true));
  // The phone keyboard's own return key is the everyday case, so it means 実行.
  // The Enter that confirms an IME conversion (kanji) is not a send
  // (2026-10-26, Mac Chrome sent on confirm): isComposing / keyCode 229 cover
  // most browsers; Safari-style ordering fires compositionend just before
  // that keydown, so an Enter within 50ms of compositionend is skipped too.
  let compositionEndAt = 0;
  textEl.addEventListener("compositionend", () => { compositionEndAt = Date.now(); });
  textEl.addEventListener("keydown", (e) => {
    if (e.isComposing || e.keyCode === 229 || Date.now() - compositionEndAt < 50) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send(true);
    }
  });
