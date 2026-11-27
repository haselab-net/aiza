// 使い方: node ~/digest/add.mjs new_items.json ["チェックのメモ"]
// new_items.json = [{id, source:"mail" か拡張の読む先の名前, time:"2026-10-09T09:00", from, title, summary, action, status, link, due?:"2026-10-30" か "2026-10-30T17:00", refs?:["mail:<threadId>", "<拡張の読む先の URL>"]}]
// refs はまとめ項目が含む元のメッセージ。既決にすると done-sync がメールはアーカイブ、拡張の読む先は既読にする
// 同じ id があれば、本人が画面で変えた status は保ったまま内容だけ更新する。
// ただし time が進んで最新が本人以外からなら(返信)、どの状態でも未読に戻して「↩ 返信」の印を付ける(lib.mjs の markReplied、2026-11-17 ユーザー)
// 任意: continues(内容で既存の項目の続きと判断したときのその項目の id。下の CONTINUES)、fromMe(最新のメッセージが本人のもの。無ければ from を設定の本人と比べる)、forMe(チャットの読む先で、新しいメッセージが本人宛てか。false ならセッションを起こさない)
import fs from 'fs'; import os from 'os'; import { execFileSync } from 'child_process'; import { threadOf, fromMe, markReplied, contTarget, nowJst, notify } from './lib.mjs'; import { DATA, CODE } from './conf.mjs'; import { byName, sourceOfRef, goodLink } from './ext.mjs'; import { keysOf } from './keys.mjs';
const DB = `${DATA}/items.json`;
const add = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
// まとめ項目(id が misc:…)の要約の [表示](mail:<threadId> …) / [表示](<拡張の refRe に当たる URL>) は refs にも入れる(既決で片付くように。refRe の無い読む先は入れない)
for (const it of add) if (/^misc:/.test(it.id || '')) for (const m of String(it.summary || '').matchAll(/\]\(((?:mail:[0-9a-f]+|https?:\/\/[^\s)]+)(?:\s+(?:mail:[0-9a-f]+|https?:\/\/[^\s)]+))*)\)/g))
  for (const r of m[1].split(/\s+/)) if ((/^mail:/.test(r) || sourceOfRef(r)) && !(it.refs ||= []).includes(r)) it.refs.push(r);
// refs の元の一覧(ページの「元のメッセージ」、2026-11-05 ユーザー依頼)。
// refInfo = {ref: {label, time, url, mobile?}}。メールは ref-info.py が Gmail から差出人・件名を取る。ほかは定期チェックが refInfo を渡す(無ければ URL だけ出る)
// Gmail に聞くのに数秒かかるので、items.json を読む前に済ませる(その間にページで変えた状態を上書きしない)
let refGot = {};
try {
  const pre = (() => { try { return JSON.parse(fs.readFileSync(DB, 'utf8')).items; } catch { return []; } })();
  const miss = [...pre.filter(i => i.refs && i.status !== '既決'), ...add].flatMap(i => (i.refs || []).filter(r => /^mail:[0-9a-f]+$/.test(r) && !(i.refInfo || {})[r]).map(r => r.slice(5)));
  if (miss.length) refGot = JSON.parse(execFileSync(`${CODE}/ref-info.py`, [...new Set(miss)], { encoding: 'utf8', timeout: 120e3 }));
} catch (e) { console.error('WARN ref-info:', e.message.split('\n')[0]); }
// 「本人が返信済み」(fromMe や差出人の「返信済み」)と書かれたメールの項目は、スレッドの最新のメッセージ(下書きを除く)が本当に本人のものか確かめる。
// 本人でなければ fromMe を外し、差出人を戻し、既決なら未決にする(2026-11-19 ユーザー: 準備のセッションが作った返信の下書きを
// 本人の返信と取り違え、未決にならずに既決・アーカイブされた)。Gmail に聞けなかったときは書かれたとおりにする
let latestGot = {};
try {
  const ask = add.filter(i => /^mail:[0-9a-f]{16}$/.test(i.id || '') && (i.fromMe === true || /返信済み/.test(i.from || ''))).map(i => i.id.slice(5));
  if (ask.length) latestGot = JSON.parse(execFileSync(`${CODE}/ref-info.py`, ['--latest', ...new Set(ask)], { encoding: 'utf8', timeout: 120e3 }));
} catch (e) { console.error('WARN ref-info --latest:', e.message.split('\n')[0]); }
for (const it of add) {
  const l = /^mail:/.test(it.id || '') && latestGot[it.id.slice(5)];
  if (!l || l.me) continue;
  console.error(`NOTSENT ${it.id}: 本人の返信が無い(下書きだけ)→ ${it.status === '既決' ? '未決' : it.status}`);
  it.fromMe = false; it.from = l.from || it.from;
  if (it.status === '既決') it.status = '未決';
}
// 同じ話のメールは1つの項目に(2026-11-10 ユーザー依頼)。Gmail は In-Reply-To の無い返信(一部の会社のサポートなど)を
// 別スレッドにするので、新しいスレッドの件名が Re:/Fwd: 付きで、Re: を除いた件名と本人以外の差出人が前の項目と同じなら、前の項目の id で出し直す
// (下の「開き直す」と同じ扱いになり、前の Claude セッションが続きを受ける。autostart.mjs)。mkey = 項目のスレッドの {subj, addrs}(ref-info.py --keys)を覚えておく
const MAIL_ID = /^mail:[0-9a-f]{16}$/, mkeyOf = {};
try {
  const pre = (() => { try { return JSON.parse(fs.readFileSync(DB, 'utf8')).items; } catch { return []; } })();
  const known = new Set(pre.map(i => i.id)), since = new Date(Date.now() - 120 * 86400e3).toISOString().slice(0, 10);
  const ask = [...add.filter(i => MAIL_ID.test(i.id || '') && !known.has(i.id)).map(i => i.id.slice(5)),
    ...pre.filter(i => i.source === 'mail' && !i.mkey && threadOf(i) && (i.time || '') >= since).map(threadOf)];
  if (ask.length) Object.assign(mkeyOf, JSON.parse(execFileSync(`${CODE}/ref-info.py`, ['--keys', ...new Set(ask)], { encoding: 'utf8', timeout: 300e3 })));
} catch (e) { console.error('WARN ref-info --keys:', e.message.split('\n')[0]); }
let d; try { d = JSON.parse(fs.readFileSync(DB, 'utf8')); } catch { d = { items: [], runs: [] }; }
let n = 0;
for (const i of d.items) if (i.source === 'mail' && !i.mkey && mkeyOf[threadOf(i)]) { const { reply, ...k } = mkeyOf[threadOf(i)]; i.mkey = k; }
const sameTalk = k => d.items.filter(o => o.source === 'mail' && !/^misc:/.test(o.id) && o.mkey && o.mkey.subj === k.subj && o.mkey.addrs.some(a => k.addrs.includes(a)))
  .sort((a, b) => (b.time || '').localeCompare(a.time || ''))[0];
// 突き合わせ済みの話(match.mjs の replies.json。取り込みの置き場 $Q)で別の id の項目を作らない: 当たった印と同じ印の新しい項目は、当たった項目の id で出し直す
const matched = (() => { try { return JSON.parse(fs.readFileSync(`${process.env.Q}/replies.json`, 'utf8')); } catch { return []; } })();
for (const it of add) {
  if (!matched.length || /^misc:/.test(it.id || '') || d.items.some(x => x.id === it.id)) continue;
  const ks = keysOf(it), hit = matched.find(r => r.id !== it.id && (r.keys || []).some(k => ks.includes(k)));
  if (hit) { console.error(`MATCHED ${it.id} → ${hit.id}(突き合わせ済みの項目の続き)`); it.id = hit.id; }
}
// 内容で続きと分かったメッセージ(2026-11-24 ユーザー:「内容から繋がりが判断できた場合に同じセッションで続きをするようにしてください」)。
// 差出人も件名も違うが同じ会・同じ手続き・同じ依頼の流れのもの(例: 委員会の案内の待ちの材料になる、別の配信元からの資料公開の知らせ)。
// 新着チェックの Claude が "continues": "<前の項目の id>" を書いたら、前の項目の id で出し直す。下の返信の扱いで未読(↩ 返信)に戻り、
// 前のセッションを autostart.mjs が continue で起こす(成立前の待ちは返信と同じく成立させる)。セッションの無い待ちはここで成立させて知らせる。
// メールどうしは SAME-TALK と同じ(新しいスレッドが threadId、前のスレッドは refs)。読む先が違えば前の項目の source・link・スレッドを保ち、新しいメッセージは refs に足す。
// 題は前の項目のまま。前の項目より古いメッセージなら refs に足すだけ。続きにできない項目(contTarget)を指したら別の項目のまま
const folded = new Set(), woke = [];
for (const it of add) {
  const cid = it.continues; delete it.continues;
  if (!cid || cid === it.id || /^misc:/.test(it.id || '')) continue;
  if (d.items.some(x => x.id === it.id)) { console.error(`WARN ${it.id}: もう項目がある。continues ${cid} は使わない`); continue; }
  const p = d.items.find(x => x.id === cid);
  if (!contTarget(p)) { console.error(`WARN ${it.id}: continues ${cid} は続きにできる項目でない(無い・まとめ・30 日より前の既決・セッションの無い既決)→ 別の項目`); continue; }
  const tid = MAIL_ID.test(it.id || '') ? it.id.slice(5) : null, same = !!tid && it.source === 'mail' && p.source === 'mail';
  const own = tid ? 'mail:' + tid : (sourceOfRef(it.link) ? it.link : null);
  const refs = new Set([...(p.refs || []), ...(it.refs || [])]);
  if (same) { const pt = threadOf(p); if (pt && pt !== tid) refs.add('mail:' + pt); refs.delete(own); }
  else if (own) refs.add(own);
  if (!(it.time && it.time > (p.time || ''))) {
    p.refs = [...new Set([...(p.refs || []), ...(it.refs || []), ...(own ? [own] : [])])]; p.refInfo = { ...(p.refInfo || {}), ...(it.refInfo || {}) }; folded.add(it);
    console.error(`CONTINUES ${it.id} → ${cid}(前の項目より古いので元のメッセージに足すだけ)`); continue;
  }
  console.error(`CONTINUES ${it.id} → ${cid}(内容で続き)`);
  Object.assign(it, { id: cid, title: p.title, refs: [...refs], contFrom: { id: it.id, at: it.time } });
  if (same) it.threadId = tid; else { it.source = p.source; it.link = p.link; if (p.threadId) it.threadId = p.threadId; else delete it.threadId; }
  if (p.wait && !p.wait.fired && !p.session && !fromMe(it)) {
    Object.assign(p.wait, { fired: nowJst(), why: `続きのメッセージ(${it.time} ${it.from || ''})` }); p.changed = new Date().toISOString(); woke.push(cid);
  }
}
for (const it of add) {
  if (folded.has(it)) continue;
  const k = MAIL_ID.test(it.id || '') && !d.items.some(x => x.id === it.id) && mkeyOf[it.id.slice(5)];
  if (k) {
    const { reply, ...key } = k, prev = reply && key.subj.length >= 8 && key.addrs.length ? sameTalk(key) : null;
    it.mkey = key;
    if (prev) {
      const tid = it.id.slice(5);
      it.refs = [...new Set([...(prev.refs || []), ...(it.refs || []), 'mail:' + threadOf(prev)])].filter(r => r !== 'mail:' + tid);
      console.error(`SAME-TALK ${it.id} → ${prev.id}(同じ件名・相手の前の項目にまとめる)`);
      Object.assign(it, { id: prev.id, threadId: tid });
    }
  }
  // 既決の片付け(done-sync)は link の元を既読にするので、拡張の読む先(urlRe のあるもの)の個別項目には元の URL が要る(まとめ項目 misc は除く)
  if (byName[it.source] && byName[it.source].urlRe && !/misc/.test(it.id) && !goodLink(it.link))
    console.error(`WARN ${it.id}: link が無い。既決にしても ${it.source} 側は既読にならない(メッセージの URL を入れる)`);
  const old = d.items.find(x => x.id === it.id);
  if (old && old.held) { console.error('SKIP ' + it.id + ': ローカルの確認で保留中の項目(held)。本人がまとめのページで「Claudeに渡す」を選ぶまで扱えません'); continue; }
  // 対応不要のまとめ(id misc:noaction、2026-10-14 ユーザー依頼): 巡回ごとに項目を立てず、1つの項目に行を足す。
  // まだ見ていなければ(既決でなければ)前の行の上に足し、既決にした後なら新しい行だけで未読に戻す
  if (it.id === 'misc:noaction') {
    if (old && old.status !== '既決') { old.refInfo = { ...(old.refInfo || {}), ...(it.refInfo || {}) }; old.summary = [...new Set((it.summary + '\n' + (old.summary || '')).split('\n'))].slice(0, 80).join('\n'); old.time = it.time; old.title = it.title; old.refs = [...new Set([...(old.refs || []), ...(it.refs || [])])]; }
    else if (old) { const refs = old.synced ? it.refs : [...new Set([...(old.refs || []), ...(it.refs || [])])]; const refInfo = old.synced ? (it.refInfo || {}) : { ...(old.refInfo || {}), ...(it.refInfo || {}) }; Object.assign(old, it, { status: '未読', byUser: false, session: undefined, refs, refInfo }); delete old.synced; n++; }
    else { d.items.push({ ...it, status: '未読' }); n++; }
    continue;
  }
  // 本人以外から新しいメッセージが来たら(time が進んだら)、状態・byUser にかかわらず未読(↩ 返信)に戻す。session は残すので、
  // autostart.mjs が同じセッションを起こす(2026-11-17 ユーザー。前は既決だけ開き直し、本人が画面で変えた状態は保っていた)
  const newer = old && it.time && it.time > (old.time || '');
  if (newer) { delete old.fromMe; delete old.forMe; delete old.bump; }
  if (newer && !fromMe(it)) {
    Object.assign(old, it, { status: old.status }); markReplied(old, it.time, it.from); n++;
    console.error(`REPLY ${it.id}: 返信(${it.time})→ 未読`);
  // 既決の後に同じスレッドへ本人の返信などが来たら(time が新しくなったら)、既決のままにせず開き直す。session は残して「続きから」で前の経緯を引き継ぐ(2026-10-14 ユーザー指摘)
  } else if (old && old.status === '既決' && newer) {
    Object.assign(old, it, { status: it.status || '未決', byUser: false, reopened: new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16) }); delete old.synced; n++;
    console.error(`REOPEN ${it.id}: 既決の後に新着(${it.time})`);
  } else if (old) { const keep = old.byUser ? old.status : (it.status || old.status); Object.assign(old, it, { status: keep, byUser: old.byUser }); }
  else { d.items.push({ status: '未読', ...it }); n++; }
}
for (const i of d.items) if (i.refs && i.status !== '既決') for (const r of i.refs) if (refGot[r] && !(i.refInfo || {})[r]) (i.refInfo ??= {})[r] = refGot[r];
const jst = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16);
d.runs.push({ at: jst, added: n, note: process.argv[3] || '' }); d.runs = d.runs.slice(-200);
fs.writeFileSync(DB + '.tmp', JSON.stringify(d, null, 1)); fs.renameSync(DB + '.tmp', DB);
console.log(`added ${n}, total ${d.items.length}`);
for (const id of woke) { const it = d.items.find(x => x.id === id); console.error(`WAIT-FIRED ${id}: 続きのメッセージで待ちが成立`); if (it) await notify(it); }
