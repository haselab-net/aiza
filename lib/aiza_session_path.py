"""Where a pane's aiza session directory is now (the deployment notes, 2026-11-14).

A pane started before the host-only store existed carries
AIZA_TALKTO=<home>/sandhome/.aiza/<id>/talkto_out.jsonl in its environment,
which cannot be changed. Once aiza-backend has moved that session to
<home>/.aiza-state/sessions/<id>/, everything that writes for the pane (talkto,
the Claude/Codex hooks) must use the new directory, not the old one -- the old
tree is writable from inside the containers. No symlink or mapping file: the
new directory's existence is the redirect, and it is found by name.

open_session_dir() returns a directory descriptor, opened one component at a
time from "/" with O_NOFOLLOW, so a caller running as root never follows a
link someone planted. The new directory must be owned by the owner of <home>
and not writable by group or others (every component from <home> down).
A legacy path may use the old directory only if neither the host store nor
the persistent migration marker exists. Containers do not see either, and
users not yet migrated keep their previous behavior. Migrated users and all
explicit host-store paths fail closed if the session directory is absent.
"""
import os as _aiza_os  # aigw-legacy: sessions started before the rename (2026-11-23) only have AIGW_*
for _k in [k for k in _aiza_os.environ if k.startswith("AIGW_")]:
    _aiza_os.environ.setdefault("AIZA_" + _k[5:], _aiza_os.environ[_k].replace("/.aigw/", "/.aiza/").replace("/.aigw-state/", "/.aiza-state/"))
import os
import re
import stat

_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_ID = re.compile(r"^[0-9a-f]{12}$")


def _walk(parts, owner=None, check_from=None):
    """fd of /parts[0]/parts[1]/..., each opened with O_NOFOLLOW. From index
    check_from on, every directory must belong to `owner` and not be group-
    or other-writable."""
    fd = os.open("/", _DIR)
    try:
        for i, name in enumerate(parts):
            nfd = os.open(name, _DIR, dir_fd=fd)
            os.close(fd)
            fd = nfd
            if check_from is not None and i >= check_from:
                st = os.fstat(fd)
                if st.st_uid != owner or st.st_mode & 0o022:
                    raise PermissionError(f"untrusted directory: {name}")
        return fd
    except BaseException:
        os.close(fd)
        raise


def split_talkto(talkto):
    """(home parts, session id) for <home>/sandhome/.aiza/<id>/talkto_out.jsonl
    or <home>/.aiza-state/sessions/<id>/talkto_out.jsonl, else None."""
    if not talkto or not os.path.isabs(talkto):
        return None
    parts = [p for p in os.path.normpath(talkto).split("/") if p]
    if len(parts) < 5 or parts[-1] != "talkto_out.jsonl" or not _ID.match(parts[-2]):
        return None
    if parts[-4:-2] == ["sandhome", ".aiza"] or parts[-4:-2] == [".aiza-state", "sessions"]:
        return parts[:-4], parts[-2]
    return None


SESSION_STORE_MARKER = '.aiza-session-store-enabled'


def _adopted_store(home, owner):
    """Only ENOENT is legacy. Invalid or unreadable state fails closed."""
    hfd = _walk(home, owner=owner, check_from=len(home)-1)
    try:
        try:
            marker = os.open(SESSION_STORE_MARKER, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=hfd)
        except FileNotFoundError:
            marker = None
        if marker is not None:
            try:
                info = os.fstat(marker)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                        or info.st_uid not in (owner, 0) or info.st_mode & 0o022):
                    raise PermissionError('untrusted migration marker')
                return True
            finally: os.close(marker)
    finally: os.close(hfd)
    # .aiza-state predates migration. Only its sessions subdirectory is the
    # new store; refusing all users with the old state directory breaks legacy panes.
    try:
        fd = _walk(home + ['.aiza-state', 'sessions'], owner=owner, check_from=len(home)-1)
    except FileNotFoundError:
        return False
    os.close(fd)
    return True


def open_session_dir(talkto):
    """(dir fd, path) of the session directory this pane should write in.
    Raises OSError when neither can be opened safely."""
    if (not isinstance(talkto, str) or not os.path.isabs(talkto)
            or '..' in talkto.split('/') or os.path.basename(talkto) != 'talkto_out.jsonl'):
        raise ValueError('invalid session path')
    split = split_talkto(talkto)
    if split is None:
        parts = [p for p in os.path.normpath(os.path.dirname(talkto or "")).split("/") if p]
        return _walk(parts), "/" + "/".join(parts)
    home, sid = split
    owner = None
    try:
        hfd = _walk(home)
        try:
            owner = os.fstat(hfd).st_uid
        finally:
            os.close(hfd)
        new = home + [".aiza-state", "sessions", sid]
        return _walk(new, owner=owner, check_from=len(home)-1), "/" + "/".join(new)
    except FileNotFoundError:
        explicit_host = os.path.normpath(talkto).split('/')[-4:-2] == ['.aiza-state', 'sessions']
        if explicit_host or owner is None or _adopted_store(home, owner):
            raise
        # No host-only store or marker: a container without the host home
        # mounted, or a user whose backend has not adopted the new store yet.
    old = home + ["sandhome", ".aiza", sid]
    return _walk(old), "/" + "/".join(old)


def session_dir_path(talkto):
    """Just the path, for a caller that does not need the descriptor."""
    fd, path = open_session_dir(talkto)
    os.close(fd)
    return path
