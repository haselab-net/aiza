# aiza for one room of the public demo (the deployment notes): the gateway, one
# backend per person (demo1..demo8, started on their first request) and the
# page. Behind the demo's door, which owns the login and signs every request.
# Build from the repository root:  docker build -f docker/room/Dockerfile -t aiza-room .
# Started with: /etc/aiza/demo_room_key.host (the room's key, root's, read-only), AIZA_DEMO_ROOM,
# AIZA_DEMO_SEATS, and the people's boxes' `sandbox` bound at /usr/local/bin/sandbox.
FROM debian:trixie-slim

ARG SEATS=8

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 python3-venv tmux socat procps util-linux git ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/aiza/venv \
 && /opt/aiza/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# The gateway runs as "aiza"; each person as demo<n>, uid 1000+n (the door's
# X-Demo-User), whose backend the gateway reaches at /run/aiza-backend/<21000+n>.sock.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin aiza \
 && for n in $(seq 1 "$SEATS"); do useradd --create-home --uid $((1000 + n)) --shell /usr/sbin/nologin "demo$n"; done \
 && install -d -o aiza -g aiza -m 700 /var/lib/aiza /var/lib/aiza/gateway-state \
 && install -d -m 755 /etc/aiza /usr/local/lib/aiza/ext

COPY bin/ /usr/local/sbin/
COPY lib/ /opt/sandbox-shared/tools/lib/
COPY static/ /opt/aiza/static/
COPY docker/room/sandbox-missing /usr/local/bin/sandbox
COPY docker/room/start-backend /usr/local/sbin/aiza-room-start-backend
COPY docker/room/entrypoint.sh /usr/local/sbin/aiza-room-entrypoint
RUN rm -rf /usr/local/sbin/__pycache__ \
 && chmod 755 /usr/local/sbin/aiza-* /usr/local/bin/sandbox \
 && ln -s /usr/local/sbin/talkto /usr/local/bin/talkto

EXPOSE 8878
ENTRYPOINT ["/usr/local/sbin/aiza-room-entrypoint"]
