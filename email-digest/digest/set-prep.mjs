// 使い方: node ~/digest/set-prep.mjs <item id> "<一行>"   (消すときは --clear)
// 項目に対応するセッションが、下準備の結果(何を用意したか+本人が決めること)を一行で項目に書く(2026-11-14)。
// まとめページの項目の下に「下準備:」で出る。状態・byUser・changed は変えない(set-status の note とは別)。
// at は項目の time と同じ形(JST の YYYY-MM-DDTHH:MM)。項目がその後に更新されたら、ページは薄く出す。
import fs from 'fs'; import { DATA } from './conf.mjs';
const DB = `${DATA}/items.json`, MAX = 200;
const [id, text] = process.argv.slice(2);
if (!id || !text || !text.trim()) { console.error('usage: set-prep.mjs <id> "<一行>" | --clear'); process.exit(2); }
const d = JSON.parse(fs.readFileSync(DB, 'utf8'));
const it = d.items.find(x => x.id === id);
if (!it) { console.error('no such item: ' + id); process.exit(1); }
if (it.held) { console.error('ローカルの確認で保留中の項目(held)。本人がまとめのページで「Claudeに渡す」を選ぶまで扱えません: ' + id); process.exit(3); }
if (text === '--clear') delete it.prep;
else {
  const jst = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16);
  const one = text.replace(/\s+/g, ' ').trim();
  it.prep = { text: one.length > MAX ? one.slice(0, MAX - 1) + '…' : one, at: jst };
}
fs.writeFileSync(DB + '.tmp', JSON.stringify(d, null, 1), { mode: 0o600 }); fs.renameSync(DB + '.tmp', DB);
console.log(`${id}: ${it.prep ? '下準備: ' + it.prep.text : '下準備を消した'}`);
