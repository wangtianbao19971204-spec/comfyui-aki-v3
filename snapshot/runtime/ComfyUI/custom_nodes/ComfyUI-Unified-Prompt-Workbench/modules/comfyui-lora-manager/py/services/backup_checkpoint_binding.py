import contextlib
import copy
import hashlib
import json
import os
import shutil
import stat
import tempfile
import uuid

if __package__:
    from .backup_fingerprints import (
        FingerprintError,
        fingerprint_path,
        validate_fingerprint,
        same_fingerprint,
    )
    from .backup_snapshot import prepare_sources
else:
    from backup_fingerprints import (
        FingerprintError,
        fingerprint_path,
        validate_fingerprint,
        same_fingerprint,
    )
    from backup_snapshot import prepare_sources


class BindingError(ValueError):
    """Raised when checkpoint binding contracts are violated."""


_SQLITE_WRITE_KINDS = frozenset(("model_update", "download_history"))
_STATE_FIELDS = frozenset((
    "version", "canonical_path", "unit_index", "approved_plan_hash",
    "approved_fingerprint", "pre_snapshot_digest", "post_snapshot_digest",
    "post_checkpoint_fingerprint", "context_identity", "sealed", "consumed",
))


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _plan_hash(plan):
    body = {k: v for k, v in plan.items() if k != "plan_hash"}
    return _sha(_canon(body))


def _freeze(value):
    return json.loads(json.dumps(value, ensure_ascii=True))


def _canonical_path(path):
    try:
        value = os.fspath(path)
    except TypeError as exc:
        raise BindingError("path must be a text path") from exc
    if isinstance(value, bytes) or "\0" in value or not os.path.isabs(value):
        raise BindingError("path must be an absolute text path")
    return os.path.normcase(os.path.abspath(os.path.normpath(value)))


def _check_ancestors(path):
    current = os.path.dirname(path)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    while True:
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            parent = os.path.dirname(current)
            if parent == current:
                return
            current = parent
            continue
        except OSError as exc:
            raise BindingError("cannot inspect path ancestor") from exc
        attrs = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attrs & reparse:
            raise BindingError("symlink or reparse point in path ancestry")
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def _stable_group(path):
    _check_ancestors(path)
    return fingerprint_path(path, sqlite=True)


def _private_copy(fp, tempdir, target):
    """Copy main+sidecars per fp into tempdir; verify byte consistency."""
    main_dest = os.path.join(tempdir, "database.sqlite")
    sides = fp.get("sqlite_files") or {}
    expected = {
        "main": fp,
        "wal": sides.get("wal") or {},
        "journal": sides.get("journal") or {},
    }
    mapping = {
        "main": (target, main_dest),
        "wal": (target + "-wal", main_dest + "-wal"),
        "journal": (target + "-journal", main_dest + "-journal"),
    }
    for label, item in expected.items():
        src, dst = mapping[label]
        if not item.get("exists"):
            if os.path.exists(dst):
                os.unlink(dst)
            continue
        if item.get("size", 0) > 0 and not item.get("sha256"):
            raise BindingError("missing sha256 for %s" % label)
        digest = hashlib.sha256()
        total = 0
        try:
            with open(src, "rb") as inp, open(dst, "wb") as out:
                while True:
                    block = inp.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
                    total += len(block)
                    out.write(block)
                out.flush()
                os.fsync(out.fileno())
        except OSError as exc:
            raise BindingError("cannot copy %s" % label) from exc
        if total != item["size"] or digest.hexdigest() != item["sha256"]:
            raise BindingError("copied %s bytes mismatch" % label)
    return main_dest


def _digest_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while True:
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


from dataclasses import dataclass

_SQLITE_WRITE_KINDS = frozenset(("model_update", "download_history"))


@dataclass(frozen=True)
class Pending:
    scope_id: str
    index: int
    target: str
    fp_json: str
    digest: object


@dataclass(frozen=True)
class Receipt:
    payload_json: str

    def to_dict(self):
        return json.loads(self.payload_json)


class CheckpointBinding:
    def __init__(self, plan, *, scratch_dir=None):
        if not isinstance(plan, dict):
            raise BindingError("plan must be a dict")
        declared = plan.get("plan_hash")
        if not isinstance(declared, str):
            raise BindingError("plan_hash must be declared")
        if _plan_hash(plan) != declared:
            raise BindingError("plan_hash mismatch")
        if plan.get("committable") is not True:
            raise BindingError("plan must be committable")
        units = plan.get("units")
        if not isinstance(units, list):
            raise BindingError("plan units must be a list")
        sqlite_units = []
        for pos, unit in enumerate(units):
            if not isinstance(unit, dict):
                raise BindingError("unit must be a dict")
            idx = unit.get("index")
            if not isinstance(idx, int) or isinstance(idx, bool):
                raise BindingError("unit index must be an int")
            if idx != pos:
                raise BindingError("unit index must equal array position")
            action = unit.get("action")
            if action == "write":
                kind = unit.get("kind")
                if kind in _SQLITE_WRITE_KINDS:
                    target = unit.get("target")
                    if not isinstance(target, str):
                        raise BindingError("sqlite write target required")
                    canon = _canonical_path(target)
                    fp = unit.get("current_fingerprint")
                    if not isinstance(fp, dict):
                        raise BindingError("current_fingerprint required")
                    validate_fingerprint(fp)
                    if not fp.get("sqlite_files"):
                        raise BindingError("sqlite_files missing")
                    sqlite_units.append((pos, canon, fp))
                else:
                    if unit.get("target") not in (None,):
                        pass
            elif action == "skip":
                pass
            else:
                raise BindingError("unknown action")
        self._plan_json = json.dumps(plan, sort_keys=True,
                                     separators=(",", ":"),
                                     ensure_ascii=True)
        self._declared_hash = declared
        self._sqlite_units = tuple(sqlite_units)
        self._sqlite_map = {pos: (canon, fp) for pos, canon, fp in sqlite_units}
        self._scratch_dir = None
        if scratch_dir is not None:
            if not os.path.isdir(scratch_dir):
                raise BindingError("scratch_dir must be an existing dir")
            self._scratch_dir = _canonical_path(scratch_dir)
        self._scope = None
        self._active = False
        self._closed = False
        self._derived = False
        self._pending = {}
        self._receipts = {}

    def _require_live(self):
        if self._closed:
            raise BindingError("binding closed")
        if not self._active:
            raise BindingError("binding not active")

    def _fp(self, path):
        try:
            return _stable_group(_canonical_path(path))
        except BindingError:
            raise
        except FingerprintError as exc:
            raise BindingError("fingerprint error") from exc
        except OSError as exc:
            raise BindingError("fingerprint error") from exc

    def __enter__(self):
        if self._closed:
            raise BindingError("binding closed")
        if self._active:
            raise BindingError("binding already active")
        self._scope = uuid.uuid4().hex
        self._active = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self._active = False
        self._closed = True
        self._pending.clear()
        self._receipts.clear()
        return False

    def _snapshot(self, target, expected):
        before = self._fp(target)
        if not same_fingerprint(before, expected):
            raise BindingError("fingerprint changed before snapshot")
        digest = None
        try:
            with tempfile.TemporaryDirectory(dir=self._scratch_dir) as tmp:
                main = _private_copy(expected, tmp, target)
                after_copy = self._fp(target)
                if not same_fingerprint(after_copy, expected):
                    raise BindingError("fingerprint changed during copy")
                snap = os.path.join(tmp, "snap")
                os.mkdir(snap)
                if expected.get("exists"):
                    prepared = prepare_sources([("model_update", "private.sqlite", main)], snap)
                    digest = prepared[0]["sha256"]
        finally:
            pass
        final = self._fp(target)
        if not same_fingerprint(final, expected):
            raise BindingError("fingerprint changed after snapshot")
        return digest

    def begin(self, index, path):
        self._require_live()
        if self._derived:
            raise BindingError("binding derived")
        if not isinstance(index, int) or isinstance(index, bool):
            raise BindingError("index must be an int")
        if index not in self._sqlite_map:
            raise BindingError("index not a sqlite write unit")
        if index in self._pending or index in self._receipts:
            raise BindingError("index already pending or finished")
        canon = _canonical_path(path)
        approved_target, approved = self._sqlite_map[index]
        if canon != approved_target:
            raise BindingError("path does not match unit")
        current = self._fp(canon)
        if not same_fingerprint(current, approved):
            raise BindingError("fingerprint does not match approved")
        digest = self._snapshot(canon, approved)
        pending = Pending(
            scope_id=self._scope,
            index=index,
            target=canon,
            fp_json=json.dumps(approved, sort_keys=True,
                               separators=(",", ":"), ensure_ascii=True),
            digest=digest,
        )
        self._pending[index] = pending
        return pending

    def finish(self, pending, path):
        self._require_live()
        if self._derived:
            raise BindingError("binding derived")
        if not isinstance(pending, Pending):
            raise BindingError("pending must be a Pending")
        stored = self._pending.get(pending.index)
        if stored is not pending:
            raise BindingError("pending was not issued by this scope")
        if pending.scope_id != self._scope:
            raise BindingError("pending scope mismatch")
        canon = _canonical_path(path)
        if canon != pending.target:
            raise BindingError("path does not match pending")
        approved = json.loads(pending.fp_json)
        current = self._fp(canon)
        if bool(current.get("exists")) != bool(approved.get("exists")):
            raise BindingError("existence changed unexpectedly")
        digest = self._snapshot(canon, current)
        if digest != pending.digest:
            raise BindingError("digest mismatch")
        payload = {
            "version": 1,
            "context_identity": self._scope,
            "unit_index": pending.index,
            "target": pending.target,
            "approved_plan_hash": self._declared_hash,
            "approved_fingerprint": json.loads(pending.fp_json),
            "post_checkpoint_fingerprint": current,
            "pre_snapshot_digest": pending.digest,
            "post_snapshot_digest": digest,
            "sealed": True,
        }
        receipt = Receipt(payload_json=json.dumps(
            payload, sort_keys=True, separators=(",", ":"),
            ensure_ascii=True))
        self._receipts[pending.index] = receipt
        del self._pending[pending.index]
        return receipt

    def derive(self, receipts):
        self._require_live()
        if self._derived:
            raise BindingError("binding already derived")
        if self._pending:
            raise BindingError("pending checkpoints remain")
        if receipts is None:
            receipts = []
        seen = {}
        for item in receipts:
            if not isinstance(item, Receipt):
                raise BindingError("receipt must be a Receipt")
            issued = self._receipts.get(item.to_dict().get("unit_index"))
            if issued is not item:
                raise BindingError("receipt was not issued by this scope")
            idx = item.to_dict()["unit_index"]
            if idx in seen:
                raise BindingError("duplicate receipt")
            if item.to_dict()["context_identity"] != self._scope:
                raise BindingError("receipt scope mismatch")
            seen[idx] = item
        expected_idx = {pos for pos, _, _ in self._sqlite_units}
        if set(seen) != expected_idx:
            raise BindingError("receipt set mismatch")
        original = json.loads(self._plan_json)
        cloned = copy.deepcopy(original)
        transitions = []
        for pos in sorted(expected_idx):
            item = seen[pos]
            data = item.to_dict()
            target = data["target"]
            live = self._fp(target)
            if not same_fingerprint(live, data["post_checkpoint_fingerprint"]):
                raise BindingError("target fingerprint drifted")
            cloned["units"][pos]["current_fingerprint"] = \
                data["post_checkpoint_fingerprint"]
            transitions.append(data)
        cloned["approved_plan_hash"] = self._declared_hash
        cloned["checkpoint_transitions"] = transitions
        cloned["plan_hash"] = _plan_hash(cloned)
        self._derived = True
        return _freeze(cloned)
