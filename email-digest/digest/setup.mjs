// 新着まとめを始める準備(ARCHITECTURE.md 2 の共用方式)。aiza の 📨 新着まとめの画面と、箱の Claude の両方が使う。
// 共用のコピーから利用者として動かす(箱の中でも、ホストの本人の backend からでも同じファイルを触る):
//   node <共用のコピー>/digest/setup.mjs status [--json]      何が済んで何が残っているか
//   node <共用のコピー>/digest/setup.mjs init --name <名前> [--sources gmail,calendar,<読む先>]
//                                       入口を作り、local/config.json(me・sources)と ~/.config/mailbox/oauth.json を書く
//   node <共用のコピー>/digest/setup.mjs confirm <読む先>   本人が済ませたと言った手作業(箱のブラウザでのログイン)を記録
//   node <共用のコピー>/digest/setup.mjs login <gmail|calendar>   (箱の中で)ホストに Google のログインを始めてもらい、箱の画面に出す
//   node <共用のコピー>/digest/setup.mjs open <読む先>            (箱の中で)箱のブラウザの画面(noVNC)にログインのページを出す
//   node <共用のコピー>/digest/setup.mjs show <Google の承認の URL>   (箱の中で)それを箱の画面に出す
//   node <共用のコピー>/digest/setup.mjs whoami <読む先>   (箱の中で)箱のブラウザでその読む先にログインしている名前を読み、準備の画面に出す
//   node <共用のコピー>/digest/setup.mjs close                    (箱の中で)その画面を閉じる(ログインは箱のブラウザに残る)
// 本人のパスワードは扱わない。ログインは本人が画面で入れる。既にある本人の値は、指定されたもの以外は変えない。
import fs from 'fs'; import os from 'os'; import path from 'path'; import { fileURLToPath } from 'url'; import { execFileSync, spawnSync } from 'child_process';

const CODE = path.dirname(fileURLToPath(import.meta.url));
const HOME = process.env.MAILBOX_HOME || process.env.HOME;
const DATA = process.env.DIGEST_DATA || path.join(HOME, 'digest');
const LOCAL = process.env.DIGEST_LOCAL || path.join(DATA, 'local');
const CONFIG = path.join(LOCAL, 'config.json');
const STATE = path.join(LOCAL, 'setup.json');       // 本人が済ませたと言った手作業({confirmed: {<読む先>: 時刻, …}})
const OAUTH = path.join(HOME, '.config', 'mailbox', 'oauth.json');
const ACCOUNTS = path.join(LOCAL, 'accounts.json');   // 箱のブラウザでログインしている名前(whoami が書く。{読む先: {name, at}})
// 選べる読む先。gmail は芯(外せない)。calendar はログインだけ。ほかは拡張の読む先(表示名のある ext/<名前>.mjs)で、
// loginUrl のあるものは本人が箱のブラウザでログインする
process.env.DIGEST_DATA ||= DATA;   // ext.mjs が読む設定を、この箱のものに合わせてから
const { allExts } = await import('./ext.mjs');
export const CHOICES = [
  { id: 'gmail', label: 'Gmail', required: true },
  { id: 'calendar', label: 'Google カレンダー', label_key: 'digest.setup.choice.calendar' },
  ...allExts.filter(e => e.label).map(e => ({ id: e.name, label: e.label, ...(e.loginUrl ? { url: e.loginUrl } : {}), ...(e.whoami ? { whoami: true } : {}) })),
];
const ids = new Set(CHOICES.map(c => c.id));
const inBox = () => fs.existsSync('/.dockerenv');
const readJson = f => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return null; } };
function writeJson(f, v) {
  fs.mkdirSync(path.dirname(f), { recursive: true, mode: 0o700 });
  const tmp = `${f}.setup-${process.pid}`; fs.writeFileSync(tmp, JSON.stringify(v, null, 2) + '\n', { mode: 0o600 }); fs.renameSync(tmp, f);
}
// ログインしているアカウント(本人に見せるだけ。gmail.py が .gmail/account に、Claude Code が ~/.claude.json に書く)
const line = f => { try { return fs.readFileSync(f, 'utf8').trim().split('\n')[0].slice(0, 200); } catch { return ''; } };
const isFile = f => { try { const s = fs.lstatSync(f); return s.isFile() && s.uid === os.userInfo().uid; } catch { return false; } };

export function chosen(c = readJson(CONFIG)) {
  const s = c && Array.isArray(c.sources) ? c.sources.filter(x => ids.has(x)) : null;
  return s ? [...new Set(['gmail', ...s])] : null;
}

// 手順の一覧。done は今のファイルから決める(覚えておくのは本人の手作業の「済んだ」だけ)
// claude.ai の Gmail コネクタの手順は 2026-11-24 に外した(gmail.py が gmail.modify で全部できる。利用者「手順を外して修正してください」)
const MODIFY = 'https://www.googleapis.com/auth/gmail.modify';
function gmailStep() {
  const tok = readJson(path.join(HOME, '.gmail', 'token.json')), has = fs.existsSync(path.join(HOME, '.gmail', 'token.json'));
  const relogin = has && !(tok && Array.isArray(tok.scopes) && tok.scopes.includes(MODIFY));
  return { id: 'gmail', label: relogin ? 'Gmail にログインし直す(今のログインは読むだけで、アーカイブできない)' : 'Gmail にログイン',
    label_key: relogin ? 'digest.setup.step.gmail_relogin' : 'digest.setup.step.gmail', done: has && !relogin,
    login: 'google', account: line(path.join(HOME, '.gmail', 'account')), ...(relogin ? { relogin: true } : {}) };
}

// 手順と読む先の名前は、画面が本人の言語で出せるよう鍵(label_key、vars)も持つ(the deployment notes。辞書は aiza の ext/digest/static/digest-setup.js)。
// label は日本語のまま(箱の Claude や端末で読む人のため)
export function status() {
  // sources の無い設定(この道具より前に始めた人)は全部を使っている。一度でも動いたこと(items.json)があれば、手作業は済んでいる
  const c = readJson(CONFIG), st = readJson(STATE) || {}, src = chosen(c) || (c ? CHOICES.map(x => x.id) : []);
  const ran = fs.existsSync(path.join(DATA, 'items.json')), ok = new Proxy(st.confirmed || {}, { get: (o, k) => ran || o[k] });
  const steps = [
    { id: 'choose', label: '使うものと名前を選ぶ', label_key: 'digest.setup.step.choose', done: !!(c && c.me && c.me.name) },
    // 入口と、Google のログインに使う研究室の共用の設定(~/.config/mailbox/oauth.json)。どちらも init が自動で作る。アカウントとは関係しない
    { id: 'entries', label: '箱の準備(自動)', label_key: 'digest.setup.step.entries', done: isFile(path.join(DATA, 'start.sh')) && isFile(path.join(DATA, 'run-check.sh')) && !!readJson(OAUTH) },
    // gmail.py だけで一覧・本文・アーカイブができるのは gmail.modify のトークン(2026-10-09 から)。それより前の読み取り専用のものはログインし直す
    gmailStep(),
  ];
  if (src.includes('calendar')) steps.push({ id: 'calendar', label: 'Google カレンダーにログイン', label_key: 'digest.setup.step.calendar', done: fs.existsSync(path.join(HOME, '.gcal', 'token.json')), login: 'google', account: line(path.join(HOME, '.gcal', 'account')) });
  steps.push({ id: 'claude', label: '新着まとめ用の Claude ログイン', label_key: 'digest.setup.step.claude', done: fs.existsSync(path.join(HOME, '.claude', '.credentials.json')),
    account: fs.existsSync(path.join(HOME, '.claude', '.credentials.json')) ? (((readJson(path.join(HOME, '.claude.json')) || {}).oauthAccount || {}).emailAddress || '') : '' });
  const acc = readJson(ACCOUNTS) || {};
  // 箱のブラウザで読んだときにログインの画面だった(loggedOut)なら、済んだ印があっても済んでいない(ログインし直す)
  for (const ch of CHOICES) if (ch.url && src.includes(ch.id)) {
    const a = acc[ch.id] || {};
    steps.push({ id: ch.id, label: `${ch.label} にログイン(箱のブラウザで)`, label_key: 'digest.setup.step.box_login', vars: { name: ch.label }, done: !!ok[ch.id] && !a.loggedOut, manual: true, login: 'box',
      account: a.name || '', ...(a.loggedOut ? { loggedOut: true } : {}), ...(ch.whoami ? { whoami: true } : {}) });
  }
  return { steps, ready: steps.every(s => s.done), sources: src, name: (c && c.me && c.me.name) || '', choices: CHOICES };
}

export function init({ name, sources }) {
  name = String(name || '').trim();
  if (!name || name.length > 40 || /[\n"\\]/.test(name)) throw new Error('名前は 1〜40 文字で');
  const src = String(sources || 'gmail').split(',').map(s => s.trim()).filter(Boolean);
  const bad = src.filter(s => !ids.has(s)); if (bad.length) throw new Error('知らない読む先: ' + bad.join(', '));
  // 1. 入口(何度動かしても同じ。入口でない本人のファイルは上書きしない)
  const r = spawnSync(process.execPath, [path.join(CODE, 'entries.mjs'), 'install'], { encoding: 'utf8', env: { ...process.env, HOME, DIGEST_DATA: DATA } });
  if (r.status !== 0) throw new Error('入口を作れなかった: ' + String(r.stderr || r.stdout).trim().slice(-300));
  // 2. 設定。無ければ見本から。me は空のところだけ埋め、sources は選んだものにする
  const ex = JSON.parse(execFileSync(process.execPath, [path.join(CODE, 'conf.mjs'), 'example'], { encoding: 'utf8', env: { ...process.env, DIGEST_DATA: DATA, DIGEST_LOCAL: LOCAL } }));
  const c = readJson(CONFIG) || JSON.parse(JSON.stringify(ex));
  const me = c.me || {}, exMe = ex.me || {}, fresh = k => !me[k] || JSON.stringify(me[k]) === JSON.stringify(exMe[k]);
  const esc = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (fresh('name')) me.name = name;
  if (fresh('profile')) me.profile = name;
  if (fresh('role')) me.role = '';
  if (fresh('mentions')) me.mentions = ['@' + name];
  if (fresh('nameRe')) me.nameRe = esc;
  if (fresh('nameHint')) me.nameHint = name;
  c.me = me; c.sources = [...new Set(['gmail', ...src])];
  writeJson(CONFIG, c);
  // 3. Google のログインの設定(共用の OAuth クライアント。戻り先のホストはホストの設定ファイルから)
  if (!readJson(OAUTH)) {
    let host = ''; try { host = fs.readFileSync('/opt/gdrive-tool/public-host', 'utf8').trim(); } catch {}
    writeJson(OAUTH, { python: '/opt/gdrive-tool/venv/bin/python3', oauthClient: '/opt/gdrive-tool/config.json', ...(host ? { publicHost: host } : {}) });
  }
  return status();
}

// 箱のブラウザで、その読む先にログインしている名前を読んで覚える(箱の中だけ。読み方は拡張の whoami が持つ)
export async function whoami(what) {
  if (!inBox()) throw new Error('箱の中で動かす');
  const e = allExts.find(x => x.name === what && x.whoami);
  if (!e) throw new Error('名前を読めるのは ' + allExts.filter(x => x.whoami).map(x => x.name).join('・'));
  const { conf } = await import('./conf.mjs');
  // 拡張の whoami: 名前、ログインの画面なら null(ログインが切れている)、分からなければ ''
  const got = await e.whoami({ conf });
  const name = String(got || '').trim().slice(0, 4000);
  const acc = readJson(ACCOUNTS) || {};
  if (got === null) acc[what] = { name: '', loggedOut: true, at: new Date().toISOString() };
  else if (name) acc[what] = { name, at: new Date().toISOString() };
  else delete acc[what];
  writeJson(ACCOUNTS, acc);
  return got === null ? null : name;
}

export function confirm(what) {
  const can = CHOICES.filter(c => c.url).map(c => c.id);
  if (!can.includes(what)) throw new Error('confirm できるのは ' + can.join('・'));
  const st = readJson(STATE) || {}; (st.confirmed ||= {})[what] = new Date().toISOString(); writeJson(STATE, st);
  return status();
}

// 箱のブラウザの共有の画面に URL を出し、noVNC の URL を返す(sandbox-desktop。箱の中だけ)
function desktop(args) {
  const r = spawnSync('sandbox-desktop', args, { encoding: 'utf8', timeout: 90000 });
  const out = String(r.stdout || '') + String(r.stderr || '');
  if (r.status !== 0) throw new Error('箱の画面を開けなかった: ' + out.trim().slice(-300));
  const m = out.match(/https:\/\/\S+\/sandbox-box\/\S+/);
  return m ? m[0] : '';
}
export function openBox(url) {
  if (!inBox()) throw new Error('箱の中で動かす');
  if (!/^https:\/\/[^\s"'`]+$/.test(url)) throw new Error('開けるのは https の URL だけ');
  return desktop(['open', '--shared', url]);
}
async function hostLogin(which) {
  // ホストの aiza の backend が本人として gmail.py/gcal.py login を始め、承認の URL を返す(箱では待ち受けられない)
  const c = readJson(CONFIG) || {}, base = c.notifyUrl || `http://172.17.0.1:${23000 + os.userInfo().uid - 1000}/notify`;
  const res = await fetch(base.replace(/\/notify$/, '/digest/setup/login'), { method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ which }), signal: AbortSignal.timeout(60000) });
  const d = await res.json().catch(() => ({}));
  if (!res.ok || !d.url) throw new Error(d.error || `ログインを始められなかった(${res.status})`);
  return d.url;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const [cmd, ...rest] = process.argv.slice(2);
  const opt = k => { const i = rest.indexOf('--' + k); return i >= 0 ? rest[i + 1] : undefined; };
  const show = s => {
    if (rest.includes('--json')) return console.log(JSON.stringify(s));
    for (const x of s.steps) console.log(`${x.done ? '✔' : '・'} ${x.label}${x.account ? '(' + x.account + ')' : ''}${x.manual && !x.done ? '(済んだら setup.mjs confirm ' + x.id + ')' : ''}`);
    console.log(s.ready ? '準備は済んだ。aiza の 📨 新着まとめで ▶ 新着まとめを動かす(ホストで sudo mailbox-digest-ctl on と同じ)' : '残りがある');
  };
  try {
    if (cmd === 'status') show(status());
    else if (cmd === 'init') show(init({ name: opt('name'), sources: opt('sources') }));
    else if (cmd === 'confirm') show(confirm(rest[0]));
    else if (cmd === 'login') {
      if (!['gmail', 'calendar'].includes(rest[0])) throw new Error('login gmail|calendar');
      const url = await hostLogin(rest[0]);
      const vnc = inBox() ? openBox(url) : '';
      console.log(`承認のページ(5分以内に、読ませたい Google アカウントで承認): ${url}`);
      if (vnc) console.log(`箱のブラウザの画面でも開いた: ${vnc}`);
    } else if (cmd === 'open') {
      const ch = CHOICES.find(c => c.id === rest[0] && c.url);
      if (!ch) throw new Error('open <' + CHOICES.filter(c => c.url).map(c => c.id).join('|') + '>');
      console.log(`箱のブラウザの画面(本人がここでログインする): ${openBox(ch.url)}`);
      console.log(`済んだら setup.mjs close と setup.mjs confirm ${ch.id}`);
    } else if (cmd === 'show') {
      // Google の承認のページを箱の画面に出す(aiza の画面が login の URL を受けたあとに使う)
      if (!/^https:\/\/accounts\.google\.com\/[^\s"'`]+$/.test(rest[0] || '')) throw new Error('show に渡せるのは Google の承認のページだけ');
      console.log(`箱のブラウザの画面: ${openBox(rest[0])}`);
    } else if (cmd === 'whoami') {
      const n = await whoami(rest[0]);
      console.log(rest.includes('--json') ? JSON.stringify(n === null ? { loggedOut: true } : { name: n }) : n === null ? '(ログインが切れている)' : (n || '(読めなかった)'));
    } else if (cmd === 'close') { desktop(['stop', '--shared']); console.log('箱の画面を閉じた'); }
    else { console.error('usage: setup.mjs status [--json] | init --name <名前> [--sources a,b] | confirm <what> | login gmail|calendar | open <読む先> | show <URL> | whoami <読む先> | close'); process.exit(2); }
  } catch (e) { console.error(String(e.message || e)); process.exit(1); }
}
