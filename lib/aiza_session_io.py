"""No-follow, regular-file-only access for local agent hook outputs."""
import os as _aiza_os  # aigw-legacy: sessions started before the rename (2026-11-23) only have AIGW_*
for _k in [k for k in _aiza_os.environ if k.startswith("AIGW_")]:
    _aiza_os.environ.setdefault("AIZA_" + _k[5:], _aiza_os.environ[_k].replace("/.aigw/", "/.aiza/").replace("/.aigw-state/", "/.aiza-state/"))
import json
import os
from pathlib import Path
import stat
import sys
import time
from aiza_session_path import open_session_dir


def open_directory(directory):
    """Resolve every component without following a link (including parents)."""
    p = Path(directory)
    if not p.is_absolute() or '..' in p.parts:
        raise ValueError('invalid directory')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in p.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def open_private(dfd, name, flags, *, allow_root=False, preserve_mode=False):
    """Validate before changing any file. Never truncate or chown an existing link."""
    if '/' in name or name in ('.', '..'):
        raise ValueError('invalid filename')
    created = False
    safe_flags = (flags & ~os.O_TRUNC & ~os.O_CREAT) | os.O_NOFOLLOW | os.O_NONBLOCK
    if flags & os.O_CREAT:
        try:
            fd = os.open(name, safe_flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=dfd)
            created = True
        except FileExistsError:
            if flags & os.O_EXCL: raise
            fd = os.open(name, safe_flags, dir_fd=dfd)
    else:
        fd = os.open(name, safe_flags, dir_fd=dfd)
    try:
        info, owner = os.fstat(fd), os.fstat(dfd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('not a private regular file')
        if created and os.geteuid() == 0:
            os.fchown(fd, owner.st_uid, owner.st_gid)
        elif info.st_uid != owner.st_uid and not (allow_root and info.st_uid == 0):
            raise ValueError('unexpected file owner')
        if not preserve_mode and flags & (os.O_WRONLY | os.O_RDWR):
            os.fchmod(fd, 0o600)
        if flags & os.O_TRUNC:
            os.ftruncate(fd, 0)
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_json(dfd, name):
    with os.fdopen(open_private(dfd, name, os.O_RDONLY)) as f:
        value = json.load(f)
    return value if isinstance(value, dict) else {}



def open_talkto(dfd, flags):
    # Older root agents created this one shared protocol file as root:0644.
    # Preserve it until migration; newly created files still get the session owner.
    return open_private(dfd, 'talkto_out.jsonl', flags, allow_root=True, preserve_mode=True)


def record_failure(directory, kind):
    try:
        dfd = open_output_directory(directory)
        try:
            fd = open_private(dfd, 'agent-hook-errors.jsonl', os.O_WRONLY | os.O_APPEND | os.O_CREAT)
            with os.fdopen(fd, 'a') as f:
                f.write(json.dumps({'ts': time.time(), 'error': kind}) + '\n')
        finally: os.close(dfd)
    except Exception:
        print('AI-za hook: output failed', file=sys.stderr)


def open_output_directory(directory):
    """Resolve migrated sessions on every operation, including error/status reads."""
    p = Path(directory)
    if not p.is_absolute() or '..' in p.parts:
        raise ValueError('invalid directory')
    return open_session_dir(str(p / 'talkto_out.jsonl'))[0]
