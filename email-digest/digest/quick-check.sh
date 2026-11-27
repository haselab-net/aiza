#!/bin/sh
# まとめページの「今すぐチェック」から呼ぶ簡易チェック(2026-10-16 ユーザー依頼)。
# 定期チェック(run-check.sh)より範囲を絞る: 本人宛てと急ぎだけ。1b の片付けは定期チェックに任せる。
# 2段階(2026-10-16。待ち時間を短くするため):
#   1段目(約10秒): メール一覧と拡張の速い取り込みを機械的に取り、要約せずに quick/quick-raw.json へ。state=raw でページが読み込み直し「速報」を出す。
#   2段目(1〜2分): 拡張の遅い取り込みを待ち、claude -p が取ってあるファイルから項目を作る。state=done でページがもう一度読み込み直す。
# 定期チェックと同じ lock を使うので、どちらかが動いている間はもう一方は走らない。状態は quick.json(server.mjs が読む)。
CODE=$(cd "$(dirname "$0")" && pwd)
DATA=${DIGEST_DATA:-$CODE}
export HOME=${MAILBOX_HOME:-$(dirname "$DATA")}
export CODE DATA EXT="${DIGEST_EXT:-$CODE/private}"
# 箱の道具は名前で呼ぶ。自分の ~/bin にあればそれが先、無ければ箱の PATH の共用のもの
export PATH="$HOME/bin:$PATH"
cd "$HOME" || exit 1
LOG=$DATA/run.log; ST=$DATA/quick.json; Q=$DATA/quick
cf() { node "$CODE/conf.mjs" "$@"; }
# 初めての回: 前回チェック時刻が無ければ1日前から
[ -f "$DATA/cursor.json" ] || echo "{\"last\": $(( $(date +%s) - 86400 ))}" > "$DATA/cursor.json"
exec 9>"$DATA/.run.lock"
if ! flock -n 9; then echo "{\"state\":\"busy\",\"at\":\"$(date -Is)\"}" > "$ST"; exit 0; fi
# pid も書く: 途中で止められた(サーバの再起動など)回を、ページが「速報」のまま出し続けないように
state() { echo "{\"state\":\"$1\",\"at\":\"$(date -Is)\",\"pid\":$$$2}" > "$ST"; }
state running
mkdir -p "$Q"; rm -f "$Q"/q-* "$Q"/quick-raw.json "$DATA/.quick-failed"
# 拡張が揃っているか・手順書と依頼文を組み立てられるか。だめなら claude を呼ばない
# 知らせは lib.mjs から直に(拡張が読めないときも届くように)
notify() { node --input-type=module -e "import { notifyText } from '$CODE/lib.mjs'; await notifyText(process.argv[1], process.argv[2]);" "$1" "$2" >> "$LOG" 2>&1; }
stop() { echo "=== $(date -Is) quick stop: $1" >> "$LOG"; notify "今すぐチェックを止めた" "$1"; state error; exit 1; }
node "$CODE/ext.mjs" verify >> "$LOG" 2>&1 || stop "拡張が足りないか読めない(run.log。local/config.json の ext.require)"
node "$CODE/compose.mjs" >> "$LOG" 2>&1 || stop "手順書を組み立てられない(run.log)"
# 拡張の読む前の処理
node "$CODE/ext.mjs" cmds prepare quick | while IFS="$(printf '\t')" read -r sec cmd; do if [ "$sec" = 0 ]; then sh -c "$cmd" >> "$LOG" 2>&1 9>&-; else timeout "$sec" sh -c "$cmd" >> "$LOG" 2>&1 9>&-; fi; done
LAST=$(python3 -c "import json;print(json.load(open('$DATA/cursor.json'))['last'])")
START=$(date +%s)
export LAST START Q
echo "=== $(date -Is) quick start (since $LAST)" >> "$LOG"
# 拡張の取り込み(行「遅い 0/1<TAB>出力のファイル<TAB>コマンド」)。遅いものは先に裏で走らせ、2段目の前に待つ
node "$CODE/ext.mjs" cmds quick quick > "$DATA/.quick-cmds" 2>>"$LOG"
SLOW=; SLOWOUT=; FAST=
TAB="$(printf '\t')"
# 読む先の取り込みを1つ動かす。終了コードが 0 でなければ、読めなかったとして $DATA/.quick-failed に書く(後で知らせる。新着が無ければ出力は空でよい)
# DIGEST_GATE_INLINE=0: 読む道具は出す前に関門に聞かない(あとの gate がまとめて確かめる。run-check.sh と同じ)
src() { DIGEST_GATE_INLINE=0 sh -c "$2" > "$Q/$1" 2>>"$LOG"; rc=$?; [ "$rc" = 0 ] || echo "$1 rc=$rc" >> "$DATA/.quick-failed"; }
while IFS="$TAB" read -r slow out cmd; do
  [ "$slow" = 1 ] || continue
  src "$out" "$cmd" & SLOW="$SLOW $!"; SLOWOUT="$SLOWOUT $out"
done < "$DATA/.quick-cmds"
# メールも同じく終了コードで見る
{ "$(dirname "$CODE")/gmail.py" list -q "after:$LAST -in:sent -in:drafts -category:promotions" -n 60 > "$Q/q-mail.jsonl" 2>>"$LOG" || echo "q-mail.jsonl rc=$?" >> "$DATA/.quick-failed"; } & FAST="$!"
while IFS="$TAB" read -r slow out cmd; do
  [ "$slow" = 1 ] && continue
  src "$out" "$cmd" & FAST="$FAST $!"
done < "$DATA/.quick-cmds"
wait $FAST
node "$CODE/quick-raw.mjs" "$Q" >> "$LOG" 2>&1
state raw
[ -n "$SLOW" ] && wait $SLOW
# 関門(拡張の gate。2026-11-25): 取ったものをローカルで読み、機微なものを抜いてから突き合わせと Claude に渡す。
# 確かめられなかったものがあれば(0 でない)、この回は Claude を呼ばず時刻も進めない。ページは state=gated で「決まりだけで進める」を出す
node "$CODE/ext.mjs" cmds gate quick > "$DATA/.gate-cmds" 2>>"$LOG"
GATED=; while read -r cmd; do sh -c "$cmd" >> "$LOG" 2>&1 9>&- < /dev/null || GATED=1; done < "$DATA/.gate-cmds"
if [ -n "$GATED" ]; then
  rm -f "$DATA/.gate-cmds" "$Q"/q-* "$Q/quick-raw.json"
  node "$CODE/cursor.mjs" hold "$LAST" "$START"
  echo "=== $(date -Is) quick end: 関門で止めた(last を $LAST のまま)" >> "$LOG"
  notify "今すぐチェック: 新着を Claude に渡していない" "ローカルの確認が済まなかった。急ぐときはまとめのページの「決まりだけで進める」"
  state gated; exit 0
fi
rm -f "$DATA/.gate-cmds"
# 関門が抜いたものは速報からも外す(何か抜いた関門は quick-raw.json を消してある)
[ -f "$Q/quick-raw.json" ] || node "$CODE/quick-raw.mjs" "$Q" >> "$LOG" 2>&1
# 取ってきた新着を既存の項目とスレッドの印で突き合わせ、返信の項目はここで進めて起こす(Claude の分類に頼らない。2026-11-18)
# チャットで本人宛てか分からないものは --sure が起こさず、Claude の後の autostart が起こす
rm -f "$Q/replies.json" "$Q/dm-open.json"
node "$CODE/match.mjs" "$Q" >> "$LOG" 2>&1; node "$CODE/autostart.mjs" --sure >> "$LOG" 2>&1
# 読めなかった読む先を知らせる(名前と、どの時刻からの分かだけ。中身は run.log)
if [ -s "$DATA/.quick-failed" ]; then
  cat "$DATA/.quick-failed" | sed 's/^/=== quick failed: /' >> "$LOG"
  notify "今すぐチェックで読めなかった読む先" "$(sed 's/^q-//; s/[.][a-z]*  *rc=.*//' "$DATA/.quick-failed" | sort -u | tr '\n' ' ')($(date -d "@$LAST" '+%m/%d %H:%M') からの分。run.log)"
fi
# 読めなかった読む先があれば、この回は last を進めない(次の回に同じ時刻から読み直す。ほかの読む先の分は id で重ならない)
hold_last() { if [ -s "$DATA/.quick-failed" ]; then node "$CODE/cursor.mjs" hold "$LAST" "$START"
  echo "=== $(date -Is) quick: last を $LAST のまま(読めなかった読む先がある)" >> "$LOG"; else node "$CODE/cursor.mjs" clear-held; fi; }
# 何も来ていなければ claude は呼ばない(カーソルだけ進める)
empty=1; [ "$(cat "$Q/quick-raw.json")" = "[]" ] || empty=0
for f in $SLOWOUT; do [ -s "$Q/$f" ] && empty=0; done
if [ "$empty" = 1 ]; then
  node "$CODE/cursor.mjs" set-last "$START"
  hold_last
  # 新着が無くても、待ちの成立でセッションを起こす(2026-11-17)
  node "$CODE/autostart.mjs" >> "$LOG" 2>&1
  echo "=== $(date -Is) quick end: 新着なし" >> "$LOG"; state done ',"rc":0'; exit 0
fi
PROMPT=$(node "$CODE/compose.mjs" prompt quick) || stop "依頼文を組み立てられない(run.log)"
timeout 900 env -u AIZA_BOX_TAG claude -p "$PROMPT" \
  --dangerously-skip-permissions >> "$LOG" 2>&1
RC=$?
hold_last
# 新しく未決になった項目・Claude が本人宛てと判断した返信に Claude セッションを起動する(aiza の箱用 POST /sessions、2026-11-07 ユーザー依頼)
node "$CODE/autostart.mjs" >> "$LOG" 2>&1
echo "=== $(date -Is) quick end rc=$RC" >> "$LOG"
state done ",\"rc\":$RC"
# 拡張の後の処理(裏で。lock は持たない)
node "$CODE/ext.mjs" cmds after quick 2>>"$LOG" | while read -r cmd; do setsid nohup sh -c "$cmd" >> "$LOG" 2>&1 9>&- < /dev/null & done
exit 0
