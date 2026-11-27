// まとめページの表示の言語(日本語・English・简体中文。2026-11-24 ユーザー依頼「/email/ を3か国語に」、同じ日に the deployment notes と同じ鍵の形に)。
// 文には鍵(mail.<名前>)を付け、3言語を並べて持つ(日本語も3つのうちの1つ)。L('mail.none') がページの言語の文。
// 訳すのはページの枠(見出し・ボタン・知らせ)だけ。項目の中身(題・要約・対応・メモ)は Claude が書いた言葉のまま、
// Claude に送る文(client.js の 1 通目など)と読み上げる文は日本語のまま(CLAUDE.md・声に合わせる)。
// 言語はページの ?lang= で決める(無ければ日本語)。ページの先頭のスクリプトが、aiza と同じブラウザの選択
// (localStorage aiza-lang)と違えば ?lang= を付けて読み直す(nginx はブラウザの持つ値をアプリに渡さないので、ここで知る方法はこれだけ)。
// 状態の名前(未決など)・読む先の名前・既決の小見出しは items.json やブラウザの覚えにそのまま入る値なので、Lv(値) で VALUE の鍵を引いて出す。
export const LANGS = ['ja', 'en', 'zh-CN'];
export const pickLang = v => LANGS.includes(v) ? v : 'ja';
const WD = { ja: [...'日月火水木金土'], en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'], 'zh-CN': ['周日', '周一', '周二', '周三', '周四', '周五', '周六'] };
export const weekday = (lang, n) => (WD[lang] || WD.ja)[n];

export const WORDS = {
  "mail.action_x": { ja: "対応: {x}", en: "Action: {x}", 'zh-CN': "处理:{x}" },
  "mail.asking_claude_decide_once_work": { ja: "Claude に、作業を終えたら既決にしてよいか決めるよう伝えています…", en: "Asking Claude to decide, once its work is done, whether this can be Done…", 'zh-CN': "正在请 Claude 完成工作后决定能否标为已处理…" },
  "mail.authentication_failed": { ja: "認証に失敗しました", en: "Authentication failed", 'zh-CN': "认证失败" },
  "mail.check_now_x": { ja: "今すぐチェック({x})", en: "Check now ({x})", 'zh-CN': "立即检查({x})" },
  "mail.checking": { ja: "確認中…", en: "Checking…", 'zh-CN': "确认中…" },
  "mail.checking_x_about_10_seconds": { ja: "チェック中…({x} は10秒ほど)", en: "Checking… ({x}: about 10 seconds)", 'zh-CN': "检查中…({x} 约 10 秒)" },
  "mail.claude_decides_after_current_work": { ja: "Claude が今の作業を終えてから既決にするか決めます(要ると判断したら未決に戻ります)", en: "Claude decides, after its current work, whether this is done (if it still needs something, it goes back to To do)", 'zh-CN': "Claude 完成当前工作后决定是否标为已处理(若仍需处理,会回到待处理)" },
  "mail.continue_ai": { ja: "AIで続きから", en: "Continue with AI", 'zh-CN': "用 AI 继续" },
  "mail.could_not_continue_earlier_conversation": { ja: "前の会話の続きから始められませんでした({x})。新しく始めますか?", en: "Could not continue the earlier conversation ({x}). Start a new one?", 'zh-CN': "无法从之前的对话继续({x})。要重新开始吗?" },
  "mail.could_not_prepare_claude_session": { ja: "Claudeセッションを用意できませんでした: {x}", en: "Could not prepare the Claude session: {x}", 'zh-CN': "无法准备 Claude 会话:{x}" },
  "mail.could_not_reach_claude_so": { ja: "Claude に伝えられなかったので、セッションを停止・アーカイブします: {x}", en: "Could not reach Claude, so the session is being stopped and archived: {x}", 'zh-CN': "无法转告 Claude,将停止并归档会话:{x}" },
  "mail.could_not_save_in_digest": { ja: "まとめ側への保存に失敗: {x}", en: "Could not save it in the digest: {x}", 'zh-CN': "保存到摘要失败:{x}" },
  "mail.could_not_start_authentication": { ja: "認証を開始できませんでした", en: "Could not start authentication", 'zh-CN': "无法开始认证" },
  "mail.could_not_stop_session_x": { ja: "セッションの停止に失敗: {x}", en: "Could not stop the session: {x}", 'zh-CN': "停止会话失败:{x}" },
  "mail.default": { ja: "既定", en: "Default", 'zh-CN': "默认" },
  "mail.device_voice": { ja: "端末の声", en: "Device voice", 'zh-CN': "设备语音" },
  "mail.digest": { ja: "新着まとめ", en: "Digest", 'zh-CN': "新消息摘要" },
  "mail.digest_x": { ja: "新着まとめ({x})", en: "Digest ({x})", 'zh-CN': "新消息摘要({x})" },
  "mail.google_voice_via_server": { ja: "Google の声(サーバー経由)", en: "Google voice (via the server)", 'zh-CN': "Google 语音(经服务器)" },
  "mail.google_voices_unavailable_device_voice": { ja: "Google の声を使えません(端末の声で読みます)", en: "Google voices unavailable (the device voice reads instead)", 'zh-CN': "无法使用 Google 语音(改用设备语音)" },
  "mail.loading_google_voices": { ja: "Google の声を読み込み中…", en: "Loading Google voices…", 'zh-CN': "正在加载 Google 语音…" },
  "mail.on_device_pick_output_in": { ja: "この端末では出力先は端末の設定で選びます", en: "On this device, pick the output in the device's settings", 'zh-CN': "此设备请在系统设置中选择输出" },
  "mail.output": { ja: "出力先", en: "Output", 'zh-CN': "输出" },
  "mail.read_aloud": { ja: "読み上げ", en: "Read aloud", 'zh-CN': "朗读" },
  "mail.show_names": { ja: "(名前を出す…)", en: "(Show names…)", 'zh-CN': "(显示名称…)" },
  "mail.speaker": { ja: "スピーカー", en: "Speaker", 'zh-CN': "扬声器" },
  "mail.task_x": { ja: "頼むこと: {x}", en: "To do: {x}", 'zh-CN': "要做的事:{x}" },
  "mail.done_if_claude_decides_still": { ja: "伝えました。Claude が要ると判断したら未決に戻ります", en: "Done. If Claude decides it is still needed, it goes back to To do", 'zh-CN': "已转告。若 Claude 判断仍需处理,会回到待处理" },
  "mail.due_d_rest": { ja: "締切 {d} {rest}", en: "Due {d} {rest}", 'zh-CN': "截止 {d} {rest}" },
  "mail.earlier_session_ended_conversation": { ja: "前のセッションは終了していて会話IDも分かりません。新しく始めますか?", en: "The earlier session has ended and its conversation is unknown. Start a new one?", 'zh-CN': "之前的会话已结束且不知道对话 ID。要重新开始吗?" },
  "mail.english": { ja: "英語", en: "English", 'zh-CN': "英语" },
  "mail.failed_x": { ja: "失敗: {x}", en: "Failed: {x}", 'zh-CN': "失败:{x}" },
  "mail.failed_x_press_again": { ja: "失敗: {x}(もう一度押す)", en: "Failed: {x} (press again)", 'zh-CN': "失败:{x}(再按一次)" },
  "mail.first_look": { ja: "速報", en: "First look", 'zh-CN': "快讯" },
  "mail.handle_ai": { ja: "AIで対応", en: "Handle with AI", 'zh-CN': "用 AI 处理" },
  "mail.japanese": { ja: "日本語", en: "Japanese", 'zh-CN': "日语" },
  "mail.last_check_x": { ja: "最終チェック: {x}", en: "Last check: {x}", 'zh-CN': "上次检查:{x}" },
  "mail.link": { ja: "リンク", en: "link", 'zh-CN': "链接" },
  "mail.long_press_speed_voice": { ja: "長押しで速さ・声", en: "Long-press for speed and voice", 'zh-CN': "长按设置语速和声音" },
  "mail.mail_id": { ja: "メール {id}", en: "Mail {id}", 'zh-CN': "邮件 {id}" },
  "mail.met_d_why": { ja: "成立 {d}: {why}", en: "Met {d}: {why}", 'zh-CN': "已满足 {d}:{why}" },
  "mail.moving_s": { ja: "{s}へ移しています…", en: "Moving to {s}…", 'zh-CN': "正在移到{s}…" },
  "mail.n_days_left": { ja: "あと{n}日", en: "{n} days left", 'zh-CN': "还剩 {n} 天" },
  "mail.n_days_overdue": { ja: "{n}日過ぎ", en: "{n} days overdue", 'zh-CN': "已过 {n} 天" },
  "mail.n_summarizing": { ja: "{n}件、要約中", en: "{n}, summarizing", 'zh-CN': "{n} 条,正在摘要" },
  "mail.next": { ja: "⏭ 次へ", en: "⏭ Next", 'zh-CN': "⏭ 下一条" },
  "mail.none": { ja: "なし", en: "None", 'zh-CN': "无" },
  "mail.not_yet": { ja: "まだ", en: "not yet", 'zh-CN': "尚无" },
  "mail.note_x": { ja: "メモ: {x}", en: "Note: {x}", 'zh-CN': "备注:{x}" },
  "mail.nothing_new": { ja: "新着なし", en: "Nothing new", 'zh-CN': "没有新消息" },
  "mail.online": { ja: " (オンライン)", en: " (online)", 'zh-CN': "(在线)" },
  "mail.open_ai": { ja: "AIを開く", en: "Open AI", 'zh-CN': "打开 AI" },
  "mail.or": { ja: " または ", en: " or ", 'zh-CN': " 或 " },
  "mail.original_messages_n": { ja: "元のメッセージ {n}件", en: "Original messages: {n}", 'zh-CN': "原始消息 {n} 条" },
  "mail.original_messages_not_in_summary": { ja: "要約に無い元のメッセージ {n}件", en: "Original messages not in the summary: {n}", 'zh-CN': "摘要中未提及的原始消息 {n} 条" },
  "mail.paused_tap_item_go_on": { ja: " ⏸ 一時停止中(項目をタップでそこから)", en: " ⏸ Paused (tap an item to go on from there)", 'zh-CN': " ⏸ 已暂停(点击某项从那里继续)" },
  "mail.prepared_t": { ja: "下準備: {t}", en: "Prepared: {t}", 'zh-CN': "准备:{t}" },
  "mail.prepared_t_updated_since": { ja: "下準備: {t}(このあと更新あり)", en: "Prepared: {t} (updated since)", 'zh-CN': "准备:{t}(之后有更新)" },
  "mail.read_item_out_long_press": { ja: "この項目を読み上げる(長押しで速さ・声)", en: "Read this item out (long-press for speed and voice)", 'zh-CN': "朗读此项(长按设置语速和声音)" },
  "mail.read_out_do_unread": { ja: "🔊 未決・未読を読み上げる", en: "🔊 Read out To do and Unread", 'zh-CN': "🔊 朗读待处理和未读" },
  "mail.regular_check_running_press_again": { ja: "定期チェックが動いているので、終わってからもう一度押してください", en: "A regular check is running; press again when it has finished", 'zh-CN': "定期检查正在运行,请在结束后再按一次" },
  "mail.reply": { ja: "↩ 返信", en: "↩ Reply", 'zh-CN': "↩ 回复" },
  "mail.move_to_s": { ja: "{s}へ", en: "→ {s}", 'zh-CN': "移到{s}" },
  "mail.settings": { ja: "設定", en: "Settings", 'zh-CN': "设置" },
  "mail.showing_first_look_summary_in": { ja: "速報を表示中。要約はあと1〜2分", en: "Showing the first look. The summary in 1–2 minutes", 'zh-CN': "正在显示快讯。摘要还需 1–2 分钟" },
  "mail.showing_first_look_summary_x": { ja: "速報を表示中。要約と {x} はあと1〜2分", en: "Showing the first look. The summary and {x} in 1–2 minutes", 'zh-CN': "正在显示快讯。摘要和 {x} 还需 1–2 分钟" },
  "mail.someone_else_replied_goes_away": { ja: "本人以外から返信が来た(本人が状態を変えると消える)", en: "Someone else replied (goes away when you change the state)", 'zh-CN': "有其他人回复(你更改状态后消失)" },
  "mail.source.mail": { ja: "メール", en: "Mail", 'zh-CN': "邮件" },
  "mail.speed": { ja: "速さ", en: "Speed", 'zh-CN': "语速" },
  "mail.starting": { ja: "開始…", en: "Starting…", 'zh-CN': "开始…" },
  "mail.starting_2": { ja: "起動中…", en: "Starting…", 'zh-CN': "启动中…" },
  "mail.status.done": { ja: "既決", en: "Done", 'zh-CN': "已处理" },
  "mail.status.read": { ja: "既読", en: "Read", 'zh-CN': "已读" },
  "mail.status.todo": { ja: "未決", en: "To do", 'zh-CN': "待处理" },
  "mail.status.unread": { ja: "未読", en: "Unread", 'zh-CN': "未读" },
  "mail.status.waiting": { ja: "待ち", en: "Waiting", 'zh-CN': "等待中" },
  "mail.stop": { ja: "⏹ 停止", en: "⏹ Stop", 'zh-CN': "⏹ 停止" },
  "mail.stop_archive_n_claude_sessions": { ja: "既決の Claude セッション {n} 件を停止・アーカイブ(パスキー)", en: "Stop and archive {n} Claude sessions of Done items (passkey)", 'zh-CN': "停止并归档已处理项目的 {n} 个 Claude 会话(通行密钥)" },
  "mail.stop_waiting": { ja: "待ちを外す", en: "Stop waiting", 'zh-CN': "取消等待" },
  "mail.stop_waiting_2": { ja: "待ちを外しますか?", en: "Stop waiting for this?", 'zh-CN': "取消等待吗?" },
  "mail.stopped_archived_claude_session": { ja: "Claude セッションを停止・アーカイブしました", en: "Stopped and archived the Claude session", 'zh-CN': "已停止并归档 Claude 会话" },
  "mail.stopping_archiving": { ja: "停止・アーカイブ中…", en: "Stopping and archiving…", 'zh-CN': "正在停止并归档…" },
  "mail.stopping_archiving_claude_session": { ja: "Claude セッションを停止・アーカイブしています…", en: "Stopping and archiving the Claude session…", 'zh-CN': "正在停止并归档 Claude 会话…" },
  "mail.stopping_session_needs_unlock_button": { ja: "セッションの停止に解錠が要ります(上のボタンから)", en: "Stopping the session needs an unlock (the button above)", 'zh-CN': "停止会话需要解锁(使用上方按钮)" },
  "mail.then_x": { ja: "成立したら: {x}", en: "Then: {x}", 'zh-CN': "满足后:{x}" },
  "mail.tomorrow": { ja: "明日", en: "Tomorrow", 'zh-CN': "明天" },
  "mail.try": { ja: "試す", en: "Try", 'zh-CN': "试听" },
  "mail.voice": { ja: "声", en: "Voice", 'zh-CN': "声音" },
  "mail.waiting_claude": { ja: "Claude起動待ち…", en: "Waiting for Claude…", 'zh-CN': "等待 Claude 启动…" },
  "mail.waiting_x": { ja: "待ち: {x}", en: "Waiting: {x}", 'zh-CN': "等待:{x}" },
  "mail.when.earlier": { ja: "それ以前", en: "Earlier", 'zh-CN': "更早" },
  "mail.when.month": { ja: "1ヶ月以内", en: "This month", 'zh-CN': "一个月内" },
  "mail.when.today": { ja: "今日", en: "Today", 'zh-CN': "今天" },
  "mail.when.week": { ja: "1週間以内", en: "This week", 'zh-CN': "一周内" },
  "mail.when.yesterday": { ja: "昨日", en: "Yesterday", 'zh-CN': "昨天" },
  "mail.when_x": { ja: "条件: {x}", en: "when: {x}", 'zh-CN': "条件:{x}" },
  "mail.x_follow": { ja: "({x} もこのあと)", en: " ({x} to follow)", 'zh-CN': "({x} 稍后)" },
  "mail.held_x": { ja: "🔒 保留({x})", en: "🔒 Held ({x})", 'zh-CN': "🔒 保留({x})" },
  "mail.held_why_rule": { ja: "決まり", en: "rule", 'zh-CN': "规则" },
  "mail.held_why_llm": { ja: "ローカルの判定", en: "local check", 'zh-CN': "本地判断" },
  "mail.held_note": { ja: "ローカルの確認で止めたもの。Claude には渡していません", en: "Held back by the local check; not given to Claude", 'zh-CN': "本地检查拦下的内容,尚未交给 Claude" },
  "mail.held_newer_x": { ja: "新しいメッセージ {x}", en: "New message {x}", 'zh-CN': "新消息 {x}" },
  "mail.give_to_claude": { ja: "Claudeに渡す", en: "Give to Claude", 'zh-CN': "交给 Claude" },
  "mail.give_to_claude_confirm": { ja: "この項目を Claude に渡しますか?(保留を外し、普通の項目にします)", en: "Give this item to Claude? (It stops being held and becomes an ordinary item.)", 'zh-CN': "要把此项交给 Claude 吗?(取消保留,变为普通项目)" },
  "mail.keep_from_claude": { ja: "渡さない", en: "Keep from Claude", 'zh-CN': "不交给" },
  "mail.kept_from_claude": { ja: "Claude に渡さないことにした", en: "Kept from Claude", 'zh-CN': "已决定不交给 Claude" },
  "mail.gate_withheld_x": { ja: "ローカルの確認が済まず、{x} からの新着をまだ Claude に渡していません(次の回に読み直します)", en: "The local check could not finish, so what came in since {x} has not been given to Claude yet (the next check reads it again)", 'zh-CN': "本地检查未能完成,{x} 以来的新消息尚未交给 Claude(下次检查会重新读取)" },
  "mail.go_on_rules_only": { ja: "決まりだけで進める", en: "Go on with the rules only", 'zh-CN': "仅按规则继续" },
  "mail.go_on_rules_only_confirm": { ja: "ローカルの確認なしで、決まりに当たらない新着を Claude に渡して、今すぐチェックしますか?(ローカルに届いたら元に戻ります)", en: "Without the local check, give Claude what does not match the rules and check now? (Back to normal once the local check is reachable.)", 'zh-CN': "不经本地检查,把不符合规则的新消息交给 Claude 并立即检查吗?(本地检查恢复后自动还原)" },
};
// 値(データに入る日本語)→ 鍵
export const VALUE = {"未読": "mail.status.unread", "未決": "mail.status.todo", "待ち": "mail.status.waiting", "既読": "mail.status.read", "既決": "mail.status.done", "メール": "mail.source.mail", "今日": "mail.when.today", "昨日": "mail.when.yesterday", "1週間以内": "mail.when.week", "1ヶ月以内": "mail.when.month", "それ以前": "mail.when.earlier"};

// 訳す関数。鍵が無ければ鍵のまま。vars はそのまま埋める(HTML に出すものは呼ぶ側で esc 済みにする)
const pick = (lang, s) => { const w = WORDS[s]; return w ? (w[lang] ?? w.en ?? w.ja) : s; };
export function translator(lang) {
  return (s, vars) => {
    let out = pick(lang, s);
    if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
    return out;
  };
}
export const valueTranslator = L => v => L(VALUE[v] || v);

// ページに埋める分(この言語の文だけと、同じ L()・Lv())。
export function clientScript(lang) {
  const d = JSON.stringify(Object.fromEntries(Object.entries(WORDS).map(([k, w]) => [k, w[lang] ?? w.en ?? w.ja]))).replace(/</g, '\\u003c');
  return `const LANG=${JSON.stringify(lang)},LT=${d},LV=${JSON.stringify(VALUE)};
function L(s,v){let o=LT[s]??s;if(v)o=o.replace(/\\{(\\w+)\\}/g,(m,k)=>k in v?String(v[k]):m);return o}
function Lv(x){return L(LV[x]||x)}
const LQ='&lang='+encodeURIComponent(LANG);`;
}
export function langRedirect(lang) {
  return `<script>try{let w=localStorage.getItem('aiza-lang');if(!${JSON.stringify(LANGS)}.includes(w))w='ja';if(w!==${JSON.stringify(lang)}){const u=new URL(location.href);u.searchParams.set('lang',w);location.replace(u)}}catch(e){}</script>`;
}
