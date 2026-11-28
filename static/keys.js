// The chat's key toolbar (aiza): named keys, Ctrl chords, the modifiers.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after voice.js and before app.js, in this order:
// form, settings, keys, api, links, search, sessionops, compose. What runs
// here at load uses only this file and the earlier ones. Moved out of
// app.js 2026-11-24 as it was; the indentation is app.js's.
"use strict";

  // This file's own elements of the page (only it uses them; from page.js, 2026-11-24).
  const modRowEl = document.getElementById("key-modrow");
  const gridEl = document.getElementById("key-grid");

  // The phone's own keyboard already sends any literal character via the
  // text box -- what it can't produce at all is terminal control input:
  // Ctrl/Alt+<anything>, and named keys with no on-screen equivalent (Esc,
  // arrows, Shift-Tab, ...). Ctrl/Alt are *sticky* toggles (tap Ctrl, then
  // tap a key, like Termux/Blink's extra-keys row) rather than requiring a
  // simultaneous multi-touch chord, which doesn't work reliably on a phone.
  // Only relevant for tmux-based presets (a real terminal) -- headless
  // presets' request/response turns have no notion of "keys".
  // Labels shortened 2026-09-08 at the user's request (⇧ PgU PgD 🏡 ⏎ Spc) --
  // this row already competes with GRID_KEYS/the attach button for width on
  // a phone screen, and abbreviations/glyphs read just as well at a glance.
  const NAMED_KEYS = [
    ["↑", "Up"], ["↓", "Down"], ["←", "Left"], ["→", "Right"],
    ["🏡", "Home"], ["End", "End"], ["PgU", "PageUp"], ["PgD", "PageDown"],
    ["Tab", "Tab"], ["⇧Tab", "BTab"], ["Esc", "Escape"], ["⏎", "Enter"],
    ["⌫", "BSpace"], ["Del", "DC"], ["Ins", "IC"], ["Spc", "Space"],
  ];
  const GRID_KEYS = "abcdefghijklmnopqrstuvwxyz0123456789".split("");
  // Claude Code's two-key Ctrl chords, one tap each while Ctrl is armed
  // (2026-11-20, the user: キーボードのctlにxsやbbなどclaude で２キー連続で
  // 入れるよく使うものを足して). From Claude Code's own default bindings.
  // 「b b」 is what a terminal under tmux needs to pass one Ctrl+B through
  // (tmux eats the first); keys sent here go straight to the pane, so one
  // Ctrl+B is what Claude gets either way.
  const CTRL_CHORDS = [
    ["x s", [["x", true], ["s", true]], "keys.send_now_even_while_working"],
    ["x ⏎", [["x", true], ["Enter", false]], "keys.send_later_queue"],
    ["b b", [["b", true]], "keys.move_running_work_background"],
    ["x b", [["x", true], ["b", true]], "keys.move_running_work_background"],
    ["x k", [["x", true], ["k", true]], "keys.stop_background_agents"],
    ["x e", [["x", true], ["e", true]], "keys.write_in_external_editor"],
    ["x a", [["x", true], ["a", true]], "keys.open_or_close_area_above"],
  ];

  let armCtrl = false;
  let armAlt = false;
  let armShift = false;

  const MODIFIERS = [
    ["Ctrl", () => armCtrl, (v) => (armCtrl = v)],
    ["⇧", () => armShift, (v) => (armShift = v)],
    ["Alt", () => armAlt, (v) => (armAlt = v)],
  ];

  function buildKeyToolbar() {
    modRowEl.innerHTML = "";
    gridEl.innerHTML = "";

    // File attach (2026-09-08, at the user's request; first at the far
    // right of this row, at the far left since 2026-11-27, the user:
    // ファイル添付のボタンを一番左に移動). Deliberately only here, not in #composer -- this
    // whole toolbar is already hidden for the headless "claude" preset
    // (buildKeyToolbar is never even reached for it, see hasPane below), so
    // this button is tmux-preset-only by the same rule everything else in
    // this row already follows; a headless chat can still attach an image
    // by pasting one directly into the composer (see the "paste" listener
    // on textEl further down).
    const attachBtn = document.createElement("button");
    attachBtn.textContent = "📎";
    attachBtn.title = t("keys.attach_file");
    attachBtn.addEventListener("click", () => attachFileInputEl.click());
    modRowEl.appendChild(attachBtn);

    for (const [label, get, set] of MODIFIERS) {
      const btn = document.createElement("button");
      btn.textContent = label;
      btn.className = "mod";
      btn.dataset.mod = label;
      btn.addEventListener("click", () => {
        set(!get());
        updateModButtons();
      });
      modRowEl.appendChild(btn);
    }
    for (const [label, key] of NAMED_KEYS) {
      const btn = document.createElement("button");
      btn.textContent = label;
      btn.addEventListener("click", () => sendKey(key));
      modRowEl.appendChild(btn);
    }


    for (const k of GRID_KEYS) {
      const btn = document.createElement("button");
      btn.textContent = k; // deliberately lowercase as displayed -- shift is
      // a separate explicit modifier now (Ctrl+Shift+a vs Ctrl+a must be
      // distinguishable), not implied by how the key label looks.
      btn.addEventListener("click", () => sendKey(k));
      gridEl.appendChild(btn);
    }
    for (const [label, seq, what] of CTRL_CHORDS) {
      const btn = document.createElement("button");
      btn.textContent = label;
      btn.className = "chord";
      btn.title = `Ctrl+${label.replace(" ", " Ctrl+")}: ${t(what)}`;
      btn.addEventListener("click", () => sendChord(seq));
      gridEl.appendChild(btn);
    }
    updateModButtons();
  }

  // Two keys in a row, as typed (the Ctrl armed for the first stays for the
  // ones marked so); only while Ctrl alone is armed.
  async function sendChord(seq) {
    if (!chatNow.id) return;
    armCtrl = false; armAlt = false; armShift = false;
    updateModButtons();
    for (const [key, ctrl] of seq) {
      try {
        await withUnlockRetry(() => api(sessionPath(chatNow.id, "/keys", chatNow.owner), {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key, ctrl, alt: false, shift: false }),
        }));
      } catch (e) { console.warn("key send failed:", e); return; }
    }
  }

  function updateModButtons() {
    for (const [label, get] of MODIFIERS) {
      modRowEl.querySelector(`button[data-mod="${label}"]`).classList.toggle("active", get());
    }
    gridEl.classList.toggle("visible", armCtrl || armAlt || armShift);
    gridEl.classList.toggle("ctrl-only", armCtrl && !armAlt && !armShift);
  }

  async function sendKey(key) {
    if (!chatNow.id) return;
    const ctrl = armCtrl;
    const alt = armAlt;
    const shift = armShift;
    armCtrl = false;
    armAlt = false;
    armShift = false;
    updateModButtons();
    await withUnlockRetry(() => api(sessionPath(chatNow.id, "/keys", chatNow.owner), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, ctrl, alt, shift }),
    })).catch((e) => console.warn("key send failed:", e));
  }
