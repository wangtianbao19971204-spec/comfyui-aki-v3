if __package__:
    from .backup_fingerprints import FingerprintError, validate_fingerprint, same_fingerprint
else:
    from backup_fingerprints import FingerprintError, validate_fingerprint, same_fingerprint

"""Execute an already validated backup plan without owning planning or uploads."""
import copy
import hashlib
import os
import re
import tempfile
import zipfile


_HEX = re.compile(r"^[0-9a-fA-F]{64}$")
_FP_KEYS = {"exists", "sha256", "size", "mtime_ns"}


class InitialJournalError(RuntimeError):
    def __init__(self, result):
        super().__init__("initial journal callback failed")
        self.result = result


def _digest(path):
    h = hashlib.sha256()
    n = 0
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
            n += len(block)
    return h.hexdigest(), n


def _valid_fp(fp):
    try:
        validate_fingerprint(fp)
        return True
    except FingerprintError:
        return False


def _same_fp(a, b):
    return same_fingerprint(a, b)


def _counts(result):
    names = ("committed", "failed", "cancelled", "skipped", "pending", "unknown")
    c = {n: 0 for n in names}
    for u in result["units"]:
        s = u["state"]
        c[s if s in c and s not in ("preparing", "prepared", "replacing") else "pending"] += 1
    return c


def _finish(result, error=None):
    result["counts"] = _counts(result)
    if error:
        result["error"] = error
    c = result["counts"]
    if c["unknown"]:
        result["status"] = "unknown"
    elif c["failed"] and c["committed"]:
        result["status"] = "partial"
    elif c["failed"]:
        result["status"] = "failed"
    elif c["cancelled"]:
        result["status"] = "cancelled"
    elif c["pending"]:
        result["status"] = "partial"
    else:
        result["status"] = "completed"
    if result.get("error") and result["status"] == "completed":
        result["status"] = "partial" if c["committed"] else "failed"
    result["success"] = result["status"] == "completed" and not result["journal_error"]
    return result


def _new(units):
    return {"units": units, "counts": {n: 0 for n in ("committed", "failed", "cancelled", "skipped", "pending", "unknown")},
            "status": "failed", "journal_error": False}


def _snap(result):
    result["counts"] = _counts(result)
    return copy.deepcopy(result)


def execute_plan(archive_path, plan, *, journal, fingerprint, cancelled=lambda: False, replace=os.replace):
    raw = plan.get("units") if isinstance(plan, dict) else None
    units, valid, targets = [], isinstance(plan, dict) and isinstance(raw, list), set()
    if valid:
        valid = isinstance(plan.get("committable"), bool) and isinstance(plan.get("archive_sha256"), str) and bool(_HEX.fullmatch(plan["archive_sha256"]))
    raw = raw if isinstance(raw, list) else []
    for i, src in enumerate(raw):
        if not valid or not isinstance(src, dict) or src.get("index") != i or isinstance(src.get("index"), bool) or not isinstance(src.get("index"), int):
            valid = False
            continue
        action, target, kind = src.get("action"), src.get("target"), src.get("kind")
        good = isinstance(src.get("member"), str) and isinstance(kind, str) and action in ("write", "skip")
        if action == "write":
            good = good and isinstance(target, str) and os.path.isabs(target) and "\0" not in target
            good = good and isinstance(src.get("size"), int) and not isinstance(src.get("size"), bool) and src["size"] >= 0
            good = good and isinstance(src.get("incoming_sha256"), str) and bool(_HEX.fullmatch(src["incoming_sha256"]))
            good = good and _valid_fp(src.get("current_fingerprint"))
            key = os.path.normcase(os.path.normpath(target)) if isinstance(target, str) else None
            good = good and key not in targets
            if good:
                targets.add(key)
        else:
            good = good and (target is None or (isinstance(target, str) and os.path.isabs(target) and "\0" not in target))
        if not good:
            valid = False
        units.append({"index": i, "member": src.get("member"), "kind": kind, "target": target, "state": "pending", "reason": None})
    if len(units) != len(raw or []):
        valid = False
    if not valid:
        units = [{"index": i, "member": None, "kind": None, "target": None, "state": "failed", "reason": "invalid_plan"} for i in range(len(raw or []))]
        result = _finish(_new(units), "invalid_plan")
        try:
            journal(_snap(result))
        except Exception as exc:
            result["journal_error"] = True
            raise InitialJournalError(result) from exc
        return result
    for u, src in zip(units, raw):
        if src["action"] == "skip":
            u["state"], u["reason"] = "skipped", src.get("reason") or "not_selected"
    result = _new(units)
    result["status"] = "running"
    result["success"] = False
    try:
        actual, _ = _digest(archive_path)
        archive_ok = actual.lower() == plan["archive_sha256"].lower()
    except (OSError, ValueError):
        archive_ok = False
    if not archive_ok:
        result["error"] = "archive_mismatch"
        for u in units:
            if u["state"] == "pending": u.update(state="failed", reason="archive_mismatch")
    if not plan["committable"]:
        result["error"] = "noncommittable"
        for u in units:
            if u["state"] == "pending": u.update(state="failed", reason="noncommittable")
    try:
        journal(_snap(result))
    except Exception as exc:
        result["journal_error"] = True
        _finish(result, "initial_journal_error")
        raise InitialJournalError(result) from exc
    if not archive_ok or not plan["committable"]:
        _finish(result)
        try: journal(_snap(result))
        except Exception:
            result.update(journal_error=True, error="journal_error")
            _finish(result)
        return result
    try:
        with zipfile.ZipFile(archive_path) as zf:
            names = zf.namelist()
            if len(names) != len(set(names)): raise ValueError("duplicate_member")
            for u, src in zip(units, raw):
                if u["state"] != "pending": continue
                if cancelled():
                    for v in units:
                        if v["state"] == "pending": v.update(state="cancelled", reason="cancelled")
                    break
                temp = None
                try:
                    u["state"] = "preparing"
                    if not _write_journal(journal, result):
                        u.update(state="failed", reason="journal_before_replace")
                        result["journal_error"] = True; _finish(result, "journal_error"); break
                    parent = os.path.dirname(src["target"]) or os.curdir
                    os.makedirs(parent, exist_ok=True)
                    fd, temp = tempfile.mkstemp(prefix=".backup-", dir=parent)
                    h, size = hashlib.sha256(), 0
                    try:
                        with os.fdopen(fd, "wb") as out, zf.open(src["member"], "r") as inp:
                            for block in iter(lambda: inp.read(1024 * 1024), b""):
                                size += len(block)
                                if size > src["size"]: raise ValueError("member_oversize")
                                h.update(block); out.write(block)
                            if size != src["size"] or h.hexdigest().lower() != src["incoming_sha256"].lower(): raise ValueError("member_verification")
                            out.flush(); os.fsync(out.fileno())
                    except Exception:
                        raise
                    u["state"] = "prepared"
                    if not _write_journal(journal, result):
                        u.update(state="failed", reason="journal_before_replace")
                        result["journal_error"] = True; _finish(result, "journal_error"); break
                    if cancelled():
                        u.update(state="cancelled", reason="cancelled")
                        for v in units:
                            if v["state"] in ("pending", "preparing", "prepared", "replacing"): v.update(state="cancelled", reason="cancelled")
                        break
                    if not _same_fp(fingerprint(src["target"]), src["current_fingerprint"]): raise ValueError("stale_target")
                    u["state"] = "replacing"
                    if not _write_journal(journal, result):
                        u.update(state="failed", reason="journal_before_replace")
                        result["journal_error"] = True; _finish(result, "journal_error"); break
                    if cancelled():
                        u.update(state="cancelled", reason="cancelled")
                        for v in units:
                            if v["state"] == "pending": v.update(state="cancelled", reason="cancelled")
                        break
                    if not _same_fp(fingerprint(src["target"]), src["current_fingerprint"]): raise ValueError("stale_target")
                    try:
                        replace(temp, src["target"])
                    except Exception:
                        u.update(state="unknown", reason="replace_error"); _finish(result, "replace_error"); break
                    temp = None; u.update(state="committed", reason=None)
                    if not _write_journal(journal, result):
                        u.update(state="unknown", reason="journal_after_replace"); result["journal_error"] = True; _finish(result, "journal_after_replace"); break
                except KeyError:
                    u.update(state="failed", reason="archive_invalid")
                    break
                except Exception as exc:
                    if u["state"] in ("preparing", "prepared", "replacing"): u.update(state="failed", reason="preparation")
                    break
                finally:
                    if temp is not None:
                        try: os.unlink(temp)
                        except OSError: pass
    except (zipfile.BadZipFile, OSError, ValueError):
        result["error"] = "archive_invalid"
        for u in units:
            if u["state"] in ("pending", "preparing", "prepared", "replacing"): u.update(state="failed", reason="archive_invalid")
    _finish(result)
    if not result.get("journal_error"):
        try: journal(_snap(result))
        except Exception:
            result["journal_error"] = True; result["error"] = "journal_error"; _finish(result)
    return result


def _write_journal(journal, result):
    try:
        journal(_snap(result)); return True
    except Exception:
        return False
