"""Public Codex conversation records, shared by the reader and local relay.

Paginated histories use completed UI items as the canonical source. Legacy
histories use response items plus human user events. Never expose model input,
encrypted reasoning, tool arguments/results, or raw reasoning. Tool progress
exports constrained tool names and classified target basenames only.
"""
import datetime
import hashlib
import json
import re
import unicodedata


def timestamp(value):
    try:
        return datetime.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


def text_blocks(content, types):
    if not isinstance(content, list):
        return ''
    return '\n\n'.join(b['text'] for b in content if isinstance(b, dict)
                       and b.get('type') in types and isinstance(b.get('text'), str))


# Tool arguments/results are private. Only constrained names and basenames
# from Codex's structured command classifier are allowed into the public relay.
_TOOL_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,79}\Z")
_TOOL_SECRET = re.compile(r"[A-Za-z0-9_\-+/=]{32,}")


def tool_label(name, path=None):
    if not isinstance(name, str) or not _TOOL_NAME.fullmatch(name):
        return None
    name = _TOOL_SECRET.sub("…", name)
    if not isinstance(path, str) or not path:
        return name
    # Never show directories, URL credentials/query strings, control characters,
    # or token-like names. A classifier path is not an arbitrary description.
    if "://" in path or any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in path):
        return name
    target = path.rstrip("/").rsplit("/", 1)[-1]
    target = _TOOL_SECRET.sub("…", target)
    return name + (": " + target[:80] if target else "")


def tool_item(item):
    if item.get("type") != "CommandExecution":
        return None
    commands = item.get("parsed_cmd")
    if not isinstance(commands, list) and not item.get("command"):
        return None
    if isinstance(commands, list) and len(commands) == 1 and isinstance(commands[0], dict):
        command = commands[0]
        name = {"read": "Read", "list_files": "List", "search": "Search"}.get(command.get("type"))
        if name:
            return tool_label(name, command.get("path"))
    return "exec_command"


def parse_record(rec, state, position):
    if not isinstance(rec, dict):
        return []
    if rec.get('type') in ('aiza_codex_event', 'aigw_codex_event'):  # aigw-legacy: records from before the rename
        event = rec.get('event')
        return [event] if isinstance(event, dict) and event.get('type') in ('user_message', 'agent_output', 'agent_thinking', 'tool') and isinstance(event.get('text'), str) and isinstance(event.get('codex_event_id'), str) else []
    p = rec.get('payload')
    if not isinstance(p, dict):
        return []
    kind = rec.get('type')
    if kind == 'session_meta':
        state['thread'] = p.get('id') or p.get('session_id') or state.get('thread', '')
        state['paginated'] = p.get('history_mode') == 'paginated'
        return []
    event_type = text = item_id = None
    phase = None
    if kind == 'response_item' and p.get('type') in ('function_call', 'custom_tool_call'):
        # Native shell calls have a richer completed CommandExecution item.
        # Their raw call and UI item can share a call id: choose the latter.
        if (state.get('paginated') and p.get('name') in
                ('exec_command', 'shell', 'shell_command', 'functions.exec_command',
                 'functions.shell', 'functions.shell_command')):
            return []
        # arguments/input may contain scripts, credentials and model context.
        # Never decode them, even for the functions.exec wrapper.
        event_type, text = 'tool', tool_label(p.get('name'))
        item_id = 'tool-call:' + str(p.get('call_id') or p.get('id') or position)
    elif state.get('paginated'):
        if kind != 'event_msg' or p.get('type') != 'item_completed':
            return []
        item = p.get('item')
        if not isinstance(item, dict):
            return []
        item_id = item.get('id')
        t = item.get('type')
        if t == 'AgentMessage':
            event_type, text = 'agent_output', text_blocks(item.get('content'), ('Text', 'text'))
            phase = item.get('phase')
        elif t == 'UserMessage':
            event_type, text = 'user_message', text_blocks(item.get('content'), ('text', 'Text'))
            images = [b for b in item.get('content', []) if isinstance(b, dict) and b.get('type') in ('image', 'localImage', 'local_image')]
            if images:
                text += ('\n' if text else '') + '\n'.join('[画像]' for _ in images)
        elif t == 'CommandExecution':
            event_type, text = 'tool', tool_item(item)
        elif t == 'Reasoning':
            event_type = 'agent_thinking'
            text = '\n\n'.join(s for s in item.get('summary_text', []) if isinstance(s, str))
    else:
        item_id = p.get('id')
        if kind == 'response_item' and p.get('type') == 'message' and p.get('role') == 'assistant':
            event_type, text = 'agent_output', text_blocks(p.get('content'), ('output_text', 'text'))
            phase = p.get('phase')
        elif kind == 'response_item' and p.get('type') == 'reasoning':
            event_type, text = 'agent_thinking', text_blocks(p.get('summary'), ('summary_text',))
        elif kind == 'event_msg' and p.get('type') == 'user_message':
            event_type, text = 'user_message', p.get('message')
    if not event_type or not isinstance(text, str) or not text.strip():
        return []
    identity = str(state.get('thread', '')) + ':' + str(item_id or ('offset-' + str(position)))
    event = {'type': event_type, 'text': text, 'codex_event_id': identity}
    if event_type == 'agent_output':
        event['ai'] = True
        if phase:
            event['phase'] = phase
    ts = timestamp(rec.get('timestamp'))
    if ts is not None:
        event['ts'] = ts
    return [event]


def parse_chunk(buf, state, offset=0):
    end = buf.rfind(b'\n') + 1
    events = []
    pos = offset
    for raw in buf[:end].splitlines(keepends=True):
        try:
            events.extend(parse_record(json.loads(raw), state, pos))
        except (ValueError, TypeError):
            pass
        pos += len(raw)
    return end, events
