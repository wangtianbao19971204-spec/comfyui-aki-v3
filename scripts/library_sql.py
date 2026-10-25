"""Reversible SQL for ordinary SQLite and the reviewed Gallery external FTS5 index.

The Gallery format preserves business rows, hidden row identities, DDL, indexes,
triggers and AUTOINCREMENT counters. FTS shadow segments are derived storage;
the index is rebuilt from its preserved content table. Never uses writable_schema.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
import sqlite3

ITERDUMP = 'sqlite_iterdump_v1'
GALLERY_FTS5 = 'gallery_fts5_v1'
FORMATS = frozenset({ITERDUMP, GALLERY_FTS5})
# Prompt-library SQLite authority (library_store.py): plain tables whose payloads are
# JSON text. It is captured with ITERDUMP plus this semantic profile; the maintenance
# tools must not import runtime plugin code, so the contract is pinned here.
LIBRARY_STORE_PROFILE = 'prompt_library_store_v1'
LIBRARY_PROFILES = frozenset({LIBRARY_STORE_PROFILE})
LIBRARY_SCHEMA_VERSIONS = frozenset({'1'})
LIBRARY_STORE_TABLES = {
    'library_meta': ('key', 'value'),
    'categories': ('id', 'name', 'position', 'payload'),
    'category_orders': ('category_id', 'order_json'),
    'prompts': ('id', 'category_id', 'payload'),
}
LIBRARY_STORE_META_SCHEMA = '__schema_version__'
LIBRARY_STORE_META_TOP_LEVEL_ORDER = '__top_level_order__'
GALLERY_FTS_DDL = """CREATE VIRTUAL TABLE hot_tags_fts USING fts5(
    tag, translation_cn, content='hot_tags', content_rowid='rowid',
    tokenize='unicode61'
)"""
SHADOWS = frozenset({'hot_tags_fts_data', 'hot_tags_fts_idx',
                     'hot_tags_fts_docsize', 'hot_tags_fts_config'})


def quote_name(name):
    return '"' + name.replace('"', '""') + '"'


_TOKENS = re.compile(r"\s+|--[^\n]*(?:\n|$)|/\*.*?\*/|'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|`(?:``|[^`])*`|\[[^]]*\]|[A-Za-z_][A-Za-z_0-9]*|.", re.S)


def _tokens(sql):
    return [token if token[0] in "'\"`[" else token.casefold()
            for token in _TOKENS.findall(sql)
            if not token.isspace() and not token.startswith(('--', '/*'))]


def _normalized(sql):
    tokens = _tokens(sql)
    return tuple(tokens[:-1] if tokens and tokens[-1] == ';' else tokens)


def _identifier(token):
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1].replace('""', '"').casefold()
    if token.startswith('`') and token.endswith('`'):
        return token[1:-1].replace('``', '`').casefold()
    if token.startswith('[') and token.endswith(']'):
        return token[1:-1].casefold()
    return token.casefold()


def _check_fts_content_integrity(conn):
    # The special FTS integrity command needs a writable connection. Copy the
    # committed backup into memory so read-only source connections stay read-only.
    if conn.in_transaction:
        raise ValueError('Gallery export requires a committed SQLite backup')
    with contextlib.closing(sqlite3.connect(':memory:')) as copy:
        conn.backup(copy)
        try:
            copy.execute("INSERT INTO hot_tags_fts(hot_tags_fts,rank) VALUES('integrity-check',1)")
        except sqlite3.DatabaseError:
            return False
        return True


def _schema(conn, sql_format, allow_stale_fts=False):
    if sql_format not in FORMATS:
        raise ValueError('Unsupported library SQL format')
    rows = conn.execute("SELECT type,name,tbl_name,sql FROM sqlite_master "
                        "WHERE sql IS NOT NULL ORDER BY type,name").fetchall()
    virtual = [r for r in rows if r[0] == 'table' and
               re.match(r'\s*CREATE\s+VIRTUAL\s+TABLE\b', r[3], re.I)]
    if sql_format == ITERDUMP:
        if virtual:
            raise ValueError('Virtual table requires an explicit reviewed format')
        return rows
    if len(virtual) != 1 or virtual[0][1] != 'hot_tags_fts' or \
            _normalized(virtual[0][3]) != _normalized(GALLERY_FTS_DDL):
        raise ValueError('Unsupported Gallery virtual table schema or module')
    shadow_names = {r[1] for r in conn.execute('PRAGMA table_list') if r[2] == 'shadow'}
    if shadow_names != SHADOWS:
        raise ValueError('Unsupported Gallery FTS shadow schema')
    columns = [r[1] for r in conn.execute('PRAGMA table_info(hot_tags)')]
    if not {'tag', 'translation_cn'}.issubset(columns):
        raise ValueError('Gallery FTS content table is missing required columns')
    if any(r[1] in SHADOWS and r[0] != 'table' for r in rows):
        raise ValueError('Unexpected object uses an FTS shadow name')
    if not _check_fts_content_integrity(conn) and not allow_stale_fts:
        raise ValueError('Gallery FTS index does not match its content table')
    return rows


def table_counts(conn, sql_format=ITERDUMP, *, allow_stale_fts=False):
    rows = _schema(conn, sql_format, allow_stale_fts)
    return {name: conn.execute('SELECT count(*) FROM ' + quote_name(name)).fetchone()[0]
            for kind, name, _, _ in rows if kind == 'table'
            and not name.startswith('sqlite_')
            and (sql_format != GALLERY_FTS5 or name not in SHADOWS)}


def _literal(value):
    if value is None:
        return 'NULL'
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    if isinstance(value, str):
        if '\0' in value:
            return "CAST(X'" + value.encode('utf-8').hex() + "' AS TEXT)"
        return "'" + value.replace("'", "''") + "'"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if math.isinf(value):
            return '-9.0e999' if value < 0 else '9.0e999'
        if math.isnan(value):
            raise ValueError('NaN cannot be faithfully exported')
        return repr(value)
    raise ValueError('Unsupported SQLite value type')


def _rows(conn, name, ddl):
    info = conn.execute('PRAGMA table_info(' + quote_name(name) + ')').fetchall()
    columns = [r[1] for r in info]
    without_rowid = next(r[4] for r in conn.execute('PRAGMA table_list')
                         if r[0] == 'main' and r[1] == name)
    if not without_rowid:
        available = next((n for n in ('_rowid_', 'rowid', 'oid')
                          if n.casefold() not in {c.casefold() for c in columns}), None)
        if available is None:
            raise ValueError('Cannot preserve hidden row identity')
        columns.insert(0, available)
    if without_rowid:
        order = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
    else:
        order = [columns[0]]
    names = ','.join(map(quote_name, columns))
    query = 'SELECT ' + names + ' FROM ' + quote_name(name)
    if order:
        query += ' ORDER BY ' + ','.join(map(quote_name, order))
    prefix = 'INSERT INTO ' + quote_name(name) + '(' + names + ') VALUES('
    for row in conn.execute(query):
        yield prefix + ','.join(_literal(v) for v in row) + ');'


def iter_sql(conn, sql_format=ITERDUMP, *, allow_stale_fts=False):
    """Yield SQL statements without trailing newlines; ordinary dumps stay unchanged."""
    schema = _schema(conn, sql_format, allow_stale_fts)
    if sql_format == ITERDUMP:
        yield from conn.iterdump()
        return
    yield 'BEGIN TRANSACTION;'
    yield 'PRAGMA user_version=' + str(conn.execute('PRAGMA user_version').fetchone()[0]) + ';'
    yield 'PRAGMA application_id=' + str(conn.execute('PRAGMA application_id').fetchone()[0]) + ';'
    tables = [r for r in schema if r[0] == 'table'
              and not r[1].startswith('sqlite_') and r[1] not in SHADOWS
              and r[1] != 'hot_tags_fts']
    for _, name, _, ddl in tables:
        yield ddl.rstrip(';') + ';'
        yield from _rows(conn, name, ddl)
    if any(r[1] == 'sqlite_sequence' for r in schema):
        yield 'DELETE FROM sqlite_sequence;'
        yield from _rows(conn, 'sqlite_sequence', 'CREATE TABLE sqlite_sequence(name,seq)')
    yield GALLERY_FTS_DDL + ';'
    yield "INSERT INTO hot_tags_fts(hot_tags_fts) VALUES('rebuild');"
    for kind, _, _, ddl in schema:
        if kind in {'index', 'trigger', 'view'}:
            yield ddl.rstrip(';') + ';'
    yield 'COMMIT;'


def summary(conn, sql_format=ITERDUMP, *, allow_stale_fts=False):
    digest = hashlib.sha256()
    size = 0
    for statement in iter_sql(conn, sql_format, allow_stale_fts=allow_stale_fts):
        data = (statement + '\n').encode('utf-8')
        digest.update(data)
        size += len(data)
    result = {'sql_format': sql_format, 'sql_sha256': digest.hexdigest(),
              'sql_bytes': size, 'tables': table_counts(conn, sql_format, allow_stale_fts=allow_stale_fts)}
    if sql_format == GALLERY_FTS5:
        result['fts_source_consistent'] = _check_fts_content_integrity(conn)
        result['fts_restore_policy'] = 'rebuild_from_preserved_content'
    return result


def _library_json(text, context):
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        raise ValueError('Prompt library store has invalid JSON in ' + context)


def library_store_summary(conn):
    """Validate the prompt-library SQLite contract and summarise it.

    Capture records the summary next to the logical SQL dump and restore compares it
    against the rebuilt database, so a dump that silently loses rows, order or the
    revision cannot be restored as if it were current. Raises ``ValueError`` for a
    schema that is missing tables/columns, carries another schema version or breaks
    the order/reference invariants.
    """
    tables = {row[0] for row in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    missing = [name for name in LIBRARY_STORE_TABLES if name not in tables]
    if missing:
        raise ValueError('Prompt library store is missing tables: ' + ', '.join(missing))
    columns = {}
    for name, required in LIBRARY_STORE_TABLES.items():
        present = {row[1] for row in conn.execute('PRAGMA table_info(' + quote_name(name) + ')')}
        missing_columns = [column for column in required if column not in present]
        if missing_columns:
            raise ValueError('Prompt library table %s is missing columns: %s'
                             % (name, ', '.join(missing_columns)))
        columns[name] = sorted(present)
    meta = {str(key): value for key, value in conn.execute('SELECT key, value FROM library_meta')}
    schema_version = _library_json(meta[LIBRARY_STORE_META_SCHEMA],
                                   'library_meta.' + LIBRARY_STORE_META_SCHEMA) \
        if LIBRARY_STORE_META_SCHEMA in meta else None
    if schema_version not in LIBRARY_SCHEMA_VERSIONS:
        raise ValueError('Unsupported prompt library schema version: %r' % (schema_version,))
    if 'last_modified' not in meta:
        raise ValueError('Prompt library store is missing library_meta.last_modified')
    revision = _library_json(meta['last_modified'], 'library_meta.last_modified')
    if not isinstance(revision, str) or not revision:
        raise ValueError('Prompt library last_modified is not a non-empty string')
    category_rows = conn.execute('SELECT id, position, payload FROM categories').fetchall()
    category_ids = []
    category_positions = []
    for category_id, position, payload in category_rows:
        if not isinstance(category_id, str) or not category_id:
            raise ValueError('Prompt library category id is invalid')
        if not isinstance(position, int):
            raise ValueError('Prompt library category position is invalid')
        if not isinstance(_library_json(payload, 'categories.payload'), dict):
            raise ValueError('Prompt library category payload is not an object')
        category_ids.append(category_id)
        category_positions.append(position)
    if len(set(category_ids)) != len(category_ids):
        raise ValueError('Prompt library category ids are not unique')
    if len(set(category_positions)) != len(category_positions):
        raise ValueError('Prompt library category positions are not unique')
    category_set = set(category_ids)
    prompt_category = {}
    for prompt_id, category_id, payload in conn.execute(
            'SELECT id, category_id, payload FROM prompts'):
        if not isinstance(prompt_id, str) or not prompt_id:
            raise ValueError('Prompt library prompt id is invalid')
        if category_id not in category_set:
            raise ValueError('Prompt library prompt %r references an unknown category' % prompt_id)
        prompt = _library_json(payload, 'prompts.payload')
        if not isinstance(prompt, dict) or str(prompt.get('id') or '') != prompt_id:
            raise ValueError('Prompt library prompt payload does not match its row id: %r' % prompt_id)
        prompt_category[prompt_id] = category_id
    order_rows = conn.execute('SELECT category_id, order_json FROM category_orders').fetchall()
    ordered_categories = [category_id for category_id, _ in order_rows]
    if len(set(ordered_categories)) != len(ordered_categories):
        raise ValueError('Prompt library category order rows are not unique')
    if set(ordered_categories) != category_set:
        raise ValueError('Prompt library category order rows do not match categories')
    covered = {}
    for category_id, raw_order in order_rows:
        order = _library_json(raw_order, 'category_orders.order_json')
        if not isinstance(order, list) or any(not isinstance(value, str) or not value for value in order):
            raise ValueError('Prompt library category order is not a string list')
        if len(set(order)) != len(order):
            raise ValueError('Prompt library category order has duplicate prompt ids')
        for prompt_id in order:
            if prompt_category.get(prompt_id) != category_id:
                raise ValueError('Prompt library order references a prompt of another category: %r' % prompt_id)
            if prompt_id in covered:
                raise ValueError('Prompt library prompt is listed more than once: %r' % prompt_id)
            covered[prompt_id] = category_id
    if set(covered) != set(prompt_category):
        raise ValueError('Prompt library prompts are not all covered by category_orders')
    if conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('Prompt library foreign key check failed')
    if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('Prompt library SQLite integrity check failed')
    top_level_order = _library_json(meta[LIBRARY_STORE_META_TOP_LEVEL_ORDER],
                                    'library_meta.' + LIBRARY_STORE_META_TOP_LEVEL_ORDER) \
        if LIBRARY_STORE_META_TOP_LEVEL_ORDER in meta else []
    if not isinstance(top_level_order, list) or any(not isinstance(value, str) for value in top_level_order):
        raise ValueError('Prompt library top-level key order is invalid')
    return {
        'profile': LIBRARY_STORE_PROFILE,
        'schema_version': schema_version,
        'counts': {name: conn.execute('SELECT count(*) FROM ' + quote_name(name)).fetchone()[0]
                   for name in LIBRARY_STORE_TABLES},
        'prompt_count': len(prompt_category),
        'category_count': len(category_rows),
        'last_modified': revision,
        'top_level_order': top_level_order,
        'columns': columns,
        'order_covers_all_prompts': True,
        'foreign_key_violations': 0,
    }


def restore_sql(conn, lines, sql_format=ITERDUMP):
    """Restore into a new empty connection; reject unreviewed virtual schemas."""
    if sql_format not in FORMATS:
        raise ValueError('Unsupported library SQL format')
    if conn.in_transaction or conn.execute('SELECT 1 FROM sqlite_master LIMIT 1').fetchone():
        raise ValueError('SQL restore requires an empty database')
    builtins = {str(r[0]).casefold() for r in conn.execute('PRAGMA function_list') if r[1]}
    def authorize(action, arg1, arg2, database, trigger):
        if action in {sqlite3.SQLITE_ATTACH, sqlite3.SQLITE_DETACH}:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_PRAGMA:
            name = str(arg1).casefold()
            if name not in {'user_version', 'application_id', 'data_version', 'page_size'}:
                return sqlite3.SQLITE_DENY
            if name in {'data_version', 'page_size'} and arg2 is not None:
                return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_FUNCTION:
            name = str(arg2).casefold()
            if name not in builtins or name in {'load_extension', 'readfile', 'writefile', 'edit', 'fts3_tokenizer'}:
                return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_CREATE_VTABLE and (sql_format != GALLERY_FTS5 or arg1 != 'hot_tags_fts' or arg2 != 'fts5'):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK
    conn.set_authorizer(authorize)
    statement = ''
    try:
        for line in lines:
            statement += line
            if not sqlite3.complete_statement(statement):
                continue
            tokens = _tokens(statement)
            if not tokens or tokens[0] not in {'begin', 'commit', 'create', 'insert', 'delete', 'pragma'}:
                raise ValueError('Operation is not part of a library SQL dump')
            if tokens[0] == 'delete' and (len(tokens) < 3 or tokens[1] != 'from' or _identifier(tokens[2]) != 'sqlite_sequence'):
                raise ValueError('Only the exported sequence counter may be cleared')
            if tokens[:3] == ['create', 'virtual', 'table']:
                if sql_format != GALLERY_FTS5 or _normalized(statement) != _normalized(GALLERY_FTS_DDL):
                    raise ValueError('Unreviewed virtual table schema')
            conn.execute(statement)
            statement = ''
        if statement.strip():
            raise ValueError('Incomplete SQL dump')
        conn.set_authorizer(None)
        _schema(conn, sql_format)
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Restored SQLite integrity check failed')
        if sql_format == GALLERY_FTS5:
            conn.execute("INSERT INTO hot_tags_fts(hot_tags_fts,rank) VALUES('integrity-check',1)")
            conn.commit()
        return summary(conn, sql_format)
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.set_authorizer(None)
