// まとめページから aiza の Email(既定 mail-tui)セッションを起動・再開する。preset・cwd・group は設定の session(server.mjs が埋める)。
// ページは aiza と同じオリジンなので、本人の aiza クッキーで /agents/api を直接叩ける。
// mail-tui は host 階層の解錠(パスキー)が要るので、aiza の app.js と同じ手順で解錠してから再試行する。
const SESSION = /*DIGEST_SESSION*/{ preset: 'mail-tui', cwd: 'digest', group: 'digest' };
const BASE = location.pathname.replace(/\/?$/, '/');
// このページの問い・知らせ(aiza の ui.confirm・ui.toast と同じ形と見た目。the deployment notes、2026-11-27 利用者「新着にまだブラウザダイアログがありました」)。
// ブラウザの confirm・alert は使わない。popConfirm は約束(はい=true)、危ないものは赤いボタン。popToast は下に数秒、失敗は赤く8秒、押すと全文。
function popStyle() {
  if (document.getElementById('pop-style')) return;
  const st = document.createElement('style'); st.id = 'pop-style';
  st.textContent = ':root{--panel:#131a22;--panel-2:#1c2531;--border:#2a3542;--border-strong:#34465d;--text:#e6e6e6;--text-strong:#d7dde5;--accent:#4285f4;--danger:#c0392b;--backdrop:#0008}'
    + '.aiza-pop{position:fixed;inset:0;background:var(--backdrop);z-index:80;display:flex;align-items:flex-start;justify-content:center;padding:16px}'
    + '.aiza-pop .box{background:var(--panel);color:var(--text);border:1px solid var(--border);border-radius:12px;padding:.8rem;width:min(560px,100%);margin-top:8vh}'
    + '.aiza-pop .pop-text{white-space:pre-wrap;margin:.3rem 0 .6rem;line-height:1.5}.aiza-pop .pop-actions{display:flex;justify-content:flex-end;gap:.5rem;margin-top:.7rem}'
    + '.aiza-pop .pop-actions button{min-height:44px;padding:0 1.2rem;border-radius:8px;cursor:pointer;font-weight:700;font-size:1em}'
    + '.aiza-pop .pop-cancel{border:1px solid var(--border);background:var(--panel-2);color:var(--text)}.aiza-pop .pop-ok{border:none;background:var(--accent);color:var(--text-strong)}'
    + '.aiza-pop .pop-danger{border:none;background:var(--danger);color:var(--text-strong)}'
    + '.aiza-toasts{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:90;display:flex;flex-direction:column;gap:.4rem;width:min(520px,calc(100vw - 32px));pointer-events:none}'
    + '.aiza-toast{pointer-events:auto;padding:.6rem .9rem;border-radius:10px;border:1px solid var(--border-strong);background:var(--panel-2);color:var(--text);font-size:.9em;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}'
    + '.aiza-toast.open{white-space:pre-wrap}.aiza-toast.error{border-color:var(--danger);background:var(--panel)}';
  document.head.appendChild(st);
}
function popConfirm(text, o = {}) {
  popStyle();
  return new Promise(resolve => {
    const el = document.createElement('div'); el.className = 'aiza-pop aiza-pop-confirm';
    el.innerHTML = '<div class="box" role="dialog" aria-modal="true"><p class="pop-text"></p><div class="pop-actions"><button type="button" class="pop-cancel"></button><button type="button"></button></div></div>';
    el.querySelector('.pop-text').textContent = text;
    const [no, ok] = el.querySelectorAll('button');
    no.textContent = L('mail.cancel'); ok.textContent = o.ok || 'OK'; ok.className = o.danger ? 'pop-danger' : 'pop-ok';
    const done = v => { el.remove(); document.removeEventListener('keydown', key, true); resolve(v); };
    const key = e => { if (e.key === 'Escape') { e.preventDefault(); done(false); } };
    no.onclick = () => done(false); ok.onclick = () => done(true); el.onclick = e => { if (e.target === el) done(false); };
    document.addEventListener('keydown', key, true);
    document.body.appendChild(el); setTimeout(() => ok.focus(), 0);
  });
}
function popToast(text, error) {
  popStyle();
  let box = document.querySelector('.aiza-toasts');
  if (!box) { box = document.createElement('div'); box.className = 'aiza-toasts'; document.body.appendChild(box); }
  const el = document.createElement('div'); el.className = 'aiza-toast' + (error ? ' error' : ''); el.setAttribute('role', error ? 'alert' : 'status');
  el.textContent = String(text);
  let t = setTimeout(() => el.remove(), error ? 8000 : 4000);
  el.onclick = () => { if (el.classList.toggle('open')) clearTimeout(t); else t = setTimeout(() => el.remove(), 2000); };
  box.appendChild(el);
  return el;
}
function api(path, opts) {
  return fetch('/agents/api' + path, opts).then(async r => {
    if (!r.ok) { const b = await r.json().catch(() => null); const e = new Error(b && b.error ? b.error : String(r.status));
      if (b && b.unlock_required) { e.unlockRequired = true; e.unlockTier = b.tier; } if (b && b.running_session) e.runningSession = b.running_session; throw e; }
    return r.json();
  });
}
const post = (path, body) => api(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const b2buf = s => { const r = atob((s + '='.repeat((4 - s.length % 4) % 4)).replace(/-/g, '+').replace(/_/g, '/')); const u = new Uint8Array(r.length); for (let i = 0; i < r.length; i++) u[i] = r.charCodeAt(i); return u.buffer; };
const buf2b = b => { let s = ''; for (const x of new Uint8Array(b)) s += String.fromCharCode(x); return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, ''); };
async function unlock(tier) {
  const begin = await post('/unlock/begin-assertion', { tier: tier === 'host' ? 'host' : 'root' });
  if (!begin.ok) throw new Error(begin.error || L('mail.could_not_start_authentication'));
  const o = begin.options.publicKey || begin.options;
  const cred = await navigator.credentials.get({ publicKey: { ...o, challenge: b2buf(o.challenge), allowCredentials: (o.allowCredentials || []).map(c => ({ ...c, id: b2buf(c.id) })) } });
  const r = cred.response;
  const json = typeof cred.toJSON === 'function' ? cred.toJSON() : { id: cred.id, rawId: buf2b(cred.rawId), type: cred.type,
    response: { clientDataJSON: buf2b(r.clientDataJSON), authenticatorData: buf2b(r.authenticatorData), signature: buf2b(r.signature), userHandle: r.userHandle ? buf2b(r.userHandle) : undefined },
    clientExtensionResults: cred.getClientExtensionResults ? cred.getClientExtensionResults() : {} };
  const fin = await post('/unlock/finish-assertion', { credential: json });
  if (!fin.ok) throw new Error(fin.error || L('mail.authentication_failed'));
}
async function withUnlock(fn) { try { return await fn(); } catch (e) { if (!e.unlockRequired) throw e; await unlock(e.unlockTier); return await fn(); } }
const sleep = ms => new Promise(r => setTimeout(r, ms));
// 1通目は短く。読み方・守ること・片付け方は ~/digest/CLAUDE.md(作業フォルダが digest なので Claude Code が自動で読む)に置いた(2026-10-11)
const context = it => `新着まとめの項目 ${it.id}「${it.title}」に対応したいです。`;
// 続きから・開いたときに、前回から項目が変わっていれば(新しい返信など)知らせる。seen は前回伝えた時点の時刻と要約
const sig = it => { let h = 0; for (const c of `${it.summary || ''}|${it.action || ''}`) h = (h * 31 + c.charCodeAt(0)) | 0; return `${it.time || ''}|${(h >>> 0).toString(36)}`; };
const updateNote = it => `この項目(${it.id})は前回から更新されています(最新 ${it.time || '?'} ${it.from || ''})。node ~/digest/item.mjs ${it.id} と元のメッセージを読み直して、新しい返信などで変わった点と対応案を教えてください。`;
// 待ち(wait.mjs)が成立していれば、その知らせと頼まれていたことを送る(2026-10-23)。送ったら told を付ける
const waitNote = it => it.wait && it.wait.fired && !it.wait.told ? `待っていた条件が成立しました(${it.wait.why})。頼まれていたこと: ${it.wait.task}\nnode ~/digest/item.mjs ${it.id} と関係するメールなどを読んで、進めてください。` : '';
const toldWait = id => fetch(BASE + 'wait-told', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id }) }).then(() => { ITEMS[id].wait.told = true; });
async function waitPrompt(sid, btn) {
  // Claude Code の入力欄が出るまで待つ(最大90秒)
  btn.textContent = L('mail.waiting_claude');
  for (let i = 0; i < 90; i++) {
    await sleep(1000);
    const sc = await api(`/sessions/${sid}/screen`).catch(() => null);
    if (sc && /for shortcuts|bypass permissions|❯/.test(sc.text || '')) { await sleep(1500); return; }
  }
}
async function saveSession(id, session) {
  const r = await fetch(BASE + 'session', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id, session }) });
  if (!r.ok) throw new Error(L('mail.could_not_save_in_digest', { x: r.status }));
}
async function claude(id, btn) {
  const it = ITEMS[id]; let label0 = btn.textContent; btn.disabled = true;
  try {
    let resume = '';
    if (it.session) {
      // 既にあるセッションがまだ生きていればそれを開くだけ
      btn.textContent = L('mail.checking');
      const { sessions } = await api('/sessions');
      const m = sessions.find(s => s.id === it.session.id);
      if (m && m.alive !== false && !it.session.deleted) {
        const wn = waitNote(it);
        if (wn || it.session.seen !== sig(it)) {
          await withUnlock(() => post(`/sessions/${m.id}/messages`, { text: wn || updateNote(it), submit: true }));
          await saveSession(id, { ...it.session, seen: sig(it) });
          if (wn) await toldWait(id);
        }
        location.href = '/agents/#' + m.id; return;
      }
      // 終わっていたら同じ会話を「続きから」で起動し直す
      resume = (m && m.claude_session_id) || it.session.claude_session_id || '';
      if (!resume && !await popConfirm(L('mail.earlier_session_ended_conversation'))) return;
    }
    btn.textContent = L('mail.starting_2');
    const label = ('digest: ' + it.title).slice(0, 40);
    // group: digest で aiza の「📨 Digest」の欄に入る。アーカイブした前のセッションから続けるときは replace_session で履歴を引き継ぐ
    const old = it.session && it.session.archived ? it.session.id : '';
    // 1通目(新規なら項目の内容、続きからなら変わっていたときの知らせ)は aiza が Claude の起動を待って送る(2026-11-05)。
    // 前はこのページが待って送っていたので、待っている間に別のセッションを開くと届かなかった
    const wn = waitNote(it);
    const firstText = r => !r ? [context(it), wn].filter(Boolean).join('\n') : (wn || (it.session && it.session.seen === sig(it) ? '' : updateNote(it)));
    const start = r => withUnlock(() => post('/sessions', { preset: SESSION.preset, label, cwd: SESSION.cwd, resume: r, cols: 100, rows: 40, group: SESSION.group, ...(r && old ? { replace_session: old } : {}), ...(firstText(r) ? { initial_message: firstText(r) } : {}) }));
    let meta;
    try { meta = await start(resume); }
    catch (e) {
      // この会話はもう別のセッションで動いている(aiza が二重の起動を断る。2026-11-04): そちらを使う
      if (e.runningSession) { meta = { id: e.runningSession, claude_session_id: resume, reused: true }; }
      else {
      // 会話ログが見つからないなどで続きから始められないときは、新しく始めるか聞く(2026-10-11)
      if (!resume || !await popConfirm(L('mail.could_not_continue_earlier_conversation', { x: e.message }))) throw e;
      resume = ''; meta = await start('');
      }
    }
    await saveSession(id, { id: meta.id, claude_session_id: meta.claude_session_id || resume || '', created: new Date().toISOString(), seen: sig(it) });
    // 新規なら1通目を、続きからなら前回から変わっていたときだけ更新の知らせを送る
    // 待ちが成立していれば、更新の知らせの代わりにその知らせを送る(新規なら1通目に足す)
    // 動いていた別のセッションを使うとき(409)は、1通目はここから送る
    const text = firstText(resume);
    if (text && meta.reused) { await waitPrompt(meta.id, btn); await withUnlock(() => post(`/sessions/${meta.id}/messages`, { text, submit: true })); }
    if (text && wn) await toldWait(id);
    // 起動したら画面は移らず、ボタンを「AIを開く」に変えるだけ(急に切り替わると割り込みになる。2026-10-30 ユーザー依頼)。開くのはもう一度押したとき
    it.session = { id: meta.id, claude_session_id: meta.claude_session_id || resume || '', seen: sig(it) }; label0 = L('mail.open_ai');
  } catch (e) { popToast(L('mail.could_not_prepare_claude_session', { x: e.message }), true); }
  finally { btn.disabled = false; btn.textContent = label0; }
}

// ページで既決にした項目に生きている Claude セッションがあれば、止めずに「作業を終えたら既決にしてよいか決めて」と伝える(2026-11-07 ユーザー依頼)。
// Claude が set-status で既決にすれば今までどおり片付けて止まりアーカイブ、未決に戻せば項目は未決の欄に戻る
const liveSession = async it => { if (!it.session || it.session.deleted) return null;
  const { sessions } = await api('/sessions');
  return sessions.find(s => s.alive !== false && !s.archived && (s.id === it.session.id || (it.session.claude_session_id && s.claude_session_id === it.session.claude_session_id))) || null; };
const doneAskText = id => `ユーザーがまとめページでこの項目(${id})を既決にしました。今している作業があれば、そのまま最後まで続けてください。終わったら既決にしてよいか判断し、よければ CLAUDE.md の 5 のとおり set-status で既決にして片付けてください。まだ対応やユーザーの判断が要るなら node ~/digest/set-status.mjs ${id} 未決 "<理由>" で未決に戻し、理由を伝えてください(ページの未決の欄に戻ります)。`;
async function askDone(id, sid) { await withUnlock(() => post(`/sessions/${sid}/messages`, { text: doneAskText(id), submit: true })); }

// 既決になった項目の aiza セッションを止めてアーカイブする(2026-10-17 ユーザー依頼)。
// stop は Claude に Ctrl+C を2回送って会話ログを書き終えさせる。group が digest のアーカイブ済みは aiza のどの一覧にも出ない(the deployment notes)。
// 既決の項目の「AIで続きから」は resume と replace_session で開き、チャットの履歴を引き継ぐ(元のセッションは aiza が消す)。
// 箱のサーバーは aiza のログインを持たないので、ページ(本人のブラウザ)が /agents/api を叩く。
// ページを開いたときと、ボタンで既決にしたときに走る。起動された Claude が set-status で既決にした分も、次に開いたときに片付ける。
// パスキーはタップからしか始められないので、開いたときは解錠なしで試し、鍵が掛かっていたら残りの件数のボタンを出す
// (2026-10-19 ユーザー指摘。開いたときの解錠が通らず、Claude が既決にした分が残っていた)。
// tap(タップから呼ぶとき)は解錠してから続ける。ボタンで既決にしたときは、ついでに残っている分も全部片付ける。
async function cleanupSessions(only, tap) {
  // Claude の確認待ち(doneAsk)は、セッションがもう動いていないときだけ普通の既決として片付ける
  const asked = Object.values(ITEMS).filter(i => i.status === '既決' && i.doneAsk && i.session && !i.session.deleted && (!only || i.id === only));
  for (const it of asked) { if (await liveSession(it).catch(() => true)) continue;
    await fetch(BASE + 'status', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id: it.id, status: '既決' }) }); delete it.doneAsk; }
  const ids = Object.values(ITEMS).filter(i => i.status === '既決' && !i.doneAsk && i.session && !i.session.deleted && (!only || i.id === only)).map(i => i.id);
  const call = path => tap ? withUnlock(() => post(path, {})) : post(path, {});
  for (const [n, id] of ids.entries()) {
    try {
      const sid = ITEMS[id].session.id;
      // 止まっているセッションの stop はエラーになるので無視して、アーカイブへ進む
      await call(`/sessions/${sid}/stop`).catch(e => { if (e.unlockRequired) throw e; console.warn('session stop', id, e.message); });
      await call(`/sessions/${sid}/archive`);
    } catch (e) {
      if (e.unlockRequired) return ids.length - n;
      if (!/^404$|not found|no such/i.test(e.message)) { console.warn('session archive failed', id, e); continue; }
    }
    await fetch(BASE + 'session-deleted', { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ id, archived: true }) });
    ITEMS[id].session.deleted = true; ITEMS[id].session.archived = true;
  }
  return 0;
}
async function cleanupTap(btn) {
  btn.disabled = true; btn.textContent = L('mail.stopping_archiving');
  try { await cleanupSessions(null, true); btn.parentNode.remove(); }
  catch (e) { btn.disabled = false; btn.textContent = L('mail.failed_x_press_again', { x: e.message }); }
}
cleanupSessions().then(left => {
  if (left) document.querySelector('h1').insertAdjacentHTML('afterend', `<div class="run"><button onclick="cleanupTap(this)">${L('mail.stop_archive_n_claude_sessions', { n: left })}</button></div>`);
}).catch(e => console.warn(e));
