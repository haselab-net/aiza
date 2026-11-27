// Starting the digest from nothing (setup.mjs): what aiza's 📨 page and the box's Claude both run.
import test from 'node:test'; import assert from 'node:assert/strict';
import fs from 'fs'; import path from 'path'; import { spawnSync } from 'child_process';
import { makeBox } from './helpers.mjs';

// A member's box before anything: the shared code elsewhere, an empty home
function fresh() {
  const b = makeBox();
  const sh = path.join(b.root, 'shared'); fs.mkdirSync(sh);
  fs.renameSync(b.code, path.join(sh, 'digest'));
  fs.rmSync(path.join(sh, 'digest', 'local'), { recursive: true, force: true });
  for (const n of ['gmail.py', 'gcal.py']) { if (fs.existsSync(path.join(b.home, n))) { fs.copyFileSync(path.join(b.home, n), path.join(sh, n)); fs.rmSync(path.join(b.home, n)); } }
  fs.rmSync(path.join(b.home, '.gmail'), { recursive: true, force: true });
  const run = (...args) => spawnSync(process.execPath, [path.join(sh, 'digest', 'setup.mjs'), ...args], { env: b.env, encoding: 'utf8' });
  const st = () => JSON.parse(run('status', '--json').stdout);
  return { b, sh, run, st };
}

test('setup: an empty box lists every step as not done', () => {
  const x = fresh();
  try {
    const s = x.st();
    assert.equal(s.ready, false);
    assert.deepEqual(s.steps.map(t => t.id), ['choose', 'entries', 'gmail', 'claude']);
    assert.ok(s.steps.every(t => !t.done));
    assert.deepEqual(s.choices.slice(0, 2).map(c => c.id), ['gmail', 'calendar']);
  } finally { x.b.cleanup(); }
});

test('setup: init makes the entries, the config with the chosen sources and the name, and the login settings', () => {
  const x = fresh();
  try {
    const r = x.run('init', '--name', '佐藤', '--sources', 'calendar', '--json');
    assert.equal(r.status, 0, r.stderr);
    const s = JSON.parse(r.stdout);
    const done = Object.fromEntries(s.steps.map(t => [t.id, t.done]));
    assert.deepEqual(done, { choose: true, entries: true, gmail: false, calendar: false, claude: false });
    const c = JSON.parse(fs.readFileSync(path.join(x.b.home, 'digest', 'local', 'config.json'), 'utf8'));
    assert.deepEqual(c.sources, ['gmail', 'calendar']);
    assert.equal(c.me.name, '佐藤'); assert.deepEqual(c.me.mentions, ['@佐藤']);
    const o = JSON.parse(fs.readFileSync(path.join(x.b.home, '.config', 'mailbox', 'oauth.json'), 'utf8'));
    assert.equal(o.oauthClient, '/opt/gdrive-tool/config.json');
    assert.equal(fs.statSync(path.join(x.b.home, 'digest', 'local', 'config.json')).mode & 0o077, 0);
  } finally { x.b.cleanup(); }
});

test('setup: init again keeps what the member wrote, changes only the sources', () => {
  const x = fresh();
  try {
    x.run('init', '--name', '佐藤', '--sources', 'calendar');
    const f = path.join(x.b.home, 'digest', 'local', 'config.json');
    const c = JSON.parse(fs.readFileSync(f, 'utf8')); c.me.nameRe = '佐藤|sato'; c.me.name = 'さとう'; fs.writeFileSync(f, JSON.stringify(c));
    assert.equal(x.run('init', '--name', '別の名前', '--sources', 'gmail').status, 0);
    const d = JSON.parse(fs.readFileSync(f, 'utf8'));
    assert.equal(d.me.name, 'さとう'); assert.equal(d.me.nameRe, '佐藤|sato');
    assert.deepEqual(d.sources, ['gmail']);
  } finally { x.b.cleanup(); }
});

test('setup: confirm records the hand-done steps; logins are seen from their files', () => {
  const x = fresh();
  try {
    x.run('init', '--name', '佐藤');
    fs.mkdirSync(path.join(x.b.home, '.claude')); fs.writeFileSync(path.join(x.b.home, '.claude', '.credentials.json'), '{}');
    // a read-only token (from before 2026-10-09): log in again, archiving needs gmail.modify (no connector step any more)
    fs.mkdirSync(path.join(x.b.home, '.gmail')); fs.writeFileSync(path.join(x.b.home, '.gmail', 'token.json'), JSON.stringify({ scopes: ['https://www.googleapis.com/auth/gmail.readonly'] }));
    let g = x.st().steps.find(t => t.id === 'gmail');
    assert.equal(g.done, false); assert.equal(g.relogin, true); assert.match(g.label, /ログインし直す/); assert.equal(x.st().ready, false);
    fs.writeFileSync(path.join(x.b.home, '.gmail', 'token.json'), JSON.stringify({ scopes: ['https://www.googleapis.com/auth/gmail.modify'] }));
    g = x.st().steps.find(t => t.id === 'gmail');
    assert.equal(g.done, true); assert.equal(g.relogin, undefined);
    assert.equal(x.st().ready, true);
    assert.notEqual(x.run('confirm', 'connector').status, 0);
    assert.notEqual(x.run('confirm', 'password').status, 0);
  } finally { x.b.cleanup(); }
});

test('setup: bad names and sources are refused', () => {
  const x = fresh();
  try {
    assert.notEqual(x.run('init', '--name', '').status, 0);
    assert.notEqual(x.run('init', '--name', '佐藤', '--sources', 'twitter').status, 0);
    assert.notEqual(x.run('open', 'https://example.com').status, 0);
  } finally { x.b.cleanup(); }
});

test('setup: the logged-in accounts are shown with their steps', () => {
  const x = fresh();
  try {
    x.run('init', '--name', '佐藤', '--sources', 'calendar');
    fs.mkdirSync(path.join(x.b.home, '.gmail')); fs.writeFileSync(path.join(x.b.home, '.gmail', 'token.json'), '{}');
    fs.writeFileSync(path.join(x.b.home, '.gmail', 'account'), 'sato@example.com\n');
    fs.mkdirSync(path.join(x.b.home, '.claude')); fs.writeFileSync(path.join(x.b.home, '.claude', '.credentials.json'), '{}');
    fs.writeFileSync(path.join(x.b.home, '.claude.json'), JSON.stringify({ oauthAccount: { emailAddress: 'sato@example.org' } }));
    const acct = Object.fromEntries(x.st().steps.map(t => [t.id, t.account]));
    assert.equal(acct.gmail, 'sato@example.com'); assert.equal(acct.claude, 'sato@example.org'); assert.equal(acct.calendar, '');
  } finally { x.b.cleanup(); }
});
