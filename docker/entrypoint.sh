#!/bin/sh
# Starts the demo's three processes (docker/README.md) and stops the container
# when any of them exits:
#   aiza-backend  as the demo user, on /run/aiza-backend/<user>-backend.sock
#   socat         root, /run/aiza-backend/<port>.sock (owner aiza) -> that socket.
#                 A real deployment does this with systemd socket activation
#                 and aiza-proxy-handler (README "ソケットアクティベーション").
#   aiza-gateway  as aiza, on 0.0.0.0:8878 inside the container
set -eu
user="${AIZA_DEMO_USER:?}"
uid=$(id -u "$user")
port=$((21000 + uid - 1000))
home=$(getent passwd "$user" | cut -d: -f6)

# Cookie signing key: new per container unless one is mounted.
if [ ! -s /etc/aiza/cookie_secret ]; then
  head -c 32 /dev/urandom | base64 > /etc/aiza/cookie_secret
fi
chown aiza:aiza /etc/aiza/cookie_secret; chmod 600 /etc/aiza/cookie_secret

install -d -m 1777 /run/aiza-backend          # as etc/tmpfiles.d/aiza-backend.conf
rm -f "/run/aiza-backend/$user-backend.sock" "/run/aiza-backend/$port.sock"
install -d -o "$user" -g "$user" "$home/sandhome"

setpriv --reuid="$user" --regid="$user" --init-groups \
  env -i HOME="$home" USER="$user" LOGNAME="$user" PATH=/usr/local/bin:/usr/bin:/bin \
      LANG=C.UTF-8 TERM=xterm-256color AIZA_NOTIFY_HOST=127.0.0.1 /usr/local/sbin/aiza-backend &
backend=$!
i=0
while [ ! -S "/run/aiza-backend/$user-backend.sock" ]; do
  i=$((i + 1)); [ $i -gt 100 ] && { echo "aiza-demo: backend did not start" >&2; exit 1; }
  kill -0 $backend 2>/dev/null || { echo "aiza-demo: backend exited" >&2; exit 1; }
  sleep 0.1
done

socat "UNIX-LISTEN:/run/aiza-backend/$port.sock,fork,user=aiza,group=aiza,mode=600" \
      "UNIX-CONNECT:/run/aiza-backend/$user-backend.sock" &
relay=$!

setpriv --reuid=aiza --regid=aiza --init-groups \
  env -i HOME=/nonexistent PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 \
      AIZA_GATEWAY_HOST=0.0.0.0 AIZA_DEMO_USER="$user" /usr/local/sbin/aiza-gateway &
gateway=$!

echo "aiza-demo: open http://localhost:<published port>/agents/ (user $user)"
trap 'kill $backend $relay $gateway 2>/dev/null' INT TERM
# busybox/dash have no `wait -n`: poll until one of them is gone.
while kill -0 $backend 2>/dev/null && kill -0 $relay 2>/dev/null && kill -0 $gateway 2>/dev/null; do
  sleep 1
done
echo "aiza-demo: a process exited; stopping" >&2
kill $backend $relay $gateway 2>/dev/null || true
exit 1
