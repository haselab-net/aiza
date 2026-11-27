// Watches a session leaves (watch.mjs, 2026-11-20): the match step wakes that session when a new message hits one.
// Only fake data; nothing leaves 127.0.0.1.
import test from 'node:test'; import assert from 'node:assert/strict';
import fs from 'fs'; import path from 'path'; import http from 'http'; import { spawn } from 'child_process';
import { makeBox, PRIVATE } from './helpers.mjs';

// aiza's notify listener: /digest/watch/wake answers with what `answer` says
async function fakeAiza(answer = () => [200, { id: 'aaaaaaaaaaa1', how: 'running' }]) {
  const got = [];
  const srv = http.createServer((req, res) => {
    let b = ''; req.on('data', c => b += c); req.on('end', () => {
      const body = JSON.parse(b || '{}'); got.push({ path: req.url, body });
      const [code, j] = req.url === '/digest/watch/wake' ? answer(body) : [200, {}];
      res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(j));
    });
  });
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  return { url: `http://127.0.0.1:${srv.address().port}/notify`, wakes: () => got.filter(g => g.path === '/digest/watch/wake'), close: () => new Promise(r => srv.close(r)) };
}
const run = (b, file, args = [], env = {}) => new Promise(res => {
  const p = spawn(process.execPath, [path.join(b.code, file), ...args], { cwd: b.code, env: { ...b.env, ...env } });
  let out = '', err = ''; p.stdout.on('data', c => out += c); p.stderr.on('data', c => err += c);
  p.on('close', status => res({ status, stdout: out, stderr: err }));
});
const mail = (id, tid, o = {}) => JSON.stringify({ id, threadId: tid, date: 'Thu, 05 Nov 2026 01:00:00 +0000', from: 'JLCPCB <noreply@jlcpcb.example>', subject: 'Your order W2026 has shipped', snippet: '出荷しました', labelIds: ['INBOX'], ...o });
const S = 'aaaaaaaaaaa1';

async function box(lines, answer) {
  const ai = await fakeAiza(answer);
  const b = makeBox({ drop: PRIVATE, publicOnly: true, items: { items: [], runs: [] }, conf: { notifyUrl: ai.url } });
  const q = path.join(b.root, 'q'); fs.mkdirSync(q);
  fs.writeFileSync(path.join(q, 'q-mail.jsonl'), lines.join('\n') + '\n');
  fs.writeFileSync(path.join(b.code, 'ref-info.py'), `#!/bin/sh\necho '{}'\n`); fs.chmodSync(path.join(b.code, 'ref-info.py'), 0o755);
  const watches = () => JSON.parse(fs.readFileSync(path.join(b.code, 'watches.json'), 'utf8')).watches;
  const calls = () => fs.readFileSync(b.log, 'utf8').trim().split('\n').filter(Boolean).map(l => JSON.parse(l));
  return { b, ai, q, watches, calls, match: (env) => run(b, 'match.mjs', [q], env), done: async () => { await ai.close(); b.cleanup(); } };
}

test('add: the current session from AIZA_OUTBOX; needs a condition and a task; list and rm', async () => {
  const x = await box([]);
  try {
    const env = { AIZA_OUTBOX: `/m/.aiza/${S}/outbox` };
    assert.equal(x.b.node('watch.mjs', ['add', '--task', 'x'], { env }).status, 2);                 // no condition
    assert.equal(x.b.node('watch.mjs', ['add', '--keyword', 'a'], { env }).status, 2);              // no task
    assert.equal(x.b.node('watch.mjs', ['add', '--keyword', 'a', '--task', 'x']).status, 2);        // no session
    assert.equal(x.b.node('watch.mjs', ['add', '--thread', 'zz', '--task', 'x'], { env }).status, 2);
    assert.equal(x.b.node('watch.mjs', ['add', '--from', 'jlc', '--task', 'x'], { env }).status, 2);
    const a = x.b.node('watch.mjs', ['add', '--query', 'from:jlcpcb.example W2026', '--task', '配達を確かめる'], { env });
    assert.equal(a.status, 0, a.stderr); assert.match(a.stdout, /見張り w1 を置きました/); assert.match(a.stdout, /👁 from:jlcpcb\.example W2026/);
    const [w] = x.watches();
    assert.deepEqual([w.id, w.session, w.query, w.task], ['w1', S, 'from:jlcpcb.example W2026', '配達を確かめる']);
    assert.match(w.until, /^\d{4}-\d{2}-\d{2}$/);
    assert.match(x.b.node('watch.mjs', ['list']).stdout, /^w1 セッション aaaaaaaaaaa1 /);
    assert.equal(x.b.node('watch.mjs', ['rm', 'w9']).status, 2);
    assert.equal(x.b.node('watch.mjs', ['rm', 'w1']).status, 0);
    assert.deepEqual(x.watches(), []);
  } finally { await x.done(); }
});

test('a query watch: a notice in a new thread wakes the session with the condition, task and the message (no body); not twice', async () => {
  const x = await box([]);
  try {
    x.b.node('watch.mjs', ['add', '--session', S, '--query', 'from:jlcpcb.example W2026', '--task', '配達を確かめる']);
    const list = path.join(x.b.root, 'list.jsonl');
    fs.writeFileSync(list, [mail('m1', '18b0000000000001'), mail('m2', '18b0000000000002', { labelIds: ['SENT'] })].join('\n') + '\n');
    const r = await x.match({ FAKE_GMAIL_LIST: list }); assert.equal(r.status, 0, r.stderr);
    const [wk] = x.ai.wakes();
    assert.equal(wk.body.session, S);
    assert.match(wk.body.message, /見張り w1 に当たりました\(検索 from:jlcpcb\.example W2026\)。頼まれていたこと: 配達を確かめる/);
    assert.match(wk.body.message, /JLCPCB「Your order W2026 has shipped」 https:\/\/mail\.google\.com\/.*FAKE18b0000000000001/);
    assert.doesNotMatch(wk.body.message, /出荷しました/);                                           // not the body
    assert.ok([...wk.body.message].length <= 500);
    const q = x.calls().find(c => c[1] === 'list'); assert.match(q[3], /^\(from:jlcpcb\.example W2026\) after:\d+ -in:sent -in:drafts$/);
    const [w] = x.watches(); assert.deepEqual([w.seen, w.last.n], [['m:m1'], 1]); assert.ok(w.checked);
    await x.match({ FAKE_GMAIL_LIST: list });                                                     // the same message again
    assert.equal(x.ai.wakes().length, 1);
    assert.equal(x.watches().length, 1);                                                          // kept after a hit
  } finally { await x.done(); }
});

test('a thread watch: someone else in the thread wakes; the owner alone does not', async () => {
  const x = await box([mail('m1', '18b0000000000003', { from: '田中 <test@example.com>' })]);
  try {
    x.b.node('watch.mjs', ['add', '--session', S, '--thread', '18b0000000000003', '--task', '返事を読む']);
    await x.match(); assert.equal(x.ai.wakes().length, 0);
    fs.writeFileSync(path.join(x.q, 'q-mail.jsonl'), mail('m2', '18b0000000000003', { from: '佐藤 <sato@example.com>' }) + '\n');
    await x.match(); assert.equal(x.ai.wakes().length, 1);
    assert.match(x.ai.wakes()[0].body.message, /スレッド 18b0000000000003/);
  } finally { await x.done(); }
});

test('a keyword watch with --from: both must hold', async () => {
  const x = await box([mail('m1', '18b0000000000004', { from: '佐藤 <sato@example.com>' }), mail('m2', '18b0000000000005')]);
  try {
    x.b.node('watch.mjs', ['add', '--session', S, '--keyword', 'shipped', '--from', 'jlcpcb', '--task', 't']);
    await x.match();
    assert.equal(x.ai.wakes().length, 1);
    assert.deepEqual(x.watches()[0].seen, ['m:m2']);
  } finally { await x.done(); }
});

test('past --until: not woken, the watch goes', async () => {
  const x = await box([mail('m1', '18b0000000000006')]);
  try {
    x.b.node('watch.mjs', ['add', '--session', S, '--keyword', 'shipped', '--until', '2020-01-01', '--task', 't']);
    const r = await x.match();
    assert.equal(x.ai.wakes().length, 0); assert.deepEqual(x.watches(), []); assert.match(r.stdout, /期限 2020-01-01 を過ぎた/);
  } finally { await x.done(); }
});

test('an archived session: the watch goes; a limit (429): kept and tried again; a new id after resume is kept', async () => {
  let ans = [410, { error: 'archived' }];
  const x = await box([mail('m1', '18b0000000000007')], () => ans);
  try {
    x.b.node('watch.mjs', ['add', '--session', S, '--keyword', 'shipped', '--task', 't']);
    await x.match(); assert.deepEqual(x.watches(), []);
    x.b.node('watch.mjs', ['add', '--session', S, '--keyword', 'shipped', '--task', 't']);
    ans = [429, { error: 'limit' }];
    await x.match(); assert.deepEqual(x.watches()[0].seen, undefined);
    ans = [200, { id: 'bbbbbbbbbbb2', how: 'resumed' }];
    await x.match(); assert.deepEqual([x.watches()[0].seen, x.watches()[0].session], [['m:m1'], 'bbbbbbbbbbb2']);
    assert.equal(x.ai.wakes().length, 3);
  } finally { await x.done(); }
});

test('a session that cannot be resumed (409): not tried again for the same message; not a box session (404): the watch goes', async () => {
  let ans = [409, { error: 'could not resume the session' }];
  const x = await box([mail('m1', '18b0000000000009')], () => ans);
  try {
    x.b.node('watch.mjs', ['add', '--session', S, '--keyword', 'shipped', '--task', 't']);
    await x.match(); await x.match();
    assert.equal(x.ai.wakes().length, 1);
    assert.deepEqual([x.watches()[0].seen, x.watches()[0].last.error], [['m:m1'], 409]);
    assert.match(x.b.node('watch.mjs', ['list']).stdout, /起こせなかった 409/);
    fs.writeFileSync(path.join(x.q, 'q-mail.jsonl'), mail('m2', '18b000000000000a') + '\n');
    ans = [404, { error: 'not a session of this Email box' }];
    await x.match(); assert.deepEqual(x.watches(), []);
  } finally { await x.done(); }
});

test('match --dry wakes nothing and changes nothing', async () => {
  const x = await box([mail('m1', '18b0000000000008')]);
  try {
    x.b.node('watch.mjs', ['add', '--session', S, '--keyword', 'shipped', '--task', 't']);
    const r = await run(x.b, 'match.mjs', [x.q, '--dry']);
    assert.match(r.stdout, /dry watch w1: 1 件/); assert.equal(x.ai.wakes().length, 0); assert.equal(x.watches()[0].seen, undefined);
  } finally { await x.done(); }
});
