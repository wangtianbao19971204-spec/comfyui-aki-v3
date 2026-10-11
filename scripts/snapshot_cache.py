"""Local snapshot fingerprints; explicit full verify/release remains uncached.

Enumerate names and metadata on every run. Reuse content work only after a
successful verification with the same policy and file identity. On Windows,
include NTFS/ReFS ChangeTime, not the creation time exposed as st_ctime.
This is an optimization for a trusted local checkout, not tamper-proof evidence.
"""
from __future__ import annotations

import functools
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

from staged_scan_cache import canonical, digest, is_digest, plain_path

LIMIT = 32 * 1024 * 1024


@functools.lru_cache(maxsize=16)
def windows_filesystem(drive):
    import ctypes
    buffer = ctypes.create_unicode_buffer(32)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive + '\\'), None, 0, None, None, None, buffer, len(buffer))
    return buffer.value if ok else ''


def signature(path):
    """No payload reads. Return None when reliable local metadata is unavailable."""
    path = Path(path)
    before = path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or getattr(before, 'st_file_attributes', 0) & 0x400):
        return None
    change = before.st_ctime_ns
    if os.name == 'nt':
        if path.drive.startswith('\\\\') or windows_filesystem(path.drive) not in ('NTFS', 'ReFS'):
            return None
        import ctypes
        import msvcrt
        class BasicInfo(ctypes.Structure):
            _fields_ = [(name, ctypes.c_int64) for name in
                        ('creation', 'access', 'write', 'change')] + [('attributes', ctypes.c_uint32)]
        info = BasicInfo()
        with path.open('rb') as stream:
            opened = os.fstat(stream.fileno())
            ok = ctypes.windll.kernel32.GetFileInformationByHandleEx(
                ctypes.c_void_p(msvcrt.get_osfhandle(stream.fileno())), 0,
                ctypes.byref(info), ctypes.sizeof(info))
        if not ok or info.attributes & 0x400:
            return None
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (
                opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise RuntimeError('File identity changed during fingerprinting')
        change = info.change
    if not before.st_ino or not change:
        return None
    return [before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            change, before.st_mode, before.st_nlink]


def policy(root, git_dir):
    scripts = Path(__file__).parent
    rules = {name: digest((scripts / name).read_bytes()) for name in
             ('snapshot_cache.py', 'snapshot.py', 'security_guard.py', 'staged_scan_cache.py')}
    identity = git_dir.stat()
    return digest(canonical({'rules': rules, 'python': list(sys.version_info[:3]),
        'root': os.path.normcase(str(root)), 'git': os.path.normcase(str(git_dir)),
        'identity': [identity.st_dev, identity.st_ino], 'schema': 1}))


class SnapshotCache:
    def __init__(self, root, git_dir):
        self.root, self.git_dir = Path(root).resolve(), Path(git_dir).resolve()
        self.path = self.git_dir / 'comfyui-snapshot-fingerprints-v1.json'
        self.policy = policy(self.root, self.git_dir)
        self.records, self.groups, self.directories = {}, set(), {}
        self.pending, self.pending_groups, self.observed = {}, set(), {}
        self.hashed_files = self.hashed_bytes = self.scanned_files = self.reused_scans = 0
        self.joined_hashed_bytes = 0
        self.reused_groups = self.reused_directories = 0
        self.state, self.written = 'cold', False
        try:
            plain_path(self.path)
            if self.path.exists():
                before = self.path.stat()
                if before.st_size > LIMIT:
                    raise ValueError('Oversize cache')
                with self.path.open('rb') as stream:
                    opened = os.fstat(stream.fileno())
                    raw = stream.read(LIMIT + 1)
                after = self.path.lstat()
                plain_path(self.path)
                if (len(raw) > LIMIT or len(raw) != after.st_size
                        or len({(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
                                for s in (before, opened, after)}) != 1):
                    raise ValueError('Cache changed while reading')
                data = json.loads(raw)
                payload = data['payload']
                if digest(canonical(payload)) != data['checksum'] or payload['schema'] != 1:
                    raise ValueError('Damaged cache')
                if payload['policy'] != self.policy:
                    self.state = 'policy_changed'
                else:
                    records, groups, directories = payload['records'], payload['groups'], payload['directories']
                    if (not isinstance(records, dict) or len(records) > 100000
                            or not isinstance(groups, list) or not isinstance(directories, dict)
                            or not all(is_digest(k) and is_digest(v) for k, v in directories.items())
                            or not all(is_digest(k) for k in groups)):
                        raise ValueError('Invalid cache records')
                    for key, row in records.items():
                        if (not is_digest(key) or set(row) != {'signature', 'sha256', 'clean'}
                                or not is_digest(row['sha256']) or row['clean'] is not True
                                or not isinstance(row['signature'], list) or len(row['signature']) != 7
                                or not all(type(n) is int for n in row['signature'])):
                            raise ValueError('Invalid file fingerprint')
                    self.records, self.groups, self.directories = records, set(groups), directories
                    self.state = 'warm'
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            self.records, self.groups, self.directories = {}, set(), {}
            self.state = 'invalid_full_rescan'

    def key(self, path):
        return digest(str(Path(path).relative_to(self.root).as_posix()).encode('utf-8'))

    def lookup(self, path):
        current = signature(path)
        key = self.key(path)
        row = self.pending.get(key, self.records.get(key))
        if Path(path) in self.observed and self.observed[Path(path)] != current:
            raise RuntimeError('Snapshot changed during verification')
        if current is not None:
            self.observed.setdefault(Path(path), current)
            if row is not None and current == row['signature']:
                self.pending[key] = row.copy()
                return row
        return None

    def hash(self, path):
        row = self.lookup(path)
        if row is not None:
            return row['sha256']
        before = signature(path)
        if Path(path) in self.observed and self.observed[Path(path)] != before:
            raise RuntimeError('File changed before hashing')
        result = hashlib.sha256()
        with Path(path).open('rb') as stream:
            for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                result.update(block)
                self.hashed_bytes += len(block)
        self.hashed_files += 1
        after = signature(path)
        if before != after:
            raise RuntimeError('File changed while hashing')
        if after is not None:
            self.observed.setdefault(Path(path), after)
            self.pending[self.key(path)] = {'signature': after, 'sha256': result.hexdigest(), 'clean': False}
        return result.hexdigest()

    def scan(self, path, scanner):
        row = self.lookup(path)
        if row is not None and row['clean']:
            self.reused_scans += 1
            return []
        self.hash(path)
        before = signature(path)
        findings = scanner(path)
        self.scanned_files += 1
        if signature(path) != before:
            raise RuntimeError('File changed during content scan')
        if not findings and before is not None:
            self.pending[self.key(path)]['clean'] = True
        return findings

    def joined_hash(self, target, parts, expected):
        # Ordered paths plus actual, independently verified part hashes bind the
        # aggregate. A rename, replacement or manifest reordering invalidates it.
        identity = [(p.relative_to(self.root).as_posix(), self.hash(p)) for p in parts]
        key = digest(canonical([target.relative_to(self.root).as_posix(), identity, expected]))
        if key in self.groups:
            self.reused_groups += 1
            self.pending_groups.add(key)
            return expected
        result = hashlib.sha256()
        for path in parts:
            before = signature(path)
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
                    result.update(block)
                    self.joined_hashed_bytes += len(block)
            if signature(path) != before:
                raise RuntimeError('Part changed during joined hash')
        if result.hexdigest() == expected:
            self.pending_groups.add(key)
        return result.hexdigest()

    def finish(self, successful):
        for path, before in self.observed.items():
            if signature(path) != before:
                raise RuntimeError('Snapshot changed during verification')
        if policy(self.root, self.git_dir) != self.policy:
            raise RuntimeError('Snapshot verification policy changed')
        directories = {}
        for path, info in self.observed.items():
            for parent in path.parents:
                if not parent.is_relative_to(self.root):
                    break
                directories.setdefault(parent, []).append([path.relative_to(parent).as_posix(), info])
        fingerprints = {self.key(folder): digest(canonical(sorted(rows))) for folder, rows in directories.items()}
        self.reused_directories = sum(self.directories.get(k) == v for k, v in fingerprints.items())
        self.directory_count = len(fingerprints)
        if not successful:
            return
        payload = {'schema': 1, 'policy': self.policy,
                   'records': {k: v for k, v in self.pending.items() if v['clean']},
                   'groups': sorted(self.pending_groups), 'directories': fingerprints}
        raw = canonical({'payload': payload, 'checksum': digest(canonical(payload))})
        if len(raw) > LIMIT:
            self.state = 'write_size_limit'
            return
        temporary = None
        try:
            plain_path(self.path)
            fd, temporary = tempfile.mkstemp(prefix='snapshot-cache-', suffix='.tmp', dir=self.git_dir)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            plain_path(self.path)
            os.replace(temporary, self.path)
            temporary = None
            self.written = True
        except (OSError, ValueError):
            self.state = 'write_unavailable'
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def report(self):
        return {'mode': 'local-snapshot-fingerprints', 'state': self.state, 'written': self.written,
                'hashed_files': self.hashed_files, 'hashed_bytes': self.hashed_bytes,
                'joined_hashed_bytes': self.joined_hashed_bytes,
                'content_scanned_files': self.scanned_files, 'reused_content_scans': self.reused_scans,
                'reused_joined_hashes': self.reused_groups, 'unchanged_directories': self.reused_directories,
                'directory_count': getattr(self, 'directory_count', 0),
                'all_names_and_metadata_checked': True, 'publication_evidence': False}


def local_cache(snapshot):
    snapshot = Path(snapshot).resolve()
    repo = snapshot.parent
    if snapshot.name != 'snapshot' or not (repo / '.git').exists():
        return None
    git_dir = subprocess.run(['git', '-C', str(repo), 'rev-parse', '--absolute-git-dir'],
                             capture_output=True, check=True).stdout.decode().strip()
    return SnapshotCache(snapshot, Path(git_dir))
