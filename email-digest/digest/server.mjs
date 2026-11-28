// 新着まとめビューア。Email の箱の中で動き、aiza 経由で本人だけが開ける
// URL: 設定の pageUrl(aiza の /email/ か /sandbox-box/mail/port9100/)
// 認証: nginx が付ける X-Aiza-User/-Exp/-Sig を ~/.aiza/viewer.key で検算(aiza の箱の画面と同じ方式)
import http from 'http'; import { spawn } from 'child_process'; import fs from 'fs'; import os from 'os'; import crypto from 'crypto';
import { CODE, DATA, conf, get as confGet } from './conf.mjs';
// 拡張の読む先(ext.mjs。無ければメールだけ)
import { sources, sourceOfUrl, EXT } from './ext.mjs';
// 表示の言語(i18n.mjs)。ページ・/rows・/row の ?lang= で、要求ごとに組み立てる前に決める(組み立ては同期なので要求どうしで混ざらない)
import { pickLang, translator, valueTranslator, weekday, clientScript, langRedirect } from './i18n.mjs';
let LANG = 'ja', L = translator('ja'), Lv = valueTranslator(L);
// 右上の「設定」(使うもの・ログインの見直し)。aiza の /email/ で開くときは、その隣の /email/setup(aiza の準備の画面)。設定の setupUrl で変えられる
const SETUP_URL = conf.setupUrl || (/\/email\/$/.test(conf.pageUrl || '') ? '/email/setup' : '');
const PORT = Number(process.env.DIGEST_PORT || 9100), HOME = os.homedir(), ME = os.userInfo().username;
const DB = `${DATA}/items.json`;
const KEY = fs.readFileSync(`${HOME}/.aiza/viewer.key`, 'utf8').trim();
const ST = ['未決', '未読', '既読', '既決'];
const CLIENT = fs.readFileSync(`${CODE}/client.js`, 'utf8').replace(/\/\*DIGEST_SESSION\*\/\{[^}]*\}/, JSON.stringify(conf.session));
// 読み上げ(2026-10-25)。種類名は芯のメールと拡張の label
const SPEAK = fs.readFileSync(`${CODE}/speak.js`, 'utf8').replace(/\/\*DIGEST_SAY_SRC\*\/\{[^}]*\}/, `{ ${[['mail', 'メール'], ...sources.map(s => [s.name, s.label])].map(([k, v]) => `${k}: ${JSON.stringify(v).replace(/^"|"$/g, "'")}`).join(', ')} }`);
// 見出し・ボタン・速報の文字(芯はメール。拡張の読む先を後ろに足す)
const LABELS = ['メール', ...sources.map(s => s.label)];
const quickExt = sources.filter(s => s.quick && s.quick.length);
const FAST = ['メール', ...quickExt.filter(s => s.quick.some(q => !q.slow)).map(s => s.label)].join('・');
const SLOW = quickExt.filter(s => s.quick.some(q => q.slow)).map(s => s.label).join('・');
function isOwner(req) {
  const u = req.headers['x-aiza-user'], exp = Number(req.headers['x-aiza-exp']), sig = String(req.headers['x-aiza-sig'] || '');
  if (u !== ME || !(exp > Date.now() / 1000)) return false;
  const want = crypto.createHmac('sha256', KEY).update(`${u}\n${exp}`).digest('hex');
  return sig.length === want.length && crypto.timingSafeEqual(Buffer.from(sig), Buffer.from(want));
}
const load = () => { try { return JSON.parse(fs.readFileSync(DB, 'utf8')); } catch { return { items: [], runs: [] }; } };
const save = d => { fs.writeFileSync(DB + '.tmp', JSON.stringify(d, null, 1)); fs.renameSync(DB + '.tmp', DB); };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
// 項目のセッションが書いた下準備の一行(set-prep.mjs)。その後に項目が更新されていたら(time が新しい)薄く出す
const prepLine = i => !i.prep || !i.prep.text ? '' : (i.time || '') > (i.prep.at || '')
  ? `<div class="pp old">${L('mail.prepared_t_updated_since', { t: esc(i.prep.text) })}</div>`
  : `<div class="pp">${L('mail.prepared_t', { t: esc(i.prep.text) })}</div>`;
// スマホのブラウザだと Gmail はスマホ版(/mail/mu/mp/)へ転送し、パソコン版の #all/FMfcgz… を捨てて受信箱を出す。
// スマホ版はスレッド ID(16進)を #cv/all/<id> で受け付けるので(2026-10-09 ユーザーが実機で確認)、その URL も持たせておき、ページ側で切り替える。
const mobileAttr = i => { const m = /^mail:([0-9a-f]{16})$/.exec(i.id); return m && i.link && i.link.includes('mail.google.com') ? ` data-mobile="https://mail.google.com/mail/mu/mp/39/#cv/all/${/^[0-9a-f]{16}$/.test(i.threadId || '') ? i.threadId : m[1]}"` : ''; };
// 「続きから」は aiza が作業フォルダ(digest)の会話一覧から探すので、別のフォルダ(cwd が ~/mailbox だった 10/9 以前など)で
// 始まった会話は見つからずにエラーになる(2026-10-11)。ページを出すときに、その会話ログを digest のフォルダへ写しておく
const PROJ = `${HOME}/.claude/projects`, DIGEST_PROJ = `${PROJ}/${`${HOME}/${conf.session.cwd}`.replace(/[^A-Za-z0-9]/g, '-')}`;
function adoptConversations(d) {
  for (const i of d.items) {
    const c = i.session && i.session.claude_session_id; if (!c || !/^[0-9a-f-]{36}$/.test(c) || fs.existsSync(`${DIGEST_PROJ}/${c}.jsonl`)) continue;
    try { const src = fs.readdirSync(PROJ).map(x => `${PROJ}/${x}/${c}.jsonl`).find(f => fs.existsSync(f));
      if (src) { fs.mkdirSync(DIGEST_PROJ, { recursive: true }); fs.copyFileSync(src, `${DIGEST_PROJ}/${c}.jsonl`); console.log('adopted', c, 'from', src); } } catch (e) { console.warn('adopt', c, e.message); }
  }
}
// 「今すぐチェック」の1段目の速報(要約前)。2段目が終わるまでだけ出す
// 動いている途中の状態(running/raw)でも、書いた quick-check.sh がもういない・20分を過ぎたものは止まった回として扱う
function quickState() {
  let q = {}; try { q = JSON.parse(fs.readFileSync(`${DATA}/quick.json`, 'utf8')); } catch { return q; }
  if ((q.state === 'running' || q.state === 'raw') && ((q.pid && !fs.existsSync(`/proc/${q.pid}`)) || !(Date.now() - Date.parse(q.at) < 20 * 60e3))) q.state = 'stopped';
  return q;
}
function quickRaw() {
  try { if (quickState().state !== 'raw') return '';
    const r = JSON.parse(fs.readFileSync(`${DATA}/quick/quick-raw.json`, 'utf8'));
    return `<h2>${L('mail.first_look')} <small>${L('mail.n_summarizing', { n: r.length })}${SLOW ? L('mail.x_follow', { x: SLOW }) : ''}</small></h2>` + (r.map(i => `<div class="it ${esc(i.source)}"><div class="hd">${srcBadge(i.source)} <span class="tm">${esc((i.time || '').replace('T', ' '))}</span> <b>${esc(i.from)}</b></div><div class="tt">${i.link ? `<a href="${esc(i.link)}" target="_blank">${esc(i.title)}</a>` : esc(i.title)}</div><div class="sm">${linkify(i.text)}</div></div>`).join('') || `<p class="none">${L('mail.nothing_new')}</p>`);
  } catch { return ''; }
}
// 要約の中の長い URL を短いリンク(読む先の名前・「メール」やドメイン名)にする(2026-10-16 ユーザー依頼)
const linkLabel = u => sourceOfUrl(u)?.label || (/mail\.google\.com/.test(u) ? L('mail.source.mail') : (/^https?:\/\/([^/]+)/.exec(u) || [, L('mail.link')])[1].replace(/^www\./, ''));
const linkifyBare = t => esc(t).replace(/https?:\/\/[^\s<>"'）)]+/g, u => `<a href="${u}" target="_blank">${linkLabel(u)}↗</a>`)
  // 元の種類はアイコンで出す(2026-11-04 ユーザー依頼)。要約の行頭の [メール] や [<読む先の名前>] も同じ
  .replace(KINDMARK, (m, k) => `<span class="ic" title="${k}">${SRC_ICON[KIND[k]]}</span>`);
const SRC_ICON = { mail: '📫', ...Object.fromEntries(sources.map(s => [s.name, s.icon || '🔗'])) };
const KIND = { メール: 'mail', ...Object.fromEntries(sources.map(s => [s.label, s.name])) };
const KINDMARK = new RegExp(`\\[(${Object.keys(KIND).map(k => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})\\]`, 'g');
// 要約の中の [表示](ref) を、その語をアンカーにしたリンクにする(2026-11-05 ユーザー依頼)。
// ref は mail:<threadId> か URL。空白区切りで複数書くと、2つ目からは語の後ろに ²³… の小さなリンクを付ける。info(項目の refInfo)があれば件名をツールチップに出す
const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/', RED = 'BCDFGHJKLMNPQRSTVWXZbcdfghjklmnpqrstvwxz';
const threadToken = hex => { let n = 0n; for (const c of Buffer.from(`f:${BigInt('0x' + hex)}`).toString('base64').replace(/=+$/, '')) n = n * 64n + BigInt(B64.indexOf(c)); let o = ''; while (n) { o = RED[Number(n % 40n)] + o; n /= 40n; } return o; }; // gmail.py の thread_token と同じ
const refHref = r => { const m = /^mail:([0-9a-f]+)$/.exec(r); return m ? [`https://mail.google.com/mail/u/?authuser=${encodeURIComponent(conf.account)}#all/${threadToken(m[1])}`, `https://mail.google.com/mail/mu/mp/39/#cv/all/${m[1]}`] : [r, '']; };
const refA = (r, text, info) => { const [h, mob] = refHref(r), t = (info || {})[r] && info[r].label; return `<a href="${esc(h)}"${mob ? ` data-mobile="${esc(mob)}"` : ''}${t ? ` title="${esc(t)}"` : ''} target="_blank">${text}</a>`; };
const SUP = '¹²³⁴⁵⁶⁷⁸⁹';
const REFMARK = /\[([^\]\n]+)\]\(((?:mail:[0-9a-f]+|https?:\/\/[^\s)]+)(?:\s+(?:mail:[0-9a-f]+|https?:\/\/[^\s)]+))*)\)/g;
const linkify = (t, info) => { t = String(t || ''); let out = '', at = 0;
  for (const m of t.matchAll(REFMARK)) { const rs = m[2].split(/\s+/);
    out += linkifyBare(t.slice(at, m.index)) + refA(rs[0], esc(m[1]), info) + rs.slice(1).map((r, k) => refA(r, `<sup>${SUP[k + 1] || k + 2}</sup>`, info)).join(''); at = m.index + m[0].length; }
  return out + linkifyBare(t.slice(at)); };
const refsInText = t => new Set([...String(t || '').matchAll(REFMARK)].flatMap(m => m[2].split(/\s+/)));
const srcBadge = s => SRC_ICON[s] ? `<span class="src ic" title="${esc(s)}">${SRC_ICON[s]}</span>` : `<span class="src">${esc(s)}</span>`;
// 締切(項目の due、"YYYY-MM-DD" か "YYYY-MM-DDTHH:MM"、JST)。未決・未読のときだけ、残り日数つきで出す(2026-10-17 ユーザー依頼)
function dueBadge(i) {
  if (!i.due || !/^(未決|未読)$/.test(i.status)) return '';
  const today = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10), day = i.due.slice(0, 10);
  const days = Math.round((Date.parse(day) - Date.parse(today)) / 86400e3);
  const text = (T, lang) => T('mail.due_d_rest', { d: md(i.due, lang), rest: days < 0 ? T('mail.n_days_overdue', { n: -days }) : days === 0 ? T('今日') : days === 1 ? T('mail.tomorrow') : T('mail.n_days_left', { n: days }) });
  // 読み上げ(speak.js)は日本語の声で読むので、日本語の文も持たせる
  return ` <span class="due${days <= 2 ? ' soon' : ''}" data-say="${esc(text(JA, 'ja'))}">${text(L, LANG)}</span>`;
}
// 待ち(wait.mjs。条件・日時のリマインダー、2026-10-23 ユーザー依頼): 成立前は状態の欄から外して「待ち」の欄に置き、成立したら未決の先頭に出す
const waiting = i => i.wait && !i.wait.fired && i.status !== '既決';
const firedNew = i => i.wait && i.wait.fired && !i.wait.told;
const sorted = (d, s) => d.items.filter(i => s === '待ち' ? waiting(i) : i.status === s && !waiting(i))
  // 対応不要のまとめは大事でないので、どの欄でも一番下(2026-10-30 ユーザー依頼)
  .sort((a, b) => (a.id === 'misc:noaction') - (b.id === 'misc:noaction') || firedNew(b) - firedNew(a) || (s === '待ち' ? (a.wait.at || '9').localeCompare(b.wait.at || '9') : (b.time || '').localeCompare(a.time || '')));
const JA = translator('ja');
const md = (t, lang = LANG) => { const w = weekday(lang, new Date(t.slice(0, 10) + 'T00:00:00Z').getUTCDay());
  return `${+t.slice(5, 7)}/${+t.slice(8, 10)}${lang === 'en' ? ` (${w})` : `(${w})`}${t.length > 10 ? ' ' + t.slice(11, 16) : ''}`; };
function waitBox(i) {
  if (!i.wait || i.status === '既決') return '';
  const w = i.wait, when = [w.at && md(w.at), w.cond && L('mail.when_x', { x: w.cond })].filter(Boolean).join(L('mail.or'));
  return w.fired ? (w.told ? '' : `<div class="wt fired">${L('mail.met_d_why', { d: esc(md(w.fired)), why: linkify(w.why) })}<br>${L('mail.task_x', { x: esc(w.task) })}</div>`)
    : `<div class="wt">${L('mail.waiting_x', { x: esc(when) })}<br>${L('mail.then_x', { x: esc(w.task) })}</div>`;
}
// 保留の項目(held。関門が止めたもの、2026-11-25): items.json には印だけ。題・要約・差出人は DATA/.local-only/prep.json にあり、ここだけが読む
const prepOf = () => { try { return JSON.parse(fs.readFileSync(`${DATA}/.local-only/prep.json`, 'utf8')); } catch { return {}; } };
let PREP = {};
const heldLink = i => i.link || (/^mail:[0-9a-f]+$/.test(i.id) ? refHref(i.id)[0] : '');
const HELD_WHY = { 決まり: 'mail.held_why_rule' };
const heldRow = (i, s) => { const p = PREP[i.id] || {}, title = p.title || p.subject || p.conv || i.id, link = heldLink(i), why = HELD_WHY[i.heldWhy] || 'mail.held_why_llm';
  return `
<div class="it held ${i.source}" data-id="${esc(i.id)}" data-time="${esc(i.time || '')}"><div class="hd">${srcBadge(i.source)} <span class="tm">${esc((i.time || '').replace('T', ' ').slice(0, 16))}</span> <b>${esc(p.from || '')}</b> <span class="hb">${L('mail.held_x', { x: L(why) })}</span>${p.due ? ` <span class="due">${esc(p.due)}</span>` : ''}</div>
<div class="tt">${link ? `<a href="${esc(link)}"${mobileAttr(i)}${i.heldKept ? '' : ` onclick="heldOpened('${esc(i.id)}')"`} target="_blank">${esc(title)}</a>` : esc(title)}</div>${p.conv && p.title ? `<div class="hd">${esc(p.conv)}</div>` : ''}
${p.summary ? `<div class="sm">${esc(p.summary)}</div>` : ''}${p.action ? `<div class="ac">${L('mail.action_x', { x: esc(p.action) })}</div>` : ''}${p.newer ? `<div class="nt">${L('mail.held_newer_x', { x: esc(md(p.newer)) })}</div>` : ''}<div class="nt">${L(i.heldKept ? 'mail.kept_from_claude' : 'mail.held_note')}</div>
<div class="bt"><button class="cl" onclick="heldAct('${esc(i.id)}','release',this)">${L('mail.give_to_claude')}</button>${ST.filter(x => x !== s).map(x => `<button onclick="st('${esc(i.id)}','${x}',this)">${L('mail.move_to_s', { s: Lv(x) })}</button>`).join('')}</div></div>`; };
// 関門がこの回の新着を Claude に渡さなかった(DATA/gate.json の withheld)。「決まりだけで進める」を出す
const gateState = () => { try { return JSON.parse(fs.readFileSync(`${DATA}/gate.json`, 'utf8')); } catch { return {}; } };
function gateBanner() {
  const g = gateState(); if (!g.withheld) return '';
  let since = ''; try { since = new Date((JSON.parse(fs.readFileSync(`${DATA}/cursor.json`, 'utf8')).last) * 1000 + 9 * 3600e3).toISOString().slice(0, 16); } catch {}
  return `<div class="wt fired" id="gate">${L('mail.gate_withheld_x', { x: esc(since ? md(since) : '?') })} <button onclick="gateBypass(this)">${L('mail.go_on_rules_only')}</button></div>`;
}
const row = (i, s) => i.held ? heldRow(i, s) : `
<div class="it ${i.source}"${i.id === 'misc:noaction' ? ' data-last="1"' : ''} data-id="${esc(i.id)}" data-time="${esc(i.time || '')}"><div class="hd">${srcBadge(i.source)} <span class="tm">${esc((i.time || '').replace('T', ' ').slice(0, 16))}</span> <b>${esc(i.from)}</b>${i.replied && i.status === '未読' ? ` <span class="rp" title="${L('mail.someone_else_replied_goes_away')}">${L('mail.reply')}</span>` : ''}${dueBadge(i)}</div>
<div class="tt">${i.link ? `<a href="${esc(i.link)}"${mobileAttr(i)} target="_blank">${esc(i.title)}</a>` : esc(i.title)}</div>
<div class="sm">${linkify(i.summary, i.refInfo)}</div>${i.action ? `<div class="ac">${L('mail.action_x', { x: esc(i.action) })}</div>` : ''}${i.note ? `<div class="nt">${L('mail.note_x', { x: esc(i.note) })}</div>` : ''}${prepLine(i)}${refList(i)}${waitBox(i)}${i.doneAsk && i.status === '既決' ? `<div class="wt">${L('mail.claude_decides_after_current_work')}</div>` : ''}
<div class="bt"><button class="cl" onclick="claude('${esc(i.id)}',this)">${L(i.session ? (i.session.deleted ? 'mail.continue_ai' : 'mail.open_ai') : 'mail.handle_ai')}</button>${waiting(i) ? `<button onclick="unwait('${esc(i.id)}',this)">${L('mail.stop_waiting')}</button>` : ''}${ST.filter(x => x !== s).map(x => `<button onclick="st('${esc(i.id)}','${x}',this)">${L('mail.move_to_s', { s: Lv(x) })}</button>`).join('')}</div></div>`;
// まとめ項目の元のメッセージ(refs)を開閉できる一覧で出す(2026-11-05 ユーザー依頼)。
// 差出人・件名は refInfo(add.mjs と ref-info.py が付ける)。無いものは URL だけ。新しい順
function refList(i) {
  // 要約の中でリンクにしたものは除き、残り(要約に印の無いもの)だけ出す
  const inText = refsInText(i.summary), rest = (i.refs || []).filter(r => !inText.has(r));
  if (!rest.length) return '';
  const info = i.refInfo || {};
  // 読む先の拡張が URL から時刻を出せれば出す(refInfo に time が無いとき)
  const refTime = r => { const s = sourceOfUrl(r); return s && s.refTime ? s.refTime(r) : ''; };
  const rs = rest.map(r => ({ r, time: refTime(r), ...(info[r] || {}) })).sort((a, b) => (b.time || '').localeCompare(a.time || ''));
  const li = rs.map(x => {
    const mail = /^mail:/.test(x.r), url = x.url || (mail ? '' : x.r);
    const src = mail ? null : sourceOfUrl(x.r);
    const label = x.label || (mail ? L('mail.mail_id', { id: x.r.slice(5) }) : linkLabel(x.r) + ' ' + (src && src.refLabel ? src.refLabel(x.r) : x.r));
    const tm = x.time ? `<span class="tm">${esc(md(x.time))}</span> ` : '';
    return `<li>${mail ? SRC_ICON.mail : src ? SRC_ICON[src.name] : '🔗'} ${tm}${url ? `<a href="${esc(url)}"${x.mobile ? ` data-mobile="${esc(x.mobile)}"` : ''} target="_blank">${esc(label)}</a>` : esc(label)}</li>`;
  }).join('');
  return `<details class="refs"><summary>${L(inText.size ? 'mail.original_messages_not_in_summary' : 'mail.original_messages_n', { n: rs.length })}</summary><ul>${li}</ul></details>`;
}
function page(d) {
  adoptConversations(d); PREP = prepOf();
  // 欄の並びは 未読・未決・待ち・既読・既決(2026-11-04 ユーザー依頼)
  const groups = ['未読', '未決', '待ち', '既読', '既決'].map(s => {
    const its = sorted(d, s);
    // どの欄も開閉でき、開閉はブラウザに覚えておく(localStorage、2026-10-23 ユーザー依頼)。既定は既決だけ閉じる。
    // 既決は開いたら、ページ全体のスクロールが下まで来たところで古いものを読み足す(/rows、2026-10-18。枠の中のスクロールは 10-23 にやめた)
    const rows = s === '既決' ? '' : its.slice(0, s === '既読' ? 60 : 500).map(i => row(i, s)).join('') || `<p class="none">${L('mail.none')}</p>`;
    return `<details id="g-${s}" data-s="${s}"${s === '既決' ? '' : ' open'} ontoggle="tog(this)"><summary><h2>${Lv(s)} <small class="n">${its.length}</small></h2></summary><div class="rows"${s === '既決' ? ' id="donebox"' : ''}>${rows}</div></details>`;
  }).join('');
  const last = d.runs.at(-1);
  return `<!doctype html><html lang="${LANG}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
${langRedirect(LANG)}<title>${L('mail.digest')}</title><style>
body{font-family:-apple-system,system-ui,sans-serif;margin:0 auto;max-width:760px;padding:12px 16px;background:#0b0f14;color:#e6e6e6;color-scheme:dark}
a{color:#7cb7ff}a:visited{color:#b59cff}
h1{font-size:1.2em}h2{font-size:1.05em;border-bottom:2px solid #3a4654;margin-top:1.4em}small{color:#9aa5b1}
.it{background:#131a22;border-radius:8px;padding:8px 10px;margin:8px 0;border:1px solid #1f2933}
.hd{font-size:.8em;color:#9aa5b1}.src{display:inline-block;padding:0 6px;border-radius:4px;background:#2a3440;color:#e6e6e6}
.mail .src{background:#1f3a5c}${sources.map(s => s.color ? `.${s.name} .src{background:${s.color}}` : '').join('')}.src.ic{background:none;padding:0;font-size:1.2em}
.due{display:inline-block;margin-left:6px;padding:0 6px;border-radius:4px;background:#2a3440;color:#cfd6dd}.due.soon{background:#b3261e;color:#fff}
.tt{font-weight:600;margin:3px 0}.rp{color:#7fd1ff;font-size:.85em;font-weight:bold}.sm{font-size:.92em;white-space:pre-wrap}.ac{font-size:.9em;color:#ffb366;margin-top:3px}
details>summary{cursor:pointer;list-style:none}details>summary h2{display:inline-block;width:calc(100% - 1.4em)}details>summary::before{content:'▶ ';color:#9aa5b1}details[open]>summary::before{content:'▼ '}
button{background:#1f2933;color:#e6e6e6;border:1px solid #3a4654;border-radius:6px;padding:3px 8px;cursor:pointer}button:hover{background:#2a3440}button:disabled{opacity:.5}
.bt button{margin:6px 6px 0 0;font-size:.85em}.bt .cl{font-weight:600;background:#1f3a5c;border-color:#2f5a8c}.nt{font-size:.88em;color:#8fc8ff;margin-top:3px}.pp{font-size:.88em;color:#b6e3a8;margin-top:3px}.pp.old{opacity:.5}.none{color:#7d8894}.run{font-size:.8em;color:#9aa5b1;white-space:pre-wrap}
.refs{font-size:.88em;margin-top:4px}.refs summary{color:#9aa5b1}.refs summary::before{content:'▶ '}.refs[open] summary::before{content:'▼ '}.refs ul{margin:4px 0;padding-left:1.2em;list-style:none}.refs li{margin:2px 0;padding-left:0}.refs .tm{color:#9aa5b1}
.wt{font-size:.88em;color:#c9b6ff;margin-top:3px;padding:3px 6px;border-left:3px solid #6b5bb3}.wt.fired{color:#fff;background:#3a2f6b;border-color:#b39cff}
.it.saying{border-color:#7cb7ff;box-shadow:0 0 0 2px #7cb7ff66}#sp{-webkit-touch-callout:none;user-select:none;-webkit-user-select:none;touch-action:manipulation}
.saypop{position:fixed;z-index:9;display:flex;flex-direction:column;gap:8px;padding:10px;background:#1f2933;border:1px solid #3a4654;border-radius:8px;box-shadow:0 4px 14px #0008;font-size:.9em;max-width:calc(100vw - 16px)}
.saypop label{display:flex;align-items:center;gap:8px}.saypop select{flex:1;min-width:0;max-width:16em;background:#131a22;color:#e6e6e6;border:1px solid #3a4654;border-radius:6px;padding:3px}.saypop button{align-self:flex-end}.saypop .sl{font-weight:bold;opacity:.8}.saypop [hidden]{display:none}.saypop .sn{opacity:.8;font-size:.9em}.saypop .sn:empty{display:none}#spbar{position:sticky;top:0;z-index:1;background:#0b0f14;padding:4px 0}
.it.held{border-color:#8c6d1f}.hb{display:inline-block;margin-left:6px;padding:0 6px;border-radius:4px;background:#5c4a12;color:#ffe9a8}.it.busy{opacity:.45;pointer-events:none}.it .mv{font-size:.85em;color:#ffb366;margin-top:4px}
#toast{position:fixed;left:50%;bottom:16px;transform:translateX(-50%);max-width:calc(100% - 32px);background:#1f2933;color:#e6e6e6;border:1px solid #3a4654;border-radius:8px;padding:8px 14px;font-size:.9em;box-shadow:0 2px 8px #0008;display:none}
h3.sub{font-size:.9em;color:#9aa5b1;margin:14px 0 4px;padding-bottom:2px;border-bottom:1px solid #2a3440;cursor:pointer;user-select:none}h3.sub::before{content:'▼ '}h3.sub.shut::before{content:'▶ '}.it.fold{display:none}h1{display:flex;align-items:baseline;gap:8px}h1 .ttl{flex:1}h1 .setup{font-size:.7em;font-weight:normal;color:#8fc8ff;text-decoration:none}
</style></head><body><h1><span class="ttl">${L('mail.digest_x', { x: LABELS.map(x => Lv(x)).join('・') })}</span>${SETUP_URL ? `<a class="setup" href="${SETUP_URL}">${L('mail.settings')}</a>` : ''}</h1>
<div class="run"><button id="qc" onclick="quick()">${L('mail.check_now_x', { x: [L('mail.source.mail'), ...sources.map(s => s.quickTag || s.label)].join('・') })}</button> <span id="qs"></span></div>
<div class="run" id="spbar" style="display:none"><button id="sp" title="${L('mail.long_press_speed_voice')}" onclick="sayAll()">${L('mail.read_out_do_unread')}</button><button id="spn" style="display:none" onclick="sayAt(sayIdx+1)">${L('mail.next')}</button> <button id="sps" style="display:none" onclick="sayStop()">${L('mail.stop')}</button> <span id="spi"></span></div>
<div class="run">${L('mail.last_check_x', { x: esc(last ? last.at.replace('T', ' ').slice(0, 16) + ' JST  ' + (last.note || '') : L('mail.not_yet')) })}</div>
${gateBanner()}${quickRaw()}${groups}<div id="toast"></div><script>
${clientScript(LANG)}
const ITEMS=${JSON.stringify(Object.fromEntries(d.items.map(i => [i.id, i]))).replace(/</g, '\\u003c')};
${CLIENT}
${SPEAK}
if (/Android|iPhone|iPad|iPod|Mobile/.test(navigator.userAgent)) document.querySelectorAll('a[data-mobile]').forEach(a => a.href = a.dataset.mobile);
// /email/#<項目id> でその項目へ飛ぶ(aiza のやること一覧からのリンク、2026-11-07)。欄に無ければ(既決など)/row でもらって先頭に出す
async function gotoHash(){const id=decodeURIComponent(location.hash.slice(1));if(!id)return;let el=[...document.querySelectorAll('.it[data-id]')].find(x=>x.dataset.id===id);
 if(!el){const h=await fetch(location.pathname.replace(/\\/?$/,'/')+'row?id='+encodeURIComponent(id)+LQ).then(r=>r.ok?r.text():'').catch(()=>'');if(!h)return;const w=document.createElement('div');w.innerHTML=h;el=w.querySelector('.it');if(!el)return;document.querySelector('h1').after(el)}
 const g=el.closest('details');if(g)g.open=true;el.scrollIntoView({block:'center'});el.classList.add('saying');setTimeout(()=>el.classList.remove('saying'),3000)}
gotoHash();window.addEventListener('hashchange',gotoHash);
const QB=location.pathname.replace(/\\/?$/,'/');
let doneN=0,doneBusy=false,doneEnd=false;
async function doneMore(){const b=document.getElementById('donebox');if(doneBusy||doneEnd||!document.getElementById('g-既決').open||doneN&&scrollY+innerHeight<document.documentElement.scrollHeight-600)return;doneBusy=true;
 const t=await fetch(QB+'rows?status='+encodeURIComponent('既決')+'&offset='+doneN+LQ).then(r=>r.text()).catch(()=>'');doneBusy=false;
 if(!t){doneEnd=true;if(!doneN)b.innerHTML='<p class="none">'+L('mail.none')+'</p>';return}b.insertAdjacentHTML('beforeend',t);doneN+=30;regroup();doneMore()}
// 既決は、今日・昨日・1週間以内・1ヶ月以内・それ以前の小見出しで分ける(項目の時刻、JST。2026-11-17 ユーザー依頼)。
// 読み足したとき・項目が出入りしたときに付け直す。並びは時刻の新しい順なので、見出しは上から順に一度ずつ
const BN=['今日','昨日','1週間以内','1ヶ月以内','それ以前'];
function bucket(t){if(!t)return 4;const d=(Date.parse(new Date(Date.now()+9*3600e3).toISOString().slice(0,10))-Date.parse(t.slice(0,10)))/864e5;return d<=0?0:d<=1?1:d<=7?2:d<=31?3:4}
// 小見出しは押すと閉じる・開く(その下の項目を隠す)。閉じたものはブラウザに覚えておく(既決の欄の開閉と同じ OPEN に「既決:<見出し>」)
function regroup(){const b=document.getElementById('donebox');if(!b)return;b.querySelectorAll(':scope>h3.sub').forEach(h=>h.remove());let last=-1,shut=false;for(const x of b.querySelectorAll(':scope>.it')){const k=x.dataset.last?4:bucket(x.dataset.time||'');if(k!==last){const h=document.createElement('h3');h.className='sub';h.textContent=Lv(BN[k]);h.dataset.k=BN[k];shut=OPEN['既決:'+BN[k]]===false;if(shut)h.classList.add('shut');h.onclick=()=>{OPEN['既決:'+h.dataset.k]=h.classList.contains('shut');try{localStorage.setItem('digest-open',JSON.stringify(OPEN))}catch{}regroup();doneMore()};b.insertBefore(h,x);last=k}x.classList.toggle('fold',shut)}}
const OPEN=(()=>{try{return JSON.parse(localStorage.getItem('digest-open'))||{}}catch{return {}}})();
function tog(el){OPEN[el.dataset.s]=el.open;try{localStorage.setItem('digest-open',JSON.stringify(OPEN))}catch{}if(el.dataset.s==='既決')doneMore()}
document.querySelectorAll('details[data-s]').forEach(el=>{const o=OPEN[el.dataset.s];if(o!==undefined&&o!==el.open)el.open=o});
addEventListener('scroll',doneMore,{passive:true});
async function qpoll(prev){const q=await fetch(QB+'quick-status').then(r=>r.json()).catch(()=>({}));const el=document.getElementById('qs'),b=document.getElementById('qc');
 const live=(q.state==='running'||q.state==='raw')&&Date.now()-Date.parse(q.at)<20*60e3, st=live?q.state:'idle';
 if(prev&&prev!==st&&prev!=='start'&&(st==='raw'||st==='idle'))return location.reload();
 if(prev==='start'&&q.state==='busy'){b.disabled=false;el.textContent=L('mail.regular_check_running_press_again');return}
 if(prev==='start'&&st==='idle'&&(q.state==='done'||q.state==='gated')&&Date.now()-Date.parse(q.at)<60e3)return location.reload();
 if(live){b.disabled=true;el.textContent=st==='running'?L('mail.checking_x_about_10_seconds',{x:${JSON.stringify(FAST.replace(/^メール/, L('mail.source.mail')))}}):${SLOW ? `L('mail.showing_first_look_summary_x',{x:${JSON.stringify(SLOW)}})` : `L('mail.showing_first_look_summary_in')`};return setTimeout(()=>qpoll(st),3000)}
 if(prev==='start')return setTimeout(()=>qpoll('start'),2000);
 b.disabled=false}
async function quick(){document.getElementById('qc').disabled=true;document.getElementById('qs').textContent=L('mail.starting');await fetch(QB+'quick-check',{method:'POST'});setTimeout(()=>qpoll('start'),1500)}
qpoll(null);
// 状態の変更はページを読み直さず、その場で項目を移す。既決のセッションの停止(aiza が Claude の終了を最大10秒待つ)は裏で進め、下に経過を出す(2026-10-22 ユーザー指摘)
function toast(t,ms){const e=document.getElementById('toast');e.textContent=t;e.style.display=t?'block':'none';clearTimeout(e._t);if(ms)e._t=setTimeout(()=>e.style.display='none',ms)}
async function unwait(id,btn){if(!await popConfirm(L('mail.stop_waiting_2')))return;const r=await fetch(QB+'wait-clear',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id})});if(!r.ok)return popToast(L('mail.failed_x',{x:r.status}),true);location.reload()}
async function heldAct(id,act,btn){if(act==='release'&&!await popConfirm(L('mail.give_to_claude_confirm'),{danger:true}))return;btn.disabled=true;const r=await fetch(QB+'held',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id,act})}).catch(e=>({ok:false,status:e.message}));if(!r.ok){btn.disabled=false;return popToast(L('mail.failed_x',{x:r.status}),true)}location.reload()}
// 保留の項目の元を開いたら、AI に渡さないと決めたことにする(2026-11-27 利用者「開いても渡さないと選んだと判断して」)。開くのは止めない
function heldOpened(id){const el=document.querySelector('.it[data-id="'+CSS.escape(id)+'"]');if(el)el.querySelectorAll('.tt a[onclick]').forEach(a=>a.removeAttribute('onclick'));fetch(QB+'held',{method:'POST',keepalive:true,headers:{'content-type':'application/json'},body:JSON.stringify({id,act:'keep'})}).then(r=>{if(r.ok&&el)el.querySelectorAll('.nt').forEach(n=>{if(n.textContent===L('mail.held_note'))n.textContent=L('mail.kept_from_claude')})}).catch(()=>{})}
async function gateBypass(btn){if(!await popConfirm(L('mail.go_on_rules_only_confirm'),{danger:true}))return;btn.disabled=true;await fetch(QB+'gate-bypass',{method:'POST'});setTimeout(()=>qpoll('start'),1500)}
function bump(s,k){const n=document.querySelector('#g-'+s+' .n');if(n)n.textContent=Math.max(0,+n.textContent+k)}
async function st(id,s,btn){
 const el=btn&&btn.closest('.it'),from=ITEMS[id]&&ITEMS[id].status;
 if(el){el.classList.add('busy');el.insertAdjacentHTML('beforeend','<div class="mv">'+L('mail.moving_s',{s:Lv(s)})+'</div>')}
 const live=s==='既決'?await liveSession(ITEMS[id]).catch(()=>null):null;
 const r=await fetch(QB+'status',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id,status:s,ask:!!live})}).catch(e=>({ok:false,status:e.message}));
 if(!r.ok){if(el){el.classList.remove('busy');el.querySelector('.mv').remove()}return popToast(L('mail.failed_x',{x:r.status}),true)}
 ITEMS[id].status=s;if(live)ITEMS[id].doneAsk=1;else delete ITEMS[id].doneAsk;
 if(live){toast(L('mail.asking_claude_decide_once_work'));
  askDone(id,live.id).then(()=>toast(L('mail.done_if_claude_decides_still'),5000)).catch(async e=>{toast(L('mail.could_not_reach_claude_so',{x:e.message}),8000);
   await fetch(QB+'status',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({id,status:'既決'})});delete ITEMS[id].doneAsk;cleanupSessions(null,true)})}
 else if(s==='既決'&&ITEMS[id].session&&!ITEMS[id].session.deleted){toast(L('mail.stopping_archiving_claude_session'));
  cleanupSessions(null,true).then(left=>toast(L(left?'mail.stopping_session_needs_unlock_button':'mail.stopped_archived_claude_session'),4000)).catch(e=>toast(L('mail.could_not_stop_session_x',{x:e.message}),8000))}
 if(el){const box=el.parentNode;el.remove();if(box&&box.classList.contains('rows')&&!box.querySelector('.it'))box.innerHTML='<p class="none">'+L('mail.none')+'</p>';if(box&&box.id==='donebox')regroup()}
 const wt=ITEMS[id].wait&&!ITEMS[id].wait.fired;if(from)bump(wt&&from!=='既決'?'待ち':from,-1);bump(wt&&s!=='既決'?'待ち':s,1);
 const w=ITEMS[id].wait,dest=s==='既決'?(doneN?document.getElementById('donebox'):null):document.querySelector('#g-'+(w&&!w.fired?'待ち':s)+' .rows');
 if(!dest)return;
 const h=await fetch(QB+'row?id='+encodeURIComponent(id)).then(r=>r.ok?r.text():'').catch(()=>'');if(!h)return;
 const t=document.createElement('div');t.innerHTML=h.trim();const nr=t.firstElementChild;if(!nr)return;
 const nn=dest.querySelector('p.none');if(nn)nn.remove();
 const after=nr.dataset.last?null:[...dest.querySelectorAll(':scope>.it')].find(x=>x.dataset.last||(x.dataset.time||'')<(nr.dataset.time||''));
 dest.insertBefore(nr,after||null);
 if(dest.id==='donebox')regroup();
}
</script></body></html>`;
}
http.createServer((req, res) => {
  if (!isOwner(req)) { res.writeHead(403); return res.end('forbidden'); }
  LANG = pickLang(new URL(req.url, 'http://x').searchParams.get('lang')); L = translator(LANG); Lv = valueTranslator(L);
  const path = req.url.split('?')[0].replace(/^\/(sandbox-box\/mail\/port9100|email)(?=\/|$)/, '') || '/';
  // 「今すぐチェック」: quick-check.sh を裏で起動し、状態は quick.json を返す(2026-10-16)
  if (req.method === 'POST' && path === '/quick-check') {
    spawn('sh', [`${CODE}/quick-check.sh`], { detached: true, stdio: 'ignore' }).unref();
    res.writeHead(200); return res.end('started');
  }
  if (path === '/rows') {
    const q = new URL(req.url, 'http://x').searchParams, st = q.get('status'), off = Math.max(0, +q.get('offset') || 0);
    PREP = prepOf();
    const html = ST.includes(st) ? sorted(load(), st).slice(off, off + 30).map(i => row(i, st)).join('') : '';
    res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' }); return res.end(html);
  }
  if (path === '/row') {
    const id = new URL(req.url, 'http://x').searchParams.get('id'), it = load().items.find(x => x.id === id); PREP = prepOf();
    res.writeHead(it ? 200 : 404, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' }); return res.end(it ? row(it, it.status) : '');
  }
  // aiza の backend が「やること」一覧に出す数と、生きている digest セッションの項目の題(2026-11-07、root セッションと決めた)。
  // 題は aiza のログイン済みの一覧にだけ出す約束(通知には出さない)。session は aiza のセッション id、claude は Claude の会話 id
  if (path === '/counts') {
    const d = load(), live = d.items.filter(i => i.session && !i.session.deleted);
    const body = { unread: sorted(d, '未読').filter(i => i.id !== 'misc:noaction').length, undecided: sorted(d, '未決').length,
      fired: d.items.filter(i => i.wait && i.wait.fired && !i.wait.told && i.status !== '既決').length,
      items: Object.fromEntries(live.map(i => [i.id, { title: String(i.title || '').slice(0, 80), url: '/email/#' + encodeURIComponent(i.id), status: i.status, session: i.session.id, claude: i.session.claude_session_id || '' }])) };
    res.writeHead(200, { 'content-type': 'application/json; charset=utf-8', 'cache-control': 'no-store' }); return res.end(JSON.stringify(body));
  }
  if (path === '/quick-status') {
    res.writeHead(200, { 'content-type': 'application/json', 'cache-control': 'no-store' }); return res.end(JSON.stringify(quickState()));
  }
  if (req.method === 'POST' && path === '/status') {
    let b = ''; req.on('data', c => b += c); req.on('end', () => {
      try { const { id, status, ask } = JSON.parse(b); if (!ST.includes(status)) throw 0;
        const d = load(); const it = d.items.find(x => x.id === id); if (!it) throw 0;
        it.status = status; it.changed = new Date().toISOString(); it.byUser = true; delete it.replied;
        // 保留の項目を欄へ移したら、AI に渡さないと決めたことにする(gate.py keep と同じ heldKept、JST。2026-11-27 利用者:
        // 「渡さないボタン不要です。渡す以外を押したらその時点で、渡さないという判断をしたと扱ってください」)
        if (it.held && !it.heldKept) it.heldKept = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16);
        // ask: 生きている Claude セッションのある項目を既決にした。Claude が作業を終えて既決にしてよいか決めるまで、元の片付けとセッションの停止を待つ(2026-11-07 ユーザー依頼)
        if (status === '既決' && ask) it.doneAsk = new Date().toISOString(); else delete it.doneAsk;
        save(d); res.writeHead(200); res.end('ok');
        // 既決にしたらすぐ元も片付ける: メールはアーカイブ(gmail.py のトークンが gmail.modify なら)、拡張の読む先は既読
        if (status === '既決' && !ask) spawn('node', [`${CODE}/done-sync.mjs`], { detached: true, stdio: ['ignore', fs.openSync(`${DATA}/done-sync.log`, 'a'), fs.openSync(`${DATA}/done-sync.log`, 'a')] }).unref();
      } catch { res.writeHead(400); res.end('bad'); } });
    return;
  }
  // 保留の項目の「AIに渡す」(release)と、元を開いたときの「渡さないと決めた」(keep。欄へ移したときは /status が heldKept を付ける)。拡張の held のコマンドを $ID に項目の id で動かし、終わるのを待つ
  if (req.method === 'POST' && path === '/held') {
    let b = ''; req.on('data', c => b += c); req.on('end', () => {
      let id, act; try { ({ id, act } = JSON.parse(b)); } catch {}
      const it = typeof id === 'string' && load().items.find(x => x.id === id);
      if (!it || !it.held || !['release', 'keep'].includes(act)) { res.writeHead(400); return res.end('bad'); }
      const p = spawn('sh', ['-c', `node "${CODE}/ext.mjs" cmds held ${act} | while read -r c; do sh -c "$c" < /dev/null || exit 1; done`],
        { env: { ...process.env, CODE, DATA, EXT, ID: id }, stdio: ['ignore', 'ignore', 'pipe'] });
      let err = ''; p.stderr.on('data', c => err += c);
      p.on('exit', code => {
        if (code !== 0 || load().items.find(x => x.id === id)?.held === (act === 'release')) { console.warn('held', act, id, err.slice(-300)); res.writeHead(500); return res.end('failed'); }
        res.writeHead(200); res.end('ok');
        // 渡したら、未決になった項目のセッションをすぐ起こす(普段の回を待たない)
        if (act === 'release') spawn('node', [`${CODE}/autostart.mjs`], { detached: true, stdio: 'ignore' }).unref();
      });
    });
    return;
  }
  // 関門が止めた回の「決まりだけで進める」: ローカルに届かない間だけ、決まりに当たらないものを渡す(gate.json の bypass。届いた回に消える)。そのまま今すぐチェック
  if (req.method === 'POST' && path === '/gate-bypass') {
    const g = gateState(); g.bypass = true; g.bypassAt = new Date().toISOString();
    fs.writeFileSync(`${DATA}/gate.json.tmp`, JSON.stringify(g)); fs.renameSync(`${DATA}/gate.json.tmp`, `${DATA}/gate.json`);
    spawn('sh', [`${CODE}/quick-check.sh`], { detached: true, stdio: 'ignore' }).unref();
    res.writeHead(200); return res.end('started');
  }
  if (req.method === 'POST' && path === '/session') {
    // まとめページが起動した aiza セッションを項目に紐付ける(次からは「開く」になる)
    let b = ''; req.on('data', c => b += c); req.on('end', () => {
      try { const { id, session } = JSON.parse(b); if (!session || !/^[\w-]+$/.test(session.id || '')) throw 0;
        const d = load(); const it = d.items.find(x => x.id === id); if (!it) throw 0;
        it.session = { id: session.id, claude_session_id: String(session.claude_session_id || ''), created: String(session.created || ''), seen: String(session.seen || '').slice(0, 64) };
        if (it.status === '未読' || it.status === '既読') { it.status = '未決'; it.byUser = true; }
        save(d); res.writeHead(200); res.end('ok');
      } catch { res.writeHead(400); res.end('bad'); } });
    return;
  }
  // 待ちの成立を Claude に伝えた(told)/待ちを外す(clear)
  if (req.method === 'POST' && (path === '/wait-told' || path === '/wait-clear')) {
    let b = ''; req.on('data', c => b += c); req.on('end', () => {
      try { const { id } = JSON.parse(b); const d = load(); const it = d.items.find(x => x.id === id); if (!it || !it.wait) throw 0;
        if (path === '/wait-told') it.wait.told = new Date().toISOString(); else delete it.wait;
        save(d); res.writeHead(200); res.end('ok');
      } catch { res.writeHead(400); res.end('bad'); } });
    return;
  }
  if (req.method === 'POST' && path === '/session-deleted') {
    let b = ''; req.on('data', c => b += c); req.on('end', () => {
      try { const { id, archived } = JSON.parse(b); const d = load(); const it = d.items.find(x => x.id === id); if (!it || !it.session) throw 0;
        // deleted は「既決で片付け済み」の印。2026-10-17 から削除でなくアーカイブなので archived も付ける(続きから開くとき replace_session に使う)
        it.session.deleted = new Date().toISOString(); if (archived) it.session.archived = true; save(d); res.writeHead(200); res.end('ok');
      } catch { res.writeHead(400); res.end('bad'); } });
    return;
  }
  res.writeHead(200, { 'content-type': 'text/html; charset=utf-8', 'cache-control': 'no-store' }); res.end(page(load()));
}).listen(PORT, '0.0.0.0', () => console.log('digest: ' + conf.pageUrl));

// 待ちの日時が来たら成立させて通知する(wait.mjs tick、1分ごと)
setInterval(() => { const log = fs.openSync(`${DATA}/wait.log`, 'a'); spawn('node', [`${CODE}/wait.mjs`, 'tick'], { stdio: ['ignore', log, log] }).on('exit', () => fs.closeSync(log)); }, 60e3);
// 1時間おきに動かすもの(設定の hooks.hourly。ログインを保つ keep-login など、2026-10-13)。シェルで $HOME などを展開する
setInterval(() => { for (const h of conf.hooks.hourly || []) { const c = typeof h === 'string' ? h : h.cmd; if (c) spawn('sh', ['-c', c], { detached: true, stdio: 'ignore' }).unref(); } }, 3600e3);
