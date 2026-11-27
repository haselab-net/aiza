// 見張り(2026-11-20 ユーザー):「セッションが新着まとめに起こすことを依頼できる仕組みがほしい。キーワードやメールのスレッドなどを指定できると良い。」
// 箱のセッション(新着まとめの項目に結んでいないものも)が「これが来たら起こして」を置いていく。取り込みの突き合わせ(match.mjs)が、
// 取ってきた新着と照らし、当たったらそのセッションを aiza に起こしてもらう(止まっていれば同じ会話で再開し、1通目に条件・task・当たったものを入れる)。
// 条件は OR: --thread(そのスレッドに本人以外から来た)・--query(Gmail の検索式。回ごとに前の回からの分を Gmail に聞く)・--keyword(件名・本文の始め・差出人に含む。
// チャットにも効く。--from があれば差出人にも含むこと)。一度当たっても消さない(同じ相手から何通も来るため)。--until(既定 30 日)か rm まで。
// 同じメッセージで二度起こさない。セッションがアーカイブされた・無くなったら見張りを外す。
// 使い方:
//   node ~/digest/watch.mjs add [--session <aiza id>] [--thread <threadId>]... [--query '<Gmail の検索式>'] [--keyword <語>]... [--from <差出人の一部>]
//                               [--until YYYY-MM-DD] [--label '<一覧に出す短い名前>'] --task '<起きたらすること>'
//   node ~/digest/watch.mjs list [--session <id>] [--json]      node ~/digest/watch.mjs rm <見張り id>
// --session を省くと今のセッション(aiza が渡す AIZA_OUTBOX の場所から分かる)。
import fs from 'fs'; import path from 'path'; import { execFileSync } from 'child_process'; import { pathToFileURL } from 'url';
import { DATA, CODE } from './conf.mjs'; import { fromMe, notifyUrl } from './lib.mjs';
const DB = `${DATA}/watches.json`;
const SEEN = 200, DAYS = 30, MSG = 500;
export const loadWatches = () => { try { return JSON.parse(fs.readFileSync(DB, 'utf8')); } catch { return { next: 1, watches: [] }; } };
const save = d => { fs.writeFileSync(DB + '.tmp', JSON.stringify(d, null, 1)); fs.renameSync(DB + '.tmp', DB); };
const cut = (t, n) => { const a = [...String(t || '')]; return a.length > n ? a.slice(0, n - 1).join('') + '…' : a.join(''); };
const jstDay = ms => new Date(ms + 9 * 3600e3).toISOString().slice(0, 10);
const jst = ms => new Date(ms + 9 * 3600e3).toISOString().slice(0, 16).replace('T', ' ');
// 期限の日の終わり(JST)を過ぎたか
const expired = (w, now = Date.now()) => !!w.until && jstDay(now) > w.until;
// 一覧に出す短い条件(件名程度)
export function short(w) {
  if (w.label) return cut(w.label, 30);
  const p = [];
  if (w.query) p.push(w.query);
  if (w.keyword && w.keyword.length) p.push([w.from && 'from:' + w.from, ...w.keyword].filter(Boolean).join(' '));
  if (w.thread && w.thread.length) p.push(`スレッド${w.thread.length > 1 ? ' ×' + w.thread.length : ''}`);
  return cut(p.join(' / '), 30);
}
const cond = w => [w.query && `検索 ${w.query}`, w.keyword && w.keyword.length && `語 ${w.keyword.join('・')}${w.from ? `(差出人 ${w.from})` : ''}`,
  w.thread && w.thread.length && `スレッド ${w.thread.join(',')}`].filter(Boolean).join('、');

// ---- 突き合わせ(match.mjs から): 取ってきた新着 inbound と Gmail の検索で照らし、当たった見張りのセッションを起こす ----
const keyOf = m => m.mid ? 'm:' + m.mid : `${m.source}:${m.also || m.key || ''}|${m.time || ''}|${cut(m.text, 40)}`;
const hay = m => `${m.title || ''}\n${m.text || ''}\n${m.from || ''}`.toLowerCase();
function hitsInbound(w, inbound) {
  const out = [];
  for (const m of inbound) {
    if (fromMe({ from: m.from })) continue;
    const t = (w.thread || []).length && m.source === 'mail' && w.thread.includes(m.thread);
    const k = (w.keyword || []).length && w.keyword.some(x => hay(m).includes(String(x).toLowerCase()))
      && (!w.from || String(m.from || '').toLowerCase().includes(w.from.toLowerCase()));
    if (t || k) out.push(m);
  }
  return out;
}
const gmail = (args, timeout = 120e3) => execFileSync(`${path.dirname(CODE)}/gmail.py`, args, { encoding: 'utf8', timeout, stdio: ['ignore', 'pipe', 'ignore'] });
const mailMsg = m => ({ source: 'mail', mid: m.id, thread: m.threadId, time: m.date ? jst(Date.parse(m.date)) : '', from: (m.from || '').replace(/<.*>/, '').replace(/"/g, '').trim(), title: m.subject || '', text: m.snippet || '' });
function hitsQuery(w, sinceSec) {
  const out = gmail(['list', '-q', `(${w.query}) after:${sinceSec} -in:sent -in:drafts`, '-n', '20']);
  return out.split('\n').flatMap(l => { try { const m = JSON.parse(l); return m.threadId && !(m.labelIds || []).some(x => x === 'DRAFT' || x === 'SENT') ? [mailMsg(m)] : []; } catch { return []; } })
    .filter(m => !fromMe({ from: m.from }));
}
function link(m) {
  if (m.link) return m.link;
  if (m.source !== 'mail' || !m.thread) return '';
  try { return gmail(['link', m.thread], 30e3).trim().split('\n')[0] || ''; } catch { return ''; }
}
export function wakeText(w, ms) {
  const head = `👁 見張り ${w.id} に当たりました(${cut(cond(w), 120)})。頼まれていたこと: ${cut(w.task, 120)}\n`;
  const tail = `\nメールは ~/gmail.py read などで読んでください。もう要らなければ node ~/digest/watch.mjs rm ${w.id}`;
  let body = '';
  for (const m of ms.slice(-3)) {
    const l = `- ${m.time || ''} ${cut(m.from, 30)}「${cut(m.title || m.text, 50)}」 ${link(m)}\n`;
    if ([...head, ...body, ...l, ...tail].length > MSG) break;
    body += l;
  }
  if (ms.length > 3) body += `(ほか ${ms.length - 3} 件)\n`;
  return cut(head + body.replace(/\n$/, '') + tail, MSG);
}
async function wake(sid, message) {
  const url = notifyUrl().replace(/\/notify$/, '/digest/watch/wake');
  const r = await fetch(url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ session: sid, message }), signal: AbortSignal.timeout(30000) });
  return { status: r.status, j: await r.json().catch(() => ({})) };
}
// inbound: match.mjs が読んだ新着(メールは mid・thread 付き)。dry なら起こさず出すだけ
export async function checkWatches(inbound, { dry = false, now = Date.now() } = {}) {
  const d0 = loadWatches();
  if (!d0.watches.length) return;
  const found = {}, checked = {};
  for (const w of d0.watches) {
    if (expired(w, now)) continue;
    let ms = hitsInbound(w, inbound);
    if (w.query) {
      const since = Math.floor(Date.parse(w.checked || w.created) / 1000) - 60;
      try { ms = ms.concat(hitsQuery(w, since)); checked[w.id] = new Date(now).toISOString(); }
      catch (e) { console.error(`watch ${w.id}: Gmail の検索に失敗(${String(e.message || e).split('\n')[0].slice(0, 80)})`); }
    }
    const seen = new Set(w.seen || []), uniq = new Map();
    for (const m of ms) { const k = keyOf(m); if (!seen.has(k) && !uniq.has(k)) uniq.set(k, m); }
    if (uniq.size) found[w.id] = [...uniq.entries()].sort((a, b) => (a[1].time || '').localeCompare(b[1].time || ''));
  }
  const res = {};
  for (const [id, hits] of Object.entries(found)) {
    const w = d0.watches.find(x => x.id === id);
    if (dry) { console.log(`dry watch ${id}: ${hits.length} 件 → ${w.session}`); continue; }
    let r;
    try { r = await wake(w.session, wakeText(w, hits.map(h => h[1]))); } catch (e) { r = { status: 0, j: { error: e.message } }; }
    res[id] = { r, keys: hits.map(h => h[0]), n: hits.length };
    console.log(`watch ${id}: ${hits.length} 件 → ${w.session} ${r.status === 200 ? r.j.how + (r.j.id !== w.session ? ' ' + r.j.id : '') : 'FAILED ' + r.status + ' ' + (r.j.error || '')}`);
    if (r.status === 429) break; // 上限。残りは次の回に(seen を進めないので同じものでもう一度)
  }
  if (dry) return;
  // 起こしている間に add・rm されたものを消さないように読み直して書く
  const d = loadWatches(), at = new Date(now).toISOString();
  d.watches = d.watches.filter(w => {
    if (expired(w, now)) { console.log(`watch ${w.id}: 期限 ${w.until} を過ぎたので外した`); return false; }
    const x = res[w.id];
    if (checked[w.id]) w.checked = checked[w.id];
    if (!x) return true;
    if (x.r.status === 410) { console.log(`watch ${w.id}: セッション ${w.session} がアーカイブ済み・無いので外した`); return false; }
    if (x.r.status === 404) { console.log(`watch ${w.id}: セッション ${w.session} は箱のセッションでないので外した`); return false; }
    // 429・5xx・通信の失敗は次の回にもう一度。それ以外(200、再開できない 409 など)は同じメッセージで繰り返さない
    // (繰り返すと、箱から起こす 1 時間 10 件の枠を項目の autostart と一緒に使い切る)
    if (x.r.status === 429 || x.r.status >= 500 || !x.r.status) return true;
    w.seen = [...(w.seen || []), ...x.keys].slice(-SEEN);
    w.last = { at, n: x.n, ...(x.r.status === 200 ? {} : { error: x.r.status }) };
    if (x.r.status === 200 && x.r.j.id && x.r.j.id !== w.session) w.session = x.r.j.id;  // 別の id で再開した
    return true;
  });
  save(d);
}

// ---- 道具 ----
const selfSession = () => { const o = process.env.AIZA_OUTBOX; return o ? path.basename(path.dirname(o)) : ''; };
const SID = /^[0-9a-f]{12}$/;
function opts(argv) {
  const o = { thread: [], keyword: [] }, many = { '--thread': 'thread', '--keyword': 'keyword' }, one = { '--session': 'session', '--query': 'query', '--from': 'from', '--until': 'until', '--task': 'task', '--label': 'label' };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (many[a]) o[many[a]].push(argv[++i]);
    else if (one[a]) o[one[a]] = argv[++i];
    else if (a === '--json') o.json = true;
    else o._ = [...(o._ || []), a];
  }
  return o;
}
const die = m => { console.error('watch: ' + m); process.exit(2); };
async function main() {
  const [cmd, ...rest] = process.argv.slice(2), o = opts(rest);
  if (cmd === 'add') {
    const session = o.session || selfSession();
    if (!SID.test(session || '')) die('--session が要ります(aiza のセッション id。aiza のセッションの中なら省けます)');
    if (!o.task || !String(o.task).trim()) die('--task が要ります(起きたらすること)');
    if (!o.thread.length && !o.query && !o.keyword.length) die('--thread・--query・--keyword のどれかが要ります');
    if (o.thread.some(t => !/^[0-9a-f]{16}$/.test(t))) die('--thread は Gmail の threadId(16 桁の 16 進)');
    if (o.from && !o.keyword.length) die('--from は --keyword と一緒に使います(差出人だけなら --query \'from:…\')');
    if (o.until && !/^\d{4}-\d{2}-\d{2}$/.test(o.until)) die('--until は YYYY-MM-DD');
    const until = o.until || jstDay(Date.now() + DAYS * 86400e3);
    const d = loadWatches(), id = 'w' + (d.next || 1);
    const w = { id, session, created: new Date().toISOString(), until, task: String(o.task).trim(),
      ...(o.thread.length ? { thread: o.thread } : {}), ...(o.query ? { query: o.query } : {}),
      ...(o.keyword.length ? { keyword: o.keyword } : {}), ...(o.from ? { from: o.from } : {}), ...(o.label ? { label: o.label } : {}) };
    w.short = short(w);  // aiza の「やること」の行に出す(件名程度)
    d.next = (d.next || 1) + 1; d.watches.push(w); save(d);
    console.log(`見張り ${id} を置きました(${cond(w)}、${until} まで)。当たるとセッション ${session} を起こします。一覧の表示: 👁 ${short(w)}`);
  } else if (cmd === 'list') {
    const ws = loadWatches().watches.filter(w => !o.session || w.session === o.session);
    if (o.json) { for (const w of ws) console.log(JSON.stringify(w)); return; }
    if (!ws.length) { console.log('見張りはありません'); return; }
    for (const w of ws) console.log(`${w.id} セッション ${w.session} ${w.until} まで: ${cond(w)} → ${cut(w.task, 60)}${w.last ? `(最後に当たった ${jst(Date.parse(w.last.at))}${w.last.error ? `、起こせなかった ${w.last.error}` : ''})` : ''}${expired(w) ? ' [期限切れ]' : ''}`);
  } else if (cmd === 'rm') {
    const id = (o._ || [])[0]; if (!id) die('rm <見張り id>');
    const d = loadWatches(), n = d.watches.length;
    d.watches = d.watches.filter(w => w.id !== id);
    if (d.watches.length === n) die(`${id} はありません`);
    save(d); console.log(`見張り ${id} を外しました`);
  } else die('使い方: watch.mjs add|list|rm(先頭の説明を見てください)');
}
if (process.argv[1] && import.meta.url === pathToFileURL(fs.realpathSync(process.argv[1])).href) await main();
