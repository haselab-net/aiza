"""Copy a single CLI rollout, never credentials, between caller-selected homes.

Callers must select and authorize both homes; this module does not discover users.
All traversal is descriptor-relative and refuses links. Interrupted transfers may
leave a UUID lock; an administrator must inspect it before retrying.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid

from aiza_session_io import open_directory

MAX_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 100000
MAX_LINE = 16 * 1024 * 1024


def _id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('invalid conversation id')
    return value


def _directory(parent, name, create=False):
    created = False
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
            created = True
        except FileExistsError:
            pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    if created and os.geteuid() == 0:
        owner = os.fstat(parent)
        os.fchown(fd, owner.st_uid, owner.st_gid)
    return fd


def _sessions(home, create=False):
    fd = open_directory(home)
    try:
        for name in ('.codex', 'sessions'):
            child = _directory(fd, name, create)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _regular(parent, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        os.close(fd)
        raise ValueError('rollout is not a single-link regular file')
    return fd


def _locate(root, conv):
    found = []
    count = 0
    def walk(fd, parts):
        nonlocal count
        for name in os.listdir(fd):
            count += 1
            if count > MAX_ENTRIES:
                raise ValueError('too many rollout entries')
            if len(parts) < 3:
                if not re.fullmatch(r'\d{4}' if not parts else r'\d{2}', name):
                    continue
                child = _directory(fd, name)
                try:
                    walk(child, parts + [name])
                finally:
                    os.close(child)
            elif name.startswith('rollout-') and name.endswith('-' + conv + '.jsonl'):
                child = _regular(fd, name)
                found.append((child, parts + [name]))
                if len(found) > 1:
                    raise ValueError('ambiguous conversation rollout')
    try:
        walk(root, [])
        if not found:
            raise FileNotFoundError('conversation rollout not found')
        return found[0]
    except BaseException:
        for fd, _ in found:
            os.close(fd)
        raise


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate rollout key')
        result[key] = value
    return result


def _json_constant(_value):
    raise ValueError('invalid rollout constant')


def _validate_line(line, conv, first):
    value = json.loads(line, object_pairs_hook=_json_object, parse_constant=_json_constant)
    if not isinstance(value, dict):
        raise ValueError('invalid rollout event')
    if first:
        meta = value.get('payload')
        if (value.get('type') != 'session_meta' or not isinstance(meta, dict)
                or meta.get('id') != conv or meta.get('source') != 'cli'):
            raise ValueError('rollout is not the requested CLI session')


def _stream(src, dst, conv):
    before = os.fstat(src)
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise ValueError('rollout is not a single-link regular file')
    if before.st_size > MAX_BYTES:
        raise ValueError('rollout exceeds size limit')
    pending = b''
    digest = hashlib.sha256()
    total = 0
    first = True
    while True:
        chunk = os.read(src, 65536)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
        if total > MAX_BYTES:
            raise ValueError('rollout exceeds size limit')
        pending += chunk
        while b'\n' in pending:
            line, pending = pending.split(b'\n', 1)
            if len(line) > MAX_LINE:
                raise ValueError('rollout line exceeds size limit')
            _validate_line(line, conv, first)
            first = False
        if len(pending) > MAX_LINE:
            raise ValueError('rollout line exceeds size limit')
        if dst is not None:
            view = memoryview(chunk)
            while view:
                written = os.write(dst, view)
                view = view[written:]
    if pending or first:
        raise ValueError('incomplete rollout')
    after = os.fstat(src)
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
    if any(getattr(before, x) != getattr(after, x) for x in fields) or total != before.st_size:
        raise ValueError('rollout changed during copy')
    return digest.hexdigest()


def find_rollout(home, conversation_id):
    """Return a validated path for display; copy_rollout does not reopen it."""
    conv = _id(conversation_id)
    root = _sessions(home)
    try:
        fd, parts = _locate(root, conv)
        try:
            _stream(fd, None, conv)
        finally:
            os.close(fd)
        return Path(home) / '.codex' / 'sessions' / Path(*parts)
    finally:
        os.close(root)


def copy_rollout(src_home, dst_home, conversation_id, *, return_receipt=False):
    """Atomically install one immutable snapshot, refusing an existing UUID.

    Return a Path by default, or a TransferReceipt for safe failure cleanup.
    The caller must retain the receipt, not reconstruct one from the pathname.
    """
    conv = _id(conversation_id)
    src_root = _sessions(src_home)
    try:
        src, parts = _locate(src_root, conv)
    finally:
        os.close(src_root)
    dest = None
    lock = '.transfer-' + conv + '.lock'
    lock_created = False
    temp = None
    target_dir = None
    try:
        dest = _sessions(dst_home, True)
        lock_fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                          0o600, dir_fd=dest)
        os.close(lock_fd)
        lock_created = True
        try:
            existing, _ = _locate(dest, conv)
        except FileNotFoundError:
            pass
        else:
            os.close(existing)
            raise FileExistsError('destination already has this conversation')
        target_dir = os.dup(dest)
        for name in parts[:-1]:
            child = _directory(target_dir, name, True)
            os.close(target_dir)
            target_dir = child
        temp = '.rollout-transfer-' + uuid.uuid4().hex
        out = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                      0o600, dir_fd=target_dir)
        try:
            if os.geteuid() == 0:
                owner = os.fstat(target_dir)
                os.fchown(out, owner.st_uid, owner.st_gid)
            digest = _stream(src, out, conv)
            os.fsync(out)
            expected = os.fstat(out)
            candidate = os.stat(temp, dir_fd=target_dir, follow_symlinks=False)
            if ((expected.st_dev, expected.st_ino) != (candidate.st_dev, candidate.st_ino)
                    or candidate.st_nlink != 1):
                raise ValueError('transfer temporary file changed')
            os.link(temp, parts[-1], src_dir_fd=target_dir, dst_dir_fd=target_dir,
                    follow_symlinks=False)
            installed = os.stat(parts[-1], dir_fd=target_dir, follow_symlinks=False)
            if ((expected.st_dev, expected.st_ino) != (installed.st_dev, installed.st_ino)
                    or not stat.S_ISREG(installed.st_mode)):
                os.unlink(parts[-1], dir_fd=target_dir)
                raise ValueError('transfer temporary file changed')
            os.unlink(temp, dir_fd=target_dir)
            temp = None
            os.fsync(target_dir)
        finally:
            os.close(out)
        path = Path(dst_home) / '.codex' / 'sessions' / Path(*parts)
        if return_receipt:
            return TransferReceipt(path, expected.st_dev, expected.st_ino,
                                   expected.st_size, digest)
        return path
    finally:
        os.close(src)
        if temp is not None and target_dir is not None:
            os.unlink(temp, dir_fd=target_dir)
        if target_dir is not None:
            os.close(target_dir)
        if lock_created:
            os.unlink(lock, dir_fd=dest)
        if dest is not None:
            os.close(dest)


@dataclass(frozen=True)
class TransferReceipt:
    path: Path
    device: int
    inode: int
    size: int
    sha256: str


def _matches(fd, receipt):
    before = os.fstat(fd)
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or (before.st_dev, before.st_ino, before.st_size) !=
               (receipt.device, receipt.inode, receipt.size)
            or before.st_size > MAX_BYTES):
        return False
    os.lseek(fd, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        data = os.read(fd, 65536)
        if not data:
            break
        total += len(data)
        if total > receipt.size:
            return False
        digest.update(data)
    after = os.fstat(fd)
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_nlink')
    return (total == receipt.size and digest.hexdigest() == receipt.sha256
            and all(getattr(before, k) == getattr(after, k) for k in fields))


def rollback_rollout(receipt):
    """Remove only an unchanged file installed by this transfer, else False.

    A candidate is moved into a fresh private holding directory before its
    identity and digest are checked again. A same-name replacement is never
    deleted. If a concurrent writer prevents restoration, the replacement is
    preserved in that holding directory for manual recovery. No directory
    containing user work is removed. Call this as the destination home owner.
    Like all files in that home, the private holding directory remains writable
    by other processes with the same uid. This handles ordinary concurrent
    name replacement, not a hostile same-uid process rewriting that directory.
    """
    if not isinstance(receipt, TransferReceipt):
        raise TypeError('a transfer receipt is required')
    parent = held = src = None
    holding = None
    moved = False
    try:
        parent = open_directory(receipt.path.parent)
        src = _regular(parent, receipt.path.name)
        if not _matches(src, receipt):
            return False
        holding = '.rollout-rollback-' + uuid.uuid4().hex
        os.mkdir(holding, 0o700, dir_fd=parent)
        held = _directory(parent, holding)
        os.rename(receipt.path.name, 'candidate', src_dir_fd=parent, dst_dir_fd=held)
        moved = True
        check = _regular(held, 'candidate')
        try:
            matches = _matches(check, receipt)
        finally:
            os.close(check)
        if not matches:
            return False
        os.unlink('candidate', dir_fd=held)
        moved = False
        os.fsync(held)
        os.fsync(parent)
        return True
    except (OSError, ValueError):
        return False
    finally:
        # link() restores without ever overwriting a newer same-name file.
        # If the original name is occupied, preserve the candidate in place.
        if moved and held is not None:
            try:
                os.link('candidate', receipt.path.name, src_dir_fd=held,
                        dst_dir_fd=parent, follow_symlinks=False)
                retained = os.stat('candidate', dir_fd=held, follow_symlinks=False)
                restored = os.stat(receipt.path.name, dir_fd=parent, follow_symlinks=False)
                if (retained.st_dev, retained.st_ino) == (restored.st_dev, restored.st_ino):
                    os.unlink('candidate', dir_fd=held)
            except OSError:
                pass
        if src is not None:
            os.close(src)
        if held is not None:
            os.close(held)
        if holding is not None and parent is not None:
            try:
                os.rmdir(holding, dir_fd=parent)
            except OSError:
                pass
        if parent is not None:
            os.close(parent)
