// 回の後の点検(2026-11-18 ユーザー「しばらくはチェックをするようにして」): 取り込みを Claude より前に機械でするようにしたので、
// 取ったものが Claude の段で抜けていないかを数えて run.log に出す。
//   メール: 取ったスレッド(下書き・送信済みを除く)が、どこか(項目の id・threadId・refs・link・まとめの文)に出ているか。
//           プロモーションは手順 1 で除いてよいので別に数える。
//   拡張の読む先: 拡張の fetched(read) が返す {unit, id, needle, alt?, loose?} ごとに、needle(か alt のどれか)が項目のどこかに出ているか(粒度は拡張が決める)。
//           対応不要のまとめ(misc:noaction)は手順で「サーバーごとに1行」のように粗く書くので、そこに loose が出ていれば
//           抜けには数えず「まとめに粗く」として別に数える。
// 出すのは件数と id だけ(件名・本文は出さない)。
// 使い方: node cover.mjs <dir>
import fs from 'fs';
import { loadItems } from './lib.mjs'; import { sources } from './ext.mjs';
const D = process.argv[2];
if (!D) { console.error('usage: cover.mjs <dir>'); process.exit(2); }
const read = f => { try { return fs.readFileSync(`${D}/${f}`, 'utf8'); } catch { return ''; } };
const items = loadItems().items;
const blob = JSON.stringify(items), naBlob = JSON.stringify(items.filter(i => i.id === 'misc:noaction'));
const mail = new Map();   // threadId → プロモーションか
for (const l of read('q-mail.jsonl').split('\n')) {
  let m; try { m = JSON.parse(l); } catch { continue; }
  const lb = m.labelIds || [];
  if (!m.threadId || lb.some(x => x === 'DRAFT' || x === 'SENT')) continue;
  mail.set(m.threadId, (mail.get(m.threadId) ?? true) && lb.includes('CATEGORY_PROMOTIONS'));
}
const missMail = [...mail].filter(([t]) => !blob.includes(t));
const parts = [`メール ${missMail.filter(([, p]) => !p).length}/${[...mail.values()].filter(p => !p).length}(プロモーション ${missMail.filter(([, p]) => p).length}/${[...mail.values()].filter(p => p).length})`];
const miss = missMail.filter(([, p]) => !p).map(([t]) => 'mail:' + t);
for (const s of sources) if (s.fetched) {
  let got = []; try { got = s.fetched(read) || []; } catch (e) { console.error(`cover: ${s.name}: ${String(e.message || e).split('\n')[0]}`); continue; }
  const by = new Map(); for (const x of got) by.set(`${x.unit}\t${x.id}`, x);
  const units = [...new Set([...by.values()].map(x => x.unit))];
  for (const u of units) {
    const all = [...by.values()].filter(x => x.unit === u), out = all.filter(x => ![x.needle, ...(x.alt || [])].some(n => blob.includes(n)));
    const rough = out.filter(x => x.loose && naBlob.includes(x.loose)), bad = out.filter(x => !rough.includes(x));
    parts.push(`${u} ${bad.length}/${all.length}${rough.length ? `(対応不要のまとめに粗く ${rough.length})` : ''}`); miss.push(...bad.map(x => `${u}:${x.id}`));
  }
}
console.log(`cover: どこにも出ていないもの ${parts.join('、')}`);
if (miss.length) console.log(`cover: 未処理 ${miss.slice(0, 20).join(' ')}${miss.length > 20 ? ` ほか ${miss.length - 20}` : ''}`);
