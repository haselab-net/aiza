// The page in three languages (digest/i18n.mjs, 2026-11-24; keys like the deployment notes): ?lang= picks the language of the
// page's frame (headings, buttons, notices); the items' own words stay as written. Every key the page code passes
// to L() has all three languages with the same {names}, and without ?lang= the page is the Japanese it always was.
import test from 'node:test'; import assert from 'node:assert/strict';
import fs from 'fs'; import path from 'path';
import { makeBox, startServer, PRIVATE, SRC } from './helpers.mjs';
import { WORDS, VALUE, LANGS, translator } from '../digest/i18n.mjs';

const ITEMS = () => ({ items: [
  { id: 'mail:18a0000000000002', source: 'mail', time: '2026-11-05T09:00', from: '佐藤', title: '見学の件', summary: '見学の日程', status: '未決',
    action: '日程を返信', due: '2099-01-06', prep: { text: '下書きを作成', at: '2099-01-01T00:00' } },
  { id: 'mail:18a0000000000003', source: 'mail', time: '2026-11-04T09:00', from: '鈴木', title: '会議', summary: 's', status: '未読', replied: true,
    wait: { at: '2099-01-05T09:00', task: '出欠を返す' } },
  { id: 'mail:18a0000000000004', source: 'mail', time: '2026-11-03T09:00', from: '高橋', title: '済んだ件', summary: 's', status: '既決' },
], runs: [{ at: '2026-11-05T09:30', note: '' }] });

// Every string literal inside an L( … ) call in the page code (server.mjs, client.js, speak.js)
function literalsInL() {
  const out = new Set();
  for (const f of ['server.mjs', 'client.js', 'speak.js']) {
    const s = fs.readFileSync(path.join(SRC, f), 'utf8');
    for (const m of s.matchAll(/(?<![\w$.])L\(/g)) {
      let i = m.index + 2, depth = 1;
      while (i < s.length && depth) {
        const c = s[i];
        if (c === "'" || c === '"' || c === '`') {
          let j = i + 1; while (j < s.length && s[j] !== c) j += s[j] === '\\' ? 2 : 1;
          if (c !== '`') out.add(s.slice(i + 1, j));
          i = j + 1; continue;
        }
        if (c === '(') depth++; else if (c === ')') depth--;
        i++;
      }
    }
  }
  return out;
}

test('i18n: every key the page uses is there, in all three languages with the same {names}', () => {
  const lits = [...literalsInL()].filter(x => x.length > 1);
  const keys = lits.filter(x => /^mail\.[a-z0-9_.]+$/.test(x));
  assert.ok(keys.length > 60, String(keys.length));
  assert.deepEqual(lits.filter(x => /[\u3040-\u30ff\u4e00-\u9fff]/.test(x)), [], 'Japanese text in L(): give it a key');
  assert.deepEqual(keys.filter(k => !(k in WORDS)), []);
  for (const [k, w] of Object.entries(WORDS)) {
    assert.match(k, /^mail\.[a-z0-9_]+(\.[a-z0-9_]+)*$/);
    for (const l of LANGS) assert.ok(typeof w[l] === 'string' && w[l], `${k}: ${l}`);
    const names = l => [...w[l].matchAll(/\{\w+\}/g)].map(x => x[0]).sort();
    assert.deepEqual(names('en'), names('ja'), k); assert.deepEqual(names('zh-CN'), names('ja'), k);
  }
  for (const k of Object.values(VALUE)) assert.ok(k in WORDS, k);
  assert.deepEqual(LANGS, ['ja', 'en', 'zh-CN']);
  assert.equal(translator('ja')('mail.move_to_s', { s: '未決' }), '未決へ');
  assert.equal(translator('en')('no.such.key'), 'no.such.key');
});

test('i18n: the page, its rows and its default', async () => {
  const b = makeBox({ drop: PRIVATE, publicOnly: true, items: ITEMS() });
  try {
    const s = await startServer(b);
    try {
      const ja = (await s.get('/email/')).text;
      assert.ok(ja.includes('<html lang="ja">'));
      for (const w of ['<title>新着まとめ</title>', '>既読へ</button>', '>AIで対応</button>', '対応: 日程を返信', '下準備: 下書きを作成',
        '>↩ 返信</span>', '待ち: 1/5(月) 09:00<br>成立したら: 出欠を返す', '>待ちを外す</button>', 'data-say="締切 1/6(火)']) assert.ok(ja.includes(w), w);

      const en = (await s.get('/email/?lang=en')).text;
      assert.ok(en.includes('<html lang="en">'));
      for (const w of ['<title>Digest</title>', 'Digest (Mail)', '>Settings</a>', '>→ Read</button>', '>Handle with AI</button>',
        '<h2>To do <small', '<h2>Waiting <small', 'Action: 日程を返信', 'Prepared: 下書きを作成', '>↩ Reply</span>',
        'Waiting: 1/5 (Mon) 09:00<br>Then: 出欠を返す', '>Stop waiting</button>', '>Due 1/6 (Tue) ', 'data-say="締切 1/6(火)',
        'Last check: 2026-11-05 09:30', 'const LANG="en"', '見学の件', '佐藤']) assert.ok(en.includes(w), w);
      // the frame's Japanese is gone from the markup (the items' own words, and the code's keys, stay)
      for (const w of ['>既読へ<', '>AIで対応<', '>設定<', '<h2>未決 ', 'class="ac">対応', 'class="run">最終チェック']) assert.ok(!en.includes(w), w);

      // the page's own scripts (the dictionary, L(), client.js, speak.js) still parse in each language
      for (const page of [ja, en]) for (const m of page.matchAll(/<script>([\s\S]*?)<\/script>/g)) assert.doesNotThrow(() => new Function(m[1]));
      const zh = (await s.get('/email/?lang=zh-CN')).text;
      for (const w of ['<html lang="zh-CN">', '新消息摘要(邮件)', '>移到已读</button>', '<h2>待处理 <small', '截止 1/6(周二)']) assert.ok(zh.includes(w), w);

      // the rows fetched later carry the language of the page that asks for them
      assert.ok((await s.get('/email/rows?status=' + encodeURIComponent('既決') + '&offset=0&lang=en')).text.includes('>→ To do</button>'));
      assert.ok((await s.get('/email/row?id=mail:18a0000000000003&lang=zh-CN')).text.includes('>移到待处理</button>'));
      assert.ok((await s.get('/email/row?id=mail:18a0000000000003')).text.includes('>未決へ</button>'));
      // an unknown language is Japanese
      assert.ok((await s.get('/email/?lang=xx')).text.includes('<html lang="ja">'));
    } finally { await s.stop(); }
  } finally { b.cleanup(); }
});
