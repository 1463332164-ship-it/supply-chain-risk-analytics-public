"""Publish complete local directories without replacing an existing destination."""
import ctypes
import errno
import os
import stat
import sys
import tempfile
from pathlib import Path


def plain_path(path):
    """Normalize paths, rejecting existing symlinks/junctions before resolving .. ."""
    path = Path(path).absolute()
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'symbolic links/reparse points are not supported: {part}')
    return path.resolve()


def check_new_output(target, sources=()):
    target = plain_path(target)
    for source in sources:
        source = plain_path(source)
        if target == source or source.is_relative_to(target) or target.is_relative_to(source):
            raise ValueError('output conflicts with an input path; use a separate new directory')
    if os.path.lexists(target):
        raise ValueError(f'output already exists; refusing overwrite: {target}')
    return target


def _rename_new_directory(source, target):
    """One OS rename with no replacement, including a last-instant empty target.

    Plain POSIX rename can replace an empty directory, so never use it as a
    fallback. Unsupported systems/filesystems fail closed. No durability claim.
    """
    if os.name == 'nt':
        os.rename(source, target)  # Windows refuses every existing destination.
        return
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform.startswith('linux') and hasattr(libc, 'renameat2'):
        rename = libc.renameat2
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(-100, os.fsencode(source), -100, os.fsencode(target), 1)
        # AT_FDCWD = -100; RENAME_NOREPLACE = 1.
    elif sys.platform == 'darwin' and hasattr(libc, 'renamex_np'):
        rename = libc.renamex_np
        rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        result = rename(os.fsencode(source), os.fsencode(target), 4)  # RENAME_EXCL
    else:
        raise OSError(errno.ENOTSUP, 'exclusive directory rename is unavailable')
    if result != 0:
        code = ctypes.get_errno()
        raise OSError(code, f'exclusive directory publish failed: {os.strerror(code)}', str(target))


def publish_bundle(target, sources, build, before_publish=None):
    """Build in a private sibling, then exclusively rename the whole directory.

    Ordinary failures remove only our staging folder. The requested destination
    is never created piecemeal. Empty parent folders can remain after failure.
    This assumes trusted local parent directories, not hostile concurrent path
    replacement, network filesystem transactions or power-loss recovery.
    """
    requested = target
    sources = tuple(sources)
    target = check_new_output(requested, sources)
    target.parent.mkdir(parents=True, exist_ok=True)
    plain_path(target.parent)
    parent = target.parent.stat()
    with tempfile.TemporaryDirectory(prefix=f'.{target.name}-', dir=target.parent) as temp:
        staging = Path(temp) / 'bundle'
        staging.mkdir()
        build(staging)
        if before_publish is not None:
            before_publish()
        if check_new_output(requested, sources) != target:
            raise ValueError('output path changed during build')
        current = target.parent.stat()
        if (parent.st_dev, parent.st_ino) != (current.st_dev, current.st_ino):
            raise ValueError('output parent changed during build')
        _rename_new_directory(staging, target)
    return target
