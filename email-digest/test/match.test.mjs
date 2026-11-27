// Matching what was fetched with the items before Claude reads it (match.mjs, 2026-11-18): a reply in an item's thread moves the item on
// and wakes its session by machine, so Claude's sorting cannot lose it. Only fake data; nothing leaves 127.0.0.1.
import test from 'node:test'; import assert from 'node:assert/strict';
import fs from 'fs'; import path from 'path'; import http from 'http'; import { spawn } from 'child_process';
import { makeBox, PRIVATE } from './helpers.mjs';

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
  return { url: `http://127.0.0.1:${srv.address().port}/notify`, sessions: () => got.filter(g => g.path === '/sessions'), close: () => new Promise(r => srv.close(r)) };
}
const run = (b, file, args = [], env = {}) => new Promise(res => {
  const p = spawn(process.execPath, [path.join(b.code, file), ...args], { cwd: b.code, env: { ...b.env, ...env } });
  let out = '', err = ''; p.stdout.on('data', c => out += c); p.stderr.on('data', c => err += c);
  p.on('close', status => res({ status, stdout: out, stderr: err }));
});
const SESSION = { id: 'sess-1', claude_session_id: '', created: '2026-11-01T00:00:00Z', seen: '2026-11-01T09:00|x' };
const item = (id, o = {}) => ({ id, source: 'mail', time: '2026-11-01T09:00', from: '佐藤', title: '件 ' + id, summary: '前の要約', action: '', status: '既決', link: '', session: { ...SESSION }, ...o });
// q-mail.jsonl as gmail.py list writes it (Date in UTC: 01:00Z = 10:00 JST)
const mail = (tid, o = {}) => JSON.stringify({ id: 'm' + tid, threadId: tid, date: 'Thu, 05 Nov 2026 01:00:00 +0000', from: '佐藤 <sato@example.com>', subject: 'Re: 件', snippet: '新しい返信', labelIds: ['INBOX'], ...o });

async function box(items, lines, latest = {}) {
  const ai = await fakeAiza();
  const b = makeBox({ drop: PRIVATE, publicOnly: true, items: { items, runs: [] }, conf: { notifyUrl: ai.url } });
  const q = path.join(b.root, 'q'); fs.mkdirSync(q);
  fs.writeFileSync(path.join(q, 'q-mail.jsonl'), lines.join('\n') + '\n');
  // ref-info.py --latest stands in for Gmail: the last message of each thread
  fs.writeFileSync(path.join(b.code, 'ref-info.py'), `#!/bin/sh\necho '${JSON.stringify(latest)}'\n`); fs.chmodSync(path.join(b.code, 'ref-info.py'), 0o755);
  const by = () => Object.fromEntries(b.items().items.map(i => [i.id, i]));
  const rd = f => JSON.parse(fs.readFileSync(path.join(q, f), 'utf8'));
  return { b, ai, q, by, rd, match: () => run(b, 'match.mjs', [q]), done: async () => { await ai.close(); b.cleanup(); } };
}

test('a reply in a 既決 item\'s thread: moved on, 未読 with ↩ 返信, in the bundle, and woken before Claude (--sure)', async () => {
  const x = await box([item('mail:18a0000000000001'), item('mail:18a0000000000002', { status: '未決' })], [mail('18a0000000000001'), mail('18a00000000000ff'), mail('18a0000000000002', { labelIds: ['DRAFT'] })],
    { '18a0000000000001': { id: 'm1', time: '2026-11-05T10:00', from: '佐藤', me: false } });
  try {
    const r = await x.match(); assert.equal(r.status, 0, r.stderr);
    const it = x.by()['mail:18a0000000000001'];
    assert.deepEqual([it.status, it.time, it.bump, it.replied.at], ['未読', '2026-11-05T10:00', 'match', '2026-11-05T10:00']);
    assert.equal(x.by()['mail:18a0000000000002'].time, '2026-11-01T09:00');          // a new thread is left to Claude
    const [rep] = x.rd('replies.json');
    assert.deepEqual([rep.id, rep.keys, rep.summary, rep.messages.length], ['mail:18a0000000000001', ['mail:18a0000000000001'], '前の要約', 1]);
    await run(x.b, 'autostart.mjs', ['--sure']);
    assert.equal(x.ai.sessions().length, 1);
    // Claude rewrites it with the same id and time: no second reply, its status kept
    fs.writeFileSync(path.join(x.q, 'up.json'), JSON.stringify([{ ...item('mail:18a0000000000001', { time: '2026-11-05T10:00', status: '未決', summary: '新しい要約' }), session: undefined }]));
    const a = await run(x.b, 'add.mjs', [path.join(x.q, 'up.json')], { Q: x.q }); assert.equal(a.status, 0, a.stderr);
    assert.doesNotMatch(a.stderr, /REPLY/);
    const up = x.by()['mail:18a0000000000001'];
    assert.deepEqual([up.status, up.summary, up.session.id], ['未決', '新しい要約', 'sess-1']);
  } finally { await x.done(); }
});

test('the owner answered last: time moves, nothing wakes', async () => {
  const x = await box([item('mail:18a0000000000001', { status: '未決' })], [mail('18a0000000000001')],
    { '18a0000000000001': { id: 'm2', time: '2026-11-05T11:00', from: '田中', me: true } });
  try {
    await x.match();
    const it = x.by()['mail:18a0000000000001'];
    assert.deepEqual([it.time, it.fromMe, it.status, it.replied], ['2026-11-05T11:00', true, '未決', undefined]);
    await run(x.b, 'autostart.mjs', ['--sure']);
    assert.equal(x.ai.sessions().length, 0);
  } finally { await x.done(); }
});

test('a former thread (refs) of an item matches it; the summary\'s threads (misc) do not; Claude cannot make a second item for it', async () => {
  const x = await box([item('mail:18a0000000000001', { threadId: '18a0000000000003', refs: ['mail:18a0000000000002'] }),
    { id: 'misc:noaction', source: 'misc', time: '2026-11-01T09:00', title: '対応不要のまとめ', summary: '', status: '既決', refs: ['mail:18a0000000000009'] }],
  [mail('18a0000000000002'), mail('18a0000000000009')], { '18a0000000000002': { id: 'm1', time: '2026-11-05T10:00', from: '佐藤', me: false } });
  try {
    await x.match();
    assert.deepEqual(x.rd('replies.json').map(r => r.id), ['mail:18a0000000000001']);
    assert.equal(x.by()['mail:18a0000000000001'].status, '未読');
    // Claude makes a new item out of the matched thread anyway: it goes onto the matched item
    fs.writeFileSync(path.join(x.q, 'new.json'), JSON.stringify([{ id: 'mail:18a0000000000002', source: 'mail', time: '2026-11-05T10:00', from: '佐藤', title: '別の件?', summary: 's', action: '', status: '未決', link: '' }]));
    const a = await run(x.b, 'add.mjs', [path.join(x.q, 'new.json')], { Q: x.q });
    assert.match(a.stderr, /MATCHED mail:18a0000000000002 → mail:18a0000000000001/);
    assert.equal(x.by()['mail:18a0000000000002'], undefined);
  } finally { await x.done(); }
});

test('cover.mjs counts what was fetched but shows up nowhere (ids and counts only; promotions apart)', async () => {
  const x = await box([item('mail:18a0000000000001'), { id: 'misc:noaction', source: 'misc', time: '2026-11-01T09:00', title: 'まとめ', summary: '', status: '未読', refs: ['mail:18a0000000000002'] }],
    [mail('18a0000000000001'), mail('18a0000000000002'), mail('18a0000000000003'), mail('18a0000000000004', { labelIds: ['INBOX', 'CATEGORY_PROMOTIONS'] }), mail('18a0000000000005', { labelIds: ['DRAFT'] })]);
  try {
    const r = await run(x.b, 'cover.mjs', [x.q]); assert.equal(r.status, 0, r.stderr);
    assert.match(r.stdout, /cover: どこにも出ていないもの メール 1\/3\(プロモーション 1\/1\)/);
    assert.match(r.stdout, /cover: 未処理 mail:18a0000000000003\n/);
    assert.doesNotMatch(r.stdout, /Re: 件|新しい返信/);
  } finally { await x.done(); }
});
