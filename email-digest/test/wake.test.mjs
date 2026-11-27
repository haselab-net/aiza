// A new message from someone else in an item's thread wakes the item's session, whatever its status, byUser or wait (2026-11-17).
// A fake aiza takes the POST /sessions and /notify that autostart.mjs and wait.mjs send. Only fake data; nothing leaves 127.0.0.1.
import test from 'node:test'; import assert from 'node:assert/strict';
import fs from 'fs'; import path from 'path'; import http from 'http'; import { spawn } from 'child_process';
import { makeBox, PRIVATE } from './helpers.mjs';

// The fake aiza: records each request; /sessions answers as aiza does for a session still running
async function fakeAiza() {
  const got = [];
  const srv = http.createServer((req, res) => {
    let b = ''; req.on('data', c => b += c); req.on('end', () => {
      got.push({ path: req.url, body: JSON.parse(b || '{}') });
      res.writeHead(req.url === '/sessions' ? 201 : 200, { 'content-type': 'application/json' });
      res.end(JSON.stringify(req.url === '/sessions' ? { id: 'sess-1', continued: 'running' } : {}));
    });
  });
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  return { got, url: `http://127.0.0.1:${srv.address().port}/notify`, sessions: () => got.filter(g => g.path === '/sessions'), close: () => new Promise(r => srv.close(r)) };
}
// spawnSync would block the fake aiza in this process
const run = (b, file, args = []) => new Promise(res => {
  const p = spawn(process.execPath, [path.join(b.code, file), ...args], { cwd: b.code, env: b.env });
  let out = '', err = ''; p.stdout.on('data', c => out += c); p.stderr.on('data', c => err += c);
  p.on('close', status => res({ status, stdout: out, stderr: err }));
});
const SESSION = { id: 'sess-1', claude_session_id: '', created: '2026-11-01T00:00:00Z', seen: '2026-11-01T09:00|x' };
const item = (id, o = {}) => ({ id, source: 'mail', time: '2026-11-01T09:00', from: '佐藤', title: '件 ' + id, summary: 's', action: '', status: '未決', link: '', session: { ...SESSION }, ...o });
const reply = (id, o = {}) => ({ id, source: 'mail', time: '2026-11-05T10:00', from: '佐藤', title: '件 ' + id, summary: '新しい返信', action: '', status: '未決', link: '', ...o });

async function box(items, conf = {}) {
  const ai = await fakeAiza();
  const b = makeBox({ drop: PRIVATE, publicOnly: true, items: { items, runs: [] }, conf: { notifyUrl: ai.url, ...conf } });
  const add = async list => { const f = path.join(b.root, 'new.json'); fs.writeFileSync(f, JSON.stringify(list)); const r = await run(b, 'add.mjs', [f]); assert.equal(r.status, 0, r.stderr); return r; };
  const by = () => Object.fromEntries(b.items().items.map(i => [i.id, i]));
  return { b, ai, add, by, wake: () => run(b, 'autostart.mjs'), done: async () => { await ai.close(); b.cleanup(); } };
}

test('a reply to an item with a pending conditional wait wakes it and fires the wait; the first message carries the wait', async () => {
  const x = await box([item('mail:18a0000000000001', { wait: { cond: '見積りが届いたら', task: '見積りを比べる', set: '2026-11-01T10:00' } })]);
  try {
    await x.add([reply('mail:18a0000000000001', { summary: '確認の問い合わせ' })]);
    assert.equal(x.by()['mail:18a0000000000001'].status, '未読');
    const r = await x.wake(); assert.equal(r.status, 0, r.stderr);
    const [s] = x.ai.sessions();
    assert.equal(s.body.continue, 'sess-1');
    assert.match(s.body.initial_message, /前回から更新されています/);
    assert.match(s.body.initial_message, /待っていた件です\(条件: 見積りが届いたら、頼まれていたこと: 見積りを比べる\)/);
    const it = x.by()['mail:18a0000000000001'];
    assert.ok(it.wait.fired); assert.match(it.wait.why, /スレッドに新しいメッセージ/); assert.ok(it.wait.told);
    assert.equal(x.ai.got.filter(g => g.path === '/notify').length, 1);
  } finally { await x.done(); }
});

test('byUser (bound with 「AIで対応」) or 既読 by the owner: a reply turns it back to 未読 (↩ 返信) and wakes it', async () => {
  const x = await box([item('mail:18a0000000000001', { byUser: true }), item('mail:18a0000000000002', { status: '既読', byUser: true })]);
  try {
    await x.add([reply('mail:18a0000000000001'), reply('mail:18a0000000000002', { status: '未読' })]);
    for (const id of ['mail:18a0000000000001', 'mail:18a0000000000002']) {
      const it = x.by()[id]; assert.equal(it.status, '未読'); assert.equal(it.byUser, false); assert.deepEqual(it.replied, { at: '2026-11-05T10:00', from: '佐藤' });
    }
    await x.wake();
    assert.equal(x.ai.sessions().length, 2);
  } finally { await x.done(); }
});

test('a chat item judged not for the owner (forMe:false) goes back to 未読 but is not woken; without forMe it is', async () => {
  const chat = (id, o) => item(id, { source: 'chat', link: 'https://chat.example/' + id, ...o });
  const x = await box([chat('chat:a'), chat('chat:b')]);
  try {
    await x.add([{ ...reply('chat:a', { source: 'chat', link: 'https://chat.example/a' }), forMe: false }, reply('chat:b', { source: 'chat', link: 'https://chat.example/b' })]);
    assert.equal(x.by()['chat:a'].status, '未読');
    await x.wake();
    assert.deepEqual(x.ai.sessions().map(s => s.body.initial_message.match(/項目\((\S+?)\)/)[1]), ['chat:b']);
  } finally { await x.done(); }
});

test('the owner\'s own reply moves time but wakes nothing', async () => {
  const x = await box([item('mail:18a0000000000001'), item('mail:18a0000000000002')]);
  try {
    await x.add([reply('mail:18a0000000000001', { fromMe: true, status: '既決' }), reply('mail:18a0000000000002', { from: '田中' })]);
    assert.equal(x.by()['mail:18a0000000000002'].replied, undefined);
    await x.wake();
    assert.equal(x.ai.sessions().length, 0);
  } finally { await x.done(); }
});

test('a wait reaching its time (tick) wakes the session with the task; the same version is not woken twice', async () => {
  const x = await box([item('mail:18a0000000000001', { status: '既読', wait: { at: '2026-01-01T09:00', task: '返事が無ければ催促する', set: '2025-12-01T10:00' } })]);
  try {
    const r = await run(x.b, 'wait.mjs', ['tick']); assert.equal(r.status, 0, r.stderr);
    const [s] = x.ai.sessions();
    assert.equal(s.body.continue, 'sess-1');
    assert.match(s.body.initial_message, /^待っていた条件が成立しました\(2026-01-01 09:00 になりました\)。頼まれていたこと: 返事が無ければ催促する/);
    const it = x.by()['mail:18a0000000000001'];
    assert.equal(it.status, '未決'); assert.ok(!it.byUser); assert.ok(it.wait.told);
    await x.wake(); await x.wake();
    assert.equal(x.ai.sessions().length, 1);
  } finally { await x.done(); }
});
