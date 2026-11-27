// A 「今すぐチェック」 run stopped partway (the server restarted under it) leaves quick.json at "raw".
// The page shows 速報 only while the run that wrote it is still alive and not older than 20 minutes.
import test from 'node:test'; import assert from 'node:assert/strict';
import fs from 'fs'; import path from 'path';
import { makeBox, startServer, PRIVATE } from './helpers.mjs';

test('速報 is shown only while the quick run is alive', async () => {
  const b = makeBox({ drop: PRIVATE, publicOnly: true });
  try {
    fs.mkdirSync(path.join(b.code, 'quick'), { recursive: true });
    fs.writeFileSync(path.join(b.code, 'quick', 'quick-raw.json'), JSON.stringify([{ source: 'mail', time: '2026-11-17T16:58', from: '佐藤', title: '件名', text: '本文' }]));
    const q = o => fs.writeFileSync(path.join(b.code, 'quick.json'), JSON.stringify({ state: 'raw', at: new Date().toISOString(), ...o }));
    const s = await startServer(b);
    try {
      q({ pid: process.pid });
      assert.ok((await s.get('/email/')).text.includes('<h2>速報'));
      assert.equal(JSON.parse((await s.get('/email/quick-status')).text).state, 'raw');
      q({ pid: 2 ** 22 + 7 });   // above pid_max: no such process
      assert.ok(!(await s.get('/email/')).text.includes('<h2>速報'));
      assert.equal(JSON.parse((await s.get('/email/quick-status')).text).state, 'stopped');
      q({ at: '2026-11-17T07:58:54+00:00' });   // no pid (written before pids were recorded), long ago
      assert.ok(!(await s.get('/email/')).text.includes('<h2>速報'));
    } finally { await s.stop(); }
  } finally { b.cleanup(); }
});
