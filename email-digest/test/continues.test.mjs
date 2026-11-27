// A message that continues an existing item by content (other sender, other subject: "continues": "<item id>")
// goes into that item like a reply, so the item's session gets it (2026-11-24)
import test from 'node:test'; import assert from 'node:assert/strict'; import fs from 'fs'; import path from 'path';
import { makeBox } from './helpers.mjs';

const OLD = '1111111111111111', NEW = '2222222222222222', X = '3333333333333333';
const recent = new Date(Date.now() + 9 * 3600e3 - 3 * 86400e3).toISOString().slice(0, 16);
const ancient = new Date(Date.now() + 9 * 3600e3 - 60 * 86400e3).toISOString().slice(0, 16);
const item = (tid, o) => ({ id: 'mail:' + tid, source: 'mail', time: recent, from: '委員会', title: '委員会の案内', summary: 's', action: '資料を読む', status: '未決', link: 'L-old', ...o });
const msg = (tid, o) => ({ id: 'mail:' + tid, source: 'mail', time: new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 16), from: '配信サービス', title: '資料公開のお知らせ', summary: '資料が公開された', action: '', status: '未読', link: 'L-new', ...o });
const stubRefInfo = b => { fs.writeFileSync(path.join(b.code, 'ref-info.py'), "#!/bin/sh\necho '{}'\n"); fs.chmodSync(path.join(b.code, 'ref-info.py'), 0o755); };
const run = (items, add) => {
  const b = makeBox({ items: { items, runs: [] } }); stubRefInfo(b);
  const f = path.join(b.root, 'n.json'); fs.writeFileSync(f, JSON.stringify(add));
  const r = b.node('add.mjs', [f, 'x']);
  return { b, r, by: Object.fromEntries(b.items().items.map(i => [i.id, i])) };
};

test('continues: a waiting item with a session takes the message as a reply (the session wakes, the wait fires there)', () => {
  const sess = { id: 's1', seen: recent + '|x' };
  const { b, r, by } = run([item(OLD, { session: sess, wait: { cond: '資料の公開', task: '資料を読んで準備', set: recent } })], [msg(NEW, { continues: 'mail:' + OLD })]);
  try {
    assert.equal(r.status, 0, r.stderr);
    assert.match(r.stderr, new RegExp(`CONTINUES mail:${NEW} → mail:${OLD}`));
    assert.equal(by['mail:' + NEW], undefined);
    const it = by['mail:' + OLD];
    assert.deepEqual([it.status, it.title, it.threadId, it.session.id, it.replied.from], ['未読', '委員会の案内', NEW, 's1', '配信サービス']);
    assert.ok(it.refs.includes('mail:' + OLD) && !it.refs.includes('mail:' + NEW));
    assert.equal(it.continues, undefined); assert.deepEqual(it.contFrom.id, 'mail:' + NEW);
    assert.equal(it.wait.fired, undefined); // autostart fires it when it wakes the session (wait-by-reply)
    const dry = b.node('autostart.mjs', ['--dry']); assert.match(dry.stdout, new RegExp(`dry mail:${OLD} continue s1 wait-by-reply`));
  } finally { b.cleanup(); }
});

test('continues: a waiting item without a session has its wait fired here', () => {
  const { b, r, by } = run([item(OLD, { wait: { cond: 'c', task: 't', set: recent } })], [msg(NEW, { continues: 'mail:' + OLD })]);
  try {
    assert.equal(r.status, 0, r.stderr); assert.match(r.stderr, /WAIT-FIRED/);
    assert.ok(by['mail:' + OLD].wait.fired); assert.match(by['mail:' + OLD].wait.why, /続きのメッセージ/);
  } finally { b.cleanup(); }
});

test('continues: a recent done item with a session reopens; an old one or one without a session stays apart', () => {
  const { b, r, by } = run([
    item(OLD, { status: '既決', synced: true, session: { id: 's1', seen: recent } }),
    item(X, { status: '既決', session: { id: 's2' }, time: ancient }),
    item('4444444444444444', { status: '既決' }),
  ], [msg(NEW, { continues: 'mail:' + OLD }), msg('5555555555555555', { continues: 'mail:' + X }), msg('6666666666666666', { continues: 'mail:4444444444444444' }), msg('7777777777777777', { continues: 'misc:noaction' })]);
  try {
    assert.equal(r.status, 0, r.stderr);
    assert.equal(by['mail:' + OLD].status, '未読'); assert.equal(by['mail:' + OLD].synced, undefined); assert.ok(by['mail:' + OLD].reopened);
    for (const t of ['5555555555555555', '6666666666666666', '7777777777777777']) assert.ok(by['mail:' + t], t);
    assert.equal((r.stderr.match(/続きにできる項目でない/g) || []).length, 3);
  } finally { b.cleanup(); }
});

test('continues: across sources the item keeps its source and link and gets the mail in refs; an older message only adds to refs', () => {
  const chat = { id: 'chat:abc', source: 'chat', time: recent, from: 'A', title: '打ち合わせ', summary: 's', action: 'a', status: '未決', link: 'L-chat' };
  const { b, r, by } = run([chat, item(OLD)], [msg(NEW, { continues: 'chat:abc' }), msg(X, { continues: 'mail:' + OLD, time: '2020-01-01T00:00' })]);
  try {
    assert.equal(r.status, 0, r.stderr);
    const c = by['chat:abc'];
    assert.deepEqual([c.source, c.link, c.status, c.threadId], ['chat', 'L-chat', '未読', undefined]);
    assert.ok(c.refs.includes('mail:' + NEW));
    assert.ok(by['mail:' + OLD].refs.includes('mail:' + X)); assert.equal(by['mail:' + OLD].status, '未決'); assert.equal(by['mail:' + X], undefined);
  } finally { b.cleanup(); }
});

test('item.mjs --open lists the items a message may continue', () => {
  const b = makeBox({ items: { items: [item(OLD), item(X, { status: '既決' }), { id: 'misc:noaction', source: 'misc', status: '未読', time: recent }], runs: [] } });
  try {
    const r = b.node('item.mjs', ['--open']); assert.equal(r.status, 0, r.stderr);
    assert.deepEqual(r.stdout.trim().split('\n').map(l => JSON.parse(l).id), ['mail:' + OLD]);
  } finally { b.cleanup(); }
});
