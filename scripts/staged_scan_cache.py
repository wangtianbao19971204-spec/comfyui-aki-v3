"""Local performance cache, never a publication attestation or a payload store.

Only the staged guard may use this cache. Every hit still reads and hashes the
Git object; names, size, manifest order and cross-part edges are checked afresh.
The checksum catches accidental damage, not an administrator who can also edit
the hooks. Full-history, pre-push and release gates never consume this cache.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

LIMIT = 8 * 1024 * 1024
HEX = frozenset('0123456789abcdef')
NAME = 'comfyui-staged-scan-v1.json'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


def is_digest(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def plain_path(path):
    """Do not follow junctions/symlinks or overwrite hardlinked cache files."""
    for part in [*reversed(path.absolute().parents), path.absolute()]:
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Linked cache path')
        if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
            raise ValueError('Hardlinked cache path')


class StagedCache:
    def __init__(self, git_dir, policy):
        self.path = Path(git_dir).absolute() / NAME
        self.policy = policy
        self.records = {}
        self.pending = {}
        self.hits = 0
        self.reused_bytes = 0
        self.written = False
        self.state = 'cold'
        self._load()

    @staticmethod
    def key(entry):
        # Paths are part of the identity but never stored in this metadata cache.
        return digest(canonical({key: entry[key] for key in ('object', 'type', 'bytes', 'paths')}))

    def _load(self):
        try:
            plain_path(self.path)
            if not self.path.exists():
                return
            before = self.path.stat()
            if not stat.S_ISREG(before.st_mode) or before.st_size > LIMIT:
                raise ValueError('Cache size/type')
            with self.path.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                raw = stream.read(LIMIT + 1)
            after = self.path.lstat()
            plain_path(self.path)
            if len({(s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns) for s in (before, opened, after)}) != 1 or len(raw) != after.st_size:
                raise ValueError('Cache changed')
            data = json.loads(raw)
            if set(data) != {'payload', 'checksum'} or digest(canonical(data['payload'])) != data['checksum']:
                raise ValueError('Cache checksum')
            payload = data['payload']
            if set(payload) != {'schema', 'policy', 'records'} or type(payload['schema']) is not int or payload['schema'] != 1:
                raise ValueError('Cache schema')
            if payload['policy'] != self.policy:
                self.state = 'policy_changed'
                return
            records = payload['records']
            if not isinstance(records, dict) or len(records) > 100000 or not all(is_digest(k) and is_digest(v) for k, v in records.items()):
                raise ValueError('Cache records')
            self.records = records
            self.state = 'warm'
        except (OSError, ValueError, TypeError, KeyError, RecursionError):
            # Damaged/untrusted metadata grants no reuse. Full scanning remains.
            self.records = {}
            self.state = 'invalid_full_rescan'

    def lookup(self, entry):
        return self.records.get(self.key(entry))

    def remember(self, entry, sha256, reused=False):
        self.pending[self.key(entry)] = sha256
        if reused:
            self.hits += 1
            self.reused_bytes += entry['bytes']

    def save(self):
        """Called only after all staged gates and stability checks passed."""
        payload = {'schema': 1, 'policy': self.policy, 'records': self.pending}
        raw = canonical({'payload': payload, 'checksum': digest(canonical(payload))}) + b'\n'
        if len(raw) > LIMIT:
            self.state = 'write_size_limit'
            return
        temporary = None
        try:
            plain_path(self.path)
            fd, temporary = tempfile.mkstemp(prefix='comfyui-scan-', suffix='.tmp', dir=self.path.parent)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            plain_path(self.path)
            os.replace(temporary, self.path)
            temporary = None
            self.written = True
        except OSError:
            self.state = 'write_unavailable'
        except ValueError:
            self.state = 'unsafe_path_not_written'
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def report(self):
        return {'mode': 'local-staged-only', 'state': self.state,
                'reused_objects': self.hits, 'reused_content_scan_bytes': self.reused_bytes,
                'written': self.written, 'policy_sha256': self.policy,
                'all_object_bytes_rehashed': True, 'publication_evidence': False}
