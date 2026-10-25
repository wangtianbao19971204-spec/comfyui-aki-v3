"""SQLite authority for the prompt library (round-3 storage layer).

The library used to be one 462 MB ``data.json`` document: every edit re-serialised
and rewrote the whole file.  This module keeps the same document shape but stores
categories, prompt order and prompt payloads as rows in ``library.sqlite3``
(WAL + ``synchronous=FULL``), so a single edit is one small transaction whose cost
does not grow with the library size.

Contract (see temp/startup-warmup/library-store-design.md):

* ``library_meta(key, value)``          JSON-encoded top-level document keys
* ``categories(id, name, position, payload)``
                                        category metadata JSON without ``prompts``
* ``category_orders(category_id, order_json)``
                                        ordered ``[prompt_id, ...]`` list
* ``prompts(id PRIMARY KEY, category_id, payload)``
                                        one full prompt object per row
* ``library_journal(seq, at, op, prompt_id, category_id, before, after)``
                                        bounded row-level undo log for recent edits

``load_document()`` rebuilds the exact document the old reader expected:
top-level keys in their recorded order, ``categories`` in ``position`` order,
each category's ``prompts`` in ``category_orders`` order, payloads round-tripped
through JSON.

Writes go through ``commit_document(document, ChangeSet(...))``; the change set
names exactly which rows changed, so a single-record edit only touches one prompt
row, one category/order row, the ``last_modified`` meta value and one journal row.

``AutoMaintenance`` is the background safety net requested for the authority DB:
it exports the current document to data.json after edits settle (debounced and
throttled), takes periodic/startup/write-count SQLite backups, prunes the journal
and publishes the last success/error state for the workbench status endpoint.  It
never runs on the request path and never blocks an edit.
"""

from __future__ import annotations

import gc
import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import uuid

try:  # orjson is used everywhere else in the plugin; the stdlib is the fallback
    import orjson as _orjson
except Exception:  # noqa: BLE001 - optional accelerator only
    _orjson = None

logger = logging.getLogger("weilin.prompt_selector.library_store")

SCHEMA_VERSION = "2"
DB_FILENAME = "library.sqlite3"
META_SCHEMA_VERSION = "__schema_version__"
META_TOP_LEVEL_ORDER = "__top_level_order__"
META_MIGRATION_RECEIPT = "__migration_receipt__"
META_LAST_BACKUP_AT = "__last_backup_at__"
INTERNAL_META_KEYS = {META_SCHEMA_VERSION, META_TOP_LEVEL_ORDER, META_MIGRATION_RECEIPT,
                      META_LAST_BACKUP_AT}

JOURNAL_DEFAULT_DAYS = 7
JOURNAL_DEFAULT_MAX_ENTRIES = 20000

# Auto-maintenance defaults (documented in the round-3 report; all overridable).
EXPORT_DEBOUNCE_S = 10.0
EXPORT_INTERVAL_S = 900.0
BACKUP_INTERVAL_S = 1800.0
BACKUP_RETAIN = 5
BACKUP_WRITES = 200
BACKUP_STARTUP_AGE_S = 24 * 3600.0
BACKUP_STARTUP_DELAY_S = 60.0

_DDL = """
CREATE TABLE IF NOT EXISTS library_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    position INTEGER NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS category_orders (
    category_id TEXT PRIMARY KEY REFERENCES categories(id) ON DELETE CASCADE,
    order_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS prompts (
    id TEXT PRIMARY KEY,
    category_id TEXT NOT NULL REFERENCES categories(id),
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS prompts_by_category ON prompts(category_id);
CREATE TABLE IF NOT EXISTS library_journal (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    at TEXT NOT NULL,
    op TEXT NOT NULL,
    prompt_id TEXT,
    category_id TEXT,
    before TEXT,
    after TEXT
);
CREATE INDEX IF NOT EXISTS journal_by_prompt ON library_journal(prompt_id, seq);
CREATE INDEX IF NOT EXISTS journal_by_time ON library_journal(at);
"""


class StoreMissingError(RuntimeError):
    """The sqlite database does not exist yet (run the migration tool)."""


class StoreRevisionConflict(RuntimeError):
    """The database revision changed between the caller's read and this commit."""

    def __init__(self, expected, actual):
        self.expected = str(expected)
        self.actual = str(actual)
        super().__init__("Library revision changed: expected %r, found %r" % (self.expected, self.actual))


def env_seconds(name, default):
    try:
        value = os.environ.get(name)
        return float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def env_flag(name):
    return str(os.environ.get(name, "")).strip().lower() in ("1", "true", "yes", "on")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _dumps(value):
    if _orjson is not None:
        return _orjson.dumps(value).decode("utf-8")
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(text):
    if _orjson is not None:
        return _orjson.loads(text)
    return json.loads(text)


def read_json_document(path):
    """Read a library document; the migration/export tools share this."""
    with open(path, "rb") as stream:
        raw = stream.read()
    if _orjson is not None:
        return _orjson.loads(raw)
    return json.loads(raw.decode("utf-8"))


def document_digest(document):
    """Stable digest of the document content (dict order independent)."""
    if _orjson is not None:
        raw = _orjson.dumps(document, option=_orjson.OPT_SORT_KEYS)
    else:
        raw = json.dumps(document, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _category_identity(category):
    return str(category.get("id") or category.get("name") or "")


def _category_payload(category):
    return {key: value for key, value in category.items() if key != "prompts"}


def _category_order(category):
    return [str(prompt.get("id") or "") for prompt in category.get("prompts") or []
            if isinstance(prompt, dict) and prompt.get("id")]


def _top_level_order(document):
    return [key for key in document if key != "categories"]


class ChangeSet:
    """The rows a document commit must rewrite.

    ``full`` rewrites everything (import/merge/replacement).  Otherwise the
    caller lists what changed: single prompt payloads, category/order rows,
    whole categories (all their prompt rows), deleted identities, plus the
    top-level meta keys that changed (``None`` means just ``last_modified``).
    """

    __slots__ = ("full", "upsert_prompts", "delete_prompt_ids", "write_categories",
                 "rewrite_categories", "delete_category_ids", "update_positions",
                 "meta_keys", "backup")

    def __init__(self, *, full=False, upsert_prompts=(), delete_prompt_ids=(),
                 write_categories=(), rewrite_categories=(), delete_category_ids=(),
                 update_positions=False, meta_keys=None, backup=False):
        self.full = bool(full)
        self.upsert_prompts = list(upsert_prompts)
        self.delete_prompt_ids = [str(value) for value in delete_prompt_ids if value]
        self.write_categories = list(write_categories)
        self.rewrite_categories = list(rewrite_categories)
        self.delete_category_ids = [str(value) for value in delete_category_ids if value]
        self.update_positions = bool(update_positions)
        self.meta_keys = None if meta_keys is None else [str(key) for key in meta_keys]
        self.backup = bool(backup)


class LibraryStore:
    """One process-wide SQLite connection; all calls are serialised by a lock."""

    def __init__(self, path, *, create=False, settle_seconds=30.0):
        self.path = os.path.abspath(str(path))
        self.timeout = float(settle_seconds)
        self._lock = threading.RLock()
        self._revision = ""
        self._conn = None
        self.last_load_seconds = 0.0
        self.last_commit_seconds = 0.0
        self.last_backup_path = None
        self.last_backup_bytes = 0
        self.last_backup_at = 0.0
        if not create and not os.path.isfile(self.path):
            raise StoreMissingError("library database not found: %s" % self.path)
        self._open(create)

    # -- connection -------------------------------------------------------
    def _open(self, create):
        directory = os.path.dirname(self.path)
        if create and directory and not os.path.isdir(directory):
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.path, timeout=self.timeout, isolation_level=None,
                               check_same_thread=False)
        try:
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=%d" % int(self.timeout * 1000))
            conn.execute("PRAGMA wal_autocheckpoint=1000")
            conn.execute("PRAGMA journal_size_limit=67108864")
            conn.execute("PRAGMA cache_size=-131072")
            conn.execute("PRAGMA mmap_size=268435456")
            conn.executescript(_DDL)
            if create:
                conn.execute("INSERT OR IGNORE INTO library_meta(key, value) VALUES (?, ?)",
                             (META_SCHEMA_VERSION, json.dumps(SCHEMA_VERSION)))
            else:
                row = conn.execute("SELECT value FROM library_meta WHERE key = ?",
                                   (META_SCHEMA_VERSION,)).fetchone()
                if row is None:
                    raise StoreMissingError("%s is not an initialized library database" % self.path)
            conn.execute("INSERT OR REPLACE INTO library_meta(key, value) VALUES (?, ?)",
                         (META_SCHEMA_VERSION, json.dumps(SCHEMA_VERSION)))
            self._conn = conn
            self._revision = self._read_revision()
            try:
                raw = conn.execute("SELECT value FROM library_meta WHERE key = ?",
                                   (META_LAST_BACKUP_AT,)).fetchone()
                self.last_backup_at = float(_loads(raw[0])) if raw and raw[0] else 0.0
            except (TypeError, ValueError):
                self.last_backup_at = 0.0
        except Exception:
            conn.close()
            raise

    def close(self):
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                except sqlite3.Error:
                    pass
                self._conn.close()
                self._conn = None

    @property
    def connection(self):
        if self._conn is None:
            raise StoreMissingError("library database is closed: %s" % self.path)
        return self._conn

    # -- reads ------------------------------------------------------------
    def _read_revision(self):
        row = self.connection.execute(
            "SELECT value FROM library_meta WHERE key = ?", ("last_modified",)).fetchone()
        return _loads(row[0]) if row and row[0] else ""

    def revision(self):
        with self._lock:
            return self._revision

    def meta_value(self, key):
        with self._lock:
            row = self.connection.execute(
                "SELECT value FROM library_meta WHERE key = ?", (key,)).fetchone()
        return _loads(row[0]) if row and row[0] else None

    def _set_meta_value(self, key, value):
        self.connection.execute(
            "INSERT INTO library_meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, _dumps(value)))

    def data_signature(self):
        """Cheap change token for the in-process read cache.

        ``data_version`` changes when another connection commits; same-process
        commits update ``_revision`` directly, so the signature moves either way.
        """
        with self._lock:
            try:
                version = self.connection.execute("PRAGMA data_version").fetchone()[0]
            except sqlite3.Error:
                version = -1
            return (self.path, int(version), self._revision)

    def load_document(self):
        """Rebuild the data.json-shaped document from the database."""
        started = time.perf_counter()
        gc_was_enabled = gc.isenabled()
        if gc_was_enabled:
            gc.disable()
        try:
            with self._lock:
                conn = self.connection
                meta = {}
                order = []
                for key, raw in conn.execute("SELECT key, value FROM library_meta"):
                    if key == META_TOP_LEVEL_ORDER:
                        parsed_order = _loads(raw)
                        if isinstance(parsed_order, list):
                            order = [str(value) for value in parsed_order]
                        continue
                    if key in INTERNAL_META_KEYS:
                        continue
                    meta[key] = _loads(raw)
                category_orders = {}
                for category_id, raw in conn.execute(
                        "SELECT category_id, order_json FROM category_orders"):
                    parsed_order = _loads(raw)
                    if isinstance(parsed_order, list):
                        category_orders[str(category_id)] = [str(value) for value in parsed_order]
                prompt_payloads = {}
                cursor = conn.execute("SELECT id, payload FROM prompts")
                while True:
                    rows = cursor.fetchmany(4096)
                    if not rows:
                        break
                    for prompt_id, payload in rows:
                        prompt_payloads[str(prompt_id)] = _loads(payload)
                categories = []
                for category_id, payload in conn.execute(
                        "SELECT id, payload FROM categories ORDER BY position"):
                    category = _loads(payload)
                    if not isinstance(category, dict):
                        category = {"value": category}
                    category_id = str(category_id)
                    category["prompts"] = [prompt_payloads[prompt_id]
                                           for prompt_id in category_orders.get(category_id, ())
                                           if prompt_id in prompt_payloads]
                    categories.append(category)
                document = {}
                inserted = False
                for key in order:
                    if key == "categories":
                        document["categories"] = categories
                        inserted = True
                    elif key in meta:
                        document[key] = meta[key]
                for key, value in meta.items():
                    if key not in document:
                        document[key] = value
                if not inserted:
                    document["categories"] = categories
                revision = meta.get("last_modified")
                if isinstance(revision, str):
                    self._revision = revision
        finally:
            if gc_was_enabled:
                gc.enable()
        self.last_load_seconds = time.perf_counter() - started
        return document

    # -- verification -----------------------------------------------------
    def verify_document_equals(self, document, max_diffs=20):
        """Deep-compare the stored rows against a document without materialising it."""
        diffs = []
        counts = {"categories": 0, "prompts": 0}
        stored_prompt_rows = 0
        expected_prompt_rows = 0

        def note(message):
            if len(diffs) < max_diffs:
                diffs.append(message)

        with self._lock:
            conn = self.connection
            stored_meta = {}
            for key, raw in conn.execute("SELECT key, value FROM library_meta"):
                if key in INTERNAL_META_KEYS:
                    continue
                stored_meta[key] = _loads(raw)
            expected_meta = {key: value for key, value in document.items() if key != "categories"}
            for key in sorted(set(stored_meta) | set(expected_meta)):
                if key not in stored_meta:
                    note("meta.%s missing from store" % key)
                elif key not in expected_meta:
                    note("meta.%s only in store" % key)
                elif stored_meta[key] != expected_meta[key]:
                    note("meta.%s differs" % key)
            expected_categories = document.get("categories") or []
            stored_categories = conn.execute(
                "SELECT id, name, payload FROM categories ORDER BY position").fetchall()
            counts["categories"] = len(stored_categories)
            if len(stored_categories) != len(expected_categories):
                note("category count %d != %d" % (len(stored_categories), len(expected_categories)))
            stored_orders = {}
            for category_id, raw in conn.execute("SELECT category_id, order_json FROM category_orders"):
                stored_orders[str(category_id)] = [str(value) for value in _loads(raw)]
            for index, expected in enumerate(expected_categories):
                expected_id = _category_identity(expected)
                expected_order = _category_order(expected)
                if index >= len(stored_categories):
                    break
                stored_id, stored_name, stored_payload = stored_categories[index]
                stored = _loads(stored_payload)
                if str(stored_id) != expected_id:
                    note("categories[%d] id %r != %r" % (index, stored_id, expected_id))
                if stored != _category_payload(expected):
                    note("categories[%d] metadata differs" % index)
                if str(stored_name) != str(expected.get("name") or ""):
                    note("categories[%d] name differs" % index)
                stored_order = stored_orders.get(str(stored_id), [])
                if expected_order != stored_order:
                    note("categories[%d] order differs (%d vs %d)"
                         % (index, len(expected_order), len(stored_order)))
                category_prompts = {}
                for prompt_id, payload in conn.execute(
                        "SELECT id, payload FROM prompts WHERE category_id = ?", (str(stored_id),)):
                    category_prompts[str(prompt_id)] = _loads(payload)
                for prompt_id in expected_order:
                    if prompt_id not in category_prompts:
                        note("prompt %r missing from category %r" % (prompt_id, expected_id))
                if len(category_prompts) != len(expected_order):
                    note("category %r has %d rows, order lists %d"
                         % (expected_id, len(category_prompts), len(expected_order)))
                for prompt in expected.get("prompts") or []:
                    prompt_id = str(prompt.get("id") or "")
                    stored_prompt = category_prompts.get(prompt_id)
                    if stored_prompt is not None and stored_prompt != prompt:
                        note("prompt %r payload differs" % prompt_id)
                    if len(diffs) >= max_diffs:
                        break
                if len(diffs) >= max_diffs:
                    break
            stored_prompt_rows = conn.execute("SELECT count(*) FROM prompts").fetchone()[0]
            expected_prompt_rows = sum(
                len(category.get("prompts") or []) for category in expected_categories)
            if stored_prompt_rows != expected_prompt_rows:
                note("prompt row count %d != %d" % (stored_prompt_rows, expected_prompt_rows))
        counts["prompts"] = expected_prompt_rows
        return {"equal": not diffs, "diffs": diffs, "counts": counts,
                "stored_prompt_rows": stored_prompt_rows,
                "expected_prompt_rows": expected_prompt_rows}

    # -- writes -----------------------------------------------------------
    def initialize_from_document(self, document, receipt=None):
        """One transaction that replaces the whole store with ``document``."""
        accepted = self._validate(document)
        with self._lock:
            conn = self.connection
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._write_full(document)
                self._write_meta(document, keys=None, receipt=receipt)
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            self._revision = str(document.get("last_modified") or "")
            self.last_commit_seconds = 0.0
        return accepted

    def commit_document(self, document, changes=None, expected_revision=None):
        changes = changes or ChangeSet(full=True)
        if changes.full:
            self._validate(document)
        else:
            self._validate_changes(document, changes)
        with self._lock:
            if changes.backup:
                self.backup(self._default_backup_dir())
            started = time.perf_counter()
            conn = self.connection
            try:
                conn.execute("BEGIN IMMEDIATE")
                current_revision = self._read_revision()
                if expected_revision is not None and str(expected_revision) != current_revision:
                    raise StoreRevisionConflict(expected_revision, current_revision)
                if changes.full:
                    self._write_full(document)
                    self._journal_record("replace", after={"document": "full replacement"})
                else:
                    self._apply_changes(document, changes)
                self._write_meta(document, keys=changes.meta_keys)
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            self._revision = str(document.get("last_modified") or "")
            self.last_commit_seconds = time.perf_counter() - started
        return self._revision

    def _apply_changes(self, document, changes):
        conn = self.connection
        journal = []
        if changes.delete_prompt_ids:
            for prompt_id in changes.delete_prompt_ids:
                row = conn.execute("SELECT category_id, payload FROM prompts WHERE id = ?",
                                   (prompt_id,)).fetchone()
                if row is not None:
                    journal.append(("delete", prompt_id, str(row[0]), row[1], None))
            self._delete_ids("DELETE FROM prompts WHERE id = ?", changes.delete_prompt_ids)
        if changes.delete_category_ids:
            for category_id in changes.delete_category_ids:
                journal.append(("delete_category", None, category_id, None,
                                {"category_id": category_id, "prompts": "deleted with category"}))
            self._delete_ids("DELETE FROM prompts WHERE category_id = ?", changes.delete_category_ids)
            self._delete_ids("DELETE FROM category_orders WHERE category_id = ?", changes.delete_category_ids)
            self._delete_ids("DELETE FROM categories WHERE id = ?", changes.delete_category_ids)
        positions = {}
        for position, category in enumerate(document.get("categories") or []):
            positions[_category_identity(category)] = position
        for category in changes.rewrite_categories:
            category_id = _category_identity(category)
            conn.execute("DELETE FROM prompts WHERE category_id = ?", (category_id,))
            self._write_category(category, positions.get(category_id, -1))
            conn.executemany(
                "INSERT INTO prompts(id, category_id, payload) VALUES (?, ?, ?)",
                [(str(prompt.get("id") or ""), category_id, _dumps(prompt))
                 for prompt in category.get("prompts") or [] if prompt.get("id")])
            journal.append(("rewrite_category", None, category_id, None,
                            {"category_id": category_id, "rows": len(category.get("prompts") or [])}))
        for category in changes.write_categories:
            category_id = _category_identity(category)
            self._write_category(category, positions.get(category_id, -1))
        if changes.upsert_prompts:
            for category_id, prompt in changes.upsert_prompts:
                prompt_id = str(prompt.get("id") or "")
                row = conn.execute("SELECT category_id, payload FROM prompts WHERE id = ?",
                                   (prompt_id,)).fetchone()
                journal.append(("update" if row is not None else "create", prompt_id,
                                str(category_id),
                                row[1] if row is not None else None, _dumps(prompt)))
            conn.executemany(
                "INSERT INTO prompts(id, category_id, payload) VALUES (?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET category_id=excluded.category_id, payload=excluded.payload",
                [(str(prompt.get("id") or ""), str(category_id), _dumps(prompt))
                 for category_id, prompt in changes.upsert_prompts])
        if changes.update_positions or changes.delete_category_ids:
            conn.executemany(
                "UPDATE categories SET position = ? WHERE id = ?",
                [(position, category_id) for category_id, position in positions.items()])
        for op, prompt_id, category_id, before, after in journal:
            self._journal_record(op, prompt_id=prompt_id, category_id=category_id,
                                 before=before, after=after)

    def _journal_record(self, op, *, prompt_id=None, category_id=None, before=None, after=None):
        self.connection.execute(
            "INSERT INTO library_journal(at, op, prompt_id, category_id, before, after) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (time.strftime("%Y-%m-%dT%H:%M:%S"), op, prompt_id, category_id,
             before if isinstance(before, str) else (None if before is None else _dumps(before)),
             after if isinstance(after, str) else (None if after is None else _dumps(after))))

    def _write_category(self, category, position):
        category_id = _category_identity(category)
        self.connection.execute(
            "INSERT INTO categories(id, name, position, payload) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, position=excluded.position, "
            "payload=excluded.payload",
            (category_id, str(category.get("name") or ""), int(position),
             _dumps(_category_payload(category))))
        self.connection.execute(
            "INSERT INTO category_orders(category_id, order_json) VALUES (?, ?) "
            "ON CONFLICT(category_id) DO UPDATE SET order_json=excluded.order_json",
            (category_id, _dumps(_category_order(category))))

    def _write_full(self, document):
        conn = self.connection
        conn.execute("DELETE FROM prompts")
        conn.execute("DELETE FROM category_orders")
        conn.execute("DELETE FROM categories")
        category_rows = []
        order_rows = []
        prompt_batches = []
        batch = []
        for position, category in enumerate(document.get("categories") or []):
            category_id = _category_identity(category)
            category_rows.append((category_id, str(category.get("name") or ""), position,
                                  _dumps(_category_payload(category))))
            order_rows.append((category_id, _dumps(_category_order(category))))
            for prompt in category.get("prompts") or []:
                if not prompt.get("id"):
                    continue
                batch.append((str(prompt["id"]), category_id, _dumps(prompt)))
                if len(batch) >= 2000:
                    prompt_batches.append(batch)
                    batch = []
        if batch:
            prompt_batches.append(batch)
        conn.executemany("INSERT INTO categories(id, name, position, payload) VALUES (?, ?, ?, ?)",
                         category_rows)
        conn.executemany("INSERT INTO category_orders(category_id, order_json) VALUES (?, ?)",
                         order_rows)
        for chunk in prompt_batches:
            conn.executemany("INSERT INTO prompts(id, category_id, payload) VALUES (?, ?, ?)", chunk)

    def _write_meta(self, document, keys, receipt=None):
        """Write only the top-level keys a commit changed (``None`` = all)."""
        conn = self.connection
        if keys is None:
            keys = [key for key in document if key != "categories"]
        keep = set(INTERNAL_META_KEYS)
        for key in keys:
            if key == "categories" or key not in document:
                continue
            keep.add(key)
            conn.execute("INSERT INTO library_meta(key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                         (key, _dumps(document[key])))
        if keys is None:
            placeholders = ",".join("?" for _ in keep)
            conn.execute("DELETE FROM library_meta WHERE key NOT IN (%s)" % placeholders,
                         tuple(sorted(keep)))
            conn.execute("INSERT OR REPLACE INTO library_meta(key, value) VALUES (?, ?)",
                         (META_TOP_LEVEL_ORDER, _dumps(_top_level_order(document))))
        if receipt is not None:
            conn.execute("INSERT OR REPLACE INTO library_meta(key, value) VALUES (?, ?)",
                         (META_MIGRATION_RECEIPT, _dumps(receipt)))

    def _delete_ids(self, statement, values):
        for start in range(0, len(values), 500):
            chunk = values[start:start + 500]
            self.connection.executemany(statement, [(value,) for value in chunk])

    @staticmethod
    def _validate(document):
        if not isinstance(document, dict):
            raise ValueError("library document must be a dict")
        categories = document.get("categories")
        if not isinstance(categories, list):
            raise ValueError("library document must carry a categories list")
        ids = set()
        total = 0
        for category in categories:
            if not isinstance(category, dict):
                raise ValueError("category entries must be dicts")
            category_id = _category_identity(category)
            if not category_id:
                raise ValueError("category without id/name")
            prompts = category.get("prompts")
            if prompts is not None and not isinstance(prompts, list):
                raise ValueError("category %r prompts must be a list" % category_id)
            for prompt in prompts or []:
                if not isinstance(prompt, dict) or not prompt.get("id"):
                    raise ValueError("prompt without id in category %r" % category_id)
                prompt_id = str(prompt["id"])
                if prompt_id in ids:
                    raise ValueError("duplicate prompt id %r" % prompt_id)
                ids.add(prompt_id)
                total += 1
        return {"categories": len(categories), "prompts": total}

    @staticmethod
    def _validate_changes(document, changes):
        """Cheap validation for a targeted commit (no full-library scan)."""
        if not isinstance(document, dict) or not isinstance(document.get("categories"), list):
            raise ValueError("library document must carry a categories list")
        categories = {_category_identity(category) for category in document.get("categories") or []}
        for category in changes.rewrite_categories + changes.write_categories:
            category_id = _category_identity(category)
            if not category_id or category_id not in categories:
                raise ValueError("changed category %r missing from document" % category_id)
            for prompt in category.get("prompts") or []:
                if not str(prompt.get("id") or ""):
                    raise ValueError("prompt without id in category %r" % category_id)
        for category_id, prompt in changes.upsert_prompts:
            if not str(prompt.get("id") or ""):
                raise ValueError("prompt without id in upsert")
            if str(category_id or "") not in categories:
                raise ValueError("upsert category %r missing from document" % category_id)

    # -- journal ----------------------------------------------------------
    def journal_entries(self, limit=50, prompt_id=None):
        limit = max(1, min(int(limit or 50), 500))
        with self._lock:
            if prompt_id:
                rows = self.connection.execute(
                    "SELECT seq, at, op, prompt_id, category_id, before, after FROM library_journal "
                    "WHERE prompt_id = ? ORDER BY seq DESC LIMIT ?", (str(prompt_id), limit)).fetchall()
            else:
                rows = self.connection.execute(
                    "SELECT seq, at, op, prompt_id, category_id, before, after FROM library_journal "
                    "ORDER BY seq DESC LIMIT ?", (limit,)).fetchall()
        entries = []
        for seq, at, op, entry_prompt, category_id, before, after in rows:
            entries.append({
                "seq": seq, "at": at, "op": op, "prompt_id": entry_prompt,
                "category_id": category_id,
                "before": _loads(before) if before else None,
                "after": _loads(after) if after else None,
            })
        return entries

    def journal_counts(self):
        with self._lock:
            count = self.connection.execute("SELECT count(*) FROM library_journal").fetchone()[0]
            oldest = self.connection.execute(
                "SELECT at FROM library_journal ORDER BY seq LIMIT 1").fetchone()
            return {"entries": count, "oldest_at": oldest[0] if oldest else None}

    def prune_journal(self, days=JOURNAL_DEFAULT_DAYS, max_entries=JOURNAL_DEFAULT_MAX_ENTRIES):
        with self._lock:
            conn = self.connection
            deleted = 0
            try:
                conn.execute("BEGIN IMMEDIATE")
                if days:
                    cutoff = time.strftime("%Y-%m-%dT%H:%M:%S",
                                           time.localtime(time.time() - float(days) * 86400))
                    deleted += conn.execute("DELETE FROM library_journal WHERE at < ?",
                                            (cutoff,)).rowcount
                count = conn.execute("SELECT count(*) FROM library_journal").fetchone()[0]
                if max_entries and count > max_entries:
                    row = conn.execute("SELECT seq FROM library_journal ORDER BY seq DESC LIMIT 1 OFFSET ?",
                                       (int(max_entries) - 1,)).fetchone()
                    if row is not None:
                        deleted += conn.execute("DELETE FROM library_journal WHERE seq < ?",
                                                (row[0],)).rowcount
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
        return deleted

    def restore_journal(self, seq, *, timestamp=None):
        """Undo one prompt-level journal entry (batch summaries are not restorable)."""
        with self._lock:
            conn = self.connection
            try:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT seq, op, prompt_id, category_id, before, after FROM library_journal "
                    "WHERE seq = ?", (int(seq),)).fetchone()
                if row is None:
                    raise KeyError("journal entry not found: %s" % seq)
                _seq, op, prompt_id, category_id, before_raw, after_raw = row
                if not prompt_id or op in ("replace", "rewrite_category", "delete_category"):
                    raise ValueError("journal entry %s is a batch summary and cannot be restored row-wise" % seq)
                before = _loads(before_raw) if before_raw else None
                current = conn.execute("SELECT category_id, payload FROM prompts WHERE id = ?",
                                       (prompt_id,)).fetchone()
                current_payload = _loads(current[1]) if current is not None else None
                current_category = str(current[0]) if current is not None else None
                self._journal_record("restore", prompt_id=prompt_id,
                                     category_id=category_id or current_category,
                                     before=current_payload, after=before)
                if before is None:
                    conn.execute("DELETE FROM prompts WHERE id = ?", (prompt_id,))
                    if current_category:
                        self._remove_from_order(current_category, prompt_id)
                else:
                    restored_category = str(category_id or current_category or "")
                    if not restored_category:
                        raise ValueError("journal entry %s has no category" % seq)
                    conn.execute(
                        "INSERT INTO prompts(id, category_id, payload) VALUES (?, ?, ?) "
                        "ON CONFLICT(id) DO UPDATE SET category_id=excluded.category_id, "
                        "payload=excluded.payload",
                        (prompt_id, restored_category, _dumps(before)))
                    if current_category and current_category != restored_category:
                        self._remove_from_order(current_category, prompt_id)
                    self._append_to_order(restored_category, prompt_id)
                now = timestamp or time.strftime("%Y-%m-%dT%H:%M:%S")
                conn.execute("INSERT INTO library_meta(key, value) VALUES ('last_modified', ?) "
                             "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (_dumps(now),))
                conn.execute("COMMIT")
            except Exception:
                try:
                    conn.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            self._revision = str(timestamp or time.strftime("%Y-%m-%dT%H:%M:%S"))
        return {"seq": int(seq), "prompt_id": prompt_id, "restored": before is not None,
                "revision": self._revision}

    def _order_ids(self, category_id):
        row = self.connection.execute(
            "SELECT order_json FROM category_orders WHERE category_id = ?", (str(category_id),)).fetchone()
        if row is None:
            return None
        parsed = _loads(row[0])
        return [str(value) for value in parsed] if isinstance(parsed, list) else []

    def _remove_from_order(self, category_id, prompt_id):
        order = self._order_ids(category_id)
        if order is None or prompt_id not in order:
            return
        order = [value for value in order if value != prompt_id]
        self.connection.execute(
            "UPDATE category_orders SET order_json = ? WHERE category_id = ?",
            (_dumps(order), str(category_id)))

    def _append_to_order(self, category_id, prompt_id):
        order = self._order_ids(category_id)
        if order is None:
            order = []
        if prompt_id not in order:
            order.append(prompt_id)
            self.connection.execute(
                "INSERT INTO category_orders(category_id, order_json) VALUES (?, ?) "
                "ON CONFLICT(category_id) DO UPDATE SET order_json=excluded.order_json",
                (str(category_id), _dumps(order)))

    # -- backup / export --------------------------------------------------
    def _default_backup_dir(self):
        return os.path.join(os.path.dirname(self.path), "library_backups")

    def backup(self, directory=None, retain=None):
        directory = os.path.abspath(str(directory or self._default_backup_dir()))
        retain = int(retain or env_seconds("UW_LIBRARY_BACKUP_RETAIN", BACKUP_RETAIN))
        with self._lock:
            os.makedirs(directory, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            target = os.path.join(directory, "library_%s_%s.sqlite3" % (stamp, uuid.uuid4().hex[:6]))
            destination = sqlite3.connect(target)
            try:
                self.connection.backup(destination)
            finally:
                destination.close()
            backups = sorted(name for name in os.listdir(directory)
                             if name.startswith("library_") and name.endswith(".sqlite3"))
            if retain > 1:
                for stale in backups[:-retain]:
                    try:
                        os.remove(os.path.join(directory, stale))
                    except OSError:
                        pass
            self.last_backup_path = target
            self.last_backup_bytes = os.path.getsize(target)
            self.last_backup_at = time.time()
            self._set_meta_value(META_LAST_BACKUP_AT, self.last_backup_at)
        return target

    def export_json(self, path, document=None):
        """Write the document in the original compact data.json form, atomically."""
        started = time.perf_counter()
        if document is None:
            document = self.load_document()
        payload = _dumps(document).encode("utf-8")
        target = os.path.abspath(str(path))
        directory = os.path.dirname(target) or "."
        os.makedirs(directory, exist_ok=True)
        temp_path = target + "." + uuid.uuid4().hex + ".tmp"
        try:
            with open(temp_path, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, target)
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        return {"path": target, "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "seconds": round(time.perf_counter() - started, 3)}

    # -- maintenance ------------------------------------------------------
    def integrity_check(self):
        with self._lock:
            return [row[0] for row in self.connection.execute("PRAGMA integrity_check")]

    def table_counts(self):
        with self._lock:
            tables = {}
            for (name,) in self.connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                tables[name] = self.connection.execute(
                    'SELECT count(*) FROM "%s"' % name).fetchone()[0]
            return tables

    def stat(self):
        stats = {"path": self.path, "exists": os.path.isfile(self.path),
                 "bytes": os.path.getsize(self.path) if os.path.isfile(self.path) else 0}
        for suffix in ("-wal", "-shm"):
            path = self.path + suffix
            stats[suffix] = os.path.getsize(path) if os.path.isfile(path) else 0
        stats["revision"] = self.revision()
        stats["last_backup_at"] = self.last_backup_at
        return stats


class AutoMaintenance(threading.Thread):
    """Background export/backup/journal-prune service for the authority DB.

    Starts as a daemon thread.  Edits only call ``notify_write()``; the export and
    backup work happens here, debounced and throttled, so no request path ever
    waits for data.json serialisation or a 600 MB backup copy.
    """

    def __init__(self, store, *, export_path=None, document_provider=None,
                 backup_dir=None, enable_export=None, enable_backup=None,
                 export_debounce_s=None, export_interval_s=None, backup_interval_s=None,
                 backup_retain=None, backup_writes=None, journal_days=None,
                 journal_max_entries=None, startup_backup_age_s=BACKUP_STARTUP_AGE_S,
                 startup_delay_s=BACKUP_STARTUP_DELAY_S):
        super().__init__(name="library-store-maintenance", daemon=True)
        self.store = store
        self.export_path = str(export_path) if export_path else None
        self.document_provider = document_provider
        self.backup_dir = str(backup_dir) if backup_dir else None
        self.export_debounce_s = float(export_debounce_s if export_debounce_s is not None
                                       else env_seconds("UW_LIBRARY_EXPORT_DEBOUNCE_S", EXPORT_DEBOUNCE_S))
        self.export_interval_s = float(export_interval_s if export_interval_s is not None
                                       else env_seconds("UW_LIBRARY_EXPORT_INTERVAL_S", EXPORT_INTERVAL_S))
        self.backup_interval_s = float(backup_interval_s if backup_interval_s is not None
                                       else env_seconds("UW_LIBRARY_BACKUP_INTERVAL_S", BACKUP_INTERVAL_S))
        self.backup_retain = int(backup_retain if backup_retain is not None
                                 else env_seconds("UW_LIBRARY_BACKUP_RETAIN", BACKUP_RETAIN))
        self.backup_writes = int(backup_writes if backup_writes is not None
                                 else env_seconds("UW_LIBRARY_BACKUP_WRITES", BACKUP_WRITES))
        self.journal_days = float(journal_days if journal_days is not None
                                  else env_seconds("UW_LIBRARY_JOURNAL_DAYS", JOURNAL_DEFAULT_DAYS))
        self.journal_max_entries = int(journal_max_entries if journal_max_entries is not None
                                       else env_seconds("UW_LIBRARY_JOURNAL_MAX_ENTRIES",
                                                        JOURNAL_DEFAULT_MAX_ENTRIES))
        self.enable_export = (not env_flag("UW_DISABLE_LIBRARY_AUTOEXPORT")) \
            if enable_export is None else bool(enable_export)
        self.enable_backup = (not env_flag("UW_DISABLE_LIBRARY_AUTOBACKUP")) \
            if enable_backup is None else bool(enable_backup)
        self.startup_backup_age_s = float(startup_backup_age_s)
        self.startup_delay_s = float(startup_delay_s)
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self.started_at = time.time()
        self.last_write_at = 0.0
        self.dirty = False
        self.last_export_attempt_at = 0.0
        self.last_export_success_at = 0.0
        self.last_export_error = None
        self.last_export_seconds = 0.0
        self.last_export_bytes = 0
        self.last_backup_attempt_at = 0.0
        self.last_backup_success_at = 0.0
        self.last_backup_error = None
        self.last_backup_path = None
        self.last_backup_bytes = 0
        self.writes_since_backup = 0
        self.backup_reasons = []
        self.last_warning_at = 0.0
        self._initial_backup_pending = False

    # -- notifications from the request path ------------------------------
    def notify_write(self, count=1):
        with self._lock:
            self.last_write_at = time.time()
            self.dirty = True
            self.writes_since_backup += int(count)
        self._wake.set()

    def request_backup(self, reason="manual"):
        with self._lock:
            self.backup_reasons.append(reason)
        self._wake.set()

    # -- thread body ------------------------------------------------------
    def run(self):
        if self.enable_backup and self.store.last_backup_at:
            with self._lock:
                self.last_backup_attempt_at = max(self.last_backup_attempt_at,
                                                  self.store.last_backup_at)
                self.last_backup_success_at = max(self.last_backup_success_at,
                                                  self.store.last_backup_at)
        if self.enable_backup:
            last = self.store.last_backup_at or 0.0
            if not last or time.time() - last > self.startup_backup_age_s:
                with self._lock:
                    self._initial_backup_pending = True
                logger.info("[Workbench] library store backup is due (last=%s)",
                            time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(last)) if last else "never")
        while not self._stop.is_set():
            timeout = self._next_timeout()
            self._wake.wait(timeout)
            self._wake.clear()
            if self._stop.is_set():
                break
            try:
                self._tick()
            except Exception as error:  # noqa: BLE001 - maintenance must never kill itself
                logger.warning("[Workbench] library store maintenance tick failed: %s", error)
        self._final_work()

    def _next_timeout(self):
        now = time.time()
        deadlines = [now + 30.0]
        with self._lock:
            if self.enable_export and self.dirty and self.export_path:
                export_at = max(self.last_write_at + self.export_debounce_s,
                                self.last_export_success_at + self.export_interval_s)
                deadlines.append(export_at)
            if self.enable_backup:
                if self._initial_backup_pending:
                    deadlines.append(self.started_at + self.startup_delay_s)
                elif self.backup_reasons:
                    deadlines.append(now)
                else:
                    deadlines.append(self.last_backup_attempt_at + self.backup_interval_s)
                if self.writes_since_backup >= self.backup_writes > 0:
                    deadlines.append(now)
        return max(0.05, min(deadlines) - now)

    def _tick(self):
        now = time.time()
        due_export = False
        due_backup = False
        backup_reason = None
        with self._lock:
            if (self.enable_export and self.dirty and self.export_path
                    and now >= max(self.last_write_at + self.export_debounce_s,
                                   self.last_export_success_at + self.export_interval_s)):
                due_export = True
            if self.enable_backup:
                if self._initial_backup_pending and now >= self.started_at + self.startup_delay_s:
                    due_backup = True
                    backup_reason = "startup"
                elif self.backup_reasons:
                    due_backup = True
                    backup_reason = self.backup_reasons[0]
                elif self.writes_since_backup >= self.backup_writes > 0:
                    due_backup = True
                    backup_reason = "write-count"
                elif now >= self.last_backup_attempt_at + self.backup_interval_s:
                    due_backup = True
                    backup_reason = "interval"
        if due_export:
            self._do_export()
        if due_backup:
            self._do_backup(backup_reason)
        self._warn_if_stale(now)

    def _do_export(self):
        with self._lock:
            if not self.export_path:
                return False
            self.last_export_attempt_at = time.time()
        document = None
        try:
            if self.document_provider is not None:
                document = self.document_provider()
            info = self.store.export_json(self.export_path, document=document)
        except Exception as error:  # noqa: BLE001 - export failure must stay non-fatal
            with self._lock:
                self.last_export_error = "%s: %s" % (type(error).__name__, error)
            logger.warning("[Workbench] library store auto-export failed: %s", error)
            return False
        with self._lock:
            self.last_export_success_at = time.time()
            self.last_export_seconds = info["seconds"]
            self.last_export_bytes = info["bytes"]
            self.last_export_error = None
            self.dirty = False
        logger.info("[Workbench] library store auto-export: %.1f MB in %.1f s",
                    info["bytes"] / 1e6, info["seconds"])
        return True

    def _do_backup(self, reason="interval"):
        with self._lock:
            self.last_backup_attempt_at = time.time()
            self.backup_reasons = [item for item in self.backup_reasons if item != reason]
            self._initial_backup_pending = False
        try:
            path = self.store.backup(self.backup_dir, self.backup_retain)
        except Exception as error:  # noqa: BLE001 - backup failure must stay non-fatal
            with self._lock:
                self.last_backup_error = "%s: %s" % (type(error).__name__, error)
            logger.warning("[Workbench] library store auto-backup failed: %s", error)
            return False
        with self._lock:
            self.last_backup_success_at = time.time()
            self.last_backup_path = path
            self.last_backup_bytes = self.store.last_backup_bytes
            self.last_backup_error = None
            self.writes_since_backup = 0
        try:
            self.store.prune_journal(self.journal_days, self.journal_max_entries)
        except Exception as error:  # noqa: BLE001 - pruning is best effort
            logger.warning("[Workbench] library journal prune failed: %s", error)
        logger.info("[Workbench] library store auto-backup (%s): %.1f MB", reason,
                    self.store.last_backup_bytes / 1e6)
        return True

    def _warn_if_stale(self, now):
        now = time.time()
        with self._lock:
            if now - self.last_warning_at < 600:
                return
            export_overdue = (self.enable_export and self.export_path and self.dirty
                              and now - max(self.last_export_success_at, self.started_at)
                              > max(self.export_interval_s * 2, 300))
            backup_overdue = (self.enable_backup
                              and now - max(self.last_backup_success_at, self.store.last_backup_at,
                                            self.started_at) > 24 * 3600)
            if not export_overdue and not backup_overdue:
                return
            self.last_warning_at = now
        if export_overdue:
            logger.warning("[Workbench] library store data.json export is overdue "
                           "(dirty edits pending, last success %s)",
                           self._format_time(self.last_export_success_at))
        if backup_overdue:
            logger.warning("[Workbench] library store backup is overdue (last success %s)",
                           self._format_time(max(self.last_backup_success_at, self.store.last_backup_at)))

    @staticmethod
    def _format_time(value):
        return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(value)) if value else "never"

    def status(self):
        now = time.time()
        with self._lock:
            last_export = self.last_export_success_at
            last_backup = max(self.last_backup_success_at, self.store.last_backup_at)
            journal = self.store.journal_counts()
            return {
                "active": True,
                "db": self.store.stat(),
                "export": {
                    "enabled": self.enable_export,
                    "dirty": self.dirty,
                    "path": self.export_path,
                    "debounce_s": self.export_debounce_s,
                    "interval_s": self.export_interval_s,
                    "last_attempt_at": self.last_export_attempt_at,
                    "last_success_at": last_export,
                    "last_success_iso": self._format_time(last_export),
                    "last_seconds": self.last_export_seconds,
                    "last_bytes": self.last_export_bytes,
                    "error": self.last_export_error,
                    "overdue": bool(self.enable_export and self.dirty
                                    and now - max(last_export, self.started_at)
                                    > max(self.export_interval_s * 2, 300)),
                },
                "backup": {
                    "enabled": self.enable_backup,
                    "interval_s": self.backup_interval_s,
                    "retain": self.backup_retain,
                    "last_success_at": last_backup,
                    "last_success_iso": self._format_time(last_backup),
                    "last_path": self.last_backup_path or self.store.last_backup_path,
                    "last_bytes": self.last_backup_bytes or self.store.last_backup_bytes,
                    "error": self.last_backup_error,
                    "writes_since_backup": self.writes_since_backup,
                    "overdue": bool(self.enable_backup and now - max(last_backup, self.started_at) > 24 * 3600),
                },
                "journal": journal,
                "writes_since_backup": self.writes_since_backup,
                "pending_backup_reasons": list(self.backup_reasons),
                "started_at": self.started_at,
            }

    def shutdown(self, timeout=60.0):
        self._stop.set()
        self._wake.set()
        try:
            self.join(timeout)
        except RuntimeError:
            pass

    def _final_work(self):
        with self._lock:
            dirty = self.dirty
            enable_export = self.enable_export
            enable_backup = self.enable_backup
        if enable_export and dirty:
            self._do_export()
        if enable_backup:
            try:
                self._do_backup("shutdown")
            except Exception as error:  # noqa: BLE001 - shutdown is best effort
                logger.warning("[Workbench] library store shutdown backup failed: %s", error)
        else:
            try:
                self.store.prune_journal(self.journal_days, self.journal_max_entries)
            except Exception:  # noqa: BLE001
                pass


def open_store(path, *, create=False):
    return LibraryStore(path, create=create)
