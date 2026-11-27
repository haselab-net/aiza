// 項目のスレッドの印(match.mjs が取り込みと突き合わせ、add.mjs が突き合わせ済みの話で別の項目を作らないようにする)。
// メールは今のスレッドと、同じ話にまとめた前のスレッド(refs)。拡張の読む先は拡張の keys(項目)。
// marks は突き合わせで当たったメッセージの印(match.mjs が残す。そのメッセージへの返信も同じ項目に当てるため)
import { threadOf } from './lib.mjs'; import { sources } from './ext.mjs';
// 保留中の項目(held。関門が止めたもの)にも当てない: 返信で進めるとセッションが起きるため
export const skipItem = i => /^misc:/.test(i.id || '') || i.source === 'misc' || !!i.held;
const mailKeys = i => i.source === 'mail' ? [threadOf(i), ...(i.refs || []).filter(r => /^mail:[0-9a-f]{16}$/.test(r)).map(r => r.slice(5))].filter(Boolean).map(t => 'mail:' + t) : [];
export const keysOf = i => [...mailKeys(i), ...sources.flatMap(s => s.name === i.source && s.keys ? s.keys(i) || [] : []), ...(Array.isArray(i.marks) ? i.marks : [])];
