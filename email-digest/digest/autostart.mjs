// 未決の項目に、クリックを待たずに Claude セッションを起動する(2026-11-07 ユーザー依頼)。
// aiza の notify リスナーの POST /sessions(箱からだけ通る。preset・cwd・group は固定、生きている箱発のセッション 8 件・1時間 10 件まで。サーバー文書 aiza)を使う。
// 1通目はページの「AIで対応」と同じ「新着まとめの項目 <id>「<題>」に対応したいです。」で、aiza が入力欄を待って送る。
// 対象(2026-11-17 ユーザー):
//   - session がある項目に、本人以外から新しいメッセージが来た(time > seen、最新が本人のものでない、チャットの読む先で本人宛てでないと判断された forMe:false でない)
//     → 状態・byUser・待ちにかかわらず同じセッションを起こす。成立前の待ちがあれば、ここで成立させて(理由「スレッドに新しいメッセージ」)1通目に待ちの条件と task を入れる
//   - 待ちが成立してまだ伝えていない(wait.fired・told なし)→ session があれば同じセッション、無ければ新しく起こし、1通目に task を入れる
//   - session が無い未決・byUser なし・成立前の待ちなしで、まだ試していない(autoStart なし、429 と通信の失敗は次の回に再試行)もの
// 使い方: node ~/digest/autostart.mjs [--max N] [--dry] [--id <項目id>] [--sure]   run-check.sh・quick-check.sh が add の後に呼ぶ
import fs from 'fs'; import { notifyUrl, fromMe, nowJst, notify } from './lib.mjs'; import { DATA, conf } from './conf.mjs';
const DB = `${DATA}/items.json`;
const load = () => { if (!fs.existsSync(DB)) return { items: [], runs: [] }; return JSON.parse(fs.readFileSync(DB, 'utf8')); }; // 初めての箱では items.json がまだ無い
const save = d => { fs.writeFileSync(DB + '.tmp', JSON.stringify(d, null, 1)); fs.renameSync(DB + '.tmp', DB); };
const arg = k => { const i = process.argv.indexOf(k); return i > 0 ? process.argv[i + 1] : null; };
const MAX = Number(arg('--max') || 5), DRY = process.argv.includes('--dry'), ONLY = arg('--id');
// client.js と同じもの(1通目・seen の印)
const context = it => `新着まとめの項目 ${it.id}「${it.title}」に対応したいです。`;
const sig = it => { let h = 0; for (const c of `${it.summary || ''}|${it.action || ''}`) h = (h * 31 + c.charCodeAt(0)) | 0; return `${it.time || ''}|${(h >>> 0).toString(36)}`; };
const updateNote = it => `この項目(${it.id})は前回から更新されています(最新 ${it.time || '?'} ${it.from || ''})。node item.mjs ${it.id} と元のメッセージを読み直して、新しい返信などで変わった点と対応案を教えてください。`;
const retryable = a => !a || a.retry;
// 続き(2026-11-10 ユーザー依頼):
// 前のセッションがある項目に、それより新しい返信が来たら(add.mjs の開き直し・同じ話のまとめ)、aiza に continue で前のセッションを渡す。
// 動いていればそこへ知らせを送り、終わって(アーカイブされて)いれば同じ id・同じ会話で再開して知らせを送る(the deployment notes)
const newer = i => i.session && (i.time || '') > String(i.session.seen || '').split('|')[0];
const tried = i => i.autoStart && i.autoStart.sig === sig(i) && !i.autoStart.retry;
const pending = i => i.wait && !i.wait.fired;
// --sure: 突き合わせ(match.mjs)の直後、Claude より前に呼ぶ。チャットで本人宛てか機械で分からない返信(forMe が無い)は Claude の判断を待つ
const SURE = process.argv.includes('--sure');
const unsure = i => SURE && i.bump === 'match' && i.source !== 'mail' && i.forMe === undefined;
const replyWake = i => i.session && newer(i) && !tried(i) && !fromMe(i) && i.forMe !== false && !unsure(i) && i.status !== '既決';
const waitWake = i => i.wait && i.wait.fired && !i.wait.told && i.status !== '既決' && !(i.autoStart && i.autoStart.wait === i.wait.fired && !i.autoStart.retry);
const fresh = i => !i.session && i.status === '未決' && !i.byUser && !pending(i) && retryable(i.autoStart);
// 保留中の項目(held)は起こさない(本人が「Claudeに渡す」を選ぶまで)
const want = load().items.filter(i => !i.held && (ONLY ? i.id === ONLY : i.id !== 'misc:noaction' && (replyWake(i) || waitWake(i) || fresh(i))));
// 1通目に足す待ちの文。成立前の待ちに返信が来たときと、条件・日時で成立したとき
// 1通目は 500 字まで(aiza)。長い条件・task は切る(全文は item.mjs の wait)
const cut = (t, n) => { const a = [...String(t || '')]; return a.length > n ? a.slice(0, n - 1).join('') + '…' : a.join(''); };
const when = w => [w.at && '日時: ' + w.at.replace('T', ' '), w.cond && '条件: ' + cut(w.cond, 80)].filter(Boolean).join('、');
const waitNote = (it, byReply) => byReply
  ? `待っていた件です(${when(it.wait)}、頼まれていたこと: ${cut(it.wait.task, 100)})。新しいメッセージを読み、待ちを外すか(wait.mjs clear)、続けて待つか(wait.mjs set で付け直す)を決めてください。`
  : `待っていた条件が成立しました(${cut(it.wait.why, 80)})。頼まれていたこと: ${cut(it.wait.task, 100)}\nnode ~/digest/item.mjs ${it.id} と関係するメールなどを読んで、進めてください。`;
const url = (notifyUrl() || '').replace(/\/notify$/, '/sessions');
if (!/\/sessions$/.test(url)) { console.error('autostart: 設定の notifyUrl から送り先が分からない'); process.exit(1); }
const ts = () => new Date().toISOString();
const post = async body => {
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body), signal: AbortSignal.timeout(30000) });
  return { status: r.status, j: await r.json().catch(() => ({})) };
};
for (const it0 of want.slice(0, MAX)) {
  const cont = it0.session && it0.session.id, byReply = replyWake(it0) && pending(it0);
  if (DRY) { console.log('dry', it0.id, cont ? 'continue ' + cont : 'new', byReply ? 'wait-by-reply' : waitWake(it0) ? 'wait' : ''); continue; }
  // 成立前の待ちに返信が来た: ここで成立させる(ページの表示と通知は条件の成立と同じ)
  if (byReply) {
    const d = load(), it = d.items.find(x => x.id === it0.id);
    if (it && it.wait && !it.wait.fired) { it.wait.fired = nowJst(); it.wait.why = `スレッドに新しいメッセージ(${it.time || ''} ${it.from || ''})`; it.changed = new Date().toISOString(); save(d); it0.wait = it.wait; await notify(it); }
  }
  const wn = it0.wait && it0.wait.fired && !it0.wait.told ? waitNote(it0, byReply) : '';
  const first = cont ? (newer(it0) ? updateNote(it0) + (wn ? '\n' + wn : '') : wn) : context(it0) + (wn ? '\n' + wn : '');
  const body = { preset: conf.session.preset, cwd: conf.session.cwd, group: conf.session.group, label: ('digest: ' + it0.title).slice(0, 40), cols: 100, rows: 40,
    initial_message: first.slice(0, 500), ...(cont ? { continue: cont } : {}) };
  let rec;
  try {
    let { status, j } = await post(body);
    if (status === 404 && cont) { // 前のセッションが aiza に残っていない: 新しく始める
      ({ status, j } = await post({ ...body, continue: undefined, initial_message: (context(it0) + (wn ? '\n' + wn : '')).slice(0, 500) }));
      if (status === 201) j.continued = 'lost';
    }
    if ((status === 201 || status === 200) && j.id) rec = { ok: true, how: j.continued || 'started', session: { id: j.id, claude_session_id: j.claude_session_id || '', created: ts(), seen: sig(it0), auto: true } };
    else rec = { ok: false, error: `${status} ${j.error || ''}`.trim(), retry: status === 429 || status >= 500 };
  } catch (e) { rec = { ok: false, error: e.message, retry: true }; }
  const d = load(), it = d.items.find(x => x.id === it0.id);
  if (!it) continue;
  if (rec.ok && (!it.session || cont)) it.session = rec.how === 'running' || rec.how === 'resumed' ? { ...it.session, ...rec.session, created: it.session.created || rec.session.created, resumed: ts(), deleted: undefined, archived: undefined } : rec.session;
  it.autoStart = { at: ts(), sig: sig(it0), ...(wn ? { wait: it0.wait.fired } : {}), ...(rec.ok ? { id: rec.session.id, how: rec.how } : { error: rec.error, retry: rec.retry }) };
  // 1通目で待ちを伝えたので、続きから開いたときに client.js が重ねて送らない
  if (rec.ok && wn && it.wait) it.wait.told = ts();
  save(d);
  console.log(`autostart ${it0.id}: ${rec.ok ? rec.how + ' ' + rec.session.id : 'FAILED ' + rec.error}`);
  if (!rec.ok && rec.error.startsWith('429')) break; // 上限。残りは次の回に
}
