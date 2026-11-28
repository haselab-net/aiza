// aiza's display language: 日本語 / English / 简体中文 (the deployment notes; keys since 2026-11-24).
//
// Every word the page shows has a key, "<area>.<name>" (lowercase, "_"),
// and its three languages side by side, none of them the source:
// t("list.empty_hint") gives it in the chosen language, "{name}" filled from
// t()'s second argument. The area is the page script that shows it
// (list, chat, ...), "index" for index.html's own markup, "common" when
// several do. A message the server makes comes as {key, vars} and the page
// says it with t() the same way. index.html's markup names its keys with
// data-i18n attributes and apply() fills them before app.js runs.
// `tools/i18n <key or words>` shows a key's three languages, or finds keys.
//
// The choice is kept in this browser (localStorage, read before the first
// paint) and in the user's own backend (GET/POST /prefs), so another device
// picks it up after logging in. Loaded by index.html, outbox-browse.html and
// the deployment's own pages (login, ...), which all share this origin;
// those define() their own words.
// The page's base (2026-11-27, the public demo, the deployment notes): "" on a
// deployment, "/r/<seat>" when the page is a seat of a demo room -- every
// address the page makes starts with it (window.aizaBase), and this
// browser's storage is the seat's own (a key prefix), so two seats in two
// tabs of one browser are two people. First thing the page runs.
(function () {
  const m = typeof location === "undefined" ? null : /^\/r\/[a-z0-9]{24}(?=\/)/.exec(location.pathname);
  window.aizaBase = m ? m[0] : "";
  if (!m) return;
  let real;
  try { real = window.localStorage; } catch (e) { return; }
  const P = `seat:${m[0].slice(3)}:`;
  const mine = () => { const ks = []; for (let i = 0; i < real.length; i++) { const k = real.key(i); if (k && k.startsWith(P)) ks.push(k); } return ks; };
  const seat = {
    getItem: (k) => real.getItem(P + k),
    setItem: (k, v) => real.setItem(P + k, v),
    removeItem: (k) => real.removeItem(P + k),
    key: (i) => { const k = mine()[i]; return k === undefined ? null : k.slice(P.length); },
    clear: () => { for (const k of mine()) real.removeItem(k); },
    get length() { return mine().length; },
  };
  try { Object.defineProperty(window, "localStorage", { value: seat, configurable: true }); } catch (e) { /* the shared storage, then */ }
})();
(function () {
  // aigw-legacy: this browser's settings from before the name AI座
  // (2026-11-23) are under keys that began with "aigw": copy them once.
  try {
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith("aigw") && localStorage.getItem("aiza" + k.slice(4)) === null) {
        localStorage.setItem("aiza" + k.slice(4), localStorage.getItem(k));
      }
    }
  } catch (e) { /* storage blocked: defaults */ }
  const LANGS = { ja: "日本語", en: "English", "zh-CN": "简体中文" };
  const STORE_KEY = "aiza-lang";

  const W = Object.create(null);

  function readStored() {
    try {
      const v = localStorage.getItem(STORE_KEY);
      return v && v in LANGS ? v : null;
    } catch (e) {
      return null;
    }
  }

  let lang = readStored() || "ja";
  document.documentElement.lang = lang;

  // t("list.new_name", { n: 3 }): the word in the chosen language; English,
  // then Japanese, when that language lacks it (the tests keep all three);
  // an unknown key comes back as it is, HTML-escaped (2026-11-28): the
  // words are put in markup in many places, and a value with no word (a
  // language code, a key the server is newer about, or anything else
  // passed in) must not become markup there. Keys never hold <>&"'.
  const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
  function t(key, vars) {
    const w = W[key];
    let out = w ? (w[lang] ?? w.en ?? w.ja) : String(key ?? "").replace(/[&<>"']/g, (c) => ESC[c]);
    if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
    return out;
  }

  const ATTRS = ["title", "placeholder", "aria-label"];

  // Static markup: an element with data-i18n="<key>" gets that word as its
  // text, data-i18n-title / -placeholder / -aria-label="<key>" that
  // attribute (the <title> too, with apply(document.documentElement)). The
  // markup's own text is the Japanese, for the moment before this runs.
  function apply(root) {
    if (!root || !root.querySelectorAll) return;
    for (const el of root.querySelectorAll("[data-i18n]")) el.textContent = t(el.getAttribute("data-i18n"));
    for (const a of ATTRS) {
      for (const el of root.querySelectorAll(`[data-i18n-${a}]`)) el.setAttribute(a, t(el.getAttribute(`data-i18n-${a}`)));
    }
  }

  // A system message saved before messages carried a key (chat history from
  // before 2026-11-24 has only its Japanese text): the key to show it with.
  const OLD_TEXT = {
    "Claude Code にまだログインしていないので、先にログインの画面を開きました。下に出る URL をタップしてブラウザで開き、承認すると表示されるコードをコピーして、この画面の入力欄に貼り付けて送信してください。ログインが済んだら、もう一度セッションを作ってください。": "auth.login.claude_first",
    "Claude Code のログインです。下に出る URL をタップしてブラウザで開き、承認すると表示されるコードをコピーして、この画面の入力欄に貼り付けて送信してください。": "auth.login.claude_new",
    "Codex にまだログインしていないので、先にログインの画面を開きました。下に出る URL をタップしてブラウザで開き、この画面に出ているコードをそのページに入力してください。ログインが済んだら、もう一度セッションを作ってください。": "auth.login.codex_first",
    "Codex のログインです。下に出る URL をタップしてブラウザで開き、この画面に出ているコードをそのページに入力してください。": "auth.login.codex_new",
    "進行中のログインがあるので、それを開きました。下に出る URL をタップしてブラウザで開き、この画面に出ているコードをそのページに入力してください。": "auth.login.codex_again",
    "進行中のログインがあるので、それを開きました。下に出る URL をタップしてブラウザで開き、承認すると表示されるコードをコピーして、この画面の入力欄に貼り付けて送信してください。(前に開いた別の URL で取ったコードは使えません。)": "auth.login.claude_again",
  };
  function fromText(text) {
    return OLD_TEXT[text] || null;
  }

  // The choice also lives in the user's own backend (POST /prefs), so a
  // new device picks it up after logging in; the page is reloaded to
  // re-render everything in the new language.
  async function setLang(next) {
    if (!(next in LANGS) || next === lang) return;
    try { localStorage.setItem(STORE_KEY, next); } catch (e) { /* private mode */ }
    try {
      await fetch(window.aizaBase + "/agents/api/prefs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lang: next }),
      });
    } catch (e) { /* kept in this browser at least */ }
    location.reload();
  }

  // After login: if this browser has no choice yet, or another device
  // changed it, follow the server's.
  async function syncFromServer() {
    let r;
    try {
      r = await fetch(window.aizaBase + "/agents/api/prefs").then((x) => (x.ok ? x.json() : null));
    } catch (e) {
      return;
    }
    const server = r && r.lang in LANGS ? r.lang : null;
    if (!server) {
      // First time on the server: record what this browser already uses.
      const local = readStored();
      if (local) fetch(window.aizaBase + "/agents/api/prefs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ lang: local }),
      }).catch(() => {});
      return;
    }
    if (server !== lang) {
      try { localStorage.setItem(STORE_KEY, server); } catch (e) { /* private mode */ }
      location.reload();
    }
  }

  // Words: { "<area>.<name>": { ja, en, "zh-CN" } }, the three languages side
  // by side. The core's are below; an extension's page file, and each of the
  // deployment's own pages, define() theirs the same way.
  function define(words) {
    for (const [k, v] of Object.entries(words || {})) W[k] = v;
  }

  window.aizaI18n = { t, apply, define, fromText, setLang, syncFromServer, LANGS, lang: () => lang, _words: W };
  window.t = t;

  /* i18n-begin */ define({
    // api
    "api.biometric_authentication_cancelled_or": {
      ja: "生体認証がキャンセルまたは失敗しました: {err}",
      en: "Biometric authentication was cancelled or failed: {err}",
      "zh-CN": "生物识别认证已取消或失败:{err}",
    },
    "api.browser_did_not_show_passkey": {
      ja: "パスキーの画面を自動では出せませんでした({err})。画面のどこかを押すと出します",
      en: "The browser did not show the passkey prompt by itself ({err}). Tap anywhere to show it",
      "zh-CN": "浏览器未能自动弹出通行密钥窗口({err})。点画面任意处即弹出",
    },
    "api.browser_does_not_support_passkeys": {
      ja: "このブラウザはパスキー(WebAuthn)に対応していません",
      en: "This browser does not support passkeys (WebAuthn)",
      "zh-CN": "此浏览器不支持通行密钥(WebAuthn)",
    },
    "api.label_unlocked_tap_lock_now": {
      ja: "{label} がアンロック中。タップでロック(今すぐ解除)",
      en: "{label} is unlocked. Tap to lock now",
      "zh-CN": "{label} 已解锁。点按立即锁定",
    },
    "api.lock_root_host_now": {
      ja: "root/hostのアンロックを今すぐ解除しますか?",
      en: "Lock root/host now?",
      "zh-CN": "要立即锁定 root/host 吗?",
    },
    "api.unlock_tap_anywhere_ask": {
      ja: "🔓 解錠する(どこかを押すと出ます)",
      en: "🔓 Unlock (tap anywhere to ask)",
      "zh-CN": "🔓 解锁(点任意处即弹出)",
    },
    // app
    "app.could_not_read_issue_err": {
      ja: "Issue を読めませんでした: {err}",
      en: "Could not read the issue: {err}",
      "zh-CN": "无法读取 Issue:{err}",
    },
    "app.desk_branches": {
      ja: "ブランチ",
      en: "Branches",
      "zh-CN": "分支",
    },
    "app.desk_choose": {
      ja: "選んでください",
      en: "Choose one",
      "zh-CN": "请选择",
    },
    "app.desk_choose_first": {
      ja: "配備するブランチかプルリクを選んでください",
      en: "Pick the branch or pull request to deploy",
      "zh-CN": "请选择要部署的分支或拉取请求",
    },
    "app.desk_closing_keeps_draft": {
      ja: "閉じても書いた文は残ります",
      en: "Closing keeps what you wrote",
      "zh-CN": "关闭后已写的内容会保留",
    },
    "app.desk_commit_from_other_host": {
      ja: "配備するコミット(もう一方のホストで選んだもの)",
      en: "The commit to deploy (picked on the other host)",
      "zh-CN": "要部署的提交(在另一台主机上选择)",
    },
    "app.desk_deploy_hint": {
      ja: "自分で直したものの配備を頼みます。直したブランチかプルリクを選び、何を直したかを書いてください。窓口の決まりの範囲なら自動で両方のホストに入ります。",
      en: "Ask for your own fix to be deployed: pick the branch or pull request with it and write what it fixes. Within the desk's rule it goes onto both hosts on its own.",
      "zh-CN": "请求部署自己的修复：选择包含修复的分支或拉取请求，并写下修复了什么。在窗口规则范围内会自动部署到两台主机。",
    },
    "app.desk_deploy_needs_session": {
      ja: "配備の依頼は、直したセッションの ⋯ の「窓口」から送ってください",
      en: "Send a deploy request from the ⋯ menu of the session where you fixed it",
      "zh-CN": "请从修复所在会话的 ⋯ 菜单发送部署请求",
    },
    "app.desk_deploy_placeholder": {
      ja: "何を直したか",
      en: "What it fixes",
      "zh-CN": "修复了什么",
    },
    "app.desk_deploy_sent": {
      ja: "配備を頼みました({what})。仕事の木の「AI座 の窓口」で進み具合が見えます。",
      en: "Deploy requested ({what}). Follow it under \"AI座 の窓口\" in the work tree.",
      "zh-CN": "已请求部署({what})。可在工作树的「AI座 の窓口」中查看进展。",
    },
    "app.desk_deploy_tab": {
      ja: "配備の依頼",
      en: "Deploy request",
      "zh-CN": "部署请求",
    },
    "app.desk_pick_what": {
      ja: "配備するもの",
      en: "What to deploy",
      "zh-CN": "要部署的内容",
    },
    "app.desk_pulls": {
      ja: "開いているプルリク",
      en: "Open pull requests",
      "zh-CN": "打开的拉取请求",
    },
    "app.desk_reading_branches": {
      ja: "ブランチとプルリクを読んでいます…",
      en: "Reading branches and pull requests…",
      "zh-CN": "正在读取分支和拉取请求…",
    },
    "app.desk_report_hint": {
      ja: "何が起きたか、何が足りないかを書いてください。座の皆に見えます。セッションはリンクだけで、devbox の会話は窓口だけが読みます。",
      en: "Write what happened or what is missing. Everyone in AI-za can see it. The session goes as a link only; only the desk reads a devbox conversation.",
      "zh-CN": "请写下发生了什么或缺少什么。座内的所有人都能看到。会话只附链接，devbox 的对话只有窗口能读。",
    },
    "app.desk_report_placeholder": {
      ja: "何が起きたか・何が足りないか",
      en: "What happened, or what is missing",
      "zh-CN": "发生了什么，或缺少什么",
    },
    "app.desk_report_tab": {
      ja: "報告(不具合・要望)",
      en: "Report (bug or request)",
      "zh-CN": "报告(问题・需求)",
    },
    "app.desk_send": {
      ja: "送る",
      en: "Send",
      "zh-CN": "发送",
    },
    "app.desk_title": {
      ja: "窓口",
      en: "Desk",
      "zh-CN": "窗口",
    },
    "app.desk_write_something": {
      ja: "何か書いてください",
      en: "Write something first",
      "zh-CN": "请先写点内容",
    },
    "app.could_not_send_desk_err": {
      ja: "窓口に送れませんでした: {err}",
      en: "Could not send to the desk: {err}",
      "zh-CN": "未能提交给窗口: {err}",
    },
    "app.issue_closed": {
      ja: "⚠ この Issue は閉じています",
      en: "⚠ This issue is closed",
      "zh-CN": "⚠ 此 Issue 已关闭",
    },
    "app.notify_blocked": {
      ja: "この端末では通知が止められています(ブラウザの設定で許可)",
      en: "Notifications are blocked on this device (allow them in the browser settings)",
      "zh-CN": "此设备的通知已被阻止(请在浏览器设置中允许)",
    },
    "app.notify_off": {
      ja: "この端末には通知しません",
      en: "This device gets no notifications",
      "zh-CN": "此设备不接收通知",
    },
    "app.notify_on": {
      ja: "この端末に通知します",
      en: "Notifications are on for this device",
      "zh-CN": "此设备已开启通知",
    },
    "app.notify_unavailable": {
      ja: "このブラウザは通知を受けられません",
      en: "This browser cannot receive notifications",
      "zh-CN": "此浏览器无法接收通知",
    },
    "app.sandhome_repo_does_not_exist": {
      ja: "~/sandhome/{repo} がありません。先に clone してください",
      en: "~/sandhome/{repo} does not exist. Clone it first",
      "zh-CN": "~/sandhome/{repo} 不存在。请先 clone",
    },
    "app.sent_desk_follow_under_ai": {
      ja: "窓口に送りました。仕事の木の「AI座 の窓口」で進み具合が見えます。",
      en: "Sent to the desk. Follow it under \"AI座 の窓口\" in the work tree.",
      "zh-CN": "已提交。可在工作树的「AI座 の窓口」中查看进展。",
    },
    "app.session_issue_already_running_open": {
      ja: "この Issue のセッションがすでに動いています。開きますか？",
      en: "A session for this issue is already running. Open it?",
      "zh-CN": "此 Issue 的会话已在运行。要打开吗？",
    },
    "app.start_claude_in_issues_worktree": {
      ja: "この Issue 用の worktree(~/sandhome/{repo}-wt/i{n})で Claude を起動しますか？",
      en: "Start Claude in this issue's worktree (~/sandhome/{repo}-wt/i{n})?",
      "zh-CN": "要在此 Issue 的 worktree(~/sandhome/{repo}-wt/i{n})中启动 Claude 吗？",
    },
    "app.status_not_ready": {
      ja: "⚠ Status が Ready ではありません",
      en: "⚠ Its Status is not Ready",
      "zh-CN": "⚠ Status 不是 Ready",
    },
    // auth.login
    "auth.login.claude_again": {
      ja: "進行中のログインがあるので、それを開きました。下に出る URL をタップしてブラウザで開き、承認すると表示されるコードをコピーして、この画面の入力欄に貼り付けて送信してください。(前に開いた別の URL で取ったコードは使えません。)",
      en: "A login was already in progress, so it was opened. Tap the URL shown below to open it in your browser, approve, then copy the code it shows and paste it into the box on this screen and send it. (A code from a URL opened earlier will not work.)",
      "zh-CN": "已有进行中的登录,已将其打开。点击下方出现的 URL 在浏览器中打开,授权后复制显示的代码,粘贴到本页的输入框并发送。(之前打开的其他 URL 获得的代码无法使用。)",
    },
    "auth.login.claude_first": {
      ja: "Claude Code にまだログインしていないので、先にログインの画面を開きました。下に出る URL をタップしてブラウザで開き、承認すると表示されるコードをコピーして、この画面の入力欄に貼り付けて送信してください。ログインが済んだら、もう一度セッションを作ってください。",
      en: "You are not logged in to Claude Code yet, so the login was opened first. Tap the URL shown below to open it in your browser, approve, then copy the code it shows and paste it into the box on this screen and send it. Once logged in, create the session again.",
      "zh-CN": "尚未登录 Claude Code,因此先打开了登录页面。点击下方出现的 URL 在浏览器中打开,授权后复制显示的代码,粘贴到本页的输入框并发送。登录完成后,请再次创建会话。",
    },
    "auth.login.claude_new": {
      ja: "Claude Code のログインです。下に出る URL をタップしてブラウザで開き、承認すると表示されるコードをコピーして、この画面の入力欄に貼り付けて送信してください。",
      en: "Claude Code login. Tap the URL shown below to open it in your browser, approve, then copy the code it shows and paste it into the box on this screen and send it.",
      "zh-CN": "Claude Code 登录。点击下方出现的 URL 在浏览器中打开,授权后复制显示的代码,粘贴到本页的输入框并发送。",
    },
    "auth.login.codex_again": {
      ja: "進行中のログインがあるので、それを開きました。下に出る URL をタップしてブラウザで開き、この画面に出ているコードをそのページに入力してください。",
      en: "A login was already in progress, so it was opened. Tap the URL shown below to open it in your browser, then enter the code shown on this screen on that page.",
      "zh-CN": "已有进行中的登录,已将其打开。点击下方出现的 URL 在浏览器中打开,然后在该页面输入本页显示的代码。",
    },
    "auth.login.codex_first": {
      ja: "Codex にまだログインしていないので、先にログインの画面を開きました。下に出る URL をタップしてブラウザで開き、この画面に出ているコードをそのページに入力してください。ログインが済んだら、もう一度セッションを作ってください。",
      en: "You are not logged in to Codex yet, so the login was opened first. Tap the URL shown below to open it in your browser, then enter the code shown on this screen on that page. Once logged in, create the session again.",
      "zh-CN": "尚未登录 Codex,因此先打开了登录页面。点击下方出现的 URL 在浏览器中打开,然后在该页面输入本页显示的代码。登录完成后,请再次创建会话。",
    },
    "auth.login.codex_new": {
      ja: "Codex のログインです。下に出る URL をタップしてブラウザで開き、この画面に出ているコードをそのページに入力してください。",
      en: "Codex login. Tap the URL shown below to open it in your browser, then enter the code shown on this screen on that page.",
      "zh-CN": "Codex 登录。点击下方出现的 URL 在浏览器中打开,然后在该页面输入本页显示的代码。",
    },
    // chat
    "chat.allow_session": {
      ja: "このセッション中は許可",
      en: "Allow for this session",
      "zh-CN": "本会话中允许",
    },
    "chat.ask_unverified": {
      ja: "このカードは AI座 の記録に無いので、中身を確かめられません。端末で答えてください。",
      en: "AI-za has no record of this card, so its content cannot be checked. Answer on the terminal.",
      "zh-CN": "AI座 的记录中没有这张卡片,无法确认其内容。请在终端回答。",
    },
    "chat.ask_unverified_question": {
      ja: "質問",
      en: "Question",
      "zh-CN": "提问",
    },
    "chat.allow_tool_run": {
      ja: "{tool} の実行を許可しますか",
      en: "Allow {tool} to run?",
      "zh-CN": "允许运行 {tool} 吗",
    },
    "chat.allowed": {
      ja: "許可済み",
      en: "Allowed",
      "zh-CN": "已允许",
    },
    "chat.dismiss_write_in_chat": {
      ja: "答えずにチャットで書く",
      en: "Write in the chat instead",
      "zh-CN": "不回答，在聊天中写",
    },
    "chat.answer_on_terminal": {
      ja: "端末で答える",
      en: "Answer on the terminal",
      "zh-CN": "在终端回答",
    },
    "chat.answered": {
      ja: "答えました",
      en: "Answered",
      "zh-CN": "已回答",
    },
    "chat.answered_on_terminal": {
      ja: "端末で答えました",
      en: "Answered on the terminal",
      "zh-CN": "已在终端回答",
    },
    "chat.bytes": {
      ja: "バイト",
      en: "bytes",
      "zh-CN": "字节",
    },
    "chat.can_also_answer_on_terminal": {
      ja: "端末でも答えられます",
      en: "You can also answer on the terminal",
      "zh-CN": "也可以在终端回答",
    },
    "chat.can_no_longer_answered": {
      ja: "もう答えられません",
      en: "Can no longer be answered",
      "zh-CN": "已无法回答",
    },
    "chat.closed": {
      ja: "終わりました",
      en: "Closed",
      "zh-CN": "已结束",
    },
    "chat.content": {
      ja: "中身",
      en: "Content",
      "zh-CN": "内容",
    },
    "chat.default": {
      ja: "(既定)",
      en: "(default)",
      "zh-CN": "(默认)",
    },
    "chat.deny": {
      ja: "拒否",
      en: "Deny",
      "zh-CN": "拒绝",
    },
    "chat.do_not_allow": {
      ja: "許可しない",
      en: "Do not allow",
      "zh-CN": "不允许",
    },
    "chat.done": {
      ja: "実行済み",
      en: "Done",
      "zh-CN": "已执行",
    },
    "chat.failed": {
      ja: "実行に失敗",
      en: "Failed",
      "zh-CN": "执行失败",
    },
    "chat.reply_to_header": {
      ja: "返信先(Reply-To)",
      en: "Reply-To",
      "zh-CN": "回复地址(Reply-To)",
    },
    "chat.address_headers_as_written": {
      ja: "宛先のヘッダー(書かれたまま)",
      en: "Address headers (as written)",
      "zh-CN": "地址头(原样)",
    },
    "chat.channel_name_declared": {
      ja: "名前「{x}」は用意した側の申告(開くのは上の URL)",
      en: "The name “{x}” is what the preparing side wrote (the URL above is what is opened)",
      "zh-CN": "名称“{x}”是准备方填写的(实际打开的是上面的 URL)",
    },
    "chat.from": {
      ja: "差出人",
      en: "From",
      "zh-CN": "发件人",
    },
    "chat.html_only_mail_shown_html": {
      ja: "(HTML だけのメール。HTML のまま表示)",
      en: "(HTML-only mail, shown as HTML source)",
      "zh-CN": "(仅 HTML 的邮件,按 HTML 源显示)",
    },
    "chat.list": {
      ja: "← 一覧",
      en: "← List",
      "zh-CN": "← 列表",
    },
    "chat.loading_failed_scroll_try_again": {
      ja: "読み込みに失敗しました(スクロールでやり直せます)",
      en: "Loading failed (scroll to try again)",
      "zh-CN": "加载失败(滚动可重试)",
    },
    "chat.tool_denied": {
      ja: "Auto モードが断った",
      en: "Refused by auto mode",
      "zh-CN": "被 Auto 模式拒绝",
    },
    "chat.tool_denied_why": {
      ja: "({reason})",
      en: " ({reason})",
      "zh-CN": "({reason})",
    },
    "chat.n_more": {
      ja: "(ほか {n} 件)",
      en: "({n} more)",
      "zh-CN": "(另有 {n} 条)",
    },
    "chat.new_mail": {
      ja: "新しいメール",
      en: "New mail",
      "zh-CN": "新邮件",
    },
    "chat.needs_you": {
      ja: "見てほしいことがあります",
      en: "Something for you to look at",
      "zh-CN": "有需要您查看的内容",
    },
    "chat.status_checked": {
      ja: "確認した",
      en: "Checked",
      "zh-CN": "已确认",
    },
    "chat.status_later": {
      ja: "後で",
      en: "Later",
      "zh-CN": "稍后",
    },
    "chat.status_checked_message": {
      ja: "確認しました",
      en: "Checked.",
      "zh-CN": "已确认。",
    },
    "chat.could_not_send_checked_err": {
      ja: "「確認しました」を送れませんでした: {err}",
      en: "Could not send \"Checked\": {err}",
      "zh-CN": "无法发送「已确认」:{err}",
    },
    "chat.no_enter": {
      ja: "⏎なし",
      en: "no ⏎",
      "zh-CN": "无 ⏎",
    },
    "chat.no_subagents_yet": {
      ja: "サブエージェントはまだありません",
      en: "No subagents yet",
      "zh-CN": "还没有子代理",
    },
    "chat.no_subject": {
      ja: "(件名なし)",
      en: "(no subject)",
      "zh-CN": "(无主题)",
    },
    "chat.not_allowed": {
      ja: "許可しなかった",
      en: "Not allowed",
      "zh-CN": "未允许",
    },
    "chat.nothing_here_yet": {
      ja: "(まだ内容がありません)",
      en: "(nothing here yet)",
      "zh-CN": "(还没有内容)",
    },
    "chat.other_type_press_enter": {
      ja: "その他(書いて送る)",
      en: "Other (type and press Enter)",
      "zh-CN": "其他(输入后回车)",
    },
    "chat.owner_s_session_watch_only": {
      ja: "{owner}さんのセッション(見るだけ)",
      en: "{owner}'s session (watch only)",
      "zh-CN": "{owner} 的会话(仅查看)",
    },
    "chat.owner_s_shared_log_read": {
      ja: "{owner}さんの共有ログ(閲覧のみ)",
      en: "{owner}'s shared log (read-only)",
      "zh-CN": "{owner} 的共享记录(只读)",
    },
    "chat.passkey_unlock_expired_open_again": {
      ja: "🔒 パスキーの解錠が切れました。開き直してください",
      en: "🔒 The passkey unlock has expired. Open it again",
      "zh-CN": "🔒 通行密钥解锁已过期。请重新打开",
    },
    "chat.post": {
      ja: "投稿先",
      en: "Post to",
      "zh-CN": "发布到",
    },
    "chat.reading_session_needs_passkey_unlock": {
      ja: "🔒 このセッションを読むにはパスキーでの解錠が要ります。開き直してください",
      en: "🔒 Reading this session needs a passkey unlock. Open it again",
      "zh-CN": "🔒 阅读此会话需要用通行密钥解锁。请重新打开",
    },
    "chat.reason_denying_optional": {
      ja: "拒否の理由(なくてもよい)",
      en: "Reason for denying (optional)",
      "zh-CN": "拒绝的理由(可不填)",
    },
    "chat.reply": {
      ja: "返信",
      en: "Reply",
      "zh-CN": "回复",
    },
    "chat.reply_in_thread": {
      ja: "スレッドへの返信",
      en: "Reply in thread",
      "zh-CN": "回复到话题",
    },
    "chat.see_everything": {
      ja: "全文を見る",
      en: "See everything",
      "zh-CN": "查看全部",
    },
    "chat.sent": {
      ja: "送り先",
      en: "Sent to",
      "zh-CN": "提交到",
    },
    "chat.session_ended": {
      ja: "セッションは終了しました",
      en: "The session has ended",
      "zh-CN": "会话已结束",
    },
    "chat.session_ended_exit_code_code": {
      ja: "セッションは終了しました (終了コード {code})",
      en: "The session has ended (exit code {code})",
      "zh-CN": "会话已结束(退出码 {code})",
    },
    "chat.shared_owner": {
      ja: "{owner}さんと共有中",
      en: "Shared by {owner}",
      "zh-CN": "{owner} 共享中",
    },
    "chat.subject": {
      ja: "件名",
      en: "Subject",
      "zh-CN": "主题",
    },
    "chat.submit_button": {
      ja: "送信のボタン",
      en: "Submit button",
      "zh-CN": "提交按钮",
    },
    "chat.take_p_on_new_session": {
      ja: "「{p}」を引き取りますか？自分の devbox に新しいセッションを作り、この項目の担当を移します(あとで取り消せます)",
      en: "Take “{p}” on? A new session starts in your devbox and holds this item (you can undo it)",
      "zh-CN": "接手「{p}」吗？将在你的 devbox 中新建会话并负责此项(之后可撤销)",
    },
    "chat.tap_anywhere_go_back": {
      ja: "画面のどこかをタップすると戻ります",
      en: "Tap anywhere to go back",
      "zh-CN": "点按任意位置返回",
    },
    "chat.thinking": {
      ja: "考え中…",
      en: "Thinking…",
      "zh-CN": "思考中…",
    },
    "chat.thinking_tap_all": {
      ja: "思考(タップで全文)",
      en: "Thinking (tap for all of it)",
      "zh-CN": "思考(点按查看全文)",
    },
    "chat.threads_move_trash": {
      ja: "ゴミ箱へ移すスレッド",
      en: "Threads to move to the trash",
      "zh-CN": "移到垃圾箱的会话",
    },
    "chat.timed_out_answer_on_terminal": {
      ja: "時間切れ(端末で答えてください)",
      en: "Timed out (answer on the terminal)",
      "zh-CN": "已超时(请在终端回答)",
    },
    "chat.to": {
      ja: "宛先",
      en: "To",
      "zh-CN": "收件人",
    },
    "chat.values_fill_in": {
      ja: "入れる値",
      en: "Values to fill in",
      "zh-CN": "填入的值",
    },
    "chat.waiting_answer": {
      ja: "許可を待っています",
      en: "Waiting for your answer",
      "zh-CN": "等待你的答复",
    },
    "chat.waiting_claude_take": {
      ja: "Claude が受け取るのを待っています",
      en: "Waiting for Claude to take it",
      "zh-CN": "等待 Claude 接收",
    },
    "chat.withdrawn": {
      ja: "取り下げ",
      en: "Withdrawn",
      "zh-CN": "已撤回",
    },
    // common
    "common.actions": {
      ja: "操作",
      en: "Actions",
      "zh-CN": "操作",
    },
    "common.ai_za": {
      ja: "AI座",
      en: "AI-za",
      "zh-CN": "AI座",
    },
    "common.all": {
      ja: "すべて",
      en: "All",
      "zh-CN": "全部",
    },
    "common.all_2": {
      ja: "全部",
      en: "All",
      "zh-CN": "全部",
    },
    "common.allow": {
      ja: "許可",
      en: "Allow",
      "zh-CN": "允许",
    },
    "common.already_running": {
      ja: "動いています",
      en: "Already running.",
      "zh-CN": "正在运行。",
    },
    "common.already_stopped": {
      ja: "止まっています",
      en: "Already stopped.",
      "zh-CN": "已停止。",
    },
    "common.arrange": {
      ja: "並べ替え",
      en: "Arrange",
      "zh-CN": "排序",
    },
    "common.assignees": {
      ja: "担当",
      en: "Assignees",
      "zh-CN": "负责人",
    },
    "common.attachments": {
      ja: "添付",
      en: "Attachments",
      "zh-CN": "附件",
    },
    "common.authentication_failed": {
      ja: "認証に失敗しました",
      en: "Authentication failed",
      "zh-CN": "认证失败",
    },
    "common.auto": {
      ja: "自動",
      en: "auto",
      "zh-CN": "自动",
    },
    "common.by_ball": {
      ja: "🙋 番ごと",
      en: "🙋 By turn",
      "zh-CN": "🙋 按轮次",
    },
    "common.ok": {
      ja: "OK",
      en: "OK",
      "zh-CN": "确定",
    },
    "common.cancel": {
      ja: "やめる",
      en: "Cancel",
      "zh-CN": "取消",
    },
    "common.cancel_2": {
      ja: "キャンセル",
      en: "Cancel",
      "zh-CN": "取消",
    },
    "common.cannot_see_session_no_longer": {
      ja: "このセッションは見られません(共有が外されたか、消されたか、もう一方のホストのものです)",
      en: "You cannot see this session (no longer shared with you, removed, or on the other host)",
      "zh-CN": "无法查看此会话(已取消共享、已删除或属于另一台主机)",
    },
    "common.cant_resume": {
      ja: "再開できません",
      en: "Can't resume.",
      "zh-CN": "无法继续。",
    },
    "common.checking": {
      ja: "確認中…",
      en: "Checking…",
      "zh-CN": "检查中…",
    },
    "common.choose_drive": {
      ja: "ドライブを選ぶ…",
      en: "Choose a drive…",
      "zh-CN": "选择驱动器…",
    },
    "common.choose_drive_2": {
      ja: "ドライブを選択…",
      en: "Choose a drive…",
      "zh-CN": "选择驱动器…",
    },
    "common.close": {
      ja: "閉じる",
      en: "Close",
      "zh-CN": "关闭",
    },
    "common.co_work": {
      ja: "共同作業",
      en: "Co-work",
      "zh-CN": "协作",
    },
    "common.co_work_2": {
      ja: "書き込み可で共有",
      en: "Co-work",
      "zh-CN": "协作",
    },
    "common.connect": {
      ja: "接続",
      en: "Connect",
      "zh-CN": "连接",
    },
    "common.continue": {
      ja: "続きから",
      en: "Continue from",
      "zh-CN": "继续",
    },
    "common.copy": {
      ja: "コピー",
      en: "Copy",
      "zh-CN": "复制",
    },
    "common.could_not_create_session_err": {
      ja: "セッションを作成できませんでした: {err}",
      en: "Could not create the session: {err}",
      "zh-CN": "无法创建会话:{err}",
    },
    "common.could_not_load_err": {
      ja: "読み込めませんでした: {err}",
      en: "Could not load: {err}",
      "zh-CN": "无法加载:{err}",
    },
    "common.could_not_start_authentication": {
      ja: "認証を開始できませんでした",
      en: "Could not start authentication",
      "zh-CN": "无法开始认证",
    },
    "common.could_not_start_login_err": {
      ja: "ログインを開始できませんでした: {err}",
      en: "Could not start the login: {err}",
      "zh-CN": "无法开始登录:{err}",
    },
    "common.default": {
      ja: "既定",
      en: "Default",
      "zh-CN": "默认",
    },
    "common.delete": {
      ja: "削除",
      en: "Delete",
      "zh-CN": "删除",
    },
    "common.deleted": {
      ja: "削除",
      en: "deleted",
      "zh-CN": "已删除",
    },
    "common.delivered": {
      ja: "届いた",
      en: "Delivered",
      "zh-CN": "已送达",
    },
    "common.done": {
      ja: "済み",
      en: "Done",
      "zh-CN": "已完成",
    },
    "common.dont_ask_before_each_ai": {
      ja: "AI の操作をいちいち確認しない(--dangerously-skip-permissions)",
      en: "Don't ask before each AI action (--dangerously-skip-permissions)",
      "zh-CN": "不逐一确认 AI 的操作(--dangerously-skip-permissions)",
    },
    "common.drag_move": {
      ja: "ドラッグで移動",
      en: "Drag to move",
      "zh-CN": "拖动以移动",
    },
    "common.ended": {
      ja: "終了",
      en: "Ended",
      "zh-CN": "结束",
    },
    "common.everyone": {
      ja: "全員",
      en: "Everyone",
      "zh-CN": "所有人",
    },
    "common.everyones_logins": {
      ja: "全員のログイン一覧",
      en: "Everyone's logins",
      "zh-CN": "所有人的登录",
    },
    "common.directory": {
      ja: "ディレクトリ",
      en: "Directory",
      "zh-CN": "目录",
    },
    "common.folder": {
      ja: "フォルダ",
      en: "Folder",
      "zh-CN": "文件夹",
    },
    "common.folder_name": {
      ja: "フォルダの名前",
      en: "Folder name",
      "zh-CN": "文件夹名称",
    },
    "common.hash": {
      ja: "ハッシュ",
      en: "Hash",
      "zh-CN": "哈希",
    },
    "common.host": {
      ja: "ホスト",
      en: "host",
      "zh-CN": "主机",
    },
    "common.host_no_work_tree": {
      ja: "このホストには仕事の木がありません",
      en: "This host has no work tree",
      "zh-CN": "此主机没有工作树",
    },
    "common.kind": {
      ja: "種類",
      en: "Kind",
      "zh-CN": "类型",
    },
    "common.link_2": {
      ja: "リンク",
      en: "link",
      "zh-CN": "链接",
    },
    "common.link_share_save": {
      ja: "連携・共有・保存",
      en: "Link, share, save",
      "zh-CN": "联动、共享、保存",
    },
    "common.list": {
      ja: "一覧へ",
      en: "To the list",
      "zh-CN": "返回列表",
    },
    "common.loading": {
      ja: "読み込み中…",
      en: "Loading…",
      "zh-CN": "加载中…",
    },
    "common.log_in": {
      ja: "ログイン",
      en: "Log in",
      "zh-CN": "登录",
    },
    "common.log_in_again": {
      ja: "ログインし直す",
      en: "Log in again",
      "zh-CN": "重新登录",
    },
    "common.log_out": {
      ja: "ログアウト",
      en: "Log out",
      "zh-CN": "退出登录",
    },
    "common.logged_in": {
      ja: "ログイン済み",
      en: "Logged in",
      "zh-CN": "已登录",
    },
    "common.machines": {
      ja: "マシン",
      en: "Machines",
      "zh-CN": "机器",
    },
    "common.mail": {
      ja: "メール",
      en: "Mail",
      "zh-CN": "邮件",
    },
    "common.make_new_folder": {
      ja: "新しいフォルダを作る",
      en: "Make a new folder",
      "zh-CN": "新建文件夹",
    },
    "common.mark_done": {
      ja: "済みにする",
      en: "Mark done",
      "zh-CN": "标为完成",
    },
    "common.me": {
      ja: "自分",
      en: "Me",
      "zh-CN": "我",
    },
    "common.messages": {
      ja: "通",
      en: "messages",
      "zh-CN": "封",
    },
    "common.min": {
      ja: "分",
      en: "min",
      "zh-CN": "分",
    },
    "common.n_hits": {
      ja: "{n}件",
      en: "{n} hits",
      "zh-CN": "{n} 条",
    },
    "common.needs": {
      ja: "要判断",
      en: "Needs you",
      "zh-CN": "需要你决定",
    },
    "common.new": {
      ja: "↓ 新着",
      en: "↓ New",
      "zh-CN": "↓ 新消息",
    },
    "common.new_2": {
      ja: "新規",
      en: "New",
      "zh-CN": "新建",
    },
    "common.new_job": {
      ja: "新しい仕事",
      en: "New job",
      "zh-CN": "新工作",
    },
    "common.new_sessions": {
      ja: "新しいセッション",
      en: "New sessions",
      "zh-CN": "新会话",
    },
    "common.no_time_limit": {
      ja: "切らない",
      en: "no time limit",
      "zh-CN": "不限时",
    },
    "common.none": {
      ja: "なし",
      en: "none",
      "zh-CN": "无",
    },
    "common.not_logged_in": {
      ja: "未ログイン",
      en: "Not logged in",
      "zh-CN": "未登录",
    },
    "common.nothing_found": {
      ja: "見つかりませんでした",
      en: "Nothing found",
      "zh-CN": "未找到",
    },
    "common.open": {
      ja: "開く",
      en: "Open",
      "zh-CN": "打开",
    },
    "common.open_archive": {
      ja: "🗄 アーカイブを開く",
      en: "🗄 Open the archive",
      "zh-CN": "🗄 打开归档",
    },
    "common.open_shared_logs": {
      ja: "🧑‍🤝‍🧑 共有ログを開く",
      en: "🧑‍🤝‍🧑 Open shared logs",
      "zh-CN": "🧑‍🤝‍🧑 打开共享记录",
    },
    "common.open_subfolder": {
      ja: "サブディレクトリを開く…",
      en: "Open a subdirectory…",
      "zh-CN": "打开子目录…",
    },
    "common.other": {
      ja: "その他",
      en: "Other",
      "zh-CN": "其他",
    },
    "common.owner": {
      ja: "{owner}さん",
      en: "{owner}",
      "zh-CN": "{owner}",
    },
    "common.period": {
      ja: "。",
      en: ". ",
      "zh-CN": "。",
    },
    "common.person": {
      ja: "人",
      en: "Person",
      "zh-CN": "人",
    },
    "common.read_aloud": {
      ja: "読み上げ",
      en: "Read aloud",
      "zh-CN": "朗读",
    },
    "common.read_aloud_voice_mode": {
      ja: "読み上げ・音声モード",
      en: "Read aloud / voice mode",
      "zh-CN": "朗读 / 语音模式",
    },
    "common.read_only": {
      ja: "閲覧のみ",
      en: "Read-only",
      "zh-CN": "只读",
    },
    "common.remove": {
      ja: "外す",
      en: "Remove",
      "zh-CN": "移除",
    },
    "common.remove_2": {
      ja: "解除",
      en: "Remove",
      "zh-CN": "取消",
    },
    "common.rename": {
      ja: "名前を変更",
      en: "Rename",
      "zh-CN": "重命名",
    },
    "common.rename_2": {
      ja: "変える",
      en: "Rename",
      "zh-CN": "更改",
    },
    "common.root": {
      ja: "ルート",
      en: "Root",
      "zh-CN": "root",
    },
    "common.run": {
      ja: "実行",
      en: "Run",
      "zh-CN": "执行",
    },
    "common.running": {
      ja: "動いている",
      en: "running",
      "zh-CN": "运行中",
    },
    "common.running_2": {
      ja: "実行中",
      en: "Running",
      "zh-CN": "执行中",
    },
    "common.save": {
      ja: "保存",
      en: "Save",
      "zh-CN": "保存",
    },
    "common.screen": {
      ja: "画面",
      en: "Screen",
      "zh-CN": "画面",
    },
    "common.search": {
      ja: "検索",
      en: "Search",
      "zh-CN": "搜索",
    },
    "common.send": {
      ja: "送る",
      en: "Send",
      "zh-CN": "发送",
    },
    "common.send_2": {
      ja: "送信",
      en: "Send",
      "zh-CN": "发送",
    },
    "common.set": {
      ja: "決める",
      en: "Set",
      "zh-CN": "确定",
    },
    "common.settings": {
      ja: "設定",
      en: "Settings",
      "zh-CN": "设置",
    },
    "common.share": {
      ja: "共有",
      en: "Share",
      "zh-CN": "共享",
    },
    "common.shared_owner": {
      ja: "{owner}さんと共有",
      en: "shared by {owner}",
      "zh-CN": "{owner} 共享",
    },
    "common.snoozed": {
      ja: "寝かせ",
      en: "Snoozed",
      "zh-CN": "搁置",
    },
    "common.start": {
      ja: "始める",
      en: "Start",
      "zh-CN": "开始",
    },
    "common.start_2": {
      ja: "開始",
      en: "Start",
      "zh-CN": "开始",
    },
    "common.start_conversation": {
      ja: "ここが会話の最初です",
      en: "This is the start of the conversation",
      "zh-CN": "这是对话的开头",
    },
    "common.state": {
      ja: "状態",
      en: "State",
      "zh-CN": "状态",
    },
    "common.stopped": {
      ja: "停止",
      en: "stopped",
      "zh-CN": "已停止",
    },
    "common.stopped_2": {
      ja: "止まっている",
      en: "stopped",
      "zh-CN": "已停止",
    },
    "common.subagents": {
      ja: "サブエージェント",
      en: "Subagents",
      "zh-CN": "子代理",
    },
    "common.take_on": {
      ja: "引き取る",
      en: "Take it on",
      "zh-CN": "接手",
    },
    "common.tap_resume": {
      ja: "タップで再開",
      en: "Tap to resume",
      "zh-CN": "点按以继续",
    },
    "common.tap_stop": {
      ja: "タップで停止",
      en: "Tap to stop",
      "zh-CN": "点按以停止",
    },
    "common.text": {
      ja: "本文",
      en: "Text",
      "zh-CN": "正文",
    },
    "common.todo": {
      ja: "やること",
      en: "To do",
      "zh-CN": "待办",
    },
    "common.tree_view": {
      ja: "🌳 木",
      en: "🌳 Tree",
      "zh-CN": "🌳 树",
    },
    "common.try_again": {
      ja: "もう一度お試しください。",
      en: "Please try again.",
      "zh-CN": "请再试一次。",
    },
    "common.turn": {
      ja: "あなたの番",
      en: "Your turn",
      "zh-CN": "轮到你",
    },
    "common.undo": {
      ja: "元に戻す",
      en: "Undo",
      "zh-CN": "撤销",
    },
    "common.unlock": {
      ja: "🔓 解錠する",
      en: "🔓 Unlock",
      "zh-CN": "🔓 解锁",
    },
    "common.unreachable": {
      ja: "届かない",
      en: "Unreachable",
      "zh-CN": "无法连接",
    },
    "common.usage_view": {
      ja: "📊 利用",
      en: "📊 Usage",
      "zh-CN": "📊 使用",
    },
    "common.use": {
      ja: "使う",
      en: "Use",
      "zh-CN": "使用",
    },
    "common.user": {
      ja: "ユーザー",
      en: "User",
      "zh-CN": "用户",
    },
    "common.username": {
      ja: "ユーザー名",
      en: "Username",
      "zh-CN": "用户名",
    },
    "common.voice": {
      ja: "声",
      en: "Voice",
      "zh-CN": "声音",
    },
    "common.waiting": {
      ja: "確認待ち",
      en: "Waiting for you",
      "zh-CN": "等待确认",
    },
    "common.waiting_snoozed": {
      ja: "待ち(寝かせ)",
      en: "Waiting (snoozed)",
      "zh-CN": "等待（搁置）",
    },
    "common.watch": {
      ja: "見る",
      en: "Watch",
      "zh-CN": "查看",
    },
    "common.week_view": {
      ja: "📅 週",
      en: "📅 Week",
      "zh-CN": "📅 周",
    },
    "common.work": {
      ja: "仕事",
      en: "Work",
      "zh-CN": "工作",
    },
    "common.work_on_in_session": {
      ja: "セッションで作業",
      en: "Work on this in a session",
      "zh-CN": "用会话做这项",
    },
    "common.working": {
      ja: "作業中",
      en: "working",
      "zh-CN": "工作中",
    },
    "common.you": {
      ja: "あなた",
      en: "you",
      "zh-CN": "你",
    },
    // compose
    "compose.could_not_attach_file_err": {
      ja: "ファイルの添付に失敗しました: {err}",
      en: "Could not attach the file: {err}",
      "zh-CN": "添加附件失败:{err}",
    },
    "compose.some_files_not_attached": {
      ja: "次のファイルは添付できませんでした(ほかは添付しました):\n{list}",
      en: "These files could not be attached (the others were):\n{list}",
      "zh-CN": "以下文件未能添加(其他文件已添加):\n{list}",
    },
    "compose.file_too_large_limit_mb": {
      ja: "ファイルが大きすぎます(上限{mb}MB)。",
      en: "The file is too large (limit {mb} MB).",
      "zh-CN": "文件过大(上限 {mb} MB)。",
    },
    "compose.open_session_unsent_text_back": {
      ja: "そのセッションを開くと、送れなかった文が入力欄に戻ります。",
      en: "Open that session and the unsent text will be back in the input box.",
      "zh-CN": "打开那个会话,未发送的文字会回到输入框。",
    },
    "compose.session_is_stopped": {
      ja: "このセッションは止まっています。",
      en: "This session has stopped.",
      "zh-CN": "这个会话已停止。",
    },
    "compose.stopped_cannot_resume": {
      ja: "セッションが止まっていて、ここからは再開できないので送っていません",
      en: "the session has stopped and cannot be resumed from here, so nothing was sent",
      "zh-CN": "会话已停止且无法从这里恢复,所以没有发送",
    },
    "compose.could_not_resume_err": {
      ja: "止まっていたセッションを再開できなかったので送っていません({err})",
      en: "the stopped session could not be resumed, so nothing was sent ({err})",
      "zh-CN": "无法恢复已停止的会话,所以没有发送({err})",
    },
    "compose.resumed_not_ready": {
      ja: "再開しましたが、{s} 秒のうちに入力を受けられるようにならなかったので送っていません",
      en: "resumed, but it was not ready for input within {s} s, so nothing was sent",
      "zh-CN": "已恢复,但 {s} 秒内未能接受输入,所以没有发送",
    },
    "compose.resuming_then_sending": {
      ja: "止まっていたので再開しています。立ち上がったら送ります",
      en: "It had stopped; resuming it. The text goes in once it is up",
      "zh-CN": "会话已停止,正在恢复。启动后发送",
    },
    "compose.sending_failed_err": {
      ja: "送信に失敗しました: {err}",
      en: "Sending failed: {err}",
      "zh-CN": "发送失败:{err}",
    },
    "compose.sending_label_failed_err": {
      ja: "「{label}」への送信に失敗しました: {err}",
      en: "Sending to \"{label}\" failed: {err}",
      "zh-CN": "发送到「{label}」失败:{err}",
    },
    // form
    "form.claude_root": {
      ja: "Claude (ルート)",
      en: "Claude (root)",
      "zh-CN": "Claude(root)",
    },
    "form.codex_root": {
      ja: "Codex (ルート)",
      en: "Codex (root)",
      "zh-CN": "Codex(root)",
    },
    "form.could_not_create_folder_err": {
      ja: "ディレクトリを作れませんでした: {err}",
      en: "Could not create the directory: {err}",
      "zh-CN": "无法创建目录:{err}",
    },
    "form.could_not_get_list": {
      ja: "(一覧を取得できません)",
      en: "(could not get the list)",
      "zh-CN": "(无法获取列表)",
    },
    "form.dont_ask_before_each_ai": {
      ja: "AI の操作をいちいち確認しない(--dangerously-bypass-approvals-and-sandbox)",
      en: "Don't ask before each AI action (--dangerously-bypass-approvals-and-sandbox)",
      "zh-CN": "不逐一确认 AI 的操作(--dangerously-bypass-approvals-and-sandbox)",
    },
    "form.in_no_folder": {
      ja: "(フォルダに入れない)",
      en: "(in no folder)",
      "zh-CN": "(不放入文件夹)",
    },
    "form.demo_ai": {
      ja: "AI",
      en: "AI",
      "zh-CN": "AI",
    },
    "form.demo_room": {
      ja: "部屋",
      en: "Room",
      "zh-CN": "房间",
    },
    "form.demo_room_invite": {
      ja: "招待する・追い出す(部屋の入口のページ)",
      en: "Invite or send out (the room's door)",
      "zh-CN": "邀请或请出(房间入口页面)",
    },
    "form.name_new_folder": {
      ja: "新しいディレクトリの名前",
      en: "Name of the new directory",
      "zh-CN": "新目录的名称",
    },
    "form.no_drives_found": {
      ja: "(ドライブが見つかりません)",
      en: "(no drives found)",
      "zh-CN": "(未找到驱动器)",
    },
    "form.no_screen_runs_in_session": {
      ja: "画面なし(セッション0で動く)。タップで画面ありに",
      en: "No screen (runs in session 0). Tap for a screen",
      "zh-CN": "无画面(在会话 0 中运行)。点按切换为有画面",
    },
    "form.no_subfolders": {
      ja: "(サブディレクトリなし)",
      en: "(no subdirectories)",
      "zh-CN": "(没有子目录)",
    },
    "form.screen_runs_in_desktop_session": {
      ja: "画面あり(デスクトップのセッション1で動く)。タップで画面なしに",
      en: "With screen (runs in desktop session 1). Tap for no screen",
      "zh-CN": "有画面(在桌面会话 1 中运行)。点按切换为无画面",
    },
    "form.shell_root": {
      ja: "Shell (ルート)",
      en: "Shell (root)",
      "zh-CN": "Shell(root)",
    },
    // index
    "form.ssh_machines": {
      ja: "ssh 機",
      en: "ssh machines",
      "zh-CN": "ssh 机器",
    },
    "index.account": {
      ja: "アカウント",
      en: "Account",
      "zh-CN": "账户",
    },
    "index.ai_logins": {
      ja: "AI のログイン",
      en: "AI logins",
      "zh-CN": "AI 登录",
    },
    "index.ai_za_company_people_who": {
      ja: "AI座 は、会社・部署・研究室など、仕事を共に進める仲間の座です。座の中の人々と AI たちが、一緒に仕事を進めます。",
      en: "AI-za is the company of people who work together — a company, a department, a lab. The people and AIs in it move the work forward together.",
      "zh-CN": "AI座 是一起推进工作的伙伴之「座」——公司、部门、研究室等。座内的人们和 AI 们一起推进工作。",
    },
    "index.all_of_it": {
      ja: "全部",
      en: "All",
      "zh-CN": "全部",
    },
    "index.archive_go_next": {
      ja: "アーカイブして次へ",
      en: "Archive and go to the next",
      "zh-CN": "归档并转到下一个",
    },
    "index.back_live": {
      ja: "● ライブに戻る",
      en: "● Back to live",
      "zh-CN": "● 返回实时",
    },
    "index.back_live_view": {
      ja: "ライブ表示に戻る",
      en: "Back to the live view",
      "zh-CN": "返回实时画面",
    },
    "index.check_everything_again": {
      ja: "全部再確認",
      en: "Check everything again",
      "zh-CN": "全部重新检查",
    },
    "index.claude_host": {
      ja: "Claude (ホスト)",
      en: "Claude (host)",
      "zh-CN": "Claude(主机)",
    },
    "index.codex_host": {
      ja: "Codex (ホスト)",
      en: "Codex (host)",
      "zh-CN": "Codex(主机)",
    },
    "index.create_new_folder_here": {
      ja: "ここに新しいディレクトリを作る",
      en: "Create a new directory here",
      "zh-CN": "在此新建目录",
    },
    "index.delete_chat_log_go_next": {
      ja: "会話ログを削除して次へ",
      en: "Delete the chat log and go to the next",
      "zh-CN": "删除聊天记录并转到下一个",
    },
    "index.display": {
      ja: "表示",
      en: "Display",
      "zh-CN": "显示",
    },
    "index.driving": {
      ja: "運転中",
      en: "Driving",
      "zh-CN": "驾驶中",
    },
    "index.everyones_logins": {
      ja: "🧑‍🤝‍🧑 全員のログイン一覧",
      en: "🧑‍🤝‍🧑 Everyone's logins",
      "zh-CN": "🧑‍🤝‍🧑 所有人的登录",
    },
    "index.existing_tmux_sessions": {
      ja: "既存のtmuxセッション",
      en: "Existing tmux sessions",
      "zh-CN": "现有的 tmux 会话",
    },
    "index.in_work_tree_can_see": {
      ja: "✅ の仕事の木で、どの仕事のボールを誰(人か AI か)が持っているかが見えます。",
      en: "In the ✅ work tree you can see who (a person or an AI) holds the ball for each job.",
      "zh-CN": "在 ✅ 的工作树中,可以看到每项工作的球在谁(人还是 AI)手里。",
    },
    "index.language": {
      ja: "表示言語",
      en: "Language",
      "zh-CN": "显示语言",
    },
    "index.link_it": {
      ja: "結びつける",
      en: "Link it",
      "zh-CN": "关联",
    },
    "index.log_out": {
      ja: "ログアウト",
      en: "Log out",
      "zh-CN": "退出登录",
    },
    "index.machine_work_on": {
      ja: "操作対象のマシン",
      en: "Machine to work on",
      "zh-CN": "要操作的机器",
    },
    "index.machines_settings_board": {
      ja: "マシン・黒板",
      en: "Machines, board",
      "zh-CN": "机器・黑板",
    },
    "index.name_optional": {
      ja: "名前(任意)",
      en: "Name (optional)",
      "zh-CN": "名称(可选)",
    },
    "index.new_folder_title": {
      ja: "フォルダを作る",
      en: "Make a folder",
      "zh-CN": "新建文件夹",
    },
    "index.new_tree_title": {
      ja: "新しい仕事(木)",
      en: "A new job (tree)",
      "zh-CN": "新工作(树)",
    },
    "index.next": {
      ja: "次 ›",
      en: "Next ›",
      "zh-CN": "下一个 ›",
    },
    "index.next_session": {
      ja: "次のセッション",
      en: "Next session",
      "zh-CN": "下一个会话",
    },
    "index.notifications": {
      ja: "通知",
      en: "Notifications",
      "zh-CN": "通知",
    },
    "index.notify_this_device": {
      ja: "この端末に通知する",
      en: "Notify this device",
      "zh-CN": "通知此设备",
    },
    "index.only_stuck_3_days": {
      ja: "3日以上動いていないものだけ",
      en: "Only what has not moved for 3 days or more",
      "zh-CN": "只显示 3 天以上没有进展的",
    },
    "index.only_your_turn": {
      ja: "あなたがボールを持つものだけ",
      en: "Only what is your turn",
      "zh-CN": "只显示轮到你的",
    },
    "index.or_without_screen": {
      ja: "画面の有無",
      en: "With or without a screen",
      "zh-CN": "有无画面",
    },
    "index.phone_or_pc_browser_start": {
      ja: "スマホや PC のブラウザから、Claude Code や Codex などの AI のセッションを作り、チャットで動かします。",
      en: "From a phone or PC browser, start sessions of AI such as Claude Code or Codex and drive them by chat.",
      "zh-CN": "在手机或电脑的浏览器中创建 Claude Code、Codex 等 AI 的会话,并通过聊天来操作。",
    },
    "index.prev": {
      ja: "‹ 前",
      en: "‹ Prev",
      "zh-CN": "‹ 上一个",
    },
    "index.previous_session": {
      ja: "前のセッション",
      en: "Previous session",
      "zh-CN": "上一个会话",
    },
    "index.problems_or_wishes_use_send": {
      ja: "困ったことや欲しいものは、セッションの ⋯ の「📮 窓口に送る」へ。",
      en: "For problems or wishes, use “📮 Send to the desk” in a session's ⋯.",
      "zh-CN": "遇到问题或有需求,请用会话 ⋯ 中的「📮 发送到窗口」。",
    },
    "index.read_aloud_and_voice": {
      ja: "読み上げと音声",
      en: "Read-aloud and voice",
      "zh-CN": "朗读与语音",
    },
    "index.root_host_locked_so_new": {
      ja: "🔒 root/hostのロックが閉じているため、新着メッセージを取得できません",
      en: "🔒 root/host is locked, so new messages cannot be fetched",
      "zh-CN": "🔒 root/host 已锁定,无法获取新消息",
    },
    "index.running": {
      ja: "動いているもの",
      en: "Running",
      "zh-CN": "运行中",
    },
    "index.search_chats": {
      ja: "チャットを検索",
      en: "Search chats",
      "zh-CN": "搜索聊天",
    },
    "index.search_chats_separate_words_spaces": {
      ja: "チャットを検索(空白で区切るとすべてを含むもの)",
      en: "Search chats (separate words with spaces to require all)",
      "zh-CN": "搜索聊天(用空格分隔表示须全部包含)",
    },
    "index.search_short": {
      ja: "🔍 探す",
      en: "🔍 Search",
      "zh-CN": "🔍 搜索",
    },
    "index.send_text_enter_just_enter": {
      ja: "文字を送ってEnter(空ならEnterだけ)",
      en: "Send the text and Enter (just Enter if empty)",
      "zh-CN": "发送文字并按 Enter(为空时只按 Enter)",
    },
    "index.send_text_without_enter": {
      ja: "Enterを送らずに文字だけ送る",
      en: "Send the text without Enter",
      "zh-CN": "只发送文字,不按 Enter",
    },
    "index.sessions_go_through": {
      ja: "巡回するセッション",
      en: "Sessions to go through",
      "zh-CN": "要巡览的会话",
    },
    "index.sessions_run_in_own_work": {
      ja: "セッションは自分の作業箱(devbox)、ホスト、座の Windows マシンなどで動きます(右のマシンのボタンで切り替え)。",
      en: "Sessions run in your own work box (devbox), on the host, or on AI-za's Windows machines (switch with the machine button to the right).",
      "zh-CN": "会话运行在自己的工作箱(devbox)、主机或座内的 Windows 电脑上(用右侧的机器按钮切换)。",
    },
    "index.share_session_people_in_ai": {
      ja: "セッションを座の中の人と共有したり、セッションどうしをつないで AI どうしに相談させたりできます(セッションの ⋯ から)。",
      en: "Share a session with people in AI-za, or link sessions so their AIs can consult each other (from a session's ⋯).",
      "zh-CN": "可以与座内成员共享会话,或把会话联动起来让 AI 彼此商量(从会话的 ⋯)。",
    },
    "index.shell_devbox": {
      ja: "Shell (devbox)",
      en: "Shell (devbox)",
      "zh-CN": "Shell(devbox)",
    },
    "index.shell_host": {
      ja: "Shell (ホスト)",
      en: "Shell (host)",
      "zh-CN": "Shell(主机)",
    },
    "index.show_what": {
      ja: "出すもの",
      en: "Show",
      "zh-CN": "显示",
    },
    "index.start_a_session": {
      ja: "＋ セッションを始める",
      en: "＋ Start a session",
      "zh-CN": "＋ 开始会话",
    },
    "index.start_session": {
      ja: "＋ 🤖 AI",
      en: "＋ 🤖 AI",
      "zh-CN": "＋ 🤖 AI",
    },
    "index.stopped_sessions_too": {
      ja: "止まったセッションも",
      en: "Stopped sessions too",
      "zh-CN": "也显示已停止的会话",
    },
    "index.stuck_3_days_short": {
      ja: "⏳ 3日止まり",
      en: "⏳ Stuck 3 days",
      "zh-CN": "⏳ 停滞 3 天",
    },
    "index.type_message": {
      ja: "メッセージを入力...",
      en: "Type a message...",
      "zh-CN": "输入消息...",
    },
    "index.up_one_folder": {
      ja: "上のディレクトリへ",
      en: "Up one directory",
      "zh-CN": "上一级目录",
    },
    "index.what_ai_za": {
      ja: "AI座 とは",
      en: "What is AI-za",
      "zh-CN": "什么是 AI座",
    },
    "index.what_run": {
      ja: "何を動かすか",
      en: "What to run",
      "zh-CN": "运行什么",
    },
    "index.where_run": {
      ja: "どこで動かすか",
      en: "Where to run it",
      "zh-CN": "在哪里运行",
    },
    "index.where_to_put": {
      ja: "置く場所",
      en: "Where to put it",
      "zh-CN": "放置位置",
    },
    "index.working_directory": {
      ja: "作業ディレクトリ",
      en: "Working directory",
      "zh-CN": "工作目录",
    },
    "index.working_drive_folder": {
      ja: "作業ドライブ/ディレクトリ",
      en: "Working drive/directory",
      "zh-CN": "工作驱动器/目录",
    },
    // keys
    "index.your_turn_short": {
      ja: "🙋 あなたの番",
      en: "🙋 Your turn",
      "zh-CN": "🙋 轮到你",
    },
    "keys.attach_file": {
      ja: "ファイルを添付",
      en: "Attach a file",
      "zh-CN": "添加附件",
    },
    "keys.move_running_work_background": {
      ja: "実行中の作業をバックグラウンドへ",
      en: "Move the running work to the background",
      "zh-CN": "把正在运行的工作转到后台",
    },
    "keys.open_or_close_area_above": {
      ja: "入力欄の上の欄を開く・閉じる",
      en: "Open or close the area above the input",
      "zh-CN": "打开或关闭输入框上方的栏",
    },
    "keys.send_later_queue": {
      ja: "あとで送る(キューに入れる)",
      en: "Send later (queue it)",
      "zh-CN": "稍后发送(加入队列)",
    },
    "keys.send_now_even_while_working": {
      ja: "今すぐ送る(実行中でも割り込んで送る)",
      en: "Send now (even while it is working)",
      "zh-CN": "立即发送(运行中也插入发送)",
    },
    "keys.stop_background_agents": {
      ja: "バックグラウンドのエージェントを止める",
      en: "Stop the background agents",
      "zh-CN": "停止后台代理",
    },
    "keys.write_in_external_editor": {
      ja: "外部エディタで書く",
      en: "Write in an external editor",
      "zh-CN": "用外部编辑器书写",
    },
    // links
    "links.add_link_b": {
      ja: "「{a}」を「{b}」の連携に加えます。",
      en: "Add “{a}” to the link of {b}.",
      "zh-CN": "将「{a}」加入「{b}」的连接。",
    },
    "links.asleep": {
      ja: "寝ている",
      en: "Asleep",
      "zh-CN": "休眠中",
    },
    "links.asleep_free": {
      ja: "寝ている(空き)",
      en: "Asleep (free)",
      "zh-CN": "休眠中(空闲)",
    },
    "links.could_not_link_err": {
      ja: "連携できませんでした: {err}",
      en: "Could not link: {err}",
      "zh-CN": "无法连接:{err}",
    },
    "links.could_not_unlink_err": {
      ja: "切断できませんでした: {err}",
      en: "Could not unlink: {err}",
      "zh-CN": "无法断开:{err}",
    },
    "links.could_not_update_board_err": {
      ja: "黒板を書き換えられませんでした: {err}",
      en: "Could not update the board: {err}",
      "zh-CN": "无法更新黑板：{err}",
    },
    "links.edit_what_being_done": {
      ja: "することを書き換える",
      en: "Edit what is being done",
      "zh-CN": "修改要做的事",
    },
    "links.enter_positive_number_minutes": {
      ja: "分数は正の数で入力してください",
      en: "Enter a positive number of minutes",
      "zh-CN": "请输入正数的分钟数",
    },
    "links.fell": {
      ja: "落ちた",
      en: "fell",
      "zh-CN": "掉线",
    },
    "links.free": {
      ja: "空き",
      en: "Free",
      "zh-CN": "空闲",
    },
    "links.h_h_left": {
      ja: "残り{h}時間",
      en: "{h} h left",
      "zh-CN": "剩余 {h} 小时",
    },
    "links.h_h_m_min_left": {
      ja: "残り{h}時間{m}分",
      en: "{h} h {m} min left",
      "zh-CN": "剩余 {h} 小时 {m} 分钟",
    },
    "links.hand_written": {
      ja: "(手書き)",
      en: "(hand-written)",
      "zh-CN": "(手写)",
    },
    "links.hand_written_2": {
      ja: "手書き",
      en: "hand-written",
      "zh-CN": "手写",
    },
    "links.host_no_place_board": {
      ja: "このホストには黒板の置き場所がありません",
      en: "This host has no place for the board",
      "zh-CN": "此主机没有黑板的存放位置",
    },
    "links.in_use": {
      ja: "使用中",
      en: "In use",
      "zh-CN": "使用中",
    },
    "links.in_use_n": {
      ja: "使用中 {n}",
      en: "In use: {n}",
      "zh-CN": "使用中 {n}",
    },
    "links.link_b": {
      ja: "「{a}」と「{b}」をつなぎます。",
      en: "Link “{a}” and “{b}”.",
      "zh-CN": "将连接「{a}」与「{b}」。",
    },
    "links.merge_links_b": {
      ja: "「{a}」の連携と「{b}」の連携を1つにまとめます(時間の制限は長いほう)。",
      en: "Merge the link of {a} with the link of {b} into one (the longer time limit is kept).",
      "zh-CN": "将「{a}」的连接与「{b}」的连接合并为一个(保留较长的时间限制)。",
    },
    "links.m_min_left": {
      ja: "残り{m}分",
      en: "{m} min left",
      "zh-CN": "剩余 {m} 分钟",
    },
    "links.machines_sessions": {
      ja: "この機械のセッション一覧へ",
      en: "This machine's sessions",
      "zh-CN": "这台机器的会话列表",
    },
    "links.no_activity_30_min": {
      ja: "30分以上動きなし",
      en: "No activity for 30+ min",
      "zh-CN": "30分钟以上无活动",
    },
    "links.nothing_host_since_time": {
      ja: "{host} の分が {time} から届いていません",
      en: "Nothing from {host} since {time}",
      "zh-CN": "自 {time} 起未收到 {host} 的信息",
    },
    "links.opening_or_starting_session_wakes": {
      ja: "開く・セッションを始めると起こします(約10秒)",
      en: "Opening it or starting a session wakes it (about 10 s)",
      "zh-CN": "打开或开始会话时会唤醒它(约10秒)",
    },
    "links.read_only_list_nothing_can": {
      ja: "見るだけの一覧です(ここからは変えられません)。root の行は、root の解錠中だけ出ます(root の列は Claude・Codex の devbox の欄に出します)。ssh 先のマシンのログインは含みません。",
      en: "A read-only list (nothing can be changed here). The root row appears only while your root window is unlocked (its logins are shown in the devbox columns). Logins on ssh machines are not included.",
      "zh-CN": "仅供查看(此处无法更改)。root 一行仅在 root 解锁期间显示(其登录显示在 devbox 列)。不含 ssh 机器上的登录。",
    },
    "links.remove_entry": {
      ja: "この書き込みを外す",
      en: "Remove this entry",
      "zh-CN": "移除此条目",
    },
    "links.remove_link_still_linked_b": {
      ja: "「{a}」を連携から外します(残り: {b})。よろしいですか?",
      en: "Remove “{a}” from the link (still linked: {b})?",
      "zh-CN": "将「{a}」移出连接(仍连接: {b})。确定吗?",
    },
    "links.ssh_auto": {
      ja: "SSH・自動",
      en: "SSH (auto)",
      "zh-CN": "SSH（自动）",
    },
    "links.ssh_closed": {
      ja: "SSH終了",
      en: "SSH closed",
      "zh-CN": "SSH 已断开",
    },
    "links.tap_session_link_label": {
      ja: "🔗「{label}」とつなぐ相手をタップしてください",
      en: "🔗 Tap the session to link with “{label}”",
      "zh-CN": "🔗 请点按要与「{label}」连接的会话",
    },
    "links.unlink_b": {
      ja: "「{a}」と「{b}」の連携を切断します。よろしいですか?",
      en: "Unlink “{a}” and “{b}”?",
      "zh-CN": "要断开「{a}」与「{b}」的连接吗?",
    },
    "links.unlink_after": {
      ja: "自動で切るまで",
      en: "Unlink automatically after",
      "zh-CN": "自动断开前",
    },
    "links.d_30m": {
      ja: "30分",
      en: "30 min",
      "zh-CN": "30 分钟",
    },
    "links.d_1h": {
      ja: "1時間",
      en: "1 h",
      "zh-CN": "1 小时",
    },
    "links.d_3h": {
      ja: "3時間",
      en: "3 h",
      "zh-CN": "3 小时",
    },
    "links.d_8h": {
      ja: "8時間",
      en: "8 h",
      "zh-CN": "8 小时",
    },
    "links.d_24h": {
      ja: "24時間",
      en: "24 h",
      "zh-CN": "24 小时",
    },
    "links.d_never": {
      ja: "切らない(どちらかが終わるまで)",
      en: "Never (until either ends)",
      "zh-CN": "不断开(直到任一结束)",
    },
    "links.or_minutes_up_to_1440": {
      ja: "または分で(最大1440)",
      en: "Or minutes (up to 1440)",
      "zh-CN": "或输入分钟(最多 1440)",
    },
    "links.link_ok": {
      ja: "つなぐ",
      en: "Link",
      "zh-CN": "连接",
    },
    "links.what_do_on_m_hand": {
      ja: "{m} ですることを書いてください(セッションに結び付かない手書きの書き込みになります):",
      en: "What will you do on {m}? (a hand-written entry, not tied to a session):",
      "zh-CN": "请写下要在 {m} 上做的事(手写条目，不关联会话)：",
    },
    "links.who_which_session_using_which": {
      ja: "どの Windows 機を、誰のどのセッションが使っているか。Windows 機で動いているセッションと、セッションから SSH でつないでいるものは自動で載るので、書き込みは要りません(「＋ 使う」はメモを残したいときだけ)。3分ごとに確かめ、止まった・落ちたセッションや切れた SSH は「終了」、30分以上動きが無ければ「30分以上動きなし」になります。",
      en: "Who (which session) is using which Windows machine. Sessions running on a Windows machine, and sessions connected to one over SSH, appear by themselves, so nothing needs to be written (“+ Use” is only for leaving a note). Checked every 3 minutes: stopped or fallen sessions and closed SSH connections become “Ended”, and 30 minutes without activity shows “No activity for 30+ min”.",
      "zh-CN": "哪个会话正在使用哪台 Windows 机器。运行在 Windows 机器上的会话、以及从会话通过 SSH 连接的会话都会自动列出，无需手动填写（“＋ 使用”仅用于留言）。每 3 分钟检查：已停止或掉线的会话以及断开的 SSH 显示“结束”，30 分钟以上没有动静显示“30分钟以上无活动”。",
    },
    "links.windows_machines_board": {
      ja: "Windows 機の黒板",
      en: "Windows machines board",
      "zh-CN": "Windows 机器黑板",
    },
    "links.written_session": {
      ja: "セッションが記入",
      en: "written by the session",
      "zh-CN": "会话写入",
    },
    // list
    "list.archive": {
      ja: "アーカイブへ移動",
      en: "Archive",
      "zh-CN": "归档",
    },
    "list.archive_folder_everything_in": {
      ja: "フォルダごとアーカイブ",
      en: "Archive the folder and everything in it",
      "zh-CN": "归档整个文件夹",
    },
    "list.archived_folder_label": {
      ja: "フォルダ「{label}」をアーカイブしました",
      en: "Archived the folder “{label}”",
      "zh-CN": "已归档文件夹「{label}」",
    },
    "list.archived_label": {
      ja: "「{label}」をアーカイブしました",
      en: "Archived “{label}”",
      "zh-CN": "已归档“{label}”",
    },
    "list.close_archive": {
      ja: "🗄 アーカイブを閉じる",
      en: "🗄 Close the archive",
      "zh-CN": "🗄 关闭归档",
    },
    "list.close_shared_logs": {
      ja: "🧑‍🤝‍🧑 共有ログを閉じる",
      en: "🧑‍🤝‍🧑 Close shared logs",
      "zh-CN": "🧑‍🤝‍🧑 关闭共享记录",
    },
    "list.could_not_archive_err": {
      ja: "アーカイブできませんでした: {err}",
      en: "Could not archive: {err}",
      "zh-CN": "无法归档:{err}",
    },
    "list.could_not_connect_err": {
      ja: "接続に失敗しました: {err}",
      en: "Could not connect: {err}",
      "zh-CN": "连接失败:{err}",
    },
    "list.could_not_delete_err": {
      ja: "削除できませんでした: {err}",
      en: "Could not delete: {err}",
      "zh-CN": "无法删除：{err}",
    },
    "list.could_not_rename_err": {
      ja: "名前を変更できませんでした: {err}",
      en: "Could not rename: {err}",
      "zh-CN": "无法重命名:{err}",
    },
    "list.could_not_restore_err": {
      ja: "元に戻せませんでした: {err}",
      en: "Could not restore: {err}",
      "zh-CN": "无法恢复:{err}",
    },
    "list.could_not_resume": {
      ja: "再開できなかったもの:",
      en: "Could not resume:",
      "zh-CN": "无法恢复:",
    },
    "list.could_not_save_folders_err": {
      ja: "フォルダを保存できませんでした: {err}",
      en: "Could not save the folders: {err}",
      "zh-CN": "无法保存文件夹: {err}",
    },
    "list.could_not_stop": {
      ja: "停止できなかったもの:",
      en: "Could not stop:",
      "zh-CN": "无法停止:",
    },
    "list.delete_conversation_log_label_cannot": {
      ja: "「{label}」の会話ログを削除します。元に戻せません。よろしいですか?",
      en: "Delete the conversation log of “{label}”? This cannot be undone.",
      "zh-CN": "要删除「{label}」的对话记录吗?此操作无法撤销。",
    },
    "list.delete_empty_folder": {
      ja: "空のフォルダを消す",
      en: "Delete this empty folder",
      "zh-CN": "删除此空文件夹",
    },
    "list.delete_folder_name": {
      ja: "フォルダ「{name}」を消しますか?",
      en: "Delete the folder “{name}”?",
      "zh-CN": "要删除文件夹「{name}」吗?",
    },
    "list.do_not_put_in_folder": {
      ja: "フォルダの指定をやめる",
      en: "Do not put it in a folder",
      "zh-CN": "不放入文件夹",
    },
    "list.drag_reorder": {
      ja: "ドラッグで並べ替え",
      en: "Drag to reorder",
      "zh-CN": "拖动以排序",
    },
    "list.finished_trees_n": {
      ja: "✓ 済んだ木 ({n})",
      en: "✓ Finished trees ({n})",
      "zh-CN": "✓ 已完成的树 ({n})",
    },
    "list.drop_into_folder": {
      ja: "📁 {name} へ",
      en: "📁 Into {name}",
      "zh-CN": "📁 放入 {name}",
    },
    "list.new_tree_in_folder": {
      ja: "📁 {name} の中に作る仕事の題",
      en: "Title of the job to make in 📁 {name}",
      "zh-CN": "在 📁 {name} 中新建的工作标题",
    },
    "list.new_folder_name": {
      ja: "フォルダの名前",
      en: "Folder name",
      "zh-CN": "文件夹名称",
    },
    "list.new_folder_in_folder": {
      ja: "📁 {name} の中に作るフォルダの名前",
      en: "Name of the folder to make in 📁 {name}",
      "zh-CN": "在 📁 {name} 中新建的文件夹名称",
    },
    "list.make": {
      ja: "作る",
      en: "Make",
      "zh-CN": "创建",
    },
    "list.arrange_hint": {
      ja: "⠿ をつまんで、セッションやフォルダを動かせます",
      en: "Drag the ⠿ handles to move sessions and folders",
      "zh-CN": "拖动 ⠿ 可移动会话和文件夹",
    },
    "list.arrange_done": {
      ja: "終わる",
      en: "Done",
      "zh-CN": "完成",
    },
    "list.make_in": {
      ja: "{name} に作る",
      en: "Make in {name}",
      "zh-CN": "在 {name} 中创建",
    },
    "list.no_folder_under_item": {
      ja: "木の項目の下にはフォルダを作れません",
      en: "No folder can go under a tree item",
      "zh-CN": "树的项目下不能建文件夹",
    },
    "list.folder_name": {
      ja: "フォルダの名前:",
      en: "Folder name:",
      "zh-CN": "文件夹名称:",
    },
    "list.kind_cannot_resumed": {
      ja: "再開できない種類です",
      en: "this kind cannot be resumed",
      "zh-CN": "此类会话无法恢复",
    },
    "list.link_another_session": {
      ja: "他のセッションとつなぐ",
      en: "Link with another session",
      "zh-CN": "与其他会话连接",
    },
    "list.linked_label_tap_unlink": {
      ja: "連携中(「{label}」)-- タップで切断",
      en: "Linked with “{label}” — tap to unlink",
      "zh-CN": "已与「{label}」连接 —— 点按断开",
    },
    "list.n_sessions_hidden_until_unlock": {
      ja: "🔒 {n} 件のセッションは、パスキーで解錠するまで名前を隠しています",
      en: "🔒 {n} sessions are hidden until you unlock with your passkey",
      "zh-CN": "🔒 {n} 个会话的名称在用通行密钥解锁前被隐藏",
    },
    "list.name_not_empty_so_cannot": {
      ja: "「{name}」は空ではないので消せません(フォルダ {f} 個、セッション {n} 件。アーカイブしたものも含みます)",
      en: "“{name}” is not empty, so it cannot be deleted ({f} folders, {n} sessions, archived ones included).",
      "zh-CN": "「{name}」不是空的,无法删除({f} 个文件夹、{n} 个会话,包括已归档的)",
    },
    "list.new_name": {
      ja: "新しい名前:",
      en: "New name:",
      "zh-CN": "新名称:",
    },
    "list.no_folder": {
      ja: "(フォルダなし)",
      en: "(no folder)",
      "zh-CN": "(无文件夹)",
    },
    "list.no_other_session_matches": {
      ja: "ほかに該当するセッションはありません",
      en: "No other session matches",
      "zh-CN": "没有其他符合的会话",
    },
    "list.no_sessions_yet_choose_ai": {
      ja: "まだセッションがありません。上の「＋ 🤖 AI」を押し、AI(Claude など)と場所を選んで「開始」を押すと始まります。",
      en: "No sessions yet. Press \"＋ 🤖 AI\" above, choose an AI (Claude etc.) and a place, then press \"Start\".",
      "zh-CN": "还没有会话。按上方的「＋ 🤖 AI」,选择 AI(Claude 等)和位置,再按「开始」即可。",
    },
    "list.not_allowed": {
      ja: "「..」は使えません",
      en: "\"..\" is not allowed",
      "zh-CN": "不能使用“..”",
    },
    "list.nothing_undo": {
      ja: "元に戻すアーカイブはありません",
      en: "Nothing to undo",
      "zh-CN": "没有可撤销的归档",
    },
    "list.open_archive_n": {
      ja: "🗄 アーカイブを開く ({n})",
      en: "🗄 Open the archive ({n})",
      "zh-CN": "🗄 打开归档({n})",
    },
    "list.open_shared_logs_n": {
      ja: "🧑‍🤝‍🧑 共有ログを開く ({n})",
      en: "🧑‍🤝‍🧑 Open shared logs ({n})",
      "zh-CN": "🧑‍🤝‍🧑 打开共享记录({n})",
    },
    "list.restore_archive": {
      ja: "アーカイブから戻す",
      en: "Restore from the archive",
      "zh-CN": "从归档恢复",
    },
    "list.restore_folder_everything_in": {
      ja: "フォルダごとアーカイブから戻す",
      en: "Restore the folder and everything in it",
      "zh-CN": "恢复整个文件夹",
    },
    "list.restored_folder_label_archive": {
      ja: "フォルダ「{label}」をアーカイブから戻しました",
      en: "Restored the folder “{label}” from the archive",
      "zh-CN": "已将文件夹「{label}」从归档中恢复",
    },
    "list.restored_label_archive": {
      ja: "「{label}」をアーカイブから戻しました",
      en: "Restored “{label}” from the archive",
      "zh-CN": "已将“{label}”移出归档",
    },
    "list.resume_n_sessions_last_stop": {
      ja: "「{name}」で前回停止した {n} 件を再開しますか?",
      en: "Resume the {n} sessions the last stop of “{name}” stopped?",
      "zh-CN": "要恢复「{name}」上次停止的 {n} 个会话吗?",
    },
    "list.row_actions": {
      ja: "操作",
      en: "Actions",
      "zh-CN": "操作",
    },
    "list.set_working_folder": {
      ja: "作業ディレクトリを設定",
      en: "Set working directory",
      "zh-CN": "设置工作目录",
    },
    "list.share_folder": {
      ja: "フォルダごと共有…",
      en: "Share the folder…",
      "zh-CN": "共享整个文件夹…",
    },
    "list.shared_folder": {
      ja: "フォルダごと共有中",
      en: "Shared as a folder",
      "zh-CN": "已按文件夹共享",
    },
    "list.show_drag_sessions_folders_into": {
      ja: "⠿ を出して、セッションやフォルダをドラッグで並べ替える",
      en: "Show ⠿ to drag sessions and folders into a new order",
      "zh-CN": "显示 ⠿，拖动会话和文件夹来排序",
    },
    "list.stop_n_sessions_in_name": {
      ja: "「{name}」の中の {n} 件のセッションを停止しますか?(Claude が動いていれば会話を残してから終わらせます)",
      en: "Stop the {n} sessions in “{name}”? (A running Claude saves its conversation before it ends.)",
      "zh-CN": "要停止「{name}」中的 {n} 个会话吗?(Claude 正在运行时会先保存对话再结束)",
    },
    "list.tap_resume_what_last_stop": {
      ja: "タップで前回停止したものを再開",
      en: "Tap to resume what the last stop stopped",
      "zh-CN": "点按以恢复上次停止的会话",
    },
    "list.tap_show_or_hide_patrol": {
      ja: "タップで巡回のバーを開閉",
      en: "Tap to show or hide the patrol bar",
      "zh-CN": "点按以显示或隐藏巡视栏",
    },
    "list.tap_stop_every_session_in": {
      ja: "タップで中のセッションをすべて停止",
      en: "Tap to stop every session in it",
      "zh-CN": "点按以停止其中所有会话",
    },
    "list.trees_in_no_folder": {
      ja: "フォルダに入れていない木",
      en: "Trees in no folder",
      "zh-CN": "未放入文件夹的树",
    },
    "list.unlock_show": {
      ja: "🔓 解錠して表示",
      en: "🔓 Unlock to show",
      "zh-CN": "🔓 解锁后显示",
    },
    "list.working_folder_dir": {
      ja: "作業ディレクトリ ~/{dir}",
      en: "working directory ~/{dir}",
      "zh-CN": "工作目录 ~/{dir}",
    },
    "list.working_folder_relative_sandhome_in": {
      ja: "作業ディレクトリ(devbox は ~/sandhome、ホストは HOME、root は /root から見た場所。空にすると無し):",
      en: "Working directory (relative to ~/sandhome in devbox, HOME on the host, /root for root; empty for none):",
      "zh-CN": "工作目录(devbox 相对 ~/sandhome，主机相对 HOME，root 相对 /root；留空表示无):",
    },
    // outbox
    "outbox.empty_folder": {
      ja: "(空のディレクトリです)",
      en: "(empty directory)",
      "zh-CN": "(空目录)",
    },
    "outbox.no_session_given": {
      ja: "セッションが指定されていません。",
      en: "No session given.",
      "zh-CN": "未指定会话。",
    },
    // page
    "page.discard_what_you_wrote": {
      ja: "書いた内容を捨てますか？",
      en: "Discard what you wrote?",
      "zh-CN": "要丢弃已写的内容吗？",
    },
    "page.keep_writing": {
      ja: "戻って続ける",
      en: "Keep writing",
      "zh-CN": "返回继续",
    },
    "page.discard": {
      ja: "捨てる",
      en: "Discard",
      "zh-CN": "丢弃",
    },
    "page.chat_stopped_updating_too_log": {
      ja: "チャットの更新も止まっています。ログインし直すと、この画面に戻ります(書きかけの文は残します)。",
      en: "The chat has stopped updating too. Log in again to come back to this screen (unsent text is kept).",
      "zh-CN": "聊天也已停止更新。重新登录后会回到此画面(未发送的文字会保留)。",
    },
    "page.google_login_expired": {
      ja: "Google のログインが切れました",
      en: "Your Google login has expired",
      "zh-CN": "Google 登录已过期",
    },
    // search
    "search.ai_thinking": {
      ja: "AI(思考)",
      en: "AI (thinking)",
      "zh-CN": "AI(思考)",
    },
    "search.log_out_who": {
      ja: "{who} からログアウトしますか？",
      en: "Log out {who}?",
      "zh-CN": "要退出 {who} 吗?",
    },
    "search.n_sessions_host_root_mailbox": {
      ja: "🔒 {n}個のセッション(ホスト・ルート・mailbox)は解錠すると検索できます",
      en: "🔒 {n} sessions (host, root, mailbox) can be searched after unlocking",
      "zh-CN": "🔒 {n} 个会话(主机、root、mailbox)解锁后可搜索",
    },
    "search.newest_first_older_ones_omitted": {
      ja: "(新しい順に表示、これより古いものは省略)",
      en: " (newest first; older ones omitted)",
      "zh-CN": "(按新到旧显示,更早的已省略)",
    },
    "search.owner": {
      ja: "[{owner}さん] ",
      en: "[{owner}] ",
      "zh-CN": "[{owner}] ",
    },
    "search.search_failed_err": {
      ja: "検索できませんでした: {err}",
      en: "Search failed: {err}",
      "zh-CN": "搜索失败:{err}",
    },
    "search.searching": {
      ja: "検索中…",
      en: "Searching…",
      "zh-CN": "搜索中…",
    },
    "search.session_no_longer_exists": {
      ja: "このセッションはもうありません",
      en: "This session no longer exists",
      "zh-CN": "此会话已不存在",
    },
    "search.system": {
      ja: "システム",
      en: "System",
      "zh-CN": "系统",
    },
    // sessionops
    "sessionops.conversation_already_running_in_another": {
      ja: "この会話は別のセッションで動いているので、そちらを開きます",
      en: "This conversation is already running in another session; opening that one",
      "zh-CN": "此对话已在另一个会话中运行，正在打开那个会话",
    },
    "sessionops.could_not_resume_err": {
      ja: "再開できませんでした: {err}",
      en: "Could not resume: {err}",
      "zh-CN": "无法继续:{err}",
    },
    "sessionops.could_not_stop_err": {
      ja: "停止できませんでした: {err}",
      en: "Could not stop: {err}",
      "zh-CN": "无法停止:{err}",
    },
    "sessionops.ended": {
      ja: "終了しています",
      en: "Ended",
      "zh-CN": "已结束",
    },
    "sessionops.resume_label": {
      ja: "「{label}」を続きから再開しますか？",
      en: "Resume “{label}”?",
      "zh-CN": "要继续「{label}」吗?",
    },
    "sessionops.starting": {
      ja: "起動中…",
      en: "Starting…",
      "zh-CN": "启动中…",
    },
    "sessionops.stop_session_if_claude_running": {
      ja: "このセッションを停止しますか？(Claude が動いていれば Ctrl+C を2回送り、会話を残してから終わらせます)",
      en: "Stop this session? (If Claude is running, it gets Ctrl+C twice so the conversation is saved first)",
      "zh-CN": "要停止此会话吗?(如果 Claude 正在运行,会先发送两次 Ctrl+C 保存对话后再结束)",
    },
    // settings
    "settings.devbox_container": {
      ja: "devbox コンテナ",
      en: "the devbox container",
      "zh-CN": "devbox 容器",
    },
    "settings.host_outside_sandbox": {
      ja: "このホスト(sandbox外・あなた自身)",
      en: "this host (outside the sandbox, as you)",
      "zh-CN": "本主机(沙箱外,以你本人身份)",
    },
    "settings.log_claude_code_out_where": {
      ja: "{where}のClaude Codeをログアウトします。よろしいですか?",
      en: "Log Claude Code out of {where}?",
      "zh-CN": "要将 {where} 的 Claude Code 退出登录吗?",
    },
    "settings.log_codex_out_where": {
      ja: "{where}のCodexをログアウトします。よろしいですか?",
      en: "Log Codex out of {where}?",
      "zh-CN": "要将 {where} 的 Codex 退出登录吗?",
    },
    "settings.logout_failed_err": {
      ja: "ログアウトに失敗しました: {err}",
      en: "Logout failed: {err}",
      "zh-CN": "退出登录失败:{err}",
    },
    "settings.no_access": {
      ja: "権限なし",
      en: "No access",
      "zh-CN": "无权限",
    },
    "settings.root_on_host": {
      ja: "このホストの root",
      en: "root on this host",
      "zh-CN": "本主机的 root",
    },
    // share
    "share.add_another_session": {
      ja: "＋ ほかのセッションを加える",
      en: "＋ Add another session",
      "zh-CN": "＋ 加入其他会话",
    },
    "share.back_list_tap_on_session": {
      ja: "一覧に戻ります。つなぐ相手の 🔗 をタップしてください",
      en: "Back to the list: tap 🔗 on the session to link with",
      "zh-CN": "返回列表:点按要联动的会话的 🔗",
    },
    "share.could_not_share_err": {
      ja: "共有に失敗しました: {err}",
      en: "Could not share: {err}",
      "zh-CN": "共享失败:{err}",
    },
    "share.could_not_stop_sharing_err": {
      ja: "共有解除に失敗しました: {err}",
      en: "Could not stop sharing: {err}",
      "zh-CN": "取消共享失败:{err}",
    },
    "share.download_failed": {
      ja: "ダウンロードに失敗しました",
      en: "Download failed",
      "zh-CN": "下载失败",
    },
    "share.every_session_in_shared_including": {
      ja: "中のセッションすべて(下のフォルダ、あとから入れたものも)が共有されます。root のシェルは閲覧のみ。mailbox は名前を指定した相手にだけ届き、「みんな」には届きません。閲覧のみ: チャットのログだけが見えます。",
      en: "Every session in it is shared (including folders under it and anything added later). Root shells are read-only; mailbox sessions reach only named people, never everyone. Read-only: only the chat log can be seen.",
      "zh-CN": "其中所有会话都会被共享(包括子文件夹及之后放入的)。root 终端仅可查看；mailbox 只共享给指定的人，不共享给所有人。仅查看：只能看到聊天记录。",
    },
    "share.leave_link": {
      ja: "✂ 連携から外す",
      en: "✂ Leave the link",
      "zh-CN": "✂ 退出联动",
    },
    "share.link_another_session": {
      ja: "🔗 ほかのセッションとつなぐ",
      en: "🔗 Link with another session",
      "zh-CN": "🔗 与其他会话联动",
    },
    "share.linked_left": {
      ja: "🔗 連携中({left})",
      en: "🔗 Linked ({left})",
      "zh-CN": "🔗 已联动({left})",
    },
    "share.mailbox_sessions_can_shared_only": {
      ja: "mailbox は、名前を指定した相手にだけ共有できます。閲覧のみはチャットのログだけ、共同作業(Claude・Codex)は送信・停止までできます。Codex を抜けた後のシェルには相手は打ち込めません(相手はあなたのパスキーなしで使えます。外へ送る許可のカードに答えられるのはあなただけです)。",
      en: "mailbox sessions can be shared only with a named user. Read-only shows the chat log; co-working (Claude, Codex) also lets them send and stop; once Codex has exited they cannot type into the shell (without your passkey; only you can answer the cards that allow sending out).",
      "zh-CN": "mailbox 只能共享给指定的用户。只读只能看聊天记录,协作(Claude、Codex)还可以发送和停止;退出 Codex 后对方不能在 shell 中输入(对方无需你的通行密钥;只有你能回答允许对外发送的卡片)。",
    },
    "share.move_into_box": {
      ja: "📨 {box}へ移す",
      en: "📨 Move into {box}",
      "zh-CN": "📨 移到{box}",
    },
    "share.move_session_into_box_conversation": {
      ja: "このセッションを{box}へ移しますか？会話を{box}にコピーして{box}の ~/work/ の下のディレクトリで続け、ここは止めてアーカイブします。{box}からこちらへは戻せません。",
      en: "Move this session into {box}? The conversation is copied there and goes on in a directory under {box}'s ~/work/; this one is stopped and archived. It cannot come back from {box}.",
      "zh-CN": "把此会话移到{box}吗？对话会复制到{box},在{box}的 ~/work/ 下的目录中继续;这里会停止并归档。之后不能从{box}移回。",
    },
    "share.not_shared_anyone_yet": {
      ja: "まだ誰とも共有していません",
      en: "Not shared with anyone yet",
      "zh-CN": "尚未与任何人共享",
    },
    "share.open_session": {
      ja: "このセッションを開く",
      en: "Open this session",
      "zh-CN": "打开此会话",
    },
    "share.read_only_they_see_only": {
      ja: "閲覧のみ: チャットのログだけが見えます(画面・送信・停止はできません)。全員 = このサーバーの AI座 の全ユーザー。",
      en: "Read-only: they see only the chat log (no screen, sending or stopping). Everyone = every AI-za user on this server.",
      "zh-CN": "只读:对方只能看到聊天记录(不能看画面、发送或停止)。所有人 = 本服务器上 AI座 的全部用户。",
    },
    "share.save_conversation_log": {
      ja: "💾 会話ログを保存",
      en: "💾 Save the conversation log",
      "zh-CN": "💾 保存对话记录",
    },
    "share.send_desk_bug_request": {
      ja: "📮 窓口に送る(不具合・要望)",
      en: "📮 Send to the desk (bug / request)",
      "zh-CN": "📮 提交给窗口(故障・需求)",
    },
    "share.session_link": {
      ja: "🔗 セッション連携",
      en: "🔗 Session link",
      "zh-CN": "🔗 会话联动",
    },
    "share.share": {
      ja: "共有する",
      en: "Share",
      "zh-CN": "共享",
    },
    "share.share_folder_name": {
      ja: "フォルダ「{name}」を共有",
      en: "Share folder “{name}”",
      "zh-CN": "共享文件夹“{name}”",
    },
    "share.sharing_co_work_lets_them": {
      ja: "⚠️ 共同作業で共有すると、相手はあなたと同じ権限でコマンドを実行できます。",
      en: "⚠️ Sharing for co-work lets them run commands with your permissions.",
      "zh-CN": "⚠️ 以协作方式共享后,对方可以用你的权限执行命令。",
    },
    "share.specific_user": {
      ja: "ユーザーを指定",
      en: "A specific user",
      "zh-CN": "指定用户",
    },
    "share.stopped": {
      ja: "(停止中)",
      en: "(stopped)",
      "zh-CN": "(已停止)",
    },
    // speak
    "speak.ai_za_read_aloud": {
      ja: "AI座 読み上げ",
      en: "AI-za read-aloud",
      "zh-CN": "AI座 朗读",
    },
    "speak.also_read_out_other_sessions": {
      ja: "ほかのセッションの返事も、名前と一言の要約で読み上げる",
      en: "Also read out other sessions' replies: the name and a one-line summary",
      "zh-CN": "也朗读其他会话的回复：名称和一句话摘要",
    },
    "speak.chinese": {
      ja: "中国語",
      en: "Chinese",
      "zh-CN": "中文",
    },
    "speak.code_omitted": {
      ja: "(コード省略)",
      en: "(code omitted)",
      "zh-CN": "(省略代码)",
    },
    "speak.device_voice": {
      ja: "端末の声",
      en: "Device voice",
      "zh-CN": "设备语音",
    },
    "speak.english": {
      ja: "英語",
      en: "English",
      "zh-CN": "英语",
    },
    "speak.google_voice_via_server": {
      ja: "Google の声(サーバー経由)",
      en: "Google voice (via the server)",
      "zh-CN": "Google 语音(经服务器)",
    },
    "speak.google_voices_unavailable_device_voice": {
      ja: "Google の声を使えません(端末の声で読みます)",
      en: "Google voices unavailable (the device voice reads instead)",
      "zh-CN": "无法使用 Google 语音(改用设备语音)",
    },
    "speak.how_replies_read": {
      ja: "この速さと声で読み上げます。",
      en: "This is how replies will be read.",
      "zh-CN": "将以此语速和声音朗读。",
    },
    "speak.japanese": {
      ja: "日本語",
      en: "Japanese",
      "zh-CN": "日语",
    },
    "speak.loading_google_voices": {
      ja: "Google の声を読み込み中…",
      en: "Loading Google voices…",
      "zh-CN": "正在加载 Google 语音…",
    },
    "speak.on_device_pick_output_in": {
      ja: "この端末では出力先は端末の設定で選びます",
      en: "On this device, pick the output in the device's settings",
      "zh-CN": "此设备请在系统设置中选择输出",
    },
    "speak.online": {
      ja: " (オンライン)",
      en: " (online)",
      "zh-CN": " (在线)",
    },
    "speak.other_sessions_replies_read_out": {
      ja: "ほかのセッションの返事も読み上げます",
      en: "Other sessions' replies will be read out too",
      "zh-CN": "也会朗读其他会话的回复",
    },
    "speak.others_too_off": {
      ja: "🔇 裏も読む オフ",
      en: "🔇 Others too: off",
      "zh-CN": "🔇 也读其他：关",
    },
    "speak.others_too_on": {
      ja: "🔊 裏も読む オン",
      en: "🔊 Others too: on",
      "zh-CN": "🔊 也读其他：开",
    },
    "speak.output": {
      ja: "出力先",
      en: "Output",
      "zh-CN": "输出",
    },
    "speak.read_aloud_off": {
      ja: "🔇 読み上げ オフ",
      en: "🔇 Read aloud: off",
      "zh-CN": "🔇 朗读: 关",
    },
    "speak.read_aloud_on": {
      ja: "読み上げをオンにしました",
      en: "Read aloud is on",
      "zh-CN": "已开启朗读",
    },
    "speak.read_aloud_on_2": {
      ja: "🔊 読み上げ オン",
      en: "🔊 Read aloud: on",
      "zh-CN": "🔊 朗读: 开",
    },
    "speak.read_aloud_paused": {
      ja: "⏸ 読み上げ 一時停止中",
      en: "⏸ Read aloud: paused",
      "zh-CN": "⏸ 朗读: 已暂停",
    },
    "speak.read_aloud_paused_tap_message": {
      ja: "読み上げを一時停止中: 吹き出しをタップでそこから再開",
      en: "Read aloud paused: tap a message to resume from there",
      "zh-CN": "朗读已暂停: 点按消息从该处继续",
    },
    "speak.replied": {
      ja: "返事がありました",
      en: "replied",
      "zh-CN": "有回复",
    },
    "speak.settings": {
      ja: "⚙ 設定",
      en: "⚙ Settings",
      "zh-CN": "⚙ 设置",
    },
    "speak.show_names": {
      ja: "(名前を出す…)",
      en: "(Show names…)",
      "zh-CN": "(显示名称…)",
    },
    "speak.speaker": {
      ja: "スピーカー",
      en: "Speaker",
      "zh-CN": "扬声器",
    },
    "speak.speed": {
      ja: "速さ",
      en: "Speed",
      "zh-CN": "语速",
    },
    "speak.tap_turn_read_aloud_on": {
      ja: "タップで読み上げをオン/オフ",
      en: "Tap to turn read aloud on/off",
      "zh-CN": "点按开关朗读",
    },
    "speak.tap_turn_voice_mode_on": {
      ja: "タップで音声モードをオン/オフ",
      en: "Tap to turn voice mode on/off",
      "zh-CN": "点按开关语音模式",
    },
    "speak.try": {
      ja: "試す",
      en: "Try",
      "zh-CN": "试听",
    },
    "speak.voice_mode_off": {
      ja: "🎙 音声モード オフ",
      en: "🎙 Voice mode: off",
      "zh-CN": "🎙 语音模式: 关",
    },
    "speak.voice_mode_on": {
      ja: "🎙 音声モード オン",
      en: "🎙 Voice mode: on",
      "zh-CN": "🎙 语音模式: 开",
    },
    // todo
    "todo.ai_working": {
      ja: "AI 作業中",
      en: "AI working",
      "zh-CN": "AI 工作中",
    },
    "todo.checked": {
      ja: "確認した",
      en: "Checked",
      "zh-CN": "已查看",
    },
    "todo.could_not_read_date": {
      ja: "日付が読めませんでした",
      en: "Could not read the date",
      "zh-CN": "无法识别日期",
    },
    "todo.do_now": {
      ja: "今やる",
      en: "Do it now",
      "zh-CN": "现在处理",
    },
    "todo.done_check_close": {
      ja: "片付いた — 確かめて閉じてください",
      en: "Done — check and close it",
      "zh-CN": "已完成 — 请确认后关闭",
    },
    "todo.done_not_checked_yet": {
      ja: "済み(未確認)",
      en: "Done (not checked yet)",
      "zh-CN": "已完成（未查看）",
    },
    "todo.handed_off": {
      ja: "引き継ぎ中",
      en: "Handed off",
      "zh-CN": "已交接",
    },
    "todo.in_3_days": {
      ja: "3日後",
      en: "In 3 days",
      "zh-CN": "3 天后",
    },
    "todo.marked_label_done": {
      ja: "「{label}」を済みにしました",
      en: "Marked “{label}” done",
      "zh-CN": "已将「{label}」标为完成",
    },
    "todo.marked_label_seen": {
      ja: "「{label}」を確認済みにしました",
      en: "Marked “{label}” seen",
      "zh-CN": "已将「{label}」标为已确认",
    },
    "todo.next_monday": {
      ja: "来週の月曜",
      en: "Next Monday",
      "zh-CN": "下周一",
    },
    "todo.nothing_do_right_now": {
      ja: "今やることはありません",
      en: "Nothing to do right now",
      "zh-CN": "现在没有待办",
    },
    "todo.other_session_gone": {
      ja: "相手のセッションはもうありません",
      en: "The other session is gone",
      "zh-CN": "对方的会话已不存在",
    },
    "todo.other_side_done": {
      ja: "相手は済み",
      en: "The other side is done",
      "zh-CN": "对方已完成",
    },
    "todo.other_side_waiting": {
      ja: "相手が寝かせ中",
      en: "The other side is waiting",
      "zh-CN": "对方在等待",
    },
    "todo.other_side_working": {
      ja: "相手が作業中",
      en: "The other side is working",
      "zh-CN": "对方正在处理",
    },
    "todo.others_turn": {
      ja: "ほかの人の番",
      en: "Someone else's turn",
      "zh-CN": "轮到别人",
    },
    "todo.restored_label": {
      ja: "「{label}」を元に戻しました",
      en: "Restored “{label}”",
      "zh-CN": "已恢复「{label}」",
    },
    "todo.snooze": {
      ja: "寝かせる",
      en: "Snooze",
      "zh-CN": "搁置",
    },
    "todo.or_pick_date_time": {
      ja: "または日時を選ぶ",
      en: "Or pick a date and time",
      "zh-CN": "或选择日期和时间",
    },
    "todo.snooze_until_when": {
      ja: "いつまで寝かせますか",
      en: "Snooze until when?",
      "zh-CN": "搁置到什么时候？",
    },
    "todo.snoozes_now_due": {
      ja: "期限が来た寝かせ",
      en: "Snoozes now due",
      "zh-CN": "到期的搁置",
    },
    "todo.stopped_no_status_given": {
      ja: "止まりました(状態の申告なし)",
      en: "Stopped (no status given)",
      "zh-CN": "已停止（未说明状态）",
    },
    "todo.stopped_now_open_continue": {
      ja: "止めてあります(開くと続きから)",
      en: "Stopped for now (open to continue)",
      "zh-CN": "已暂停（打开即可继续）",
    },
    "todo.tomorrow": {
      ja: "明日",
      en: "Tomorrow",
      "zh-CN": "明天",
    },
    "todo.waiting_on_there": {
      ja: "相手が要判断",
      en: "Waiting on you there",
      "zh-CN": "对方等待判断",
    },
    // tree
    "todo.your_turn_in_the_tree": {
      ja: "あなたの番(木の項目)",
      en: "Your turn (items of the tree)",
      "zh-CN": "轮到你(树的项目)",
    },
    "tree.12_weeks": {
      ja: "12 週",
      en: "12 weeks",
      "zh-CN": "12 周",
    },
    "tree.1_week": {
      ja: "1 週",
      en: "1 week",
      "zh-CN": "1 周",
    },
    "tree.4_weeks": {
      ja: "4 週",
      en: "4 weeks",
      "zh-CN": "4 周",
    },
    "tree.add": {
      ja: "足す",
      en: "Add",
      "zh-CN": "添加",
    },
    "tree.add_child": {
      ja: "子を足す",
      en: "Add a child",
      "zh-CN": "添加子项",
    },
    "tree.archived": {
      ja: "アーカイブ済み",
      en: "archived",
      "zh-CN": "已归档",
    },
    "tree.back_tree": {
      ja: "木に戻る",
      en: "Back to the tree",
      "zh-CN": "返回树",
    },
    "tree.cannot_see_branch_no_longer": {
      ja: "この枝は見られません(共有が外されたか、消されました)",
      en: "You cannot see this branch (no longer shared with you, or removed)",
      "zh-CN": "无法查看此分支(已取消共享或已删除)",
    },
    "tree.chat_line_n": {
      ja: "会話 {n} 行目",
      en: "chat line {n}",
      "zh-CN": "对话第 {n} 行",
    },
    "tree.claude_log_line_n": {
      ja: "Claude の記録 {n} 行目",
      en: "Claude log line {n}",
      "zh-CN": "Claude 记录第 {n} 行",
    },
    "tree.co_work_type_into_session": {
      ja: "書き込み可で共有(このセッションに一緒に入力する)",
      en: "Co-work (type into this session too)",
      "zh-CN": "协作(也能在此会话中输入)",
    },
    "tree.copy": {
      ja: "コピーする",
      en: "Copy",
      "zh-CN": "复制",
    },
    "tree.counted_per_week_sent_messages": {
      ja: "週ごとに数えています。送った数は人が送ったメッセージ、トークンと額は Claude の分で、API の定価での見積もりです。トークンは {d} からの増え方を週に分け、それより前の分は「全部」にだけ入ります。",
      en: "Counted per week. \"Sent\" is messages people sent; tokens and $ are Claude's, estimated at API list prices. Tokens are split into weeks by how they grew since {d}; what came before is only in \"All\".",
      "zh-CN": "按周统计。\"发送\"是人发送的消息数;令牌和金额只算 Claude,按 API 标价估算。令牌按 {d} 以来的增长分到各周,之前的部分只计入\"全部\"。",
    },
    "tree.d_n_done": {
      ja: "{d}/{n} 済み",
      en: "{d}/{n} done",
      "zh-CN": "{d}/{n} 已完成",
    },
    "tree.done": {
      ja: "済んだもの",
      en: "Done",
      "zh-CN": "已完成",
    },
    "tree.drag_change_order_siblings_or": {
      ja: "⠿ をドラッグして、兄弟の順番や親を変える",
      en: "Drag ⠿ to change the order of siblings or the parent",
      "zh-CN": "拖动 ⠿ 来调整同级顺序或父项",
    },
    "tree.estimate": {
      ja: "見積もり",
      en: "Estimate",
      "zh-CN": "估算",
    },
    "tree.estimate_at_api_list_prices": {
      ja: "API の単価での見積り(定額の契約の請求額ではありません)",
      en: "An estimate at API list prices (not what a subscription is billed)",
      "zh-CN": "按 API 标价估算(不是订阅的实际账单)",
    },
    "tree.everyone_in_ai_za": {
      ja: "座の全員",
      en: "Everyone in AI-za",
      "zh-CN": "座内全员",
    },
    "tree.filter_name_enter_adds": {
      ja: "名前で絞る・Enter で加える",
      en: "Filter by name; Enter adds",
      "zh-CN": "按名字筛选,回车添加",
    },
    "tree.finished_n": {
      ja: "終了済み {n} 件",
      en: "Finished ({n})",
      "zh-CN": "已完成({n})",
    },
    "tree.first_message": {
      ja: "仕事の木「{path}」のセッションです(分けるときは aiza-tree split「題」)。指示を待ってください。",
      en: "This is the session of \"{path}\" in AI-za's work tree (to split it: aiza-tree split \"title\"). Wait for instructions.",
      "zh-CN": "这是 AI座 工作树「{path}」的会话(拆分时用 aiza-tree split「题」)。请等待指示。",
    },
    "tree.fold": {
      ja: "(畳む)",
      en: " (fold)",
      "zh-CN": "(收起)",
    },
    "tree.guessed": {
      ja: "(推測)",
      en: " (guessed)",
      "zh-CN": "(推测)",
    },
    "tree.handed_over_n_times": {
      ja: "{n} 回渡った",
      en: "handed over {n} times",
      "zh-CN": "交接了 {n} 次",
    },
    "tree.issues_become_branches_under_parent": {
      ja: "その Issue が、親子のとおりにこの下の枝になります",
      en: "Its issues become the branches under this, parent and child as they are",
      "zh-CN": "其 Issue 会按父子关系成为此项下的分支",
    },
    "tree.last_7_days_since_d": {
      ja: "この 7 日間({d} から)",
      en: "The last 7 days (since {d})",
      "zh-CN": "最近 7 天(自 {d})",
    },
    "tree.left_behind_session_moved_on": {
      ja: "置き去り(担当のセッションはほかへ移った)",
      en: "Left behind (its session moved on)",
      "zh-CN": "已搁置(负责的会话已转去别处)",
    },
    "tree.link": {
      ja: "結びつける",
      en: "Link it",
      "zh-CN": "关联",
    },
    "tree.link_github": {
      ja: "GitHub につなぐ",
      en: "Link to GitHub",
      "zh-CN": "连接 GitHub",
    },
    "tree.m_sent_k": {
      ja: "送{m}・{k}",
      en: "{m} sent · {k}",
      "zh-CN": "发送 {m} · {k}",
    },
    "tree.m_sent_k_c": {
      ja: "送{m}・{k}・{c}",
      en: "{m} sent · {k} · {c}",
      "zh-CN": "发送 {m} · {k} · {c}",
    },
    "tree.make_at_top": {
      ja: "いちばん上に作る",
      en: "Make it at the top",
      "zh-CN": "在最上层创建",
    },
    "tree.make_under_p": {
      ja: "{p} の下に作る",
      en: "Make it under {p}",
      "zh-CN": "在 {p} 下创建",
    },
    "tree.messages_sent_per_week": {
      ja: "週ごとの送った数",
      en: "Messages sent per week",
      "zh-CN": "每周发送数",
    },
    "tree.moved": {
      ja: "動いたもの",
      en: "Moved",
      "zh-CN": "有进展的",
    },
    "tree.n_finished_branches": {
      ja: "済みの枝 {n} 件",
      en: "{n} finished branches",
      "zh-CN": "已完成的分支 {n} 个",
    },
    "tree.n_finished_handoffs": {
      ja: "済みの引き継ぎ {n} 件",
      en: "{n} finished handoffs",
      "zh-CN": "{n} 个已完成的交接",
    },
    "tree.new_title": {
      ja: "新しい題",
      en: "New title",
      "zh-CN": "新标题",
    },
    "tree.no_one_else_add": {
      ja: "ほかに候補はいません",
      en: "No one else to add",
      "zh-CN": "没有其他候选",
    },
    "tree.no_one_matches": {
      ja: "合う人がいません",
      en: "No one matches",
      "zh-CN": "没有匹配的人",
    },
    "tree.no_one_yet": {
      ja: "まだいません",
      en: "No one yet",
      "zh-CN": "暂无",
    },
    "tree.no_tree_yet_start_one": {
      ja: "木はまだありません。セッションで aiza-tree split「題」か、＋ で始められます",
      en: "No tree yet. Start one with aiza-tree split \"title\" in a session, or with ＋",
      "zh-CN": "还没有树。可在会话中用 aiza-tree split「标题」或 ＋ 开始",
    },
    "tree.nobody_holds_yet": {
      ja: "まだ誰も持っていない",
      en: "Nobody holds it yet",
      "zh-CN": "尚无人负责",
    },
    "tree.none_back_guessing": {
      ja: "決めない(推測に戻す)",
      en: "None (back to guessing)",
      "zh-CN": "不指定(恢复推测)",
    },
    "tree.not_counted_yet": {
      ja: "まだ数えていません",
      en: "Not counted yet",
      "zh-CN": "尚未统计",
    },
    "tree.nothing_holds_up": {
      ja: "止めているものはありません",
      en: "Nothing holds it up",
      "zh-CN": "没有阻碍",
    },
    "tree.now_c": {
      ja: "今: {c}",
      en: "Now: {c}",
      "zh-CN": "当前: {c}",
    },
    "tree.only_roots_creator_u_can": {
      ja: "根を作った人({u})だけが変えられます",
      en: "Only the root's creator ({u}) can change them",
      "zh-CN": "只有根的创建者({u})可以更改",
    },
    "tree.orig": {
      ja: "原文",
      en: "Orig",
      "zh-CN": "原文",
    },
    "tree.other_what_left_before_split": {
      ja: "その他(分ける前の作業の残り)",
      en: "Other (what was left before the split)",
      "zh-CN": "其他(拆分前剩下的工作)",
    },
    "tree.other_work_label": {
      ja: "その他 — 「{label}」の作業",
      en: "Other — the work of 「{label}」",
      "zh-CN": "其他 —「{label}」的工作",
    },
    "tree.paste_into_chat_ai_can": {
      ja: "チャットの入力欄に貼ると、AI がそのセッションを読めます",
      en: "Paste it into a chat and the AI can read that session",
      "zh-CN": "粘贴到聊天输入框,AI 就能读取该会话",
    },
    "tree.paste_reference_into_chat": {
      ja: "この参照をチャットの入力欄に貼ってください",
      en: "Paste this reference into a chat",
      "zh-CN": "请把此引用粘贴到聊天输入框",
    },
    "tree.person": {
      ja: "人ごと",
      en: "By person",
      "zh-CN": "按人",
    },
    "tree.read_again_github": {
      ja: "GitHub から読み直す",
      en: "Read again from GitHub",
      "zh-CN": "从 GitHub 重新读取",
    },
    "tree.reference_copied_paste_into_chat": {
      ja: "参照をコピーしました。チャットの入力欄に貼ると、AI がそのセッションを読めます",
      en: "Reference copied. Paste it into a chat and the AI can read that session",
      "zh-CN": "已复制引用。粘贴到聊天输入框,AI 就能读取该会话",
    },
    "tree.reference_session_copy": {
      ja: "このセッションを参照(コピー)",
      en: "Reference this session (copy)",
      "zh-CN": "引用此会话(复制)",
    },
    "tree.rename": {
      ja: "名前を変える",
      en: "Rename",
      "zh-CN": "重命名",
    },
    "tree.reopen": {
      ja: "開き直す",
      en: "Reopen",
      "zh-CN": "重新打开",
    },
    "tree.repository_owner_name": {
      ja: "リポジトリ(owner/name)",
      en: "Repository (owner/name)",
      "zh-CN": "仓库(owner/name)",
    },
    "tree.root_into_confirm": {
      ja: "木「{a}」を「{b}」の下の枝にします。",
      en: "Make the tree \"{a}\" a branch under \"{b}\"?",
      "zh-CN": "把树“{a}”变成“{b}”下面的分支。",
    },
    "tree.root_not_found": {
      ja: "根が見つかりません",
      en: "The root was not found",
      "zh-CN": "找不到根",
    },
    "tree.see_what_holds_up": {
      ja: "止めているものを見る",
      en: "See what holds it up",
      "zh-CN": "查看阻碍",
    },
    "tree.sent": {
      ja: "送った",
      en: "Sent",
      "zh-CN": "发送",
    },
    "tree.session_folder_2": {
      ja: "置くフォルダ…",
      en: "Folder to put it in…",
      "zh-CN": "放入的文件夹…",
    },
    "tree.session_gone": {
      ja: "担当のセッションはもうない",
      en: "its session is gone",
      "zh-CN": "负责的会话已不在",
    },
    "tree.session_made_stopped_archived_item": {
      ja: "作ったセッションは止めてアーカイブし、担当を元に戻します",
      en: "The session made is stopped and archived, and the item goes back to its former holder",
      "zh-CN": "停止并归档所建的会话,负责人改回原来的",
    },
    "tree.session_said_done_stopped_check": {
      ja: "担当は済みと言って止まった。確かめて ✓ 済みに",
      en: "its session said done and stopped — check it, then ✓ mark it done",
      "zh-CN": "负责的会话说已完成并停止了——确认后 ✓ 标为完成",
    },
    "tree.sessions_not_in_tree": {
      ja: "木に結びついていないセッション",
      en: "Sessions not in the tree",
      "zh-CN": "未关联工作树的会话",
    },
    "tree.settings_p_every_branch_below": {
      ja: "「{p}」の設定です。この下の枝はみなこれに合わせます",
      en: "Settings of “{p}”; every branch below follows them",
      "zh-CN": "这是「{p}」的设置,其下的分支都跟随它",
    },
    "tree.sharing_set_at_root": {
      ja: "共有(根で設定)",
      en: "Sharing (set at the root)",
      "zh-CN": "共享(在根上设置)",
    },
    "tree.show_finished_branches_too": {
      ja: "終わった枝も見る",
      en: "Show finished branches too",
      "zh-CN": "也显示已完成的分支",
    },
    "tree.show_in_tree": {
      ja: "木で見る",
      en: "Show in the tree",
      "zh-CN": "在树中查看",
    },
    "tree.show_original": {
      ja: "原文を見る",
      en: "Show the original",
      "zh-CN": "看原文",
    },
    "tree.show_translation": {
      ja: "訳を見る",
      en: "Show the translation",
      "zh-CN": "看译文",
    },
    "tree.start_links_item": {
      ja: "🔗 仕事の木「{path}」のセッションになります",
      en: "🔗 It becomes the session of \"{path}\" in the work tree",
      "zh-CN": "🔗 将成为工作树「{path}」的会话",
    },
    "tree.start_under_item": {
      ja: "🔗 仕事の木「{path}」の下に、このセッションの項目を作って結びます",
      en: "🔗 An item for this session is made under \"{path}\" in the work tree",
      "zh-CN": "🔗 将在工作树「{path}」下为此会话新建项目并关联",
    },
    "tree.stuck_3_days": {
      ja: "3日以上止まっている",
      en: "Stuck 3+ days",
      "zh-CN": "停滞 3 天以上",
    },
    "tree.stuck_3_days_2": {
      ja: "3日以上止まっているもの",
      en: "Stuck 3+ days",
      "zh-CN": "停滞 3 天以上的",
    },
    "tree.stuck_n_days": {
      ja: "{n} 日止まっている",
      en: "stuck {n} days",
      "zh-CN": "已停滞 {n} 天",
    },
    "tree.take_note": {
      ja: "🤛 {who} さんの「{title}」を、このセッションで引き取ります",
      en: "🤛 This session takes on {who}'s \"{title}\"",
      "zh-CN": "🤛 由此会话接手 {who} 的「{title}」",
    },
    "tree.take_on_new_session_own": {
      ja: "引き取る(自分の環境に新しいセッションを作る)",
      en: "Take it on (a new session of your own)",
      "zh-CN": "接手(在自己的环境中新建会话)",
    },
    "tree.talk_on_discord": {
      ja: "Discord で話す",
      en: "Talk on Discord",
      "zh-CN": "在 Discord 上讨论",
    },
    "tree.those_who_can_edit": {
      ja: "本人と書ける人だけ",
      en: "You and those who can edit",
      "zh-CN": "仅自己和可编辑的人",
    },
    "tree.title": {
      ja: "題で足す",
      en: "By title",
      "zh-CN": "按标题添加",
    },
    "tree.title_child": {
      ja: "子の題",
      en: "Title of the child",
      "zh-CN": "子项标题",
    },
    "tree.title_job": {
      ja: "仕事の題",
      en: "Title of the job",
      "zh-CN": "工作标题",
    },
    "tree.tokens": {
      ja: "トークン",
      en: "Tokens",
      "zh-CN": "令牌",
    },
    "tree.translation_short": {
      ja: "訳",
      en: "Tr",
      "zh-CN": "译",
    },
    "tree.undo": {
      ja: "取り消す",
      en: "Undo",
      "zh-CN": "撤销",
    },
    "tree.undo_taking_on": {
      ja: "引き取りを取り消す",
      en: "Undo taking it on",
      "zh-CN": "撤销接手",
    },
    "tree.updated_n": {
      ja: "{n} 件を直しました",
      en: "Updated {n}",
      "zh-CN": "已更新 {n} 项",
    },
    "tree.waiting_on_others": {
      ja: "外の返事待ち",
      en: "Waiting on others",
      "zh-CN": "等待外部回复",
    },
    "tree.went_back_forth": {
      ja: "ボールが行ったり来たりしたもの",
      en: "Went back and forth",
      "zh-CN": "来回交接的",
    },
    "tree.what_holds_up_p": {
      ja: "「{p}」を止めているもの",
      en: "What holds up “{p}”",
      "zh-CN": "阻碍「{p}」的项目",
    },
    "tree.where_session_holding_work_now": {
      ja: "この作業を持っているセッションの今",
      en: "where the session holding this work is now",
      "zh-CN": "负责这项工作的会话的现状",
    },
    "tree.which_folder_make_under": {
      ja: "どのフォルダの下に作りますか",
      en: "Which folder to make it under",
      "zh-CN": "在哪个文件夹下创建",
    },
    "tree.who_can_edit_they_can": {
      ja: "書ける人(見ることもできる)",
      en: "Who can edit (they can see it too)",
      "zh-CN": "可编辑的人(也可查看)",
    },
    "tree.helping_others_lead_not_yet": {
      ja: "ほかの人の担当を手伝う(協力)は、まだできません",
      en: "Helping someone else's lead is not possible yet",
      "zh-CN": "还不能协助别人的负责会话",
    },
    "tree.drop_move_here": {
      ja: "ここへ移す",
      en: "Move here",
      "zh-CN": "移到这里",
    },
    "tree.drop_no_here": {
      ja: "ここには入れられません",
      en: "Cannot go here",
      "zh-CN": "不能放到这里",
    },
    "tree.drop_no_done": {
      ja: "済みの枝には入れられません",
      en: "Not into a finished item",
      "zh-CN": "不能放入已完成的项目",
    },
    "tree.drop_no_write": {
      ja: "書けない木です",
      en: "You cannot edit this tree",
      "zh-CN": "你不能编辑这棵树",
    },
    "tree.drop_no_others_lead": {
      ja: "ほかの人の担当への協力はまだできません",
      en: "Helping someone else's lead: not yet",
      "zh-CN": "还不能协助别人的负责会话",
    },
    "tree.drop_no_already": {
      ja: "もうここにいます",
      en: "Already here",
      "zh-CN": "已经在这里",
    },
    "tree.drop_no_under_itself": {
      ja: "自分の枝の下へは移せません",
      en: "Not under its own item",
      "zh-CN": "不能移到自己的项目下面",
    },
    "tree.help_lead_confirm": {
      ja: "「{s}」を、担当「{lead}」の協力にします。2つを talkto でつなぎ(期限なし)、協力は木に書きません。",
      en: "\"{s}\" will help the lead \"{lead}\": the two are linked by talkto (no time limit), and the helper writes nothing in the tree.",
      "zh-CN": "让「{s}」协助负责会话「{lead}」：两者用 talkto 连接（不限时），协助者不写入工作树。",
    },
    "tree.someones_session": {
      ja: "{who} さんのセッション",
      en: "{who}'s session",
      "zh-CN": "{who} 的会话",
    },
    "tree.lead_and_helpers": {
      ja: "🧭 担当と 🤝 協力",
      en: "🧭 Lead and 🤝 helpers",
      "zh-CN": "🧭 负责与 🤝 协助",
    },
    "tree.lead": {
      ja: "担当",
      en: "Lead",
      "zh-CN": "负责",
    },
    "tree.helper": {
      ja: "協力",
      en: "Helper",
      "zh-CN": "协助",
    },
    "tree.stop_helping": {
      ja: "「{s}」の協力をやめる",
      en: "Stop \"{s}\" helping",
      "zh-CN": "让「{s}」停止协助",
    },
    "tree.shared_with_no_one": {
      ja: "だれとも共有していない木",
      en: "A tree shared with no one",
      "zh-CN": "未与任何人共享的树",
    },
    "tree.take_lead_off": {
      ja: "担当を外す",
      en: "Take the lead off",
      "zh-CN": "取消负责会话",
    },
    "tree.lead_lets_go_to_help": {
      ja: "「{s}」は「{items}」の担当です。担当を外して、協力にしますか？(talkto でつなぎ、協力は木に書きません)",
      en: "\"{s}\" is the lead of \"{items}\". Take it off and make it a helper? (linked by talkto; a helper writes nothing in the tree)",
      "zh-CN": "「{s}」是「{items}」的负责会话。要取消负责，改为协助吗？（用 talkto 连接，协助者不写入工作树）",
    },
    "tree.make_lead_confirm": {
      ja: "「{s}」を「{item}」の担当にします。",
      en: "\"{s}\" becomes the lead of \"{item}\".",
      "zh-CN": "让「{s}」成为「{item}」的负责会话。",
    },
    "tree.make_child_lead_confirm": {
      ja: "「{item}」の下に「{s}」の項目を作り、その担当にします。",
      en: "A new item for \"{s}\" goes under \"{item}\", with it as the lead.",
      "zh-CN": "在「{item}」下为「{s}」建一个项目，并由它负责。",
    },
    "tree.release_lead_confirm": {
      ja: "「{s}」を「{items}」の担当から外し、フォルダに戻します。",
      en: "\"{s}\" stops being the lead of \"{items}\" and goes back to its folder.",
      "zh-CN": "取消「{s}」对「{items}」的负责，放回文件夹。",
    },
    "tree.release_helper_confirm": {
      ja: "「{s}」の協力をやめます(talkto のつながりは残ります)。",
      en: "\"{s}\" stops helping (its talkto link stays).",
      "zh-CN": "让「{s}」停止协助（talkto 连接保留）。",
    },
    "tree.who_can_see": {
      ja: "見られる人",
      en: "Who can see it",
      "zh-CN": "可查看的人",
    },
    "tree.work_cannot_see": {
      ja: "見えない仕事",
      en: "Work you cannot see",
      "zh-CN": "看不到的工作",
    },
    "tree.work_tree": {
      ja: "仕事の木ごと",
      en: "By work tree",
      "zh-CN": "按工作树",
    },
    "tree.work_under_in_session": {
      ja: "この下でセッションで作業",
      en: "Work under this in a session",
      "zh-CN": "在此下用会话工作",
    },
    "tree.write_owner_name": {
      ja: "owner/name の形で書いてください",
      en: "Write it as owner/name",
      "zh-CN": "请写成 owner/name 的形式",
    },
    // voice
    "voice.allow_microphone": {
      ja: "マイクを許可してください",
      en: "Allow the microphone.",
      "zh-CN": "请允许麦克风。",
    },
    "voice.bye": {
      ja: "終わります",
      en: "Bye.",
      "zh-CN": "结束。",
    },
    "voice.change_failed": {
      ja: "変更失敗",
      en: "Change failed.",
      "zh-CN": "更改失败。",
    },
    "voice.dictating_into_l_say_send": {
      ja: "✍️ 入力中(「{l}」)— 「送信」で送る・「取り消し」で消す・「入力終わり」でやめる",
      en: "✍️ Dictating into “{l}” — say 送信 to send, 取り消し to clear, 入力終わり to stop",
      "zh-CN": "✍️ 正在输入(「{l}」)— 说“送信”发送,“取り消し”清除,“入力終わり”结束",
    },
    "voice.do_n": {
      ja: "やること、{n}件",
      en: "To-do, {n}.",
      "zh-CN": "待办,{n} 项。",
    },
    "voice.empty": {
      ja: "空です",
      en: "Empty.",
      "zh-CN": "是空的。",
    },
    "voice.interrupt_failed": {
      ja: "中断失敗",
      en: "Interrupt failed.",
      "zh-CN": "中断失败。",
    },
    "voice.listening": {
      ja: "🎙 聞いています",
      en: "🎙 Listening",
      "zh-CN": "🎙 正在听",
    },
    "voice.no_reply_yet": {
      ja: "返事なし",
      en: "No reply yet.",
      "zh-CN": "还没有回复。",
    },
    "voice.nothing": {
      ja: "あなたの番なし",
      en: "Nothing for you.",
      "zh-CN": "没有轮到你的。",
    },
    "voice.open_session": {
      ja: "セッションを開いて",
      en: "Open a session.",
      "zh-CN": "请打开会话。",
    },
    "voice.send_failed": {
      ja: "送信失敗",
      en: "Send failed.",
      "zh-CN": "发送失败。",
    },
    "voice.send_what": {
      ja: "何を送りますか",
      en: "Send what?",
      "zh-CN": "发送什么?",
    },
    "voice.send_x_l": {
      ja: "「{l}」へ「{x}」。送りますか",
      en: "Send “{x}” to “{l}”?",
      "zh-CN": "向「{l}」发送「{x}」?",
    },
    "voice.stop_failed": {
      ja: "停止失敗",
      en: "Stop failed.",
      "zh-CN": "停止失败。",
    },
    "voice.stop_l": {
      ja: "「{l}」を停止しますか",
      en: "Stop “{l}”?",
      "zh-CN": "停止「{l}」?",
    },
    "voice.unlock": {
      ja: "解錠してください",
      en: "Please unlock.",
      "zh-CN": "请解锁。",
    },
    "voice.use_chrome_or_edge_voice": {
      ja: "音声認識は Chrome か Edge で",
      en: "Use Chrome or Edge for voice.",
      "zh-CN": "语音识别请用 Chrome 或 Edge。",
    },
    "voice.which_date": {
      ja: "日付は？",
      en: "Which date?",
      "zh-CN": "哪天?",
    },
    "voice.which_session": {
      ja: "どのセッション？",
      en: "Which session?",
      "zh-CN": "哪个会话?",
    },
    "voice.yes_or_no": {
      ja: "はい か いいえ で",
      en: "Yes or no.",
      "zh-CN": "是或否。",
    },
  }); /* i18n-end */
})();
