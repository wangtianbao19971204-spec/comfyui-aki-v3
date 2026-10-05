"""Pair files that vanished from a scan with the live entry that holds them.

A model renamed or moved outside the app is observed by the next scan as "old
path gone, new path added".  The shared-collection membership can only follow it
when the two entries provably describe the same file, so the match is made on
content, never on the file name alone:

* a non-empty ``sha256`` on both sides that is identical, or
* - when one side carries no hash yet - the same file name *and* the same byte
  size, and never onto a file that is known to have different content.

Every match also has to be one-to-one.  A batch that contains two identical
copies therefore claims nothing: an ambiguous match is dropped so a group can
never be redirected to the wrong file.
"""
from __future__ import annotations

import os


def fingerprint(entry):
    """Identity of a cache entry that survives a rename or a move."""
    path = str((entry or {}).get('file_path') or '').replace('\\', '/')
    try:
        size = int((entry or {}).get('size') or 0)
    except (TypeError, ValueError):
        size = 0
    sha256 = str((entry or {}).get('sha256') or '').strip().lower()
    return sha256, size, os.path.basename(path).lower()


def match_moved_files(vanished, live):
    """Return ``[(old_path, new_path), ...]`` for the moves a scan can prove."""
    candidates = []
    for item in live or ():
        path = str((item or {}).get('file_path') or '')
        if path:
            candidates.append((path, *fingerprint(item)))

    pools = {}
    for item in vanished or ():
        old_path = str((item or {}).get('file_path') or '')
        if not old_path:
            continue
        old_sha, old_size, old_name = fingerprint(item)
        strong, weak = [], []
        for path, sha, size, name in candidates:
            if path == old_path:
                continue
            if old_sha and sha and sha == old_sha:
                strong.append(path)
            elif name and name == old_name and old_size and size == old_size \
                    and not (old_sha and sha and sha != old_sha):
                weak.append(path)
        pool = strong or weak
        if pool:
            pools[old_path] = sorted(set(pool))

    claimed = {}
    for pool in pools.values():
        for path in pool:
            claimed[path] = claimed.get(path, 0) + 1
    return [(old_path, pool[0]) for old_path, pool in sorted(pools.items())
            if len(pool) == 1 and claimed[pool[0]] == 1]
