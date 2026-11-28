#!/usr/bin/env python3
"""agent-turn.py -- one turn of an aiza "agent" session (the public demo,
the deployment notes): the Claude Agent SDK (Python) inside the room's box.

    agent-turn.py [--resume <conversation id>] [--cwd <dir>]  < prompt

The prompt comes on stdin (no length or quoting limits on the command
line). Output: the lines `claude -p --output-format stream-json` writes,
as far as aiza-backend reads them -- the headless "claude" preset and this
go through the same _run_claude_headless_turn (2026-11-27: one code path for
the demo and the regular install):

    {"type": "system", "subtype": "init", "session_id": "..."}
    {"type": "assistant", "message": {"content": [{"type": "tool_use", "name", "input"}]}}
    {"type": "result", "result": "...", "session_id": "...", "is_error": bool,
     "api_error_status": 429 | null, "total_cost_usd": 0.01}
    {"type": "error", "text": "..."}       # this script's own failure (not the CLI's)

The box gives the environment: ANTHROPIC_BASE_URL (the relay),
ANTHROPIC_API_KEY (a per-seat stand-in the relay swaps for the real key),
HTTPS_PROXY (GitHub only). CLAUDE_CODE_ENTRYPOINT is left to the SDK
("sdk-py"): the relay's free tier is for the Agent SDK, not for Claude
Code's own entry ("cli"), and tells them apart by it.
"""
import argparse
import asyncio
import json
import os
import sys

# Nothing but the API: no telemetry, error reports, update checks or other
# traffic (the box has no DNS and one way out, the relay).
QUIET_ENV = {
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "DISABLE_TELEMETRY": "1",
    "DISABLE_ERROR_REPORTING": "1",
    "DISABLE_AUTOUPDATER": "1",
    "DISABLE_BUG_COMMAND": "1",
    "DISABLE_COST_WARNINGS": "1",
}


def emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


async def run(prompt, resume, cwd):
    from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ResultMessage,
                                  SystemMessage, ToolUseBlock, query)
    for k, v in QUIET_ENV.items():
        os.environ.setdefault(k, v)
    opts = ClaudeAgentOptions(
        # The box is the boundary (gVisor, no network but the relay): the
        # agent runs its tools without asking, as the headless "claude" does.
        permission_mode="bypassPermissions",
        resume=resume or None,
        cwd=cwd or None,
        # No user/project settings files: nothing in the box steers the run.
        setting_sources=[],
        env=dict(QUIET_ENV),
    )
    said_init = False
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, SystemMessage):
            sid = (msg.data or {}).get("session_id") if isinstance(getattr(msg, "data", None), dict) else None
            if sid and not said_init:
                emit({"type": "system", "subtype": "init", "session_id": sid})
                said_init = True
        elif isinstance(msg, AssistantMessage):
            tools = [{"type": "tool_use", "name": b.name, "input": b.input if isinstance(b.input, dict) else {}}
                     for b in msg.content or [] if isinstance(b, ToolUseBlock)]
            if tools:
                emit({"type": "assistant", "message": {"content": tools}})
        elif isinstance(msg, ResultMessage):
            emit({"type": "result", "result": msg.result, "session_id": msg.session_id,
                  "is_error": bool(msg.is_error), "api_error_status": msg.api_error_status,
                  "total_cost_usd": msg.total_cost_usd})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", default="")
    ap.add_argument("--cwd", default="")
    a = ap.parse_args()
    try:
        # Its own process group, with the SDK's claude under it: aiza's stop
        # kills the group (_kill_claude_container_process).
        os.setpgid(0, 0)
    except OSError:
        pass
    prompt = sys.stdin.read()
    if not prompt.strip():
        emit({"type": "error", "text": "empty prompt"})
        return 2
    try:
        asyncio.run(run(prompt, a.resume, a.cwd))
    except Exception as e:  # noqa: BLE001 -- said to the chat, not a trace
        emit({"type": "error", "text": f"{type(e).__name__}: {str(e)[:1500]}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
