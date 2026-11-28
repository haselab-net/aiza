# docker/box: the room's box, for the "agent" session (the deployment notes)

What the box image needs for aiza's "agent" session (the public demo). These are
the parts aiza's backend calls; the Dockerfile here builds the box around them.

- `agent-turn.py` → `/opt/aiza-agent/agent-turn.py` (0755). One turn: the
  prompt on stdin, JSON lines out (see its docstring).
- A venv at `/opt/aiza-agent/venv` with `requirements.txt`:

      python3 -m venv /opt/aiza-agent/venv
      /opt/aiza-agent/venv/bin/pip install --no-cache-dir -r /opt/aiza-agent/requirements.txt

  aiza-backend runs `/opt/aiza-agent/venv/bin/python3 /opt/aiza-agent/agent-turn.py`
  (`AGENT_PYTHON`, `AGENT_TURN`). The claude-agent-sdk wheel (manylinux x86_64)
  carries its own claude CLI (`claude_agent_sdk/_bundled/claude`, about 400MB,
  2.1.332 for 0.2.189): nothing else to install, and no Node.
- `sandbox --stdin exec -- sh -c '…'`: the prompt reaches the command's stdin.
- The environment comes from the box (not from aiza): `ANTHROPIC_BASE_URL`
  (the relay), `ANTHROPIC_API_KEY` (the seat's stand-in), `HTTPS_PROXY`,
  `NO_PROXY`. agent-turn.py adds the `DISABLE_*` and
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` settings and leaves
  `CLAUDE_CODE_ENTRYPOINT` to the SDK (`sdk-py`): the relay's free tier is told
  apart by it.
- Runs as a user, not root: the CLI refuses `bypassPermissions` as root.
- Writes only `$HOME/.claude` (conversations, for `--resume`) and `/tmp`.
- For the relay: on its own refusals (429 budget and the like), the header
  `x-should-retry: false` makes the CLI give up at once; without it the CLI
  retries a 429 for about two minutes (checked 2026-11-27 against a stand-in).
