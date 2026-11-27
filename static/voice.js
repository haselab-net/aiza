// Voice mode (the deployment notes): listening all the time, the fixed words and the
// server's commands, reading back and waiting for 「はい」.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after page.js and before app.js. What runs here at
// load uses only this file and the earlier ones. Moved out of app.js
// 2026-11-24; the indentation is app.js's.
"use strict";

  // ---- voice mode (the deployment notes, 2026-11-08) ----------------------------------
  // The user: "aiza を音声だけで操作するモード…クリックやフォーカスの移動が
  // 手作業になって、完全なハンズフリーでは使えない". 🎙 turns it on: the
  // browser's speech recognition listens all the time; a few fixed words
  // act at once (次・読んで・ストップ・はい/いいえ・送信…), everything else goes
  // to the server's resident Haiku (POST /voice/command), which answers with
  // one action. Anything that sends is read back and waits for 「はい」.
  // While this page speaks, listening pauses (so it does not hear itself).
  const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
  // Both buttons (the list's top bar and the open session's header) only
  // show the state; the menu they open toggles.
  const voiceBtns = [document.getElementById("voice-btn"), document.getElementById("audio-btn")].filter(Boolean);
  const voiceBarEl = document.getElementById("voice-bar");
  let voiceOn = false;
  let voiceRec = null;
  let voiceSpeaking = false;
  let voicePending = null;   // {say, run} waiting for はい/いいえ
  let voiceDraft = null;     // {session, text} while dictating
  let voiceLastSay = "";
  let voiceSaidEnd = 0;
  let voiceInterimBase = null; // the input box's text before the guess being shown
  // Japanese runs on with no space; a space only between two Latin words.
  const voiceJoin = (a, b) => a + (a && /[A-Za-z0-9]$/.test(a) && /^[A-Za-z0-9]/.test(b) ? " " : "") + b;
  // Dictation goes where the cursor is, replacing a selection (2026-11-11,
  // the user: マウスで選択してから喋ったら、選択したところが消えてそこに
  // 文字が入るように。今は常に一番後ろに追加される). The textarea keeps its
  // selection while focus is elsewhere, so a selection made before speaking
  // still counts. After it, the cursor sits after what was put in.
  function voiceSplice(base, start, end, text) {
    const before = base.slice(0, start), after = base.slice(end);
    const head = voiceJoin(before, text);
    const sp = after && /[A-Za-z0-9]$/.test(text) && /^[A-Za-z0-9]/.test(after) ? " " : "";
    return { value: head + sp + after, caret: head.length, atEnd: !after };
  }
  function voiceInsert(text) {
    const r = voiceSplice(textEl.value, textEl.selectionStart, textEl.selectionEnd, text);
    textEl.value = r.value;
    textEl.setSelectionRange(r.caret, r.caret);
    autoResizeTextarea();
    if (r.atEnd) textEl.scrollTop = textEl.scrollHeight;
  }
  let voiceTodoDone = new Set();
  const voiceDrive = () => !!(voiceBarEl.querySelector(".drive") || {}).checked;
  const vnorm = (s) => s.replace(/[。、,.!?！？\s]/g, "");

  function voiceShow(heard) {
    const st = voiceBarEl.querySelector(".st");
    st.textContent = voiceDraft
      ? t("voice.dictating_into_l_say_send", { l: labelOf(voiceDraft.session) })
      : voicePending ? `❓ ${voicePending.say}` : (heard ? `👂 ${heard}` : t("voice.listening"));
  }
  function labelOf(id) {
    const s = lastSessions.find((x) => x.id === id);
    return s ? s.label : id;
  }
  // Short sounds instead of words for the frequent acknowledgements
  // (2026-11-08, the user: the talkback was too much, and 「送信しました」was
  // lost under the reading of replies). A tone can overlap speech and still
  // be told apart. The context is made on 🎙's own tap (browsers start
  // audio only from one).
  let voiceAudio = null;
  const EARCONS = {
    on: [[660, 0.08], [880, 0.1]],
    start: [[880, 0.07]],          // dictation started
    sent: [[784, 0.07], [1175, 0.12]],
    cancel: [[523, 0.07], [392, 0.12]],
    back: [[660, 0.06]],
    err: [[220, 0.25]],
  };
  function voiceTone(kind) {
    if (!voiceAudio) return;
    let t0 = voiceAudio.currentTime + 0.01;
    for (const [hz, dur] of EARCONS[kind] || []) {
      const o = voiceAudio.createOscillator(), g = voiceAudio.createGain();
      o.frequency.value = hz;
      g.gain.setValueAtTime(0.0001, t0);
      g.gain.exponentialRampToValueAtTime(0.25, t0 + 0.01);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      o.connect(g).connect(voiceAudio.destination);
      o.start(t0); o.stop(t0 + dur + 0.02);
      t0 += dur + 0.03;
    }
  }
  const voiceTtsAudio = new Audio();
  voiceTtsAudio.preservesPitch = true;
  function voiceHush() { // stop our own voice, either kind
    if (canSpeak) speechSynthesis.cancel();
    if (!voiceTtsAudio.paused) { voiceTtsAudio.pause(); if (voiceTtsAudio.onended) voiceTtsAudio.onended(); }
  }
  function voiceSay(text) {
    return new Promise((resolve) => {
      if (!text || !canSpeak) return resolve();
      voiceLastSay = text;
      voiceSpeaking = true;
      try { if (voiceRec) { voiceRec.abort(); voiceRec.running = false; } } catch (e) {}
      const chunks = speechChunks(speechText(text));
      let i = 0, timer = null;
      const next = () => {
        clearTimeout(timer);
        if (i >= chunks.length || !voiceOn) { voiceSpeaking = false; voiceSaidEnd = Date.now(); voiceListen(); return resolve(); }
        const c = chunks[i++];
        let done = false;
        let via = null; // "device" | "cloud": whichever began, the other keeps out
        const once = () => { if (!done) { done = true; next(); } };
        const device = () => {
          if (done || via === "device") return;
          via = "device";
          clearTimeout(timer);
          const u = utterance(c);
          u.onend = u.onerror = once;
          // Android's speech often reports its end late or not at all, and
          // listening waited for it (2026-11-09, the user: after 「停止しますか」
          // nothing was heard for a while): go on after the time it should take.
          timer = setTimeout(once, 600 + c.length * 120);
          speechSynthesis.speak(u);
        };
        // Google's voice when read-aloud is set to it (2026-11-12, the user,
        // after read-aloud and voice mode came under one button: 読み上げが
        // 古くなってしまいました。GoogleAPI版は？ -- voice mode had always
        // used the device's voice). Any failure: the device's voice.
        if (!useCloud()) return device();
        timer = setTimeout(device, 4000); // Google slow to answer
        loadCloudVoices().then(() => {
          const lang = pieceLang(c);
          const voice = cloudVoiceFor(lang);
          if (!voice) return device();
          if (chunks[i]) { const v2 = cloudVoiceFor(pieceLang(chunks[i])); if (v2) ttsUrl(v2, chunks[i]); }
          return ttsUrl(voice, c).then((url) => {
            if (done || via) return;
            via = "cloud";
            clearTimeout(timer);
            const sink = speakPref(SPEAK_SINK_KEY);
            if (canSink && voiceTtsAudio.sinkId !== sink) voiceTtsAudio.setSinkId(sink).catch(() => {});
            voiceTtsAudio.onended = once;
            voiceTtsAudio.onerror = () => { cloudFailed(); via = null; device(); };
            voiceTtsAudio.src = url;
            voiceTtsAudio.playbackRate = pieceRate(lang);
            timer = setTimeout(once, 3000 + c.length * 250); // onended missing
            return voiceTtsAudio.play();
          });
        }).catch(() => { cloudFailed(); device(); });
      };
      next();
    });
  }
  function voiceListen() {
    if (!voiceOn || voiceSpeaking || !SpeechRec) return;
    if (voiceRec) { voiceRecStart(voiceRec); return; }
    const r = new SpeechRec();
    r.lang = "ja-JP";
    r.continuous = true;
    r.interimResults = true;
    // What is being recognized is shown as it comes (2026-11-08, the user:
    // the text arrived all at once, well after speaking, with nothing to
    // see before): while dictating, straight in the input box (replaced
    // as the guess changes, kept when final); otherwise on the bar.
    // Android's Chrome (2026-11-09, the user: text came in many times over)
    // hands back results already given -- the same final again, and each
    // final holding everything said so far in this run. A final is taken
    // once per index, and on Android only the part after the last one.
    r.onresult = (e) => {
      if (voiceSpeaking) return; // our own voice
      let interim = "";
      const finals = [];
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i];
        const tx = res[0].transcript;
        if (!res.isFinal) {
          if (voicePending && !r.doneIdx.has(i)) {
            const g = voiceAndroid && r.lastFinal && tx.trim().startsWith(r.lastFinal) ? tx.trim().slice(r.lastFinal.length) : tx;
            const gn = vnorm(g);
            if (gn && gn.length <= 8 && (VOICE_YES.test(gn) || VOICE_NO.test(gn))) {
              r.doneIdx.add(i);
              r.early = { text: gn, at: Date.now() };
              finals.push(g.trim());
              continue;
            }
          }
          interim += tx;
          continue;
        }
        if (r.doneIdx.has(i)) continue;
        r.doneIdx.add(i);
        const f = voiceNewPart(r, tx.trim());
        // the settled form of an answer already taken from its guess
        if (f && r.early && Date.now() - r.early.at < 4000 && vnorm(f).startsWith(r.early.text)) { r.early = null; continue; }
        if (f) finals.push(f);
      }
      if (voiceAndroid && r.lastFinal && interim.trim().startsWith(r.lastFinal)) interim = interim.trim().slice(r.lastFinal.length);
      if (finals.length && voiceInterimBase !== null) {
        // the guess goes; the final text is put in its place (or acted on) below
        textEl.value = voiceInterimBase.value;
        textEl.setSelectionRange(voiceInterimBase.start, voiceInterimBase.end);
        voiceInterimBase = null;
        autoResizeTextarea();
      }
      for (const f of finals) voiceHeard(f);
      if (interim) {
        if (voiceDraft && chatNow.id === voiceDraft.session) {
          if (voiceInterimBase === null) {
            voiceInterimBase = { value: textEl.value, start: textEl.selectionStart, end: textEl.selectionEnd };
          }
          const b = voiceInterimBase;
          const r = voiceSplice(b.value, b.start, b.end, interim);
          textEl.value = r.value;
          textEl.setSelectionRange(r.caret, r.caret);
          autoResizeTextarea();
          if (r.atEnd) textEl.scrollTop = textEl.scrollHeight;
        } else voiceShow(interim);
      }
    };
    r.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        voiceStop();
        alert(t("voice.allow_microphone"));
      }
    };
    // Chrome ends a continuous recognition now and then: start it again.
    r.onend = () => { r.running = false; if (voiceOn && !voiceSpeaking) setTimeout(() => voiceRecStart(r), 250); };
    voiceRec = r;
    voiceRecStart(r);
  }
  // start() throws while the last run is still ending (after an abort for
  // our own speech): try again shortly instead of staying deaf.
  function voiceRecStart(r, tries = 0) {
    if (!voiceOn || voiceSpeaking || r !== voiceRec || r.running) return;
    r.doneIdx = new Set();
    r.lastFinal = "";
    try { r.start(); r.running = true; }
    catch (e) { if (tries < 8) setTimeout(() => voiceRecStart(r, tries + 1), 300); }
  }
  const voiceAndroid = /Android/i.test(navigator.userAgent);
  function voiceNewPart(r, full) {
    if (!voiceAndroid) return full;
    const prev = r.lastFinal;
    r.lastFinal = full;
    if (prev && full.startsWith(prev)) return full.slice(prev.length).trim();
    return full;
  }
  function voiceStart() {
    if (!SpeechRec) return alert(t("voice.use_chrome_or_edge_voice"));
    voiceOn = true;
    voiceBtns.forEach((b) => b.classList.add("on"));
    voiceBarEl.hidden = false;
    try { voiceAudio = voiceAudio || new (window.AudioContext || window.webkitAudioContext)(); voiceAudio.resume(); } catch (e) {}
    voiceShow();
    voiceTone("on");
    voiceListen();
  }
  function voiceStop() {
    voiceOn = false;
    voicePending = null;
    voiceDraft = null;
    voiceBtns.forEach((b) => b.classList.remove("on"));
    voiceBarEl.hidden = true;
    try { voiceRec && voiceRec.abort(); } catch (e) {}
    voiceRec = null;
    voiceHush();
  }
  { const vb = document.getElementById("voice-btn"); vb.addEventListener("click", () => openAudioMenu(vb)); }
  voiceBarEl.querySelector(".off").addEventListener("click", voiceStop);

  async function voiceSend(sid, text) {
    try {
      await withUnlockRetry(() => api(sessionPath(sid, "/messages", null), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, submit: true }),
      }));
      voiceTone("sent");
    } catch (e) {
      voiceTone("err");
      await voiceSay(e.unlockRequired ? t("voice.unlock") : t("voice.send_failed"));
    }
  }
  function voiceConfirm(say, run) {
    voicePending = { say, run };
    voiceShow();
    return voiceSay(say);
  }
  async function voiceOpen(sid) {
    const meta = lastSessions.find((s) => s.id === sid);
    if (!meta) return false;
    if (chatNow.id !== sid) chatNow.open(meta);
    return true;
  }
  async function voiceSummary(sid) {
    try {
      const r = await api("/voice/summary", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ session_id: sid }) });
      return r.say || "";
    } catch (e) { return ""; }
  }
  // 「次」: the next session whose turn is yours (and 寝かせ whose date came),
  // opened, its note and a short summary of its last reply read out.
  async function voiceTodoNext() {
    await refreshSessions().catch(() => {});
    const due = lastSessions.filter((s) => ["you", "due"].includes(taskGroup(s)));
    let s = due.find((x) => !voiceTodoDone.has(x.id));
    if (!s && due.length) { voiceTodoDone = new Set(); s = due[0]; }
    if (!s) return voiceSay(t("voice.nothing"));
    voiceTodoDone.add(s.id);
    await voiceOpen(s.id);
    const note = (s.task && s.task.text) || "";
    await voiceSay(`${s.label}。${note}`);
    const sum = await voiceSummary(s.id);
    if (sum) await voiceSay(sum);
  }
  function voiceUntil(str) {
    const m = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?/.exec(str || "");
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3], m[4] ? +m[4] : 9, m[5] ? +m[5] : 0).getTime() / 1000;
  }
  async function voiceAct(a) {
    const sid = a.session;
    switch (a.action) {
      case "open":
        await voiceOpen(sid);
        return voiceSay(labelOf(sid));
      case "send":
        if (!a.text) return voiceSay(a.say || t("voice.send_what"));
        return voiceConfirm(t("voice.send_x_l", { l: labelOf(sid), x: a.text }), () => voiceSend(sid, a.text));
      case "dictate":
        await voiceOpen(sid);
        return voiceStartDictation(sid);
      case "show":
        if (a.what === "email") return voiceShowEmail();
        if (a.what === "todo") return voiceShowTodo();
        return voiceBack();
      case "read":
        await voiceOpen(sid);
        return voiceSay(a.read_text || a.say);
      case "todo":
        return voiceTodoNext();
      case "task": {
        const body = { state: a.state };
        if (a.state === "snooze") {
          const u = voiceUntil(a.until);
          if (!u) return voiceSay(t("voice.which_date"));
          body.until = u;
        }
        try {
          await api(`/sessions/${encodeURIComponent(sid)}/task`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
          return voiceTone("sent");
        } catch (e) { return voiceSay(t("voice.change_failed")); }
      }
      case "interrupt":
        return voiceInterrupt(sid);
      case "stop":
        return voiceStopSession(sid);
      case "resume":
        return voiceResume(sid);
      case "close":
        if (chatNow.id) chatNow.close();
        return voiceSay(a.say);
      default:
        return voiceSay(a.say);
    }
  }
  // 中断・停止・再開 (2026-11-08, the user: "セッションの中断・再開も音声で").
  // 中断 is Esc (Claude stops what it is doing, the session stays); 停止
  // ends the session (asked first, like the green dot); 再開 resumes an
  // ended one with its conversation (the grey dot's ↻).
  async function voiceInterrupt(sid) {
    try {
      await withUnlockRetry(() => api(sessionPath(sid, "/keys", null), {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ key: "Escape", ctrl: false, alt: false, shift: false }),
      }));
      voiceTone("cancel");
    } catch (e) { voiceTone("err"); return voiceSay(e.unlockRequired ? t("voice.unlock") : t("voice.interrupt_failed")); }
  }
  function voiceStopSession(sid) {
    const s = lastSessions.find((x) => x.id === sid);
    if (!s || s.alive === false) return voiceSay(t("common.already_stopped"));
    return voiceConfirm(t("voice.stop_l", { l: s.label }), async () => {
      try {
        await withUnlockRetry(() => api(sessionPath(sid, "/stop", null), { method: "POST" }));
        if (chatNow.id === sid) chatNow.close(); else await refreshSessions();
        voiceTone("sent");
      } catch (e) { voiceTone("err"); return voiceSay(e.unlockRequired ? t("voice.unlock") : t("voice.stop_failed")); }
    });
  }
  async function voiceResume(sid) {
    await refreshSessions().catch(() => {});
    const s = lastSessions.find((x) => x.id === sid);
    if (!s) return voiceSay(t("voice.which_session"));
    if (s.alive) return voiceSay(t("common.already_running"));
    if (s.owner || !canResumeEnded(s)) return voiceSay(t("common.cant_resume"));
    await voiceSay(s.label);
    return resumeEndedSession(s, true);
  }
  function voiceStartDictation(sid) {
    voiceDraft = { session: sid };
    voiceInterimBase = null;
    voiceShow();
    textEl.focus({ preventScroll: true });
    voiceTone("start");
  }
  async function voiceComposerSend() {
    const d = voiceDraft;
    if (!textEl.value.trim()) return voiceSay(t("voice.empty"));
    // Dictation goes on after a send, until 「入力終わり」 (2026-11-09, the
    // user: having to say 「入力」 again after every 送信 was tedious).
    const go = async () => {
      await send(true);
      if (chatNow.id !== d.session) { voiceDraft = null; voiceShow(); }
      voiceTone("sent");
    };
    if (voiceDrive()) return voiceConfirm(t("voice.send_x_l", { l: labelOf(d.session), x: textEl.value }), go);
    return go();
  }
  function voiceShowTodo() {
    showTodoView(true);
    const n = lastSessions.filter((s) => ["you", "due"].includes(taskGroup(s))).length;
    return voiceSay(t("voice.do_n", { n }));
  }
  // The Email box's page (/email/): the way an extension opens it over this
  // page (aizaExt links) when there is one, else a tab of its own.
  function voiceShowEmail() {
    const open = window.aizaExt.linkHandler("/email/");
    if (open) open("/email/");
    else window.open("/email/", "_blank");
    return voiceSay(t("common.mail"));
  }
  function voiceBack() {
    if (window.aizaExt.closeOverlay()) { /* the extension's overlay closed */ }
    else if (todoOn()) hideTodoView();
    else if (chatNow.id) chatNow.close();
    voiceTone("back");
  }
  textEl.addEventListener("focus", () => {
    if (voiceOn && chatNow.id && !voiceDraft) { voiceDraft = { session: chatNow.id }; voiceShow(); }
  });

  // Answers to a question (はい/いいえ). Taken from the guess already, not
  // only once the recognizer settles on it (2026-11-09, the user: answering
  // 「停止しますか」 took very long -- on Android the settled result comes
  // well after one stops talking).
  const VOICE_YES = /^(はい|はーい|うん|お願い|送って|オッケー|オーケー|OK|いいよ|どうぞ)/i;
  const VOICE_NO = /^(いいえ|いや|やめ|キャンセル|取り消|違う|ちがう|だめ|ダメ|ノー)/;
  const VOICE_DICT_END = /^(入力|書き取り)(終わり|終わって|終了|停止|ストップ|やめ|やめて|止めて|を終わって|を終了|を止めて|をやめて)(して)?$/;
  async function voiceHeard(text) {
    if (!text) return;
    // Our own words caught by the mic (the end of speech is guessed on
    // Android, see voiceSay): what was just said is not taken as an answer.
    const bare = (x) => (x || "").replace(/[^\p{L}\p{N}]/gu, "");
    // A "no" while a yes/no is waiting is always taken (2026-11-24): the
    // question itself says いいえ, so right after it an answer いいえ looked
    // like our own words and was dropped, leaving the question open for the
    // next はい. Taking an echo as "no" only cancels; はい is too short to
    // be dropped.
    const n = vnorm(text);
    const said = bare(voiceLastSay), heard = bare(text);
    const no = voicePending && VOICE_NO.test(n);
    if (!no && said && heard.length >= 3 && Date.now() - voiceSaidEnd < 5000 && said.includes(heard)) return;
    voiceShow(text);
    if (voicePending) {
      const p = voicePending;
      if (VOICE_YES.test(n)) { voicePending = null; voiceShow(); return p.run(); }
      if (VOICE_NO.test(n)) { voicePending = null; voiceShow(); return voiceTone("cancel"); }
      return voiceSay(t("voice.yes_or_no"));
    }
    if (voiceDraft) {
      // Dictation goes into the session's own input box (2026-11-08, the
      // user could not find how to get the transcript into it).
      if (chatNow.id !== voiceDraft.session) { voiceDraft = null; voiceShow(); }
      else {
        if (/^(送信|送信して|送信します|送って|送る|送ります|実行|実行して|そうしん|ソウシン)$/.test(n)) return voiceComposerSend();
        if (/^(取り消し|キャンセル|消して|全部消して)$/.test(n)) {
          textEl.value = ""; autoResizeTextarea(); voiceDraft = null; voiceShow();
          return voiceTone("cancel");
        }
        if (VOICE_DICT_END.test(n)) { voiceDraft = null; voiceShow(); return voiceTone("back"); }
        if (/^(読んで|読み上げて|確認)$/.test(n)) return voiceSay(textEl.value || t("voice.empty"));
        if (/^改行$/.test(n)) { voiceInsert("\n"); return; }
        voiceInsert(text);
        return;
      }
    }
    // 「入力停止」 outside dictation must not become 停止 (2026-11-09: it was
    // taken as stopping the session).
    if (VOICE_DICT_END.test(n)) return voiceTone("back");
    if (/^(中断|中断して|エスケープ|作業を止めて|作業中断)$/.test(n)) {
      if (!chatNow.id) return voiceSay(t("voice.open_session"));
      return voiceInterrupt(chatNow.id);
    }
    if (/^(停止|停止して|セッションを止めて|セッション停止|終了して)$/.test(n)) {
      if (!chatNow.id) return voiceSay(t("voice.open_session"));
      return voiceStopSession(chatNow.id);
    }
    if (/^(再開|再開して|続きから|続きから再開)$/.test(n)) {
      if (!chatNow.id) return voiceSay(t("voice.open_session"));
      return voiceResume(chatNow.id);
    }
    if (/^(書いて|入力|入力して|書き取り|口述)$/.test(n)) {
      if (!chatNow.id) return voiceSay(t("voice.open_session"));
      return voiceStartDictation(chatNow.id);
    }
    if (/^(やること|やることリスト|ToDo|トゥードゥー)$/i.test(n)) return voiceShowTodo();
    if (/^(メール|メール一覧|新着まとめ|メールのリスト|Eメール)$/i.test(n)) return voiceShowEmail();
    if (/^(戻る|閉じて|戻って|一覧|一覧に戻って)$/.test(n)) return voiceBack();
    if (/^(ストップ|止めて|静かに|黙って)$/.test(n)) { speechSynthesis.cancel(); voiceHush(); return; }
    if (/^(もう一度|もう一回|もういっかい)$/.test(n)) return voiceSay(voiceLastSay);
    if (/^(次|次の|つぎ)$/.test(n)) return voiceTodoNext();
    if (/^(音声モード終了|音声終わり|おしまい)$/.test(n)) { await voiceSay(t("voice.bye")); return voiceStop(); }
    if (/^(読んで|要約して)$/.test(n) && chatNow.id) return voiceSay((await voiceSummary(chatNow.id)) || t("voice.no_reply_yet"));
    voiceBarEl.classList.add("busy");
    try {
      const a = await api("/voice/command", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, current: chatNow.id, mode: voiceDrive() ? "drive" : "desk" }),
      });
      await voiceAct(a);
    } catch (e) {
      voiceTone("err");
    } finally {
      voiceBarEl.classList.remove("busy");
      voiceShow();
    }
  }
