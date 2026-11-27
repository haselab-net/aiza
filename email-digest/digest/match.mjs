// 取り込みの突き合わせ(2026-11-18 ユーザー): 取ってきた新着を、Claude に渡す前にスレッドの印で既存の項目と機械的に照らす。
// 当たった項目は、ここで time・from を進めて未読(↩ 返信)に戻す(markReplied)。Claude の分類の誤り・見落とし・回の失敗で返信が抜けないように。
// 印: メールは threadId(項目の id・threadId・refs の前のスレッド)。拡張の読む先は拡張の keys(項目)と inbound(取り込みのファイル)が決める。
// 取り込みのメッセージは key(当てる印。無ければ key2)と also(そのメッセージ自身の印)を持てる。当たったら also を項目の marks に残し、
// 同じ回の後のメッセージもそれで当てる(返信への返信)。
// 話題でしか決まらないもの(拡張が dm を付けたもの)は当てず、同じ会話の開いている項目を候補として Claude に渡す。
// 出すもの(<dir> は取り込みのファイルの置き場):
//   <dir>/replies.json  既存の項目への返信の束 [{id, source, title, summary, keys, messages:[{time, from, text, link}]}]。Claude は要約と対応だけ書き直す。
//                       keys は当たった印(add.mjs が、同じ話で別の id の項目を作らせない)
//   <dir>/dm-open.json  話題で決めるものの候補 [{dm, messages:[…], items:[{id, title, time, summary}]}]
// チャットで本人宛てか機械で分からない返信は forMe を付けない。autostart.mjs --sure はそれを起こさず、Claude の後の autostart が起こす(Claude が forMe:false にしなければ)
// 見張り: 最後に watch.mjs の checkWatches で、セッションが置いた見張りとも照らす(当たればそのセッションを起こす)
// 使い方: node match.mjs <dir> [--dry]
import fs from 'fs'; import { execFileSync } from 'child_process';
import { loadItems, saveItems, markReplied, fromMe } from './lib.mjs'; import { keysOf, skipItem as skip } from './keys.mjs'; import { CODE, conf } from './conf.mjs'; import { sources } from './ext.mjs'; import { checkWatches } from './watch.mjs';
const D = process.argv[2], DRY = process.argv.includes('--dry');
if (!D) { console.error('usage: match.mjs <dir> [--dry]'); process.exit(2); }
const MARKS = 40;   // 項目に残す当たったメッセージの印の数(古いものから捨てる)
const read = f => { try { return fs.readFileSync(`${D}/${f}`, 'utf8'); } catch { return ''; } };
const jst = t => new Date(t + 9 * 3600e3).toISOString().slice(0, 16);
// 取ってきた新着
const inbound = [];
for (const l of read('q-mail.jsonl').split('\n')) {
  let m; try { m = JSON.parse(l); } catch { continue; }
  // 下書き・送信済みは本人のもの(一覧の -in:sent は下書きを除かない)。本人の返信は ref-info --latest が見る
  if (!m.threadId || (m.labelIds || []).some(l => l === 'DRAFT' || l === 'SENT')) continue;
  inbound.push({ source: 'mail', key: 'mail:' + m.threadId, mid: m.id, thread: m.threadId, time: m.date ? jst(Date.parse(m.date)) : '', from: (m.from || '').replace(/<.*>/, '').replace(/"/g, '').trim(), text: m.snippet || '', title: m.subject || '' });
}
for (const s of sources) if (s.inbound) inbound.push(...s.inbound(read).map(x => ({ source: s.name, ...x })));
const d0 = loadItems();
// 取り込みに出ない返信(スレッドの返信が一覧に出ない読む先)は、拡張が項目のスレッドを見て足す
for (const s of sources) if (s.watch) {
  try { inbound.push(...(await s.watch(d0.items.filter(i => i.source === s.name && !skip(i)), conf)).map(x => ({ source: s.name, ...x }))); }
  catch (e) { console.error(`match: ${s.name} の見張り: ${String(e.message || e).split('\n')[0]}`); }
}

// 印 → 項目(同じ印の項目が複数あれば新しいほう)
function index(items) {
  const by = {};
  for (const i of items) if (!skip(i)) for (const k of keysOf(i)) if (!by[k] || (i.time || '') > (by[k].time || '')) by[k] = i;
  return by;
}
const by0 = index(d0.items);
const hits = {};    // 項目 id → 当たったメッセージ
const dms = {};     // 会話 → メッセージ
inbound.sort((a, b) => (a.time || '').localeCompare(b.time || ''));
for (const m of inbound) {
  const it = (m.key && by0[m.key]) || (m.key2 && by0[m.key2]);
  if (it && m.also && !by0[m.also]) by0[m.also] = it;
  if (it) (hits[it.id] ||= []).push(m);
  else if (m.dm) (dms[m.dm] ||= []).push(m);
}
// メールは最後のメッセージが本人のものかを Gmail に聞く(一覧は送信済みを除いているので、後から本人が返していても分からない)
let latest = {};
const mailT = [...new Set(Object.keys(hits).flatMap(id => hits[id].filter(m => m.source === 'mail').map(m => m.key.slice(5))))];
if (mailT.length) {
  try { latest = JSON.parse(execFileSync(`${CODE}/ref-info.py`, ['--latest', ...mailT], { encoding: 'utf8', timeout: 120e3 })); }
  catch (e) { console.error('match: ref-info --latest: ' + e.message.split('\n')[0]); }
}

// 当てる前に読み直す(Gmail に聞いている間にページが書いたものを上書きしない)
const d = DRY ? d0 : loadItems(), replies = [];
let n = 0, moved = 0;
for (const [id, ms] of Object.entries(hits)) {
  const it = d.items.find(x => x.id === id); if (!it) continue;
  ms.sort((a, b) => (a.time || '').localeCompare(b.time || ''));
  // 時刻は分まで。同じ分のものは、まだ項目に覚えていない発言(also)なら新しいものとする(2026-11-18 の試しで、同じ分の返信が落ちた)
  const known = new Set(keysOf(it)), t0 = it.time || '';
  const isNew = m => (m.time || '') > t0 || ((m.time || '') === t0 && !!m.also && !known.has(m.also));
  const also = ms.map(m => m.also).filter(m => m && !known.has(m));
  if (also.length && !DRY) { it.marks = [...(it.marks || []), ...new Set(also)].slice(-MARKS); moved++; }
  let last = ms[ms.length - 1];
  if (last.source === 'mail') {
    const g = Object.values(latest).length ? ms.map(m => latest[m.key.slice(5)]).filter(Boolean).sort((a, b) => (a.time || '').localeCompare(b.time || '')).pop() : null;
    if (g) last = { ...last, time: g.time, from: g.from, me: g.me };
  }
  const me = last.me !== undefined ? last.me : fromMe({ from: last.from });
  const newMs = ms.filter(isNew);
  if (!(last.time > t0) && !(last.time === t0 && newMs.length)) continue;
  replies.push({ id, source: it.source, title: it.title, summary: it.summary, keys: [...new Set(ms.flatMap(m => [m.key, m.key2]).filter(Boolean))], messages: newMs.map(({ time, from, text, link }) => ({ time, from, text, link })) });
  if (DRY) { console.log(`dry ${id}: ${it.time} → ${last.time}${me ? '(本人)' : ''}`); continue; }
  it.time = last.time; it.from = last.from; delete it.bump; moved++;
  if (me) { it.fromMe = true; delete it.forMe; console.log(`match ${id}: 本人の返信(${last.time})`); continue; }
  it.fromMe = false; delete it.forMe;
  if (newMs.some(m => m.forMe === true)) it.forMe = true;
  it.bump = 'match'; markReplied(it, last.time, last.from); n++;
  console.log(`match ${id}: 返信(${last.time})→ 未読`);
}
if (moved && !DRY) saveItems(d);
// 話題で決めるもの: 同じ会話の、既決でない項目を候補に
const open = d.items.filter(i => !skip(i) && i.status !== '既決');
const dmOpen = Object.entries(dms).map(([dm, messages]) => ({ dm, messages: messages.map(({ time, from, text, link }) => ({ time, from, text, link })),
  items: open.filter(i => keysOf(i).includes(dm)).map(({ id, title, time, summary }) => ({ id, title, time, summary })) })).filter(x => x.items.length);
if (!DRY) {
  fs.writeFileSync(`${D}/replies.json`, JSON.stringify(replies, null, 1));
  fs.writeFileSync(`${D}/dm-open.json`, JSON.stringify(dmOpen, null, 1));
}
console.log(`match: 返信 ${replies.length} 件(起こす ${n})、話題で決める会話 ${dmOpen.length}`);
// セッションが置いた見張り(watch.mjs、2026-11-20): 同じ新着と Gmail の検索で照らし、当たったセッションを起こす
try { await checkWatches(inbound, { dry: DRY }); } catch (e) { console.error('match: 見張り: ' + String(e.message || e).split('\n')[0]); }
