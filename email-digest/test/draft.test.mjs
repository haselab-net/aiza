// A reply draft (the prep session writes one) is not the owner's reply: add.mjs checks a mail item said to be
// replied by the owner against the thread's latest sent message, and the mail lists leave drafts out (2026-11-19)
import test from 'node:test'; import assert from 'node:assert/strict'; import fs from 'fs'; import path from 'path';
import { makeBox, SRC } from './helpers.mjs';

const T1 = '0123456789abcdef', T2 = 'fedcba9876543210';
const it = (tid, o) => ({ id: 'mail:' + tid, source: 'mail', time: '2026-11-19T09:14', from: '長谷川(返信済み)', title: '件', summary: 's', action: '', status: '既決', link: '', fromMe: true, ...o });

test('add: a mail said to be replied by the owner, whose latest sent message is not the owner\'s, stays open', () => {
  const b = makeBox({ items: { items: [], runs: [] } });
  try {
    const latest = { [T1]: { id: 'x', time: '2026-11-18T18:16', from: '学生A', me: false }, [T2]: { id: 'y', time: '2026-11-19T09:20', from: '長谷川', me: true } };
    fs.writeFileSync(path.join(b.code, 'ref-info.py'), `#!/bin/sh\necho '${JSON.stringify(latest)}'\n`); fs.chmodSync(path.join(b.code, 'ref-info.py'), 0o755);
    const f = path.join(b.root, 'n.json'); fs.writeFileSync(f, JSON.stringify([it(T1), it(T2)]));
    const r = b.node('add.mjs', [f, 'x']); assert.equal(r.status, 0, r.stderr);
    assert.match(r.stderr, new RegExp(`NOTSENT mail:${T1}`));
    const by = Object.fromEntries(b.items().items.map(i => [i.id, i]));
    assert.deepEqual([by['mail:' + T1].status, by['mail:' + T1].fromMe, by['mail:' + T1].from], ['未決', false, '学生A']);
    assert.deepEqual([by['mail:' + T2].status, by['mail:' + T2].fromMe], ['既決', true]);
  } finally { b.cleanup(); }
});

test('the mail lists leave drafts out', () => {
  for (const f of ['run-check.sh', 'quick-check.sh']) assert.match(fs.readFileSync(path.join(SRC, f), 'utf8'), /gmail\.py" list -q "after:\$LAST -in:sent -in:drafts/);
});
