# Docker で試す(デモ)

aiza のゲートウェイ・1人分のバックエンド・PWA を、コンテナ1つで動かす。手元のブラウザ(PCでもスマホの開発者表示でも)で、
仕事の画面(セッションとフォルダ)・チャット画面・ターミナル画面・Claude Code のセッションを試せる。**試すためのもので、本番の構成ではない。** 画面写真付きの手順は`docs/tutorial/docker.html`(GitHub Pages では https://haselab-net.github.io/aiza/tutorial/docker.html )。

```sh
# リポジトリの一番上で
docker build -f docker/Dockerfile -t aiza-demo .
docker run -d --name aiza-demo -p 127.0.0.1:8878:8878 -v aiza-demo-home:/home/demo aiza-demo
# ブラウザで http://localhost:8878/agents/ を開き、「Log in as the demo user」
```

- **ログイン**: Google のログインは無い。ページを開ける人は誰でも、ただ1人のデモの利用者(`demo`)になる。だからポートは
  **`127.0.0.1:` を付けてホストのループバックにだけ出す**(付けないと、同じネットワークの誰でも入れる)。
  離れたサーバーで動かすときも、ポートは外に出さず、手元から`ssh -L 8878:127.0.0.1:8878 <サーバー>`でつないで開く。
  デモのログインは、アドレスが`localhost`・`127.0.0.1`・`[::1]`のときだけ通す(別の名前で開くなら`-e AIZA_DEMO_HOSTS=名前,名前`)。
- **ブラウザ**: Chrome・Firefox・Edge で開く。セッションの Cookie に`Secure`が付いているので、`http://localhost`では Safari はログインを受け取らない。
- **始められるセッション**: 仕事の画面の上の段の「＋ 🤖 AI」で開く始める画面の2つの選択肢(何を動かすか × どこで動かすか)で、「Claude」(Claude Code の画面そのもの)または「Shell」× 「devbox」。
  「Codex」はイメージに入っていない。場所の「ホスト」・「ルート」はパスキーで開く窓が要るので、デモでは使えない。「mailbox」は設定していないので出ない。
- **Claude Code**: イメージに入っている(`--build-arg WITH_CLAUDE=0` で外せる)。初回は「Claude」を始めると、代わりに「Claude ログイン」のチャットが開くので、そこでログインする。ログインと作業ファイルは `/home/demo` にあるので、上の `-v aiza-demo-home:/home/demo` を付ければ
  コンテナを作り直しても残る。
- **止める・消す**: `docker stop aiza-demo` / `docker rm aiza-demo`(`docker volume rm aiza-demo-home` でデータも)。
- **確かめる**: `docker/test.sh` がイメージを作って起動し、ログイン・シェルのセッション・入力と画面・Claude Code の最初の画面までを確かめる
  (`WITH_CLAUDE=0 docker/test.sh` で Claude Code を外して速く)。Docker の要らない部分は `tests/test_docker_demo.py`。

## 本番の構成との違い

| 本番 | デモ |
|---|---|
| Google OAuth でログインし、メールアドレスから Unix ユーザーを引く | `docker/ext/demo/` の拡張が `/agents/demo-login` で `$AIZA_DEMO_USER` としてログインさせる(この拡張はデモのイメージにだけ入る) |
| 利用者ごとのバックエンドを systemd のソケットアクティベーションで起こす(`aiza-backend-proxy-<port>.socket` と `aiza-proxy-handler`) | `entrypoint.sh` がバックエンドを1つ起動し、`socat` で `/run/aiza-backend/<port>.sock` からつなぐ |
| セッションのコマンドは利用者ごとのコンテナで動く(`sandbox exec`) | `docker/sandbox` が代わりをする: そのコンテナの中で、利用者として、`HOME=$HOME/sandhome` で動かす(tmux は別のソケット) |
| ゲートウェイは 127.0.0.1 で待ち、手前の nginx 等が TLS を終える | ゲートウェイはコンテナの中で 0.0.0.0(`AIZA_GATEWAY_HOST`)、外へはループバックだけに出す。TLS は無い(localhost なので PWA・Cookie は動く。Safari を除く) |
| mailbox・ホスト・ルートで動くセッション(パスキーで開く)、ssh の機械、Web Push | 無い(`aiza-unlockd` も VAPID の鍵も無い。画面にボタンが出ても使えない) |

コンテナの中では、デモの利用者のセッションとバックエンドが同じ箱にいるので、本番のような「利用者のコンテナ」と「ホスト」の隔たりは無い。
**信頼できない人に触らせない**こと(デモの利用者のシェルが、そのままコンテナの中のシェルになる)。
同じ理由で、デモにログインしたブラウザで**信頼できないページを開いたままにしない**(同じ機械の別のポートのページは、Cookie の上では同じサイトに当たる)。

## ファイル

| ファイル | 役割 |
|---|---|
| `Dockerfile` | イメージ(Debian、Python の venv、tmux、socat、任意で Claude Code のネイティブ版)。デモの利用者は uid 1000 |
| `entrypoint.sh` | バックエンド・中継・ゲートウェイを起動し、どれかが終わったらコンテナを止める。Cookie の署名鍵はコンテナごとに作る |
| `sandbox` | `sandbox exec`・`sandbox ip` の代わり(ほかの使い方は失敗する) |
| `ext/demo/gateway.py` | デモのログイン(上) |
| `static/login.html`・`static/not_configured.html` | ログイン前のページ(デモのログインへのボタン) |
| `test.sh` | 上の「確かめる」 |
