// 読み上げ(2026-10-25 ユーザー依頼)。
// 端末の音声(ブラウザの speechSynthesis。Android は Google の音声)で読む。aiza の読み上げで「Google の声(サーバー経由)」を
// 選んでいればそちら(下の sayRun。2026-11-25 ユーザー依頼)。まとめのサーバー側には何も無い。
// 読むのは未決・未読の欄の項目だけ(画面の並び順。成立したばかりの待ちは未決の先頭にある)。待ち・既読・既決・速報は読まない。
// 文は画面からでなく ITEMS から組み立てる: 種類・差出人・件名・要約・対応・締切。時刻・ボタン・URL・メモ・待ちの条件は読まない。
// 読み終えても状態は変えない(既読へは自分で移す)。
const SAY_OK = 'speechSynthesis' in window && typeof SpeechSynthesisUtterance === 'function';
const SAY_SRC = /*DIGEST_SAY_SRC*/{ mail: 'メール' };
let sayGen = 0, sayList = [], sayIdx = -1, sayPaused = false;
// 速さ・声(2026-10-25 ユーザー依頼。Windows の「音声の速度」は一部のブラウザに効かない)。🔊 の長押し(PC は右クリック)で出す。
// aiza のチャットの読み上げと同じオリジンなので、同じ localStorage のキーで設定を共有する(the deployment notes)
const SAY_RATES = [0.75, 1, 1.25, 1.5, 1.75, 2, 2.5];
const sayPref = k => { try { return localStorage.getItem(k) || ''; } catch { return ''; } };
// 言語ごとの速さ・声(2026-11-03 ユーザー依頼)。
// the deployment notes と同じ決め方: かな・漢字を含む文は日本語、含まずに英字があれば英語の声で読む。
// キーは aiza と同じ: aiza の表示言語(aiza-lang)のものが素のキー、もう一方は "-en"/"-ja" 付き(未設定なら素の速さ)。
// localStorage はブラウザごとなので、設定はその機械(ブラウザ)ごと。
const SAY_JA_RE = /[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uff66-\uff9f]/;
const sayLangOf = t => SAY_JA_RE.test(t) ? 'ja-JP' : /[A-Za-z]{2,}/.test(t) ? 'en-US' : 'ja-JP';
const sayPlain = () => { const l = sayPref('aiza-lang'); return l.startsWith('en') ? 'en' : l.startsWith('zh') ? 'zh' : 'ja'; };
const sayKeys = lang => { const x = lang.slice(0, 2); return x === sayPlain() ? ['aiza-speak-rate', 'aiza-speak-voice'] : [`aiza-speak-rate-${x}`, `aiza-speak-voice-${x}`]; };
const sayVoices = lang => speechSynthesis.getVoices().filter(v => v.lang.replace('_', '-').toLowerCase().startsWith(lang.slice(0, 2)));
// 既定の声: Google の声があればそれ(Windows の Microsoft の声より聞きやすい、2026-11-03 ユーザー)、無ければ端末の既定
function sayBest(lang) {
  const vs = sayVoices(lang), exact = vs.filter(v => v.lang.replace('_', '-').toLowerCase() === lang.toLowerCase());
  return exact.find(v => /Google/.test(v.name)) || vs.find(v => /Google/.test(v.name)) || vs.find(v => v.default) || exact[0] || vs[0] || null;
}
function sayUtter(text) {
  const u = new SpeechSynthesisUtterance(text), lang = sayLangOf(text), [rk, vk] = sayKeys(lang);
  u.lang = lang; u.rate = Number(sayPref(rk)) || Number(sayPref('aiza-speak-rate')) || 1;
  const name = sayPref(vk) || sayPref('aiza-speak-voice'), c = name && speechSynthesis.getVoices().find(x => x.voiceURI === name);
  const v = c && c.lang.slice(0, 2).toLowerCase() === lang.slice(0, 2) ? c : sayBest(lang);
  if (v) { u.voice = v; u.lang = v.lang; }
  return u;
}
// Google の声(2026-11-25 ユーザー依頼「新着リストも対応して」。the deployment notes と同じ仕組み・同じキー):
// aiza の 🔊 の長押しで「Google の声(サーバー経由)」を選んでいると(aiza-speak-engine = cloud)、文ごとに
// /agents/tts(同じオリジンのゲートウェイ。鍵はそちら、ページと同じログインで通る)から MP3 をもらって <audio> で鳴らす。
// 声は aiza-speak-cvoice[-xx]、出力先(PC のブラウザ)は aiza-speak-sink、速さは同じ速さのキーを再生の速さに。
// 失敗した文はもう一度だけ頼み、だめなら端末の声で読む。3回続けて失敗したら1分は Google に頼まない。次の文は鳴らしている間にもらう。
const SAY_CLOUD_LANG = { ja: 'ja-JP', en: 'en-US', zh: 'cmn-CN' };
const sayCanSink = typeof HTMLMediaElement !== 'undefined' && 'setSinkId' in HTMLMediaElement.prototype;
let sayCloud = null, sayCloudAsked = null, sayCloudOff = 0, sayCloudFails = 0, sayCur = null; // sayCur: 一部のブラウザは捨てられた発話の onend を呼ばない
const sayAudio = new Audio(); sayAudio.preservesPitch = true;
const sayMp3 = new Map(); // "声\n文" -> Promise<objectURL>
const sayUseCloud = () => sayPref('aiza-speak-engine') === 'cloud' && Date.now() >= sayCloudOff;
function sayLoadCloud() {
  if (sayCloud) return Promise.resolve(sayCloud);
  if (!sayCloudAsked) sayCloudAsked = fetch('/agents/tts/voices', { credentials: 'same-origin' })
    .then(r => r.ok ? r.json() : Promise.reject(new Error(String(r.status)))).then(j => (sayCloud = j.voices || []))
    .catch(e => { sayCloudAsked = null; throw e; });
  return sayCloudAsked;
}
const sayCvoiceKey = x => x === sayPlain() ? 'aiza-speak-cvoice' : `aiza-speak-cvoice-${x}`;
function sayCloudVoice(lang) {
  const x = lang.slice(0, 2), vs = (sayCloud || []).filter(v => v.lang === SAY_CLOUD_LANG[x]), name = sayPref(sayCvoiceKey(x));
  return (vs.find(v => v.name === name) || vs.find(v => v.kind === 'Wavenet') || vs[0] || {}).name || '';
}
const sayRate = lang => { const [rk] = sayKeys(lang); return Number(sayPref(rk)) || Number(sayPref('aiza-speak-rate')) || 1; };
function sayMp3Url(voice, text) {
  const k = voice + '\n' + text;
  if (!sayMp3.has(k)) {
    const p = fetch('/agents/tts', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ voice, text }) })
      .then(r => r.ok ? r.blob() : Promise.reject(new Error(String(r.status)))).then(b => URL.createObjectURL(b));
    p.catch(() => sayMp3.delete(k)); sayMp3.set(k, p);
    if (sayMp3.size > 40) { const [old, op] = sayMp3.entries().next().value; sayMp3.delete(old); op.then(u => URL.revokeObjectURL(u), () => {}); }
  }
  return sayMp3.get(k);
}
function saySink() { const id = sayPref('aiza-speak-sink'); if (sayCanSink && sayAudio.sinkId !== id) sayAudio.setSinkId(id).catch(() => {}); }
function sayCloudFailed() { if (++sayCloudFails >= 3) { sayCloudFails = 0; sayCloudOff = Date.now() + 60000; } }
// 鳴っているものを止める(端末の声も <audio> も)
function sayHush() { sayCur = null; if (SAY_OK) speechSynthesis.cancel(); sayAudio.onended = sayAudio.onerror = null; sayAudio.pause(); }
// 文の並び cs を1つずつ読み、読み終えたら done()。g は呼んだ側の世代(sayGen)で、変わったら(止め・一時停止・別の項目)黙ってやめる
function sayRun(cs, g, done) {
  let j = 0;
  const step = () => {
    if (g !== sayGen) return;
    if (j >= cs.length) { if (done) done(); return; }
    const text = cs[j++];
    let went = false; const next = () => { if (!went && g === sayGen) { went = true; step(); } };
    const device = () => { if (g !== sayGen) return; const u = sayUtter(text); u.onend = u.onerror = next; sayCur = u; speechSynthesis.speak(u); };
    if (!sayUseCloud()) return device();
    sayLoadCloud().then(() => {
      const lang = sayLangOf(text), voice = sayCloudVoice(lang);
      if (!voice) return device();
      if (j < cs.length) { const v2 = sayCloudVoice(sayLangOf(cs[j])); if (v2) sayMp3Url(v2, cs[j]).catch(() => {}); }
      const get = () => sayMp3Url(voice, text).catch(() => new Promise(ok => setTimeout(ok, 700)).then(() => sayMp3Url(voice, text)));
      return get().then(url => {
        if (g !== sayGen) return;
        sayCloudFails = 0; saySink();
        sayAudio.onended = next;
        sayAudio.onerror = () => { sayAudio.onended = sayAudio.onerror = null; sayCloudFailed(); device(); };
        sayAudio.src = url; sayAudio.playbackRate = sayRate(lang);
        return sayAudio.play();
      });
    }).catch(() => { if (g !== sayGen) return; sayCloudFailed(); device(); });
  };
  step();
}
function sayPopup(btn) {
  document.querySelectorAll('.saypop').forEach(x => x.remove());
  const pop = document.createElement('div'); pop.className = 'saypop';
  const row = (label, el) => { const l = document.createElement('label'); l.append(label + ' ', el); return l; };
  // 端末の声か Google の声か(aiza の 🔊 の長押しと同じ設定。こちらで変えれば aiza も変わる)
  const eng = document.createElement('select');
  eng.add(new Option(L('mail.device_voice'), '')); eng.add(new Option(L('mail.google_voice_via_server'), 'cloud'));
  eng.value = sayPref('aiza-speak-engine') === 'cloud' ? 'cloud' : '';
  const note = document.createElement('div'); note.className = 'sn';
  pop.append(row(L('mail.read_aloud'), eng), note);
  const pairs = [], fills = [];
  for (const [lang, head] of [['ja-JP', L('mail.japanese')], ['en-US', L('mail.english')]]) {
    const [rk, vk] = sayKeys(lang), rate = sayRate(lang), cur = sayPref(vk), x = lang.slice(0, 2);
    const g = document.createElement('div');
    g.innerHTML = `<div class="sl">${head}</div><label>${L('mail.speed')} <select class="r"></select></label><label class="dv">${L('mail.voice')} <select class="v"></select></label><label class="cv">${L('mail.voice')} <select class="c"></select></label>`;
    g.style.cssText = 'display:flex;flex-direction:column;gap:6px';
    const rs = g.querySelector('.r'), vs = g.querySelector('.v'), cs = g.querySelector('.c');
    for (const r of SAY_RATES) rs.add(new Option('×' + r, String(r), false, r === rate));
    const fill = () => { vs.innerHTML = ''; vs.add(new Option(L('mail.default'), ''));
      for (const v of sayVoices(lang)) vs.add(new Option(v.name + (v.localService ? '' : L('mail.online')), v.voiceURI, false, v.voiceURI === cur)); };
    fill(); speechSynthesis.addEventListener('voiceschanged', fill, { once: true }); // 一部のブラウザは声の一覧をあとから埋める
    fills.push(() => { const now = sayCloudVoice(lang); cs.innerHTML = '';
      for (const v of (sayCloud || []).filter(v => v.lang === SAY_CLOUD_LANG[x]))
        cs.add(new Option(`${v.name.replace(/^[a-z]+-[A-Z]+-/, '')} (${v.gender === 'FEMALE' ? '♀' : v.gender === 'MALE' ? '♂' : '-'})`, v.name, false, v.name === now)); });
    const save = () => { try { localStorage.setItem(rk, rs.value); localStorage.setItem(vk, vs.value); } catch {} };
    rs.onchange = vs.onchange = save;
    cs.onchange = () => { try { localStorage.setItem(sayCvoiceKey(x), cs.value); } catch {} };
    pairs.push([g.querySelector('.dv'), g.querySelector('.cv')]);
    pop.appendChild(g);
  }
  // 出力先: Google の声(<audio>)だけ選べる。名前はブラウザによってはマイクの許可が要るので、選んだときに聞く
  const sink = document.createElement('select'), sinkRow = row(L('mail.output'), sink);
  const fillSinks = async ask => {
    try {
      if (ask) (await navigator.mediaDevices.getUserMedia({ audio: true })).getTracks().forEach(t => t.stop());
      const outs = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === 'audiooutput'), cur = sayPref('aiza-speak-sink');
      sink.innerHTML = ''; sink.add(new Option(L('mail.default'), ''));
      outs.forEach((d, i) => { if (d.deviceId && d.deviceId !== 'default') sink.add(new Option(d.label || `${L('mail.speaker')} ${i + 1}`, d.deviceId, false, d.deviceId === cur)); });
      if (!ask && outs.some(d => !d.label)) sink.add(new Option(L('mail.show_names'), '?ask'));
    } catch {}
  };
  sink.onchange = () => { if (sink.value === '?ask') return fillSinks(true); try { localStorage.setItem('aiza-speak-sink', sink.value); } catch {} saySink(); };
  if (sayCanSink && navigator.mediaDevices && navigator.mediaDevices.enumerateDevices) { pop.append(sinkRow); fillSinks(false); }
  const show = () => {
    const cloud = eng.value === 'cloud';
    for (const [dv, cv] of pairs) { dv.hidden = cloud; cv.hidden = !cloud; }
    sinkRow.hidden = !cloud;
    note.textContent = !cloud ? '' : sayCloud ? (sayCanSink ? '' : L('mail.on_device_pick_output_in')) : L('mail.loading_google_voices');
  };
  eng.onchange = () => { try { localStorage.setItem('aiza-speak-engine', eng.value); } catch {} sayCloudOff = 0; show(); };
  show();
  sayLoadCloud().then(() => { fills.forEach(f => f()); show(); })
    .catch(() => { if (eng.value === 'cloud') note.textContent = L('mail.google_voices_unavailable_device_voice'); });
  const b = document.createElement('button'); b.textContent = L('mail.try'); pop.appendChild(b);
  b.onclick = () => { sayStop(); sayCloudOff = 0; sayRun(['この速さと声で読み上げます。', 'This is how English will be read.'], ++sayGen); };
  document.body.appendChild(pop);
  const r = btn.getBoundingClientRect();
  pop.style.top = Math.min(r.bottom + 6, innerHeight - pop.offsetHeight - 8) + 'px'; pop.style.left = Math.max(8, Math.min(r.left, innerWidth - pop.offsetWidth - 8)) + 'px';
  setTimeout(() => { const close = e => { if (pop.contains(e.target)) return; pop.remove(); document.removeEventListener('pointerdown', close, true); };
    document.addEventListener('pointerdown', close, true); }, 0);
}
// 長押し: 500ms で開き、その押下の終わりのクリック(onclick の読み上げ)は捕捉段階で止める
let sayPressT = null, sayLong = false;
const sayBtnOf = e => e.target.closest && e.target.closest('#sp');
document.addEventListener('pointerdown', e => { const b = sayBtnOf(e); if (!b) return; sayLong = false; clearTimeout(sayPressT); sayPressT = setTimeout(() => { sayLong = true; sayPopup(b); }, 500); });
for (const ty of ['pointerup', 'pointercancel']) document.addEventListener(ty, () => clearTimeout(sayPressT));
document.addEventListener('pointerout', e => { if (sayBtnOf(e)) clearTimeout(sayPressT); });
document.addEventListener('contextmenu', e => { const b = sayBtnOf(e); if (!b) return; e.preventDefault(); clearTimeout(sayPressT); if (!sayLong) sayPopup(b); sayLong = true; });
document.addEventListener('click', e => { if (sayLong && sayBtnOf(e)) { sayLong = false; e.stopPropagation(); e.preventDefault(); } }, true);
const sayClean = t => String(t || '').replace(/\[([^\]\n]+)\]\((?:mail:[0-9a-f]+|https?:\/\/[^\s)]+)(?:\s+(?:mail:[0-9a-f]+|https?:\/\/[^\s)]+))*\)/g, '$1').replace(/https?:\/\/\S+/g, 'mail.link').replace(/[*_`#>|]+/g, ' ').replace(/\s+/g, ' ').trim();
const sayDate = t => t.replace(/(\d{1,2})\/(\d{1,2})/, (m, a, b) => `${a}月${b}日`);
function sayText(el) {
  const i = ITEMS[el.dataset.id]; if (!i) return '';
  const due = el.querySelector('.due'), fired = i.wait && i.wait.fired && !i.wait.told;
  return [fired ? '待ちが成立しました。' + sayClean(i.wait.why) : '',
    `${SAY_SRC[i.source] || i.source}、${sayClean(i.from)}から。`, sayClean(i.title) + '。', sayClean(i.summary),
    i.action ? '対応: ' + sayClean(i.action) : '', due ? sayDate((due.dataset.say || due.textContent).trim()) : ''].filter(Boolean).join('\n');
}
// 長い発話は一部のブラウザで途中で止まる(パソコン約15秒、Android 約4000字)ので、文ごと・200字までに切って続けて出す
function sayChunks(t) {
  const out = [];
  for (let p of t.split(/(?<=[。！？!?\n])/)) { p = p.trim(); while (p.length > 200) { out.push(p.slice(0, 200)); p = p.slice(200); } if (p) out.push(p); }
  return out;
}
function sayMark(el) { document.querySelectorAll('.it.saying').forEach(x => x.classList.remove('saying')); if (el) { el.classList.add('saying'); el.scrollIntoView({ block: 'center', behavior: 'smooth' }); } }
function sayUi() {
  const on = sayIdx >= 0;
  document.getElementById('sp').style.display = on ? 'none' : '';
  document.getElementById('spn').style.display = document.getElementById('sps').style.display = on ? '' : 'none';
  document.getElementById('spi').textContent = (on && sayList.length > 1 ? `${sayIdx + 1}/${sayList.length}` : '') + (sayPaused ? L('mail.paused_tap_item_go_on') : '');
}
function sayStop() { sayGen++; sayIdx = -1; sayPaused = false; sayHush(); sayMark(null); sayUi(); }
// 1件を文ごとに読み(sayRun)、読み終えたら次へ。cancel() は待っていた発話の onend も呼ぶので、世代(sayGen)で古い続きを捨てる
function sayAt(k, from = 0) {
  const g = ++sayGen; sayHush(); sayPaused = false;
  while (k < sayList.length && !sayList[k].isConnected) k++; // 読んでいる間に既読などへ移したもの
  if (k >= sayList.length) { sayIdx = -1; sayMark(null); sayUi(); return; }
  sayIdx = k; sayMark(sayList[k]); sayUi();
  sayRun(sayChunks(sayText(sayList[k])).slice(from), g, () => setTimeout(() => { if (g === sayGen) sayAt(k + 1); }, 400));
}
function sayAll() {
  sayList = [...document.querySelectorAll('#g-未決 .rows>.it, #g-未読 .rows>.it')];
  if (!sayList.length) { sayStop(); sayRun(['未決と未読はありません'], ++sayGen); return; }
  sayAt(0);
}
// 項目 el の from 番目の文から読む。未決・未読の項目ならそのまま下へ続け、ほかの欄の項目はその1件だけ
function sayFrom(el, from = 0) {
  const all = [...document.querySelectorAll('#g-未決 .rows>.it, #g-未読 .rows>.it')], k = all.indexOf(el);
  sayList = k < 0 ? [el] : all;
  sayAt(Math.max(k, 0), from);
}
if (SAY_OK) document.getElementById('spbar').style.display = '';
// 項目をタップすると、その項目のタップした文から読み始める(2026-11-27 利用者: 各行の 🔊 は不要、タップしたところから
// 読み始めれば良い。読んでいないときも)。読み上げ中のタップは一時停止、次のタップでそこから続き(2026-10-26 ユーザー依頼)。
// 一時停止は cancel()(Android の一部のブラウザは pause() を止めとして扱う)。ボタン・リンク・入力欄・文字の選択・保留の項目は除く
const sayKey = s => s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
function sayTapped(el, cs, x, y) { // 画面の文字のタップ位置を、各文の頭の文字が画面のどこにあるかと照らして文の番号にする
  let node = null, off = 0;
  if (document.caretPositionFromPoint) { const p = document.caretPositionFromPoint(x, y); if (p) { node = p.offsetNode; off = p.offset; } }
  else if (document.caretRangeFromPoint) { const r = document.caretRangeFromPoint(x, y); if (r) { node = r.startContainer; off = r.startOffset; } }
  if (!node || !el.contains(node)) return 0;
  const r = document.createRange(); r.setStart(el, 0); r.setEnd(node, off);
  const at = sayKey(r.toString()).length, shown = sayKey(el.textContent);
  let from = 0, best = 0;
  cs.forEach((c, i) => { const k = sayKey(c).slice(0, 8), p = k ? shown.indexOf(k, from) : -1; if (p < 0) return; from = p + 1; if (p <= at) best = i; });
  return best;
}
document.addEventListener('click', e => {
  if (!SAY_OK) return;
  const el = e.target.closest && e.target.closest('.it[data-id]:not(.held)');
  if (!el || e.target.closest('a, button, input, textarea, select, summary, label')) return;
  if (String(getSelection() || '').trim()) return;
  if (sayIdx >= 0 && !sayPaused) { sayGen++; sayHush(); sayPaused = true; sayUi(); return; }
  const from = sayTapped(el, sayChunks(sayText(el)), e.clientX, e.clientY), k = sayList.indexOf(el);
  if (sayIdx >= 0 && k >= 0) sayAt(k, from); else sayFrom(el, from);
});
