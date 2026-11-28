// Reading replies aloud (the deployment notes): the 🔊 button and its menu, the browser's and the
// cloud voices, background reading and the keep-alive that lets a phone keep playing.
//
// One of the page's own scripts (the deployment notes): one global scope
// with the others, loaded after page.js and before app.js. What runs here at
// load uses only this file and the earlier ones. Moved out of app.js
// 2026-11-24; the indentation is app.js's.
"use strict";

  // Read-aloud of new AI replies (2026-10-25, at the user's request:
  // "Chatの新しいメッセージだけを読み上げる"). Uses the browser's own
  // speechSynthesis, i.e. the phone's/PC's TTS voice -- nothing server-side.
  // Only agent_output events that arrive over the live SSE stream are read
  // (see connectSessionEvents), never the history page or older history. In
  // AI presets every agent_output is a reply; in a shell session most are the
  // pane's raw output, so only those marked "ai" (from the transcript of a
  // `claude` run in it, _assistant_block_events in aiza-backend) are read.
  // On/off is per browser (localStorage), not per session. Chrome refuses
  // speak() until the page has had a user gesture, so after a reload the
  // first tap anywhere primes it with a silent utterance.
  const SPEAK_KEY = "aiza-speak";
  const speakBtn = document.getElementById("audio-btn");
  const canSpeak = "speechSynthesis" in window && typeof SpeechSynthesisUtterance === "function";
  let speakOn = false;
  try { speakOn = canSpeak && localStorage.getItem(SPEAK_KEY) === "1"; } catch (e) {}
  const isSpeakPreset = (p) => p === "claude" || p === "mail-tui" || /^(claude|codex)-tui(-|$)/.test(String(p || ""));
  const isShellPreset = (p) => /^(shell|host-shell|root-shell|attach)$|^shell-/.test(String(p || ""));
  const speakable = (p, ev) => ev.type === "agent_output" && (isSpeakPreset(p) || (isShellPreset(p) && ev.ai === true));
  const SPEECH_LANG = { ja: "ja-JP", en: "en-US", "zh-CN": "zh-CN" };
  function speechText(md) {
    return String(md || "")
      .replace(/```[\s\S]*?(```|$)/g, "\n" + t("speak.code_omitted") + "\n")
      .replace(/`([^`\n]*)`/g, "$1")
      .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
      .replace(/https?:\/\/\S+/g, t("common.link_2"))
      .replace(/^[ \t]*\|?[ \t:|-]*-{3,}[ \t:|-]*$/gm, "")
      .replace(/^[ \t]*\|(.*?)\|?[ \t]*$/gm, "$1")
      .replace(/[ \t]*\|[ \t]*/g, "、")
      .replace(/^[ \t]*(#{1,6}|>|[-*+]|\d+\.)[ \t]+/gm, "")
      // Arrows and > between words (a menu path, "A → B") are a pause, not
      // 「大なり」 (2026-11-11, the user: the reading went odd, maybe at >).
      .replace(/[ \t]*(?:-+>|=+>|→|⇒|>+(?!=))[ \t]*/g, "、")
      .replace(/[ \t]*(?:<-+|←|⇐)[ \t]*/g, "、")
      .replace(/[*_~]{1,3}([^*_~\n]+)[*_~]{1,3}/g, "$1")
      .replace(/\n{2,}/g, "\n")
      .trim();
  }
  // Long single utterances stall in Chrome (desktop ~15s, Android ~4000
  // chars), so speak sentence-sized pieces; speechSynthesis queues them.
  function speechChunks(text) {
    const out = [];
    for (const part of text.split(/(?<=[。！？!?\n])|(?<=[.] )/)) {
      let p = part.trim();
      while (p.length > 200) { out.push(p.slice(0, 200)); p = p.slice(200); }
      if (p) out.push(p);
    }
    return out;
  }
  // Speed and voice (2026-10-25, at the user's request): the OS's own speech
  // rate setting does not reach Chrome, which passes every utterance's rate
  // itself. Set from a long-press popup on 🔊 (no room for more buttons in
  // the header). The keys are shared with the read-aloud of the Email box's
  // own pages, which are on this same origin.
  const SPEAK_RATE_KEY = "aiza-speak-rate";
  const SPEAK_VOICE_KEY = "aiza-speak-voice";
  const SPEAK_RATES = [0.75, 1, 1.25, 1.5, 1.75, 2, 2.5];
  function speakPref(key) {
    try { return localStorage.getItem(key) || ""; } catch (e) { return ""; }
  }
  function speechLang() {
    return SPEECH_LANG[window.aizaI18n ? window.aizaI18n.lang() : "ja"] || "ja-JP";
  }
  // Per-language speed and voice (2026-11-02, the user: "Japanese is slow
  // and English fast -- can each language have its own speed?"). The plain
  // keys are the display language's; the other language read aloud (English,
  // or Japanese when the display is English) has "-<xx>" keys, falling back
  // to the plain speed when unset.
  function otherSpeechLang() {
    return speechLang().startsWith("en") ? "ja-JP" : "en-US";
  }
  function speakKeys(lang) {
    if (lang.slice(0, 2) === speechLang().slice(0, 2)) return [SPEAK_RATE_KEY, SPEAK_VOICE_KEY];
    const x = lang.slice(0, 2);
    return [`${SPEAK_RATE_KEY}-${x}`, `${SPEAK_VOICE_KEY}-${x}`];
  }
  function speechVoices(lang) {
    const prefix = (lang || speechLang()).slice(0, 2).toLowerCase();
    return speechSynthesis.getVoices().filter((v) => v.lang.replace("_", "-").toLowerCase().startsWith(prefix));
  }
  // English in English (2026-11-02, at the user's request): a piece with
  // no Japanese in it but with Latin letters is read by an English voice;
  // one with any kana/kanji by a Japanese voice. A Japanese sentence with a
  // few English words stays Japanese. The chosen voice (long-press 🔊) is
  // used for pieces in its own language.
  const JA_RE = /[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f]/;
  function pieceLang(text) {
    if (JA_RE.test(text)) return "ja-JP";
    if (/[A-Za-z]{2,}/.test(text)) return "en-US";
    return speechLang();
  }
  function bestVoice(lang) {
    const p = lang.slice(0, 2).toLowerCase();
    const vs = speechSynthesis.getVoices().filter((v) => v.lang.replace("_", "-").toLowerCase().startsWith(p));
    const exact = vs.filter((v) => v.lang.replace("_", "-").toLowerCase() === lang.toLowerCase());
    // Google first (2026-11-03, the user: Windows' Microsoft voices were
    // worse than Google's), then the device default.
    return exact.find((v) => /Google/.test(v.name)) || vs.find((v) => /Google/.test(v.name)) || vs.find((v) => v.default) || exact[0] || vs[0] || null;
  }
  function utterance(text) {
    const u = new SpeechSynthesisUtterance(text);
    const lang = pieceLang(text);
    u.lang = lang;
    const [rateKey, voiceKey] = speakKeys(lang);
    u.rate = Number(speakPref(rateKey)) || Number(speakPref(SPEAK_RATE_KEY)) || 1;
    const name = speakPref(voiceKey) || speakPref(SPEAK_VOICE_KEY);
    const chosen = name && speechSynthesis.getVoices().find((x) => x.voiceURI === name);
    const v = chosen && chosen.lang.slice(0, 2).toLowerCase() === lang.slice(0, 2) ? chosen : bestVoice(lang);
    if (v) {
      u.voice = v;
      u.lang = v.lang;
    }
    return u;
  }
  // Tap to pause / tap to resume from there (2026-10-26, at the user's
  // request): while reading, a tap in the chat pauses; the next tap on a
  // bubble (or any tap on one while idle) reads from the tapped sentence on,
  // through the replies below it.
  // So speech runs from its own queue, one chunk per utterance, to know
  // where it is. Pausing is cancel(), not speechSynthesis.pause() (which
  // Android Chrome treats as a cancel anyway); replies arriving while
  // paused are not queued -- resuming above them reads them in order.
  // Google's voices (the deployment notes, 2026-11-11, the user: 読み上げの
  // スピーカーを切り替えたい → WaveNet で): each piece is fetched as MP3 from
  // the gateway (/agents/tts, which holds the key) and played in an <audio>,
  // whose output a PC's Chrome can send to a chosen speaker (setSinkId).
  // Any failure reads that piece with the device's voice instead and keeps
  // off Google for a minute. The next piece is fetched while one plays.
  const SPEAK_ENGINE_KEY = "aiza-speak-engine";   // "" (device) | "cloud"
  const SPEAK_CVOICE_KEY = "aiza-speak-cvoice";   // + "-<xx>" per language
  const SPEAK_SINK_KEY = "aiza-speak-sink";       // audiooutput deviceId
  const canSink = typeof HTMLMediaElement !== "undefined" && "setSinkId" in HTMLMediaElement.prototype;
  const CLOUD_LANG = { ja: "ja-JP", en: "en-US", zh: "cmn-CN" };
  let cloudVoices = null;       // [{name, lang, kind, gender}] once fetched
  let cloudVoicesAsked = null;  // the fetch in flight
  let cloudOffUntil = 0;
  let cloudFails = 0;           // in a row; three keep off Google for a minute
  const ttsAudio = new Audio();
  ttsAudio.preservesPitch = true;
  const ttsFetched = new Map(); // "voice\ntext" -> Promise<objectURL>
  const useCloud = () => speakPref(SPEAK_ENGINE_KEY) === "cloud" && Date.now() >= cloudOffUntil;
  function loadCloudVoices() {
    if (cloudVoices) return Promise.resolve(cloudVoices);
    if (!cloudVoicesAsked) {
      cloudVoicesAsked = fetch(window.aizaBase + "/agents/tts/voices", { credentials: "same-origin" })
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
        .then((j) => (cloudVoices = j.voices || []))
        .catch((e) => { cloudVoicesAsked = null; throw e; });
    }
    return cloudVoicesAsked;
  }
  function cloudVoiceFor(lang) {
    const x = lang.slice(0, 2);
    const want = CLOUD_LANG[x];
    const vs = (cloudVoices || []).filter((v) => v.lang === want);
    const key = x === speechLang().slice(0, 2) ? SPEAK_CVOICE_KEY : `${SPEAK_CVOICE_KEY}-${x}`;
    const name = speakPref(key);
    return (vs.find((v) => v.name === name) || vs.find((v) => v.kind === "Wavenet") || vs[0] || {}).name || "";
  }
  function pieceRate(lang) {
    const [rateKey] = speakKeys(lang);
    return Number(speakPref(rateKey)) || Number(speakPref(SPEAK_RATE_KEY)) || 1;
  }
  function ttsUrl(voice, text) {
    const k = voice + "\n" + text;
    if (!ttsFetched.has(k)) {
      const p = fetch(window.aizaBase + "/agents/tts", {
        method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ voice, text }),
      }).then((r) => (r.ok ? r.blob() : Promise.reject(new Error(String(r.status))))).then((b) => URL.createObjectURL(b));
      p.catch(() => ttsFetched.delete(k));
      ttsFetched.set(k, p);
      if (ttsFetched.size > 40) {
        const [old, op] = ttsFetched.entries().next().value;
        ttsFetched.delete(old);
        op.then((u) => URL.revokeObjectURL(u), () => {});
      }
    }
    return ttsFetched.get(k);
  }
  function applySink() {
    const id = speakPref(SPEAK_SINK_KEY);
    if (canSink && ttsAudio.sinkId !== id) ttsAudio.setSinkId(id).catch(() => {});
  }
  const speechSource = new WeakMap(); // speakable bubble -> its raw text
  let speakQueue = []; // [{el, chunks}]; [0] is the one being read
  let speakPos = 0; // chunk index within speakQueue[0]
  let speakGen = 0; // bumped on every cancel, so stale onend callbacks drop
  let speakPaused = false;
  let speakCurrent = null; // Chrome drops onend of a garbage-collected utterance
  let bgQueue = []; // [{el: null, chunks}]: other sessions' replies, read when the chat has nothing (the deployment notes)
  function bgKick() {
    if (!speakQueue.length && bgQueue.length && !speakPaused) speakPump();
  }
  function markSpeaking(el) {
    for (const b of messagesEl.querySelectorAll(".bubble.speaking")) if (b !== el) b.classList.remove("speaking");
    if (el) el.classList.add("speaking");
  }
  function speakPump() {
    const g = speakGen;
    while (speakQueue.length && speakPos >= speakQueue[0].chunks.length) {
      speakQueue.shift();
      speakPos = 0;
    }
    // Other sessions' replies (the deployment notes) wait for the open chat's own.
    if (!speakQueue.length && bgQueue.length && !speakPaused) {
      speakQueue.push(bgQueue.shift());
      speakPos = 0;
    }
    markSpeaking(speakQueue.length ? speakQueue[0].el : null);
    if (!speakQueue.length) return;
    const text = speakQueue[0].chunks[speakPos];
    const next = () => {
      if (g !== speakGen) return;
      speakPos++;
      speakPump();
    };
    const device = () => {
      if (g !== speakGen) return;
      const u = utterance(text);
      u.onend = u.onerror = next;
      speakCurrent = u;
      speechSynthesis.speak(u);
    };
    if (!useCloud()) return device();
    loadCloudVoices().then(() => {
      const lang = pieceLang(text);
      const voice = cloudVoiceFor(lang);
      if (!voice) return device();
      // Fetch the piece after this one meanwhile, so the gap stays short.
      const after = speakQueue[0] && speakQueue[0].chunks[speakPos + 1];
      if (after) { const v2 = cloudVoiceFor(pieceLang(after)); if (v2) ttsUrl(v2, after); }
      // A failed piece is asked for once more before the device's voice
      // reads it (2026-11-11: one passing failure switched voices mid-reply).
      const get = () => ttsUrl(voice, text).catch(() => new Promise((ok) => setTimeout(ok, 700)).then(() => ttsUrl(voice, text)));
      return get().then((url) => {
        if (g !== speakGen) return;
        cloudFails = 0;
        applySink();
        ttsAudio.onended = next;
        ttsAudio.onerror = () => { cloudFailed(); device(); };
        ttsAudio.src = url;
        ttsAudio.playbackRate = pieceRate(lang);
        return ttsAudio.play();
      });
    }).catch(() => { cloudFailed(); device(); });
  }
  function cloudFailed() {
    if (++cloudFails >= 3) { cloudFails = 0; cloudOffUntil = Date.now() + 60000; }
  }
  function speak(md, el) {
    if (!speakOn || speakPaused) return;
    const chunks = speechChunks(speechText(md));
    if (!chunks.length) return;
    speakQueue.push({ el: el || null, chunks });
    if (speakQueue.length === 1) {
      speakPos = 0;
      speakPump();
    }
  }
  function cancelSpeech() {
    speakGen++;
    speakQueue = [];
    speakPos = 0;
    speakCurrent = null;
    if (canSpeak) speechSynthesis.cancel();
    ttsAudio.onended = ttsAudio.onerror = null;
    ttsAudio.pause();
    markSpeaking(null);
  }
  function stopSpeaking() {
    cancelSpeech();
    speakPaused = false;
    updateSpeakBtn();
    setTimeout(bgKick, 0); // a notice cut off by opening or leaving a session: the next one goes on
  }
  function pauseSpeaking() {
    cancelSpeech();
    speakPaused = true;
    updateSpeakBtn();
  }
  // Where in a bubble the tap landed, as a chunk index: the caret offset in
  // the shown text, matched against where each chunk's opening letters sit in
  // it (letters and digits only -- the shown text keeps the markdown, URLs
  // and tables that speechText rewrites).
  const speechKey = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "");
  function tappedChunk(el, chunks, x, y) {
    let node = null;
    let off = 0;
    if (document.caretPositionFromPoint) {
      const p = document.caretPositionFromPoint(x, y);
      if (p) { node = p.offsetNode; off = p.offset; }
    } else if (document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(x, y);
      if (r) { node = r.startContainer; off = r.startOffset; }
    }
    if (!node || !el.contains(node)) return 0;
    const before = document.createRange();
    before.setStart(el, 0);
    before.setEnd(node, off);
    const tapAt = speechKey(before.toString()).length;
    const shown = speechKey(el.textContent);
    let from = 0;
    let best = 0;
    chunks.forEach((c, i) => {
      const k = speechKey(c).slice(0, 8);
      const at = k ? shown.indexOf(k, from) : -1;
      if (at < 0) return;
      from = at + 1;
      if (at <= tapAt) best = i;
    });
    return best;
  }
  // A tapped thought (2026-10-26, the user's follow-up) is read too, opened
  // in full; the replies below follow, but not the other thoughts.
  const readsOn = (b) => speechSource.has(b) && !b.classList.contains("thought");
  function resumeSpeaking(bubble, x, y) {
    const all = [...messagesEl.querySelectorAll(".bubble")].filter((b) => b === bubble || readsOn(b));
    const rest = all.slice(all.indexOf(bubble)).filter((b) => b === bubble ? speechSource.has(b) : readsOn(b));
    if (!rest.length) return;
    if (rest[0].classList.contains("thought")) rest[0].classList.add("open");
    cancelSpeech();
    speakPaused = false;
    speakQueue = rest.map((b) => ({ el: b, chunks: speechChunks(speechText(speechSource.get(b))) }));
    speakPos = rest[0] === bubble ? tappedChunk(bubble, speakQueue[0].chunks, x, y) : 0;
    updateSpeakBtn();
    speakPump();
  }
  // With 🔊 on and nothing being read (2026-10-26, the user's follow-up), a
  // tap on a bubble reads from there just as it does while paused.
  messagesEl.addEventListener("click", (e) => {
    if (!speakOn) return;
    if (e.target.closest("a, button, img, video, audio, input, textarea, select, summary")) return;
    if (String(window.getSelection() || "").trim()) return; // selecting text, not a tap
    if (speakQueue.length && !speakPaused) {
      pauseSpeaking();
      return;
    }
    const bubble = e.target.closest(".bubble");
    if (bubble) resumeSpeaking(bubble, e.clientX, e.clientY);
  });
  // One header button for read-aloud and voice mode (2026-11-12, the user:
  // "読み上げと音声モードのメニューのアイコンを一緒にしたい。タップで1行メニューが
  // でるようにして、その中に ON,OFF と設定を開くためのボタンを"). Its look
  // only shows the state (blue: reading aloud, ⏸ badge: paused, red: voice
  // mode, set by voiceStart/voiceStop); a tap opens openAudioMenu().
  function speakAvailable() {
    return canSpeak && (isSpeakPreset(chatNow.preset) || isShellPreset(chatNow.preset));
  }
  // Under the button, right edges aligned, but kept inside the screen: with
  // the button near the left edge a right-aligned box ran off the left side.
  let audioMenuAnchor = speakBtn;
  function placeUnderSpeakBtn(el) {
    const r = audioMenuAnchor.getBoundingClientRect();
    const vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const top = Math.min(r.bottom + 6, vh - 120);
    el.style.top = `${top}px`;
    el.style.maxHeight = `${vh - top - 8}px`;
    el.style.overflowY = "auto";
    el.style.left = `${Math.max(8, Math.min(r.right - el.offsetWidth, vw - 8 - el.offsetWidth))}px`;
  }
  let audioMenuEl = null;
  function updateSpeakBtn() {
    speakBtn.classList.toggle("active", speakOn);
    speakBtn.classList.toggle("paused", speakOn && speakPaused);
    speakBtn.title = speakOn && speakPaused ? t("speak.read_aloud_paused_tap_message")
      : t("common.read_aloud_voice_mode");
    if (audioMenuEl) { audioMenuEl.refresh(); placeUnderSpeakBtn(audioMenuEl); }
  }
  function closeAudioMenu() {
    if (!audioMenuEl) return;
    audioMenuEl.remove();
    audioMenuEl = null;
  }
  // The list's 🎙 opens it too (2026-11-23), under itself.
  function openAudioMenu(anchor) {
    if (audioMenuEl) return closeAudioMenu();
    audioMenuAnchor = anchor instanceof Element ? anchor : speakBtn;
    const menu = document.createElement("div");
    menu.className = "audio-menu";
    const mk = (cls, onclick) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = cls;
      b.addEventListener("click", onclick);
      menu.appendChild(b);
      return b;
    };
    const speakB = mk("speak", () => setSpeakOn(!speakOn));
    const voiceB = mk("voice", () => { voiceOn ? voiceStop() : voiceStart(); menu.refresh(); });
    // Other sessions' replies too (2026-11-23, the user: マイクのボタンを押した
    // ときにポップアップが出て設定できるのが良い) -- it was a list button first.
    const bgB = mk("speak-bg", () => setSpeakBg(!speakBg));
    // To 設定's 読み上げと音声 (2026-11-26, the user: マイクのポップアップの中の
    // 設定は、設定タブの読み上げと音声へのリンクが良い).
    const setB = mk("settings", () => {
      closeAudioMenu();
      if (chatNow.id) chatNow.close();
      ui.tabs.show("settings");
      setTimeout(() => speakSettingsEl.closest(".set-card").scrollIntoView({ block: "start" }), 0);
    });
    setB.textContent = t("speak.settings");
    menu.refresh = () => {
      const avail = speakAvailable();
      speakB.hidden = !avail;
      setB.hidden = !canSpeak;
      speakB.textContent = !speakOn ? t("speak.read_aloud_off") : speakPaused ? t("speak.read_aloud_paused") : t("speak.read_aloud_on_2");
      speakB.classList.toggle("on", speakOn);
      speakB.title = t("speak.tap_turn_read_aloud_on");
      bgB.hidden = !canSpeak;
      bgB.textContent = speakBg ? t("speak.others_too_on") : t("speak.others_too_off");
      bgB.classList.toggle("on", speakBg);
      bgB.title = t("speak.also_read_out_other_sessions");
      voiceB.textContent = voiceOn ? t("speak.voice_mode_on") : t("speak.voice_mode_off");
      voiceB.classList.toggle("on", voiceOn);
      voiceB.title = t("speak.tap_turn_voice_mode_on");
    };
    menu.refresh();
    document.body.appendChild(menu);
    placeUnderSpeakBtn(menu);
    audioMenuEl = menu;
    setTimeout(() => {
      const close = (e) => {
        if (menu.contains(e.target) || audioMenuAnchor.contains(e.target)) return;
        if (audioMenuEl === menu) closeAudioMenu();
        document.removeEventListener("pointerdown", close, true);
      };
      document.addEventListener("pointerdown", close, true);
    }, 0);
  }
  speakBtn.addEventListener("click", () => openAudioMenu(speakBtn));

  // What aiza is (2026-11-21): the logo top-left opens it.
  const aboutModalEl = document.getElementById("about-modal");
  document.getElementById("about-btn").addEventListener("click", () => { aboutModalEl.hidden = false; });
  aboutModalEl.addEventListener("click", (e) => {
    if (e.target === aboutModalEl || e.target.closest(".close")) aboutModalEl.hidden = true;
  });
  let speakPopEl = null;
  function closeSpeakPop() {   // (a session closed: chat.js)
    if (speakPopEl) { speakPopEl.remove(); speakPopEl = null; }
  }
  // The read-aloud settings (the engine, each language's speed and voice,
  // the output, 試す) built into `pop`: 設定's 読み上げと音声 card, laid open (2026-11-26, the user: ポップアップで選ぶ
  // のではなく展開しておいて).
  function buildSpeakSettings(pop) {
    pop.textContent = "";
    // One speed/voice pair per language: the display language's, then the
    // other one read aloud (English, or Japanese on an English display).
    const langs = [speechLang(), otherSpeechLang()];
    const sels = langs.map((lang) => {
      const [rateKey, voiceKey] = speakKeys(lang);
      const rateSel = document.createElement("select");
      const rate = Number(speakPref(rateKey)) || Number(speakPref(SPEAK_RATE_KEY)) || 1;
      for (const r of SPEAK_RATES) rateSel.add(new Option(`×${r}`, String(r), false, r === rate));
      const voiceSel = document.createElement("select");
      const x = lang.slice(0, 2);
      const cvoiceKey = x === speechLang().slice(0, 2) ? SPEAK_CVOICE_KEY : `${SPEAK_CVOICE_KEY}-${x}`;
      const cvoiceSel = document.createElement("select");
      const fillCloud = () => {
        cvoiceSel.innerHTML = "";
        const cur = cloudVoiceFor(lang);
        for (const v of (cloudVoices || []).filter((v) => v.lang === CLOUD_LANG[x])) {
          cvoiceSel.add(new Option(`${v.name.replace(/^[a-z]+-[A-Z]+-/, "")} (${v.gender === "FEMALE" ? "♀" : v.gender === "MALE" ? "♂" : "-"})`, v.name, false, v.name === cur));
        }
      };
      cvoiceSel.addEventListener("change", () => { try { localStorage.setItem(cvoiceKey, cvoiceSel.value); } catch (e) {} });
      const fillVoices = () => {
        const cur = speakPref(voiceKey);
        voiceSel.innerHTML = "";
        voiceSel.add(new Option(t("common.default"), ""));
        for (const v of speechVoices(lang)) {
          voiceSel.add(new Option(v.name + (v.localService ? "" : t("speak.online")), v.voiceURI, false, v.voiceURI === cur));
        }
      };
      fillVoices();
      // Chrome fills getVoices() asynchronously; the first call can be empty.
      speechSynthesis.addEventListener("voiceschanged", fillVoices, { once: true });
      const save = () => {
        try {
          localStorage.setItem(rateKey, rateSel.value);
          localStorage.setItem(voiceKey, voiceSel.value);
        } catch (e) {}
      };
      rateSel.addEventListener("change", save);
      voiceSel.addEventListener("change", save);
      return { lang, rateSel, voiceSel, cvoiceSel, fillCloud };
    });
    const SAMPLE = { ja: "この速さと声で読み上げます。", en: "This is how English replies will be read." };
    const tryBtn = document.createElement("button");
    tryBtn.textContent = t("speak.try");
    tryBtn.addEventListener("click", () => {
      cancelSpeech();
      cloudOffUntil = 0;
      const o = otherSpeechLang().slice(0, 2);
      speakQueue = [{ el: null, chunks: [t("speak.how_replies_read"), ...(SAMPLE[o] ? [SAMPLE[o]] : [])] }];
      speakPos = 0;
      speakPump();
    });
    const row = (label, el) => {
      const l = document.createElement("label");
      l.append(label, el);
      return l;
    };
    const LANG_NAME = { ja: "speak.japanese", en: "speak.english", zh: "speak.chinese" };
    const engineSel = document.createElement("select");
    engineSel.add(new Option(t("speak.device_voice"), ""));
    engineSel.add(new Option(t("speak.google_voice_via_server"), "cloud"));
    engineSel.value = speakPref(SPEAK_ENGINE_KEY) === "cloud" ? "cloud" : "";
    const note = document.createElement("div");
    note.className = "speak-pop-note";
    pop.append(row(t("common.read_aloud"), engineSel), note);
    const voiceRows = [];
    for (const { lang, rateSel, voiceSel, cvoiceSel } of sels) {
      const head = document.createElement("div");
      head.className = "speak-pop-lang";
      head.textContent = t(LANG_NAME[lang.slice(0, 2)] || lang);
      const dv = row(t("common.voice"), voiceSel);
      const cv = row(t("common.voice"), cvoiceSel);
      voiceRows.push([dv, cv]);
      pop.append(head, row(t("speak.speed"), rateSel), dv, cv);
    }
    // Output speaker: only Google's voices can be sent to one (an <audio>);
    // names need the microphone permission in Chrome, asked on demand.
    const sinkSel = document.createElement("select");
    const sinkRow = row(t("speak.output"), sinkSel);
    const fillSinks = async (ask) => {
      try {
        if (ask) (await navigator.mediaDevices.getUserMedia({ audio: true })).getTracks().forEach((tr) => tr.stop());
        const outs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audiooutput");
        const cur = speakPref(SPEAK_SINK_KEY);
        sinkSel.innerHTML = "";
        sinkSel.add(new Option(t("common.default"), ""));
        outs.forEach((d, i) => { if (d.deviceId && d.deviceId !== "default") sinkSel.add(new Option(d.label || `${t("speak.speaker")} ${i + 1}`, d.deviceId, false, d.deviceId === cur)); });
        if (!ask && outs.some((d) => !d.label)) sinkSel.add(new Option(t("speak.show_names"), "?ask"));
      } catch (e) {}
    };
    sinkSel.addEventListener("change", () => {
      if (sinkSel.value === "?ask") return fillSinks(true);
      try { localStorage.setItem(SPEAK_SINK_KEY, sinkSel.value); } catch (e) {}
      applySink();
    });
    if (canSink && navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) { pop.append(sinkRow); fillSinks(false); }
    const showEngine = () => {
      const cloud = engineSel.value === "cloud";
      for (const [dv, cv] of voiceRows) { dv.hidden = cloud; cv.hidden = !cloud; }
      sinkRow.hidden = !cloud;
      note.textContent = !cloud ? "" : cloudVoices ? (canSink ? "" : t("speak.on_device_pick_output_in"))
        : t("speak.loading_google_voices");
    };
    engineSel.addEventListener("change", () => {
      try { localStorage.setItem(SPEAK_ENGINE_KEY, engineSel.value); } catch (e) {}
      cloudOffUntil = 0;
      showEngine();
    });
    showEngine();
    loadCloudVoices().then(() => { for (const x of sels) x.fillCloud(); showEngine(); })
      .catch(() => { if (engineSel.value === "cloud") note.textContent = t("speak.google_voices_unavailable_device_voice"); });
    pop.append(tryBtn);
  }
  // 設定's card: built when 設定 is shown (the voices may have come meanwhile).
  const speakSettingsEl = document.getElementById("speak-settings");
  ui.subscribe((st, prev) => { if (st.page === "auth" && prev.page !== "auth") buildSpeakSettings(speakSettingsEl); });
  function setSpeakOn(on) {
    speakOn = on;
    try { localStorage.setItem(SPEAK_KEY, speakOn ? "1" : "0"); } catch (e) {}
    stopSpeaking();
    keepAlive(speakOn || speakBg);
    if (speakOn) speak(t("speak.read_aloud_on"));
    updateSpeakBtn();
  }
  // Read out the other sessions too (the deployment notes, 2026-11-23, the user:
  // 読み上げをセッション単位でなく裏のも含めて全てに。裏の読み上げは経過は
  // 含めず、短くセッション名をつけたあと、メッセージの要約だけ。通知的な位置
  // づけ。一覧から裏も読むかどうか選べると良い; then: マイクのボタンを押したときに
  // ポップアップが出て設定できるのが良い). A switch of its own in 🎙's menu,
  // kept per browser like 🔊: when one of one's own sessions other than
  // the one being read out on screen ends a turn (its state on the list
  // changes to one nobody has seen yet), its name and a one-sentence summary
  // of its last reply (the voice mode's model, POST /voice/summary brief) are
  // read after whatever the chat is reading. The list is fetched every 20 s
  // for this while it is on.
  const SPEAK_BG_KEY = "aiza-speak-bg";
  let speakBg = false;
  try { speakBg = canSpeak && localStorage.getItem(SPEAK_BG_KEY) === "1"; } catch (e) {}
  const bgLast = new Map(); // session id -> "state:ts" last seen on the list
  let bgPrimed = false;
  function setSpeakBg(on) {
    speakBg = on;
    try { localStorage.setItem(SPEAK_BG_KEY, on ? "1" : "0"); } catch (e) {}
    if (!on) bgQueue = [];
    keepAlive(speakOn || speakBg);
    updateSpeakBgBtn();
    if (on) speakNotice(t("speak.other_sessions_replies_read_out"));
  }
  function speakNotice(text) {
    const chunks = speechChunks(speechText(text));
    if (!chunks.length) return;
    bgQueue.push({ el: null, chunks });
    bgKick();
  }
  function bgCheck(list) {
    for (const s of list) {
      if (s.owner || s.archived) continue;
      const tk = s.task;
      const key = tk ? `${tk.state}:${tk.ts}` : "";
      const was = bgLast.get(s.id);
      bgLast.set(s.id, key);
      if (!bgPrimed || was === undefined || was === key || !speakBg || !tk) continue;
      if (!["you", "done", "snooze"].includes(tk.state) || tk.seen === true || tk.by_hand) continue;
      // The open chat reads its own replies in full when 🔊 is on.
      if (s.id === chatNow.id && speakOn && speakAvailable()) continue;
      bgAnnounce(s, tk);
    }
    bgPrimed = true;
  }
  async function bgAnnounce(s, tk) {
    const name = s.label || s.id;
    let say = "";
    if (!tk.prompt) {
      try {
        const r = await api("/voice/summary", { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: s.id, brief: true }) });
        say = (r && r.say) || "";
      } catch (e) { /* the status line below instead */ }
    }
    // Opened meanwhile and read aloud there: not said twice.
    if (!speakBg || (s.id === chatNow.id && speakOn && speakAvailable())) return;
    speakNotice(`${name}。${say || tk.text || t("speak.replied")}`);
  }
  setInterval(() => {
    if (!speakBg) return;
    // The list refreshes itself every 20 s only while it is on screen.
    const listSelf = !chatNow.id && document.visibilityState === "visible" && pageNow() === "list";
    if (!listSelf && !dragState) refreshSessions({ light: true }).catch(() => null);
  }, 20000);
  if (canSpeak) {
    document.addEventListener("pointerdown", () => {
      const u = new SpeechSynthesisUtterance(" ");
      u.volume = 0;
      speechSynthesis.speak(u);
      keepAlive(speakOn || speakBg); // play() also needs a user gesture
    }, { once: true, capture: true });
  }
  // Keep reading on a locked/backgrounded Android screen (2026-10-26, at the
  // user's suggestion): Chrome there freezes a page that is not playing
  // media, which also stops speechSynthesis. So while 🔊 is on, loop a clip
  // made in the page (no network): 10 s, since a shorter one does not count
  // as media playback, of a 25 Hz tone at about -60 dBFS -- not heard, but
  // above the level Chrome treats as silence. Whether this holds is up to
  // Chrome. On a PC too (2026-11-02, the user: a tab moved to the back
  // stopped reading): Chrome there also freezes a hidden, silent tab (e.g.
  // under Energy Saver), and a tab playing audio is left alone. iPhone/iPad
  // stay as they were (the user: leave the phone as it is).
  const isPhone = /Android|iPhone|iPad|iPod/i.test(navigator.userAgent)
    || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
  const keepAliveWanted = /Android/i.test(navigator.userAgent) || !isPhone;
  // PC: when a hidden tab comes back, restart a reading that stalled while
  // it was in the back (its onend never came), from the piece it was on.
  if (!isPhone && canSpeak) {
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible" || !speakOn || speakPaused || !speakQueue.length) return;
      if (speechSynthesis.speaking || speechSynthesis.pending || !ttsAudio.paused) return;
      speakGen++;
      speakPump();
    });
  }
  let keepAliveEl = null;
  function keepAliveClipUrl() {
    const rate = 8000;
    const n = rate * 10;
    const buf = new ArrayBuffer(44 + n * 2);
    const v = new DataView(buf);
    const str = (o, x) => { for (let i = 0; i < x.length; i++) v.setUint8(o + i, x.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + n * 2, true); str(8, "WAVEfmt ");
    v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, rate, true); v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, n * 2, true);
    for (let i = 0; i < n; i++) v.setInt16(44 + i * 2, Math.round(32 * Math.sin(2 * Math.PI * 25 * i / rate)), true);
    return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
  }
  function keepAlive(on) {
    if (!keepAliveWanted || !canSpeak) return;
    if (!on) {
      if (keepAliveEl) keepAliveEl.pause();
      if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "none";
      return;
    }
    if (!keepAliveEl) {
      keepAliveEl = new Audio(keepAliveClipUrl());
      keepAliveEl.loop = true;
      // Speech can take the audio focus and pause the loop; start it again.
      keepAliveEl.addEventListener("pause", () => {
        if (speakOn || speakBg) setTimeout(() => { if (speakOn || speakBg) keepAliveEl.play().catch(() => {}); }, 1000);
      });
      if ("mediaSession" in navigator) {
        navigator.mediaSession.metadata = new MediaMetadata({ title: t("speak.ai_za_read_aloud") });
        // The lock screen's ⏸ turns read-aloud off, the same as 🔊.
        navigator.mediaSession.setActionHandler("pause", () => { setSpeakOn(false); if (speakBg) setSpeakBg(false); });
        navigator.mediaSession.setActionHandler("play", () => setSpeakOn(true));
      }
    }
    keepAliveEl.play().catch(() => {});
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing";
  }
