// 使い方: node ~/digest/item.mjs <item id>
//         node ~/digest/item.mjs --open   内容で続きにできる項目の一覧(新着チェックの continues の候補。lib.mjs の contTarget)。1件1行の JSON
// まとめページの項目を1件出す(「AIで対応」で起動された Claude が最初に読む。~/digest/CLAUDE.md)
import fs from 'fs'; import { threadOf, contTarget } from './lib.mjs'; import { DATA } from './conf.mjs';
const id = process.argv[2];
if (id === '--open') {
  for (const i of JSON.parse(fs.readFileSync(`${DATA}/items.json`, 'utf8')).items.filter(x => contTarget(x)))
    console.log(JSON.stringify({ id: i.id, status: i.status, time: i.time, from: i.from, title: i.title, action: i.action || '', session: !!i.session,
      ...(i.wait && !i.wait.fired ? { wait: { cond: i.wait.cond, at: i.wait.at, task: i.wait.task } } : {}) }));
  process.exit(0);
}
const it = JSON.parse(fs.readFileSync(`${DATA}/items.json`, 'utf8')).items.find(x => x.id === id);
if (!it) { console.error('no such item: ' + id); process.exit(1); }
if (it.held) { console.error('ローカルの確認で保留中の項目(held)。本人がまとめのページで「Claudeに渡す」を選ぶまで扱えません: ' + id); process.exit(3); }
const { session, ...rest } = it;
if (it.source === 'mail') rest.threadId = threadOf(it);
console.log(JSON.stringify(rest, null, 1));
