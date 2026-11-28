#!/bin/sh
# A room of the public demo (Dockerfile): per person a listener that starts
# their backend on their first request, and the gateway on 0.0.0.0:8878,
# which lets in only what the door signed (the deployment notes).
set -eu
: "${AIZA_DEMO_ROOM:?}" "${AIZA_DEMO_SEATS:?}"
# The room's key comes read-only (root's, bound by the demo's VM) as
# demo_room_key.host; the gateway (aiza) reads its own copy.
if [ -s /etc/aiza/demo_room_key.host ]; then
  install -m 600 -o aiza -g aiza /etc/aiza/demo_room_key.host /etc/aiza/demo_room_key
fi
[ -s /etc/aiza/demo_room_key ] || { echo "aiza-room: no /etc/aiza/demo_room_key(.host)" >&2; exit 1; }
chown aiza:aiza /etc/aiza/demo_room_key; chmod 600 /etc/aiza/demo_room_key
# The gateway's own cookie key (unused for people -- the door logs them in).
[ -s /etc/aiza/cookie_secret ] || head -c 32 /dev/urandom | base64 > /etc/aiza/cookie_secret
chown aiza:aiza /etc/aiza/cookie_secret; chmod 600 /etc/aiza/cookie_secret
install -d -m 1777 /run/aiza-backend
install -d -m 755 /var/log/aiza-room
install -d -o aiza -g aiza -m 700 /var/lib/aiza /var/lib/aiza/gateway-state   # bound from the room's data
install -d -o root -g aiza -m 770 /run/aiza-room /run/aiza-room/kick   # the gateway's notes: who was sent out
install -d -o root -g root -m 700 /run/aiza-room-lock   # aiza-room-start-backend's locks: root's only, outside anything aiza can write
export AIZA_DEMO_ROOM

pids=""
n=1
while [ "$n" -le "$AIZA_DEMO_SEATS" ]; do
  user="demo$n"
  getent passwd "$user" >/dev/null || { echo "aiza-room: no user $user" >&2; exit 1; }
  port=$((21000 + n))
  rm -f "/run/aiza-backend/$port.sock"
  socat "UNIX-LISTEN:/run/aiza-backend/$port.sock,fork,user=aiza,group=aiza,mode=600" \
        "SYSTEM:/usr/local/sbin/aiza-room-start-backend $user" &
  pids="$pids $!"
  n=$((n + 1))
done

setpriv --reuid=aiza --regid=aiza --init-groups \
  env -i HOME=/nonexistent PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 \
      AIZA_GATEWAY_HOST=0.0.0.0 AIZA_DEMO_ROOM="$AIZA_DEMO_ROOM" AIZA_DEMO_SEATS="$AIZA_DEMO_SEATS" \
      /usr/local/sbin/aiza-gateway &
gateway=$!
echo "aiza-room: room $AIZA_DEMO_ROOM, $AIZA_DEMO_SEATS seats, gateway on :8878"
trap 'kill $gateway $pids 2>/dev/null' INT TERM
while kill -0 $gateway 2>/dev/null; do
  # Someone sent out of the room (the door's POST /_room/kick, the deployment notes):
  # their backend and everything they run here stop. Their box is the door's.
  for f in /run/aiza-room/kick/*; do
    [ -e "$f" ] || continue
    u=$(basename "$f"); rm -f "$f"
    case "$u" in demo[1-9]|demo[1-9][0-9]) ;; *) continue ;; esac
    pkill -KILL -u "$u" 2>/dev/null || true
    rm -f "/run/aiza-backend/$u-backend.sock"
    echo "aiza-room: $u sent out of the room" >&2
  done
  sleep 1
done
echo "aiza-room: the gateway exited; stopping" >&2
kill $pids 2>/dev/null || true
exit 1
