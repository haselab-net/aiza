// The item's session writes its preparation result as one line (set-prep.mjs, 2026-11-14) and the page shows it
// under the item ("下準備:"), faded once the item has been updated after it. Status, byUser and changed stay as they are.
import test from 'node:test'; import assert from 'node:assert/strict';
import { makeBox, startServer, PRIVATE } from './helpers.mjs';

const ITEMS = () => ({ items: [
  { id: 'mail:18a0000000000002', source: 'mail', time: '2026-11-05T09:00', from: '佐藤', title: '見学の件', summary: '見学の日程', status: '未決' },
  { id: 'mail:18a0000000000003', source: 'mail', time: '2099-01-01T09:00', from: '鈴木', title: '更新された件', summary: 's', status: '未決',
    prep: { text: '古い下準備', at: '2026-11-05T10:00' } },
], runs: [] });

test('set-prep writes prep only; --clear removes it; usage errors', () => {
  const b = makeBox({ drop: PRIVATE, publicOnly: true, items: ITEMS() });
  try {
    const r = b.node('set-prep.mjs', ['mail:18a0000000000002', '  返信の下書きを作成。\n送るか確認待ち ']);
    assert.equal(r.status, 0, r.stderr);
    const it = b.items().items.find(i => i.id === 'mail:18a0000000000002');
    assert.equal(it.prep.text, '返信の下書きを作成。 送るか確認待ち');
    assert.match(it.prep.at, /^\d{4}-\d\d-\d\dT\d\d:\d\d$/);
    assert.equal(it.status, '未決'); assert.equal(it.byUser, undefined); assert.equal(it.changed, undefined);
    assert.equal(b.node('set-prep.mjs', ['mail:18a0000000000002', 'x'.repeat(500)]).status, 0);
    assert.equal(b.items().items.find(i => i.id === 'mail:18a0000000000002').prep.text.length, 200);
    assert.equal(b.node('set-prep.mjs', ['mail:18a0000000000002', '--clear']).status, 0);
    assert.equal(b.items().items.find(i => i.id === 'mail:18a0000000000002').prep, undefined);
    assert.equal(b.node('set-prep.mjs', ['mail:18a0000000000002']).status, 2);
    assert.equal(b.node('set-prep.mjs', ['mail:nope', 'x']).status, 1);
  } finally { b.cleanup(); }
});

test('the page shows the prep line, faded when the item changed after it', async () => {
  const b = makeBox({ drop: PRIVATE, publicOnly: true, items: ITEMS() });
  try {
    b.node('set-prep.mjs', ['mail:18a0000000000002', '11/19 17:00 の見学を提案する下書き。時刻を決めて']);
    const s = await startServer(b);
    try {
      const p = (await s.get('/email/')).text;
      assert.ok(p.includes('<div class="pp">下準備: 11/19 17:00 の見学を提案する下書き。時刻を決めて</div>'));
      assert.ok(p.includes('<div class="pp old">下準備: 古い下準備(このあと更新あり)</div>'));
    } finally { await s.stop(); }
  } finally { b.cleanup(); }
});

test('the item session is told to write it', async () => {
  const fs = await import('fs'); const path = await import('path');
  const b = makeBox({ drop: PRIVATE, publicOnly: true, items: ITEMS() });
  try {
    assert.equal(b.node('compose.mjs').status, 0);
    const md = fs.readFileSync(path.join(b.code, 'CLAUDE.md'), 'utf8');
    assert.match(md, /set-prep\.mjs <id> "<一行>"/);
  } finally { b.cleanup(); }
});
