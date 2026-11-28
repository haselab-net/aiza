# One person's box in the public demo (docker/demo-host/README.md; built on the demo host and
# run under gVisor in the demo VM by aiza-demo-boxd). Read-only root: only
# /tmp and $HOME (/home/demo<n>/sandhome, shared with the room) are writable.
# Build from the repository root:  docker build -f docker/box/Dockerfile -t aiza-demo-box .
FROM debian:trixie-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      tmux git ca-certificates curl python3 python3-venv less nano procps \
 && rm -rf /var/lib/apt/lists/* \
 && for n in 1 2 3 4 5 6 7 8; do useradd -u $((1000+n)) -m -d /home/demo$n -s /bin/bash demo$n; done
# The "agent" session (the deployment notes, docker/box/README.md): the Agent SDK,
# pinned, with the claude CLI its wheel brings.
COPY docker/box/requirements.txt /opt/aiza-agent/requirements.txt
RUN python3 -m venv /opt/aiza-agent/venv \
 && /opt/aiza-agent/venv/bin/pip install --no-cache-dir -r /opt/aiza-agent/requirements.txt
COPY docker/box/agent-turn.py /opt/aiza-agent/agent-turn.py
RUN chmod 755 /opt/aiza-agent/agent-turn.py
