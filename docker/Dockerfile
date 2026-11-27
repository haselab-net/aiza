# aiza demo: the gateway, one user's backend and the PWA in one container.
# Build from the repository root:  docker build -f docker/Dockerfile -t aiza-demo .
# See docker/README.md.
FROM debian:trixie-slim

ARG WITH_CLAUDE=1
ARG DEMO_USER=demo

RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      python3 python3-venv tmux socat procps git curl ca-certificates less nano \
 && rm -rf /var/lib/apt/lists/*

# Claude Code's native build, installed once and shared at /usr/local/bin/claude
# (the installer puts it under the installing user's ~/.local; copy it out).
RUN if [ "$WITH_CLAUDE" = 1 ]; then \
      curl -fsSL https://claude.ai/install.sh | bash \
      && install -m 755 "$(readlink -f /root/.local/bin/claude)" /usr/local/bin/claude \
      && rm -rf /root/.local/share/claude /root/.local/bin/claude /root/.claude /root/.claude.json*; \
    fi

COPY requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/aiza/venv \
 && /opt/aiza/venv/bin/pip install --no-cache-dir -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# The gateway runs as the system user "aiza", the backend as the demo user.
# The demo user must be uid 1000: the gateway reaches a user's backend at
# /run/aiza-backend/<21000 + uid - 1000>.sock.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin aiza \
 && useradd --create-home --uid 1000 --shell /bin/bash "$DEMO_USER" \
 && install -d -o aiza -g aiza -m 700 /var/lib/aiza /var/lib/aiza/gateway-state \
 && install -d -m 755 /etc/aiza /usr/local/lib/aiza/ext \
 && install -d -o root -g "$DEMO_USER" -m 2770 /var/lib/aiza-board

COPY bin/ /usr/local/sbin/
# Libraries the backend and the session tools import (codex_chat, aiza_session_path, ...):
# the same fallback location as a deployed host.
COPY lib/ /opt/sandbox-shared/tools/lib/
COPY static/ /opt/aiza/static/
COPY docker/static/ /opt/aiza/static/
COPY docker/ext/ /usr/local/lib/aiza/ext/
COPY docker/sandbox /usr/local/bin/sandbox
COPY docker/entrypoint.sh /usr/local/sbin/aiza-demo-entrypoint
RUN rm -rf /usr/local/sbin/__pycache__ \
 && chmod 755 /usr/local/sbin/aiza-* /usr/local/bin/sandbox \
 && ln -s /usr/local/sbin/talkto /usr/local/bin/talkto

ENV AIZA_DEMO_USER=$DEMO_USER
EXPOSE 8878
ENTRYPOINT ["/usr/local/sbin/aiza-demo-entrypoint"]
