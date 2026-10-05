"""Stable, transactional access to the existing WeiLin Tag dictionary."""
from array import array
from contextlib import closing, contextmanager
from pathlib import Path
import json
import logging
import sqlite3
import threading
import time
import uuid

_SCHEMA_LOCK = threading.RLock()
logger = logging.getLogger("weilin.prompt_selector")
# A text search cannot use an index, so a cold filtered page scans the 289k-row dictionary.
# The pager asks for the same page again on every re-render (view switch, editor round trip,
# favourite toggle), so the *page's* row numbers are cached per revision: a repeat costs an
# indexed 100-row fetch instead of another full scan.  Only the requested slice is cached —
# caching the whole match list made common terms slower, the A/B is in phase4/ab_tag_page.py.
_PAGE_CACHE = {}
_PAGE_CACHE_LIMIT = 32
_PAGE_SLICE_LIMIT = 64
# The folder tree with its per-folder counts scans all 282k rows; the revision stamps it,
# so the panel's index request is served from here until the dictionary actually changes.
_CATEGORY_CACHE = {'revision': None, 'payload': None}

# 「标签 tags 串」分流（2026-09-15）：单行正文超过 6 个词记为一个串行；某个法典分组
# （子夹，或整个区域）里串行占比超过 30%，就整组搬到旁边的「标签 tags 串」里，
# 基础 Tag 只留真正的词条。判定只依赖 tag_tags.text，跟着 revision 自动失效重建。
# 2026-09-15 用户定稿：正文 ≥5 个词就算串行；分组里串行占比 >25% 整组算标签串。
STRING_WORD_MIN = 5
STRING_GROUP_RATIO = 0.25
STRING_GROUP_UUID = '__tag_strings__'
STRING_AREA_PREFIX = '__tag_strings_area__:'
STRING_LOOSE_UUID = '__tag_strings_loose__'
STRING_LOOSE_NAME = '其他长串（所属分组未整组迁移）'
# 派生表结构版本；改判定口径时 +1，下一次 prepare 会自动重建（一次性全表扫描）。
STRING_FLAGS_VERSION = 4
# 2026-09-15：这些分组已经以分类形态并入「提示词片段」（见 prompt_selector 的
# `_tag_string_categories`），tag 侧不再单列这个桶；要临时回看把它设成 True 即可。
SHOW_STRING_BUCKET = False
_STRING_CACHE = {'revision': None, 'layout': None, 'used': 0.0}
# 分类清单/分流判定本身很小（883 个子夹 + 533 个串组），但重算是整表一遍；
# 闲下来就丢掉，下一次访问从派生表读回来（毫秒级）。
_STRING_CACHE_IDLE_SECONDS = 600.0


def _category_lock():
    """Lazy so partial-source harnesses that drop module-level calls still work."""
    lock = globals().get('_CATEGORY_LOCK')
    if lock is None:
        lock = threading.RLock()
        globals()['_CATEGORY_LOCK'] = lock
    return lock


class TagConflict(ValueError):
    def __init__(self, revision):
        super().__init__('Tag 库已更新，请重新读取后再保存；当前输入保留。')
        self.revision = revision


class TagLibrary:
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError('Tag 数据库不存在')
        self.prepare()

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def prepare(self):
        with _SCHEMA_LOCK, self.connection() as conn:
            ready = conn.execute("SELECT 1 FROM sqlite_master WHERE name='workbench_tag_revision'").fetchone()
            members_ready = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='workbench_tag_folder_members'").fetchone()
            text_ready = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='workbench_tag_text_revision'").fetchone()
            flags_table = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name='workbench_tag_string_flags'").fetchone()
            meta = conn.execute(
                "SELECT version FROM workbench_tag_flags_meta WHERE id=1").fetchone() \
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name='workbench_tag_flags_meta'").fetchone() \
                else None
            flags_ready = bool(flags_table) and meta is not None and meta[0] == STRING_FLAGS_VERSION
            if ready and members_ready and text_ready and flags_ready:
                return
            if not ready:
                backup = self.path.with_suffix(self.path.suffix + '.before-workbench')
                if not backup.exists():
                    with closing(sqlite3.connect(backup)) as target:
                        conn.backup(target)
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('CREATE TABLE IF NOT EXISTS workbench_tag_revision (id INTEGER PRIMARY KEY, value INTEGER NOT NULL)')
                conn.execute('INSERT OR IGNORE INTO workbench_tag_revision VALUES (1, 0)')
                conn.execute('CREATE TABLE IF NOT EXISTS workbench_tag_meta (tag_uuid TEXT PRIMARY KEY, data TEXT NOT NULL)')
                for table in ('tag_groups', 'tag_subgroups', 'tag_tags', 'workbench_tag_meta'):
                    for event in ('INSERT', 'UPDATE', 'DELETE'):
                        conn.execute(f'''CREATE TRIGGER IF NOT EXISTS workbench_{table}_{event.lower()}
                            AFTER {event} ON {table} BEGIN
                            UPDATE workbench_tag_revision SET value=value+1 WHERE id=1; END''')
                conn.execute('CREATE INDEX IF NOT EXISTS workbench_tag_identity ON tag_tags(t_uuid)')
                self._prepare_members(conn, members_ready)
                self._prepare_text_revision(conn, text_ready)
                self._prepare_string_flags(conn, flags_ready)

    @staticmethod
    def _prepare_string_flags(conn, flags_ready):
        """Per-row 「是不是串行」标记，触发器随行维护。

        以前每打开一次资料库、或每改一次 tag，都要把 28.9 万行正文整表扫一遍才能算出分类；
        现在只在这一张派生表上做聚合（883 行），改动时由触发器只更新被改的那一行。

        `suspect` 只标"可能因为空段而改变判定"的行：词数永远 ≤ 逗号数+1，所以
        ①逗号数没到线的行一定不是串；②逗号数远高于线（> 线+6）的行一定是串，
        除非正文里有 3 个以上连续逗号（那种才可能一次吃掉很多"词"）。
        这样需要逐词复核的行从 22 万降到四千上下。
        """
        commas = ("(length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),',',''))) + "
                  "(length(COALESCE(NEW.text,''))-length(replace(COALESCE(NEW.text,''),'，','')))")
        normalized = ("replace(replace(replace(replace(COALESCE(NEW.text,''),'，',','),' ',''),"
                      "char(9),''),char(10),'')")
        empty_segment = (f"(instr({normalized}, ',,') > 0 OR substr({normalized}, 1, 1) = ',' "
                         f"OR substr({normalized}, -1, 1) = ',')")
        suspect = (f"({commas} >= {STRING_WORD_MIN - 1} AND {empty_segment} AND "
                   f"({commas} <= {STRING_WORD_MIN + 6} OR instr({normalized}, ',,,') > 0))")
        conn.execute('CREATE TABLE IF NOT EXISTS workbench_tag_flags_meta '
                     '(id INTEGER PRIMARY KEY, version INTEGER NOT NULL)')
        version = conn.execute('SELECT version FROM workbench_tag_flags_meta WHERE id=1').fetchone()
        if version is not None and version[0] == STRING_FLAGS_VERSION and flags_ready:
            return
        conn.execute('DROP TABLE IF EXISTS workbench_tag_string_flags')
        for name in ('insert', 'update', 'delete'):
            conn.execute(f'DROP TRIGGER IF EXISTS workbench_tag_string_flags_{name}')
        conn.execute('''CREATE TABLE IF NOT EXISTS workbench_tag_string_flags (
            tag_uuid TEXT PRIMARY KEY, g_uuid TEXT NOT NULL DEFAULT '',
            commas INTEGER NOT NULL DEFAULT 0, suspect INTEGER NOT NULL DEFAULT 0,
            words INTEGER NOT NULL DEFAULT 0)''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tag_string_flags_group '
                     'ON workbench_tag_string_flags(g_uuid)')
        logger.info("[Workbench] 正在建立 tags 串行标记表（一次性全表扫描）…")
        text_commas = ("(length(COALESCE(text,''))-length(replace(COALESCE(text,''),',',''))) + "
                       "(length(COALESCE(text,''))-length(replace(COALESCE(text,''),'，','')))")
        text_empty = ("(instr(replace(replace(replace(replace(COALESCE(text,''),'，',','),' ',''),"
                      "char(9),''),char(10),''), ',,') > 0 "
                      "OR substr(replace(replace(replace(replace(COALESCE(text,''),'，',','),' ',''),"
                      "char(9),''),char(10),''),1,1) = ',' "
                      "OR substr(replace(replace(replace(replace(COALESCE(text,''),'，',','),' ',''),"
                      "char(9),''),char(10),''),-1,1) = ',')")
        text_norm = ("replace(replace(replace(replace(COALESCE(text,''),'，',','),' ',''),"
                     "char(9),''),char(10),'')")
        text_commas = ("(length(COALESCE(text,''))-length(replace(COALESCE(text,''),',',''))) + "
                       "(length(COALESCE(text,''))-length(replace(COALESCE(text,''),'，','')))")
        text_empty = ("(instr(replace(replace(replace(replace(COALESCE(text,''),'，',','),' ',''),"
                      "char(9),''),char(10),''), ',,') > 0 "
                      "OR substr(replace(replace(replace(replace(COALESCE(text,''),'，',','),' ',''),"
                      "char(9),''),char(10),''),1,1) = ',' "
                      "OR substr(replace(replace(replace(replace(COALESCE(text,''),'，',','),' ',''),"
                      "char(9),''),char(10),''),-1,1) = ',')")
        text_norm = ("replace(replace(replace(replace(COALESCE(text,''),'，',','),' ',''),"
                     "char(9),''),char(10),'')")
        conn.execute('INSERT OR REPLACE INTO workbench_tag_string_flags '
                     '(tag_uuid, g_uuid, commas, suspect, words) '
                     f"SELECT t_uuid, COALESCE(g_uuid,''), {text_commas}, "
                     f"({text_commas} >= {STRING_WORD_MIN - 1} AND {text_empty} AND "
                     f"({text_commas} <= {STRING_WORD_MIN + 6} OR instr({text_norm}, ',,,') > 0)), "
                     "0 FROM tag_tags")
        # 精确词数只能逐行数（空段不算词），一次 Python 扫描把它写准；
        # 之后每条写入都会由 apply() 立刻补成精确值。
        fixup = []
        for row in conn.execute('SELECT tag_uuid, g_uuid, commas, suspect FROM workbench_tag_string_flags '
                                'WHERE suspect = 1'):
            text = conn.execute('SELECT text FROM tag_tags WHERE t_uuid=?', (row['tag_uuid'],)).fetchone()
            fixup.append((TagLibrary._exact_words(text['text'] if text else ''), row['tag_uuid']))
        conn.executemany('UPDATE workbench_tag_string_flags SET words=? WHERE tag_uuid=?', fixup)
        conn.execute('UPDATE workbench_tag_string_flags SET words = commas + 1 WHERE suspect = 0')
        conn.execute('INSERT OR REPLACE INTO workbench_tag_flags_meta VALUES (1, ?)', (STRING_FLAGS_VERSION,))
        for event, source in (('INSERT', 'NEW'), ('UPDATE', 'NEW'), ('DELETE', 'OLD')):
            if event == 'DELETE':
                body = 'DELETE FROM workbench_tag_string_flags WHERE tag_uuid = OLD.t_uuid;'
            else:
                body = (f'INSERT OR REPLACE INTO workbench_tag_string_flags '
                        f'(tag_uuid, g_uuid, commas, suspect, words) '
                        f"VALUES ({source}.t_uuid, COALESCE({source}.g_uuid,''), {commas}, {suspect}, "
                        f'{commas} + 1);')
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS workbench_tag_string_flags_{event.lower()}
                AFTER {event} ON tag_tags BEGIN {body} END''')
    @staticmethod
    def _prepare_text_revision(conn, text_ready):
        """A separate counter for writes that can change the 标签串 split.

        The split reads the whole dictionary (~0.4 s), so keying its cache on the global
        revision would make every favourite/note toggle pay it again. Only tag_tags text
        and folder changes bump this counter.
        """
        conn.execute('CREATE TABLE IF NOT EXISTS workbench_tag_text_revision '
                     '(id INTEGER PRIMARY KEY, value INTEGER NOT NULL)')
        conn.execute('INSERT OR IGNORE INTO workbench_tag_text_revision VALUES (1, 0)')
        if not text_ready:
            conn.execute('UPDATE workbench_tag_text_revision SET value=value+1 WHERE id=1')
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS workbench_tag_text_{event.lower()}
                AFTER {event} ON tag_tags BEGIN
                UPDATE workbench_tag_text_revision SET value=value+1 WHERE id=1; END''')
        # 子夹改名/移动也会影响分流（分类名与所属区域），一并计入这一版号。
        for event in ('INSERT', 'UPDATE', 'DELETE'):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS workbench_tag_text_subgroup_{event.lower()}
                AFTER {event} ON tag_subgroups BEGIN
                UPDATE workbench_tag_text_revision SET value=value+1 WHERE id=1; END''')

    @staticmethod
    def _prepare_members(conn, members_ready):
        """Derived folder membership so area filters stop JSON-scanning every tag row.

        `workbench_tag_meta.data.folder_ids` stays the source of truth; the table is
        rebuilt from it once and kept in sync by triggers on every metadata write.
        """
        conn.execute('''CREATE TABLE IF NOT EXISTS workbench_tag_folder_members (
            tag_uuid TEXT NOT NULL, g_uuid TEXT NOT NULL, PRIMARY KEY (tag_uuid, g_uuid))''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tag_folder_members_g_uuid '
                     'ON workbench_tag_folder_members(g_uuid)')
        if not members_ready:
            conn.execute('INSERT OR IGNORE INTO workbench_tag_folder_members (tag_uuid, g_uuid) '
                         'SELECT tag_uuid, value FROM workbench_tag_meta, '
                         "json_each(json_extract(workbench_tag_meta.data,'$.folder_ids'))")
        for event, source in (('insert', 'NEW'), ('update', 'NEW'), ('delete', 'OLD')):
            conn.execute(f'''CREATE TRIGGER IF NOT EXISTS workbench_tag_members_{event}
                AFTER {event.upper()} ON workbench_tag_meta BEGIN
                DELETE FROM workbench_tag_folder_members WHERE tag_uuid = {source}.tag_uuid;
                {'' if event == 'delete' else
                 "INSERT OR IGNORE INTO workbench_tag_folder_members (tag_uuid, g_uuid) "
                 "SELECT " + source + ".tag_uuid, value FROM json_each(json_extract(" + source + ".data,'$.folder_ids'));"}
                END''')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_tag_meta_favorite '
                     "ON workbench_tag_meta(json_extract(data,'$.favorite'))")

    @staticmethod
    def revision_of(conn):
        return 'tags-v1:' + str(conn.execute('SELECT value FROM workbench_tag_revision WHERE id=1').fetchone()[0])

    def revision(self):
        with self.connection() as conn:
            return self.revision_of(conn)

    @staticmethod
    def tag_id(value):
        return str(value or '').removeprefix('tag:')

    @staticmethod
    def require_text(value, label):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f'请填写{label}')
        return value

    @staticmethod
    def find(conn, table, identity, value):
        row = conn.execute(f'SELECT * FROM {table} WHERE {identity}=?', (value,)).fetchone()
        if row is None:
            raise KeyError('资料或分类已不存在，请刷新列表')
        return row

    def categories(self):
        with self.connection() as conn:
            conn.execute('BEGIN')
            revision = self.revision_of(conn)
            with _category_lock():
                if _CATEGORY_CACHE['payload'] is not None and _CATEGORY_CACHE['revision'] == revision:
                    return _CATEGORY_CACHE['payload']
                groups = [dict(row) for row in conn.execute('SELECT * FROM tag_groups ORDER BY create_time,id_index')]
                children = [dict(row) for row in conn.execute('SELECT * FROM tag_subgroups ORDER BY create_time,id_index')]
                counts = {row[0]: row[1] for row in conn.execute('SELECT g_uuid,count(*) FROM tag_tags GROUP BY g_uuid')}
                member_counts = {row[0]: row[1] for row in conn.execute(
                    'SELECT g_uuid,count(*) FROM workbench_tag_folder_members GROUP BY g_uuid')}
                layout = self.string_layout(conn, self.text_revision_of(conn))
                for group in groups:
                    group['groups'] = [{**row, 'count': counts.get(row['g_uuid'], 0),
                                        'member_count': member_counts.get(row['g_uuid'], 0)}
                                       for row in children if row['p_uuid'] == group['p_uuid']]
                split = self._apply_string_split(groups, layout)
                payload = {'groups': groups, 'total': sum(counts.values()), 'revision': revision}
                payload['string_group'] = STRING_GROUP_UUID
                payload['string_rules'] = {'word_min': STRING_WORD_MIN, 'ratio_limit': STRING_GROUP_RATIO}
                payload['string_moved'] = split
                _CATEGORY_CACHE['revision'] = revision
                _CATEGORY_CACHE['payload'] = payload
                return payload

    @staticmethod
    def _comma_count(column='t.text'):
        """逗号个数；对没有空段的正文（绝大多数）就等于词数减一。"""
        return (f"(length({column})-length(replace({column},',',''))) + "
                f"(length({column})-length(replace({column},'，','')))")

    @staticmethod
    def text_revision_of(conn):
        """只在 tag_tags 的正文/归类变化时自增，收藏、备注一类的写入不牵连它。"""
        row = conn.execute('SELECT value FROM workbench_tag_text_revision WHERE id=1').fetchone()
        return 'tags-text-v1:' + str(row[0] if row else 0)

    @staticmethod
    def _word_over_limit(text, minimum=STRING_WORD_MIN):
        """正文是否达到 ``minimum`` 个词（空段不算词）；数够就停，长串不用数完。"""
        count = 0
        for part in str(text or '').replace('，', ',').split(','):
            if part.strip():
                count += 1
                if count >= minimum:
                    return True
        return False

    @staticmethod
    def _exact_words(text):
        """正文的精确词数（空段不算词）。"""
        return sum(1 for part in str(text or '').replace('，', ',').split(',') if part.strip())

    @classmethod
    def refresh_string_flags(cls, conn, tag_uuid):
        """把一条 tag 的词数标记写成精确值（所有 Python 写路径改完正文后调用）。"""
        row = conn.execute('SELECT COALESCE(g_uuid,\'\') AS g_uuid, text FROM tag_tags WHERE t_uuid=?',
                           (tag_uuid,)).fetchone()
        if row is None:
            conn.execute('DELETE FROM workbench_tag_string_flags WHERE tag_uuid=?', (tag_uuid,))
            return
        text = str(row['text'] or '').replace('，', ',')
        conn.execute('INSERT OR REPLACE INTO workbench_tag_string_flags '
                     '(tag_uuid, g_uuid, commas, suspect, words) VALUES (?,?,?,?,?)',
                     (tag_uuid, row['g_uuid'], text.count(','), 0, cls._exact_words(text)))

    def string_layout(self, conn, revision=None):
        """每个法典分组的行数与「片段行」数（词数 ≥ STRING_WORD_MIN 的行）。

        2026-09-16 定稿：分流是**逐行**的 —— 1–4 个词归基础 Tag，≥5 个词归片段。
        这里只汇总每个分组的两个数，供分类清单使用；分页过滤直接用派生表的 `words`。
        缓存键是"正文/分组版本"，空闲会自动释放。
        """
        # 缓存键统一用"正文/分组版本"，避免调用方传进来的是全局 revision 导致反复重算。
        revision = self.text_revision_of(conn)
        cached = _STRING_CACHE.get('layout')
        if cached is not None:
            if _STRING_CACHE.get('revision') == revision \
                    and time.monotonic() - _STRING_CACHE.get('used', 0.0) < _STRING_CACHE_IDLE_SECONDS:
                _STRING_CACHE['used'] = time.monotonic()
                return cached
            release_string_caches()
        folder_names, folder_area = {}, {}
        for row in conn.execute('SELECT g_uuid, name, p_uuid FROM tag_subgroups'):
            folder_names[row['g_uuid']] = row['name']
            folder_area[row['g_uuid']] = row['p_uuid'] or ''
        area_names = {row['p_uuid']: row['name'] for row in conn.execute('SELECT p_uuid, name FROM tag_groups')}
        folders = {}
        for row in conn.execute(
                'SELECT g_uuid, count(*) AS total, sum(CASE WHEN words >= ? THEN 1 ELSE 0 END) AS strings '
                'FROM workbench_tag_string_flags GROUP BY g_uuid', (STRING_WORD_MIN,)):
            key = row['g_uuid'] or ''
            area_uuid = folder_area.get(key, '')
            folders[key] = {'name': folder_names.get(key) or '未分组', 'area_uuid': area_uuid,
                            'area_name': area_names.get(area_uuid) or '未分区',
                            'rows': row['total'], 'strings': row['strings'] or 0}
        if not folders:
            # 派生表还没建好（例如首次迁移中）：退回直接扫全库。
            is_string_row = self._word_over_limit
            for g_uuid, text in conn.execute("SELECT COALESCE(g_uuid,'') AS g_uuid, text FROM tag_tags"):
                key = g_uuid or ''
                record = folders.get(key)
                if record is None:
                    area_uuid = folder_area.get(key, '')
                    record = folders[key] = {'name': folder_names.get(key) or '未分组',
                                             'area_uuid': area_uuid,
                                             'area_name': area_names.get(area_uuid) or '未分区',
                                             'rows': 0, 'strings': 0}
                record['rows'] += 1
                if is_string_row(text):
                    record['strings'] += 1
        areas = {}
        for folder in folders.values():
            area = areas.setdefault(folder['area_uuid'],
                                    {'name': folder['area_name'], 'rows': 0, 'strings': 0})
            area['rows'] += folder['rows']
            area['strings'] += folder['strings']

        def group_over_limit(record):
            return bool(record['rows']) and record['strings'] / record['rows'] > STRING_GROUP_RATIO

        # 判定单位 = 法典最小组（子夹）：组内片段行占比 > STRING_GROUP_RATIO 整组归片段，
        # 否则整组留基础 Tag —— 即使组里混了几条 5 个词以上的行，也不把组打散。
        string_folders = {uuid_value for uuid_value, record in folders.items() if group_over_limit(record)}
        kept = sorted(set(folders) - string_folders)
        layout = {'folders': folders, 'areas': areas,
                  'string_folders': string_folders, 'kept': kept,
                  'string_rows': sum(folders[key]['rows'] for key in string_folders)}
        _STRING_CACHE['revision'] = revision
        _STRING_CACHE['layout'] = layout
        _STRING_CACHE['used'] = time.monotonic()
        return layout

    @classmethod
    def _apply_string_split(cls, groups, layout):
        """把整组归片段的分组从基础 Tag 目录里摘掉，并修正留存分组的计数。

        2026-09-16 定稿：判定单位是法典最小组（子夹），组内 ≥5 词行占比 >25% 整组归片段，
        否则整组留基础 Tag —— 组内不混拆，所以留存分组的计数就是该组全部行。
        """
        folders = layout['folders']
        moved = layout['string_folders']
        emptied = set()
        for group in groups:
            kept_rows = []
            for row in group.get('groups', []):
                if row['g_uuid'] in moved:
                    emptied.add(group['p_uuid'])
                    continue
                record = folders.get(row['g_uuid'])
                if record:
                    row['count'] = record['rows']
                kept_rows.append(row)
            group['groups'] = kept_rows
        # 整区都搬走的区域不再出现在基础 Tag；从未建过子夹的空区域保留（仍要能管理）。
        groups[:] = [group for group in groups if group['groups'] or group['p_uuid'] not in emptied]
        return {'rows': sum(folders[key]['rows'] for key in moved), 'groups': len(moved),
                'visible': SHOW_STRING_BUCKET}

    @staticmethod
    def entry(row):
        item = dict(row)
        metadata = json.loads(item.pop('metadata') or '{}')
        item.update(resource_id='tag:' + item['t_uuid'], kind='tag', favorite=bool(metadata.get('favorite')),
                    notes=metadata.get('notes', ''), collection_ids=metadata.get('collection_ids', []),
                    # 自己绑定的预览图文件名（资源库与 Tag 面板共用同一份存放位置）。
                    preview=metadata.get('preview', ''),
                    # Extra folders this entry is also filed under (multi-area membership).
                    folder_ids=metadata.get('folder_ids', []) or [],
                    themes=metadata.get('themes', []) or [])
        return item

    SELECT = '''SELECT t.*, s.name AS subgroup_name, s.p_uuid, g.name AS group_name, m.data AS metadata
        FROM tag_tags t LEFT JOIN tag_subgroups s ON s.g_uuid=t.g_uuid
        LEFT JOIN tag_groups g ON g.p_uuid=s.p_uuid
        LEFT JOIN workbench_tag_meta m ON m.tag_uuid=t.t_uuid'''

    def page(self, query='', subgroup='', group='', offset=0, limit=100, favorite=False, collection='',
             known_collections=(), shape='', scope='', theme=''):
        """``scope`` selects which side of the 标签串 split to read.

        ``tags`` = the base-tag side (kept folders, at most 6 words per row);
        ``strings`` = everything the folder rule moved to 「标签 tags 串」.
        Empty keeps the historical behaviour for callers that do not ask for the split.
        """
        offset, limit = max(0, int(offset)), max(1, min(500, int(limit)))
        query = str(query or '').strip()
        if not isinstance(theme, str) or len(theme) > 128 or theme != theme.strip():
            raise ValueError('主题筛选必须是完整的主题名称')
        forms = [query]
        alternate = query.replace('_', ' ') if '_' in query else query.replace(' ', '_')
        if alternate != query:
            forms.append(alternate)
        clauses, args = [], []
        # 正文形状：基础 tag 是单个词，其它是所长法典里的 tags 串（属提示词片段）。
        if shape:
            commas = ("(length(t.text)-length(replace(t.text,',',''))) + "
                      "(length(t.text)-length(replace(t.text,'，','')))")
            if shape == 'atomic':
                clauses.append("instr(t.text, ',')=0 AND instr(t.text,'，')=0")
            elif shape == 'group':
                clauses.append(f'{commas} BETWEEN 1 AND 2')
            elif shape == 'string':
                clauses.append(f'{commas} >= 3')
            else:
                raise ValueError('Unknown tag shape filter')
        if query:
            escape = lambda value: value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            text_matches = ["t.text LIKE ? ESCAPE '\\'" for _ in forms]
            clauses.append('(' + ' OR '.join([*text_matches, "t.desc LIKE ? ESCAPE '\\'"]) + ')')
            args.extend(['%' + escape(value) + '%' for value in forms])
            args.append('%' + escape(query) + '%')
        if subgroup and not subgroup.startswith(STRING_AREA_PREFIX) and subgroup != STRING_LOOSE_UUID:
            # A composite entry stays in its primary folder and in every extra area it belongs to.
            clauses.append('(t.g_uuid=? OR t.t_uuid IN '
                           '(SELECT tag_uuid FROM workbench_tag_folder_members WHERE g_uuid=?))')
            args.extend([subgroup, subgroup])
        # The synthetic 「标签 tags 串」 bucket is not a real 法典区域; its rows come from
        # the scope clause plus whichever entry is selected inside it.
        if group and group != STRING_GROUP_UUID:
            # Both branches are expressed against t alone: an OR that reaches through the
            # folder join cannot use a tag_tags index and degrades to a full scan.
            clauses.append('t.t_uuid IN ('
                           'SELECT t_uuid FROM tag_tags WHERE g_uuid IN '
                           '(SELECT g_uuid FROM tag_subgroups WHERE p_uuid=?) '
                           'UNION SELECT tag_uuid FROM workbench_tag_folder_members WHERE g_uuid IN '
                           '(SELECT g_uuid FROM tag_subgroups WHERE p_uuid=?))')
            args.extend([group, group])
        if favorite:
            # Evaluated on the 66k metadata rows (indexed by expression) instead of once
            # per tag row.
            clauses.append("t.t_uuid IN (SELECT tag_uuid FROM workbench_tag_meta "
                           "WHERE json_extract(data,'$.favorite')=1)")
        if theme:
            clauses.append("t.t_uuid IN (SELECT tag_uuid FROM workbench_tag_meta WHERE EXISTS "
                           "(SELECT 1 FROM json_each(CASE WHEN json_type(data,'$.themes')='array' "
                           "THEN json_extract(data,'$.themes') ELSE '[]' END) WHERE value=?))")
            args.append(theme)
        if collection:
            if collection == 'default':
                placeholders = ','.join('?' for _ in known_collections) or 'NULL'
                clauses.append("(t.t_uuid IN (SELECT tag_uuid FROM workbench_tag_meta WHERE EXISTS "
                               "(SELECT 1 FROM json_each(json_extract(data,'$.collection_ids')) WHERE value='default')) "
                               "OR t.t_uuid NOT IN (SELECT tag_uuid FROM workbench_tag_meta WHERE EXISTS "
                               "(SELECT 1 FROM json_each(json_extract(data,'$.collection_ids')) "
                               'WHERE value IN (' + placeholders + '))))')
                args.extend(known_collections)
            else:
                clauses.append("t.t_uuid IN (SELECT tag_uuid FROM workbench_tag_meta WHERE EXISTS "
                               "(SELECT 1 FROM json_each(json_extract(data,'$.collection_ids')) WHERE value=?))")
                args.append(collection)
        # Every filter is expressed against tag_tags alone (folders/members/favourites via
        # subqueries), so the count never has to join the folder or metadata tables —
        # an unconditional join turned a 2.8 ms count into a 147 ms one.
        count_from = 'tag_tags t'
        with self.connection() as conn:
            conn.execute('BEGIN')
            revision = self.revision_of(conn)
            if scope or subgroup.startswith(STRING_AREA_PREFIX) or subgroup == STRING_LOOSE_UUID:
                # 分流按"法典最小组（子夹）"整组判定，所以这里用留存子夹名单过滤；
                # 派生表给出每组的精确词数统计（见 string_layout）。
                layout = self.string_layout(conn, self.text_revision_of(conn))
                kept = layout['kept']
                in_kept = (f"COALESCE(t.g_uuid,'') IN ({','.join('?' for _ in kept)})" if kept else '0')
                if subgroup.startswith(STRING_AREA_PREFIX):
                    clauses.append('t.t_uuid IN (SELECT t_uuid FROM tag_tags WHERE g_uuid IN '
                                   '(SELECT g_uuid FROM tag_subgroups WHERE p_uuid=?))')
                    args.append(subgroup[len(STRING_AREA_PREFIX):])
                elif subgroup == STRING_LOOSE_UUID:
                    # 不再从留存分组里剥散串（保持分组成整），这个入口留空。
                    clauses.append('0')
                if scope == 'strings':
                    clauses.append(f'NOT ({in_kept})')
                    args.extend(kept)
                elif scope == 'tags':
                    clauses.append(in_kept)
                    args.extend(kept)
                elif scope:
                    raise ValueError('Unknown tag scope filter')
            where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
            cache_key = (revision, query, subgroup, group, favorite, collection,
                         tuple(known_collections or ()), shape, scope, theme)
            cached = _PAGE_CACHE.get(cache_key)
            if cached is None:
                total = conn.execute('SELECT count(*) FROM ' + count_from + where, args).fetchone()[0]
                if len(_PAGE_CACHE) >= _PAGE_CACHE_LIMIT:
                    _PAGE_CACHE.clear()
                cached = (total, {})
                _PAGE_CACHE[cache_key] = cached
            else:
                total = cached[0]
            slices = cached[1]
            row_numbers = slices.get((offset, limit))
            if row_numbers is None:
                if query and all(ord(value[-1]) < 0x10ffff for value in forms):
                    exact_match = 't.text IN (' + ','.join('?' for _ in forms) + ')'
                    ranges = ['(t.text>=? AND t.text<?)' for _ in forms]
                    range_condition = '(' + ' OR '.join(ranges) + ')'
                    range_args = [bound for value in forms for bound in (value, value[:-1] + chr(ord(value[-1]) + 1))]
                    tiers = [
                        (exact_match, forms, 't.text,t.id_index'),
                        (range_condition + ' AND NOT ' + exact_match,
                         [*range_args, *forms], 't.text,t.id_index'),
                        ('NOT ' + range_condition, range_args, 't.create_time DESC,t.id_index'),
                    ]
                    exact = conn.execute('SELECT count(*) FROM ' + count_from + where + ' AND ' + tiers[0][0],
                                         [*args, *tiers[0][1]]).fetchone()[0]
                    prefix = conn.execute('SELECT count(*) FROM ' + count_from + where + ' AND ' + tiers[1][0],
                                          [*args, *tiers[1][1]]).fetchone()[0]
                    rows, skip = [], offset
                    for (condition, extra, order), count in zip(tiers, (exact, prefix, total - exact - prefix)):
                        if skip >= count:
                            skip -= count
                            continue
                        rows.extend(conn.execute(self.SELECT + where + ' AND ' + condition +
                                                 ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
                                                 [*args, *extra, limit - len(rows), skip]).fetchall())
                        skip = 0
                        if len(rows) >= limit:
                            break
                else:
                    rows = conn.execute(
                        self.SELECT + where + ' ORDER BY t.create_time DESC,t.id_index LIMIT ? OFFSET ?',
                        [*args, limit, offset]).fetchall()
                if len(slices) >= _PAGE_SLICE_LIMIT:
                    slices.clear()
                slices[(offset, limit)] = array('i', (row['id_index'] for row in rows))
            else:
                rows = []
                if len(row_numbers):
                    placeholders = ','.join('?' for _ in row_numbers)
                    fetched = conn.execute(
                        self.SELECT + f' WHERE t.id_index IN ({placeholders})', list(row_numbers)).fetchall()
                    by_number = {row['id_index']: row for row in fetched}
                    rows = [by_number[number] for number in row_numbers if number in by_number]
            items = [self.entry(row) for row in rows]
            if query:
                for item in items:
                    value = item['text'] or ''
                    item['match_reason'] = ('Tag 精确匹配' if value in forms else
                                            'Tag 前缀匹配' if any(value.startswith(term) for term in forms) else
                                            'Tag 文本命中' if any(term.casefold() in value.casefold() for term in forms)
                                            else '说明命中')
            return {'items': items, 'total': total, 'offset': offset,
                    'limit': limit, 'revision': self.revision_of(conn)}

    def get(self, identity):
        with self.connection() as conn:
            conn.execute('BEGIN')
            row = conn.execute(self.SELECT + ' WHERE t.t_uuid=?', (self.tag_id(identity),)).fetchone()
            if row is None:
                raise KeyError('Tag 已不存在')
            return {'item': self.entry(row), 'revision': self.revision_of(conn)}

    def export_bundle(self, identities=None):
        with self.connection() as conn:
            conn.execute('BEGIN')
            where, args = '', []
            if identities is not None:
                if not identities or len(identities) > 500:
                    raise ValueError('选中导出需要 1–500 条 Tag；完整库请使用导出全部')
                args = list(dict.fromkeys(self.tag_id(identity) for identity in identities))
                where = ' WHERE t.t_uuid IN (' + ','.join('?' for _ in args) + ')'
            rows = [self.entry(row) for row in conn.execute(self.SELECT + where, args)]
            if args and len(rows) != len(args):
                raise KeyError('部分所选 Tag 已不存在，请刷新后导出')
            return {'format': 'weilin-tags-v1', 'groups': [dict(row) for row in conn.execute('SELECT * FROM tag_groups')],
                    'subgroups': [dict(row) for row in conn.execute('SELECT * FROM tag_subgroups')],
                    'items': rows, 'revision': self.revision_of(conn)}

    def import_bundle(self, conn, bundle, overwrite):
        if not isinstance(bundle, dict) or bundle.get('format') != 'weilin-tags-v1':
            raise ValueError('请选择共享 Tag 管理导出的 JSON 文件')
        if not isinstance(bundle.get('items'), list) or len(bundle['items']) > 500000:
            raise ValueError('Tag 文件格式或数量无效')
        count = {'created': 0, 'updated': 0, 'unchanged': 0}
        for entity, table, key, collection, fields in (
            ('group', 'tag_groups', 'p_uuid', 'groups', ('name', 'color')),
            ('subgroup', 'tag_subgroups', 'g_uuid', 'subgroups', ('name', 'color', 'p_uuid')),
            ('tag', 'tag_tags', 't_uuid', 'items', ('text', 'desc', 'color', 'g_uuid')),
        ):
            rows = bundle.get(collection)
            if not isinstance(rows, list):
                raise ValueError('Tag 文件缺少分类或词条列表')
            identities = [row.get(key) for row in rows if isinstance(row, dict)]
            if len(identities) != len(rows) or not all(isinstance(value, str) and value for value in identities) or len(set(identities)) != len(identities):
                raise ValueError('Tag 文件的稳定 ID 缺失或重复')
            for row in rows:
                if entity == 'tag' and 'themes' in row:
                    self.validate_themes(row['themes'])
                old = conn.execute(f'SELECT * FROM {table} WHERE {key}=?', (row[key],)).fetchone()
                changed = bool(old and any(old[field] != row.get(field, '') for field in fields))
                if changed and not overwrite:
                    raise ValueError('相同 ID 的内容已有变化。未写入任何记录；请核对后明确选择覆盖已有 ID。')
                payload = {'entity': entity, 'operation': 'edit' if old else 'create', key: row[key],
                           **{field: row.get(field, '') for field in fields}}
                if not old and isinstance(row.get('create_time'), int):
                    payload['create_time'] = row['create_time']
                if entity == 'tag' and (not old or overwrite):
                    payload.update({field: row[field] for field in ('favorite', 'notes', 'collection_ids', 'themes') if field in row})
                metadata_changed = False
                if entity == 'tag' and old is not None and overwrite:
                    metadata_row = conn.execute('SELECT data FROM workbench_tag_meta WHERE tag_uuid=?', (row[key],)).fetchone()
                    metadata = json.loads(metadata_row[0]) if metadata_row else {}
                    defaults = {'favorite': False, 'notes': '', 'collection_ids': [], 'themes': []}
                    metadata_changed = any(field in row and metadata.get(field, default) != row[field] for field, default in defaults.items())
                self.apply(conn, payload)
                if entity == 'tag':
                    count['created' if old is None else 'updated' if changed or metadata_changed else 'unchanged'] += 1
        return count

    def update(self, payload, expected=None):
        if not isinstance(payload, dict):
            raise ValueError('Tag 操作格式无效')
        # A single body edit is mirrored to the shared library entry for the same concept
        # (see shared_sync); batch/import keep their own paths so a 500-row import does not
        # turn into 500 library writes.
        mirror = None
        with self.connection() as conn:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                revision = self.revision_of(conn)
                if expected is not None and expected.strip('"') != revision:
                    raise TagConflict(revision)
                operation = payload.get('operation')
                if operation == 'import':
                    result = self.import_bundle(conn, payload.get('bundle'), payload.get('overwrite') is True)
                elif operation == 'batch':
                    items = payload.get('items')
                    if not isinstance(items, list) or not 1 <= len(items) <= 500:
                        raise ValueError('每次批量操作需要 1–500 条记录')
                    result = [self.apply(conn, item) for item in items]
                else:
                    if payload.get('entity', 'tag') == 'tag' and operation in (None, 'edit') and 'text' in payload:
                        identity = self.tag_id(payload.get('resource_id') or payload.get('t_uuid'))
                        row = conn.execute('SELECT text FROM tag_tags WHERE t_uuid=?', (identity,)).fetchone()
                        if row is not None and row[0] != payload.get('text'):
                            mirror = (identity, row[0], payload.get('text'))
                    result = self.apply(conn, payload)
                outcome = {'success': True, 'result': result, 'revision': self.revision_of(conn)}
        if mirror is not None:
            try:
                from . import shared_sync
                sync = shared_sync.mirror_from_tag(*mirror)
                if sync is not None:
                    outcome['mirrored'] = sync
            except Exception as error:  # noqa: BLE001 - the Tag write is already committed
                logger.warning("Tag 正文同步到资源库失败: %s", error)
        return outcome

    def legacy_identity(self, entity, id_index):
        table, key = {'tag': ('tag_tags', 't_uuid'), 'group': ('tag_groups', 'p_uuid'),
                      'subgroup': ('tag_subgroups', 'g_uuid')}[entity]
        with self.connection() as conn:
            return self.find(conn, table, 'id_index', id_index)[key]

    def legacy_sql(self, statements):
        with self.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            for statement in statements:
                conn.execute(statement)

    def reorder(self, entity, identity, reference, position):
        table, key = {'tag': ('tag_tags', 't_uuid'), 'group': ('tag_groups', 'p_uuid'),
                      'subgroup': ('tag_subgroups', 'g_uuid')}[entity]
        if position not in ('before', 'after'):
            raise ValueError('排序位置无效')
        with self.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            row = self.find(conn, table, key, reference)
            self.find(conn, table, key, identity)
            delta = 1 if position == 'after' else -1
            if entity == 'tag':
                delta = -delta
            conn.execute(f'UPDATE {table} SET create_time=? WHERE {key}=?', (row['create_time'] + delta, identity))

    @staticmethod
    def validate_themes(themes):
        if (not isinstance(themes, list) or len(themes) > 64
                or any(not isinstance(value, str) or not value or len(value) > 128
                       or value != value.strip() for value in themes)
                or len(set(themes)) != len(themes)):
            raise ValueError('主题必须是最多64项、不重复且非空的名称列表，每项不超过128字符')

    def apply(self, conn, payload):
        if not isinstance(payload, dict):
            raise ValueError('Tag 操作格式无效')
        operation = payload.get('operation')
        entity = payload.get('entity', 'tag')
        if 'themes' in payload:
            self.validate_themes(payload['themes'])
            if entity != 'tag' or operation not in ('create', 'edit', 'metadata'):
                raise ValueError('此操作不支持修改主题')
        if entity in ('group', 'subgroup'):
            return self.apply_category(conn, payload)
        if entity != 'tag':
            raise ValueError('未知的 Tag 对象类型')
        identity = self.tag_id(payload.get('resource_id') or payload.get('t_uuid'))
        if operation != 'create' and not identity:
            raise ValueError('需要稳定的 Tag ID')
        for key in ('text', 'desc', 'color'):
            if key in payload and not isinstance(payload[key], str) and not (key != 'text' and payload[key] is None):
                raise ValueError('Tag 正文、描述和颜色必须为文本')
        if operation == 'create':
            identity = identity or str(uuid.uuid4())
            text = self.require_text(payload.get('text'), 'Tag 正文')
            parent = self.find(conn, 'tag_subgroups', 'g_uuid', payload.get('g_uuid'))
            old = conn.execute('SELECT * FROM tag_tags WHERE t_uuid=?', (identity,)).fetchone()
            if old:
                if (old['text'], old['desc'], old['color'], old['g_uuid']) != (text, payload.get('desc', ''), payload.get('color', ''), parent['g_uuid']):
                    raise ValueError('Tag ID 已存在，请重新加载')
                if 'themes' in payload:
                    metadata_row = conn.execute('SELECT data FROM workbench_tag_meta WHERE tag_uuid=?', (identity,)).fetchone()
                    metadata = json.loads(metadata_row[0]) if metadata_row else {}
                    if metadata.get('themes', []) != payload['themes']:
                        raise ValueError('Tag ID 已存在且主题不同，请重新读取后编辑')
                return {'resource_id': 'tag:' + identity}
            conn.execute('INSERT INTO tag_tags (subgroup_id,text,desc,color,create_time,t_uuid,g_uuid) VALUES (?,?,?,?,?,?,?)',
                         (parent['id_index'], text, payload.get('desc', ''), payload.get('color', ''), payload.get('create_time', time.time_ns()//1_000_000), identity, parent['g_uuid']))
            # 新建行也要有精确词数（触发器写的是上界）。
            self.refresh_string_flags(conn, identity)
        elif operation in ('edit', 'move', 'metadata'):
            old = self.find(conn, 'tag_tags', 't_uuid', identity)
            values = {key: old[key] for key in ('text', 'desc', 'color', 'subgroup_id', 'g_uuid')}
            if operation == 'edit':
                for key in ('text', 'desc', 'color'):
                    if key in payload:
                        values[key] = payload[key]
                self.require_text(values['text'], 'Tag 正文')
            if payload.get('g_uuid'):
                parent = self.find(conn, 'tag_subgroups', 'g_uuid', payload['g_uuid'])
                values.update(subgroup_id=parent['id_index'], g_uuid=parent['g_uuid'])
            if any(values[key] != old[key] for key in values):
                conn.execute('UPDATE tag_tags SET text=?,desc=?,color=?,subgroup_id=?,g_uuid=? WHERE t_uuid=?', [*values.values(), identity])
            # 正文/归属变了就立刻把这一行的精确词数写回派生表（触发器只给上界）。
            if values['text'] != old['text'] or values['g_uuid'] != old['g_uuid']:
                self.refresh_string_flags(conn, identity)
        elif operation == 'delete':
            conn.execute('DELETE FROM tag_tags WHERE t_uuid=?', (identity,))
            conn.execute('DELETE FROM workbench_tag_meta WHERE tag_uuid=?', (identity,))
            return {'resource_id': 'tag:' + identity, 'deleted': True}
        else:
            raise ValueError('未知的 Tag 操作')
        # preview 是"给这条 tag 绑定预览图"用的文件名；和收藏/备注一样存在 tag 元数据里。
        fields = {key: payload[key] for key in ('favorite', 'notes', 'collection_ids', 'preview', 'themes') if key in payload}
        if fields:
            if 'favorite' in fields and not isinstance(fields['favorite'], bool):
                raise ValueError('收藏状态必须为布尔值')
            if 'notes' in fields and not isinstance(fields['notes'], str):
                raise ValueError('备注必须为文本')
            if 'preview' in fields and fields['preview'] is not None and not isinstance(fields['preview'], str):
                raise ValueError('预览图名称必须为文本')
            if 'collection_ids' in fields and (not isinstance(fields['collection_ids'], list) or any(not isinstance(x, str) for x in fields['collection_ids'])):
                raise ValueError('收藏组格式无效')
            row = conn.execute('SELECT data FROM workbench_tag_meta WHERE tag_uuid=?', (identity,)).fetchone()
            data = json.loads(row[0]) if row else {}
            if any(data.get(key, [] if key == 'themes' else None) != value for key, value in fields.items()):
                # Retain ancestors/extra links when only personal metadata changes.
                # A real primary-folder move keeps its existing membership behavior.
                members = []
                if operation != 'create' and values['g_uuid'] == old['g_uuid']:
                    members = conn.execute('SELECT tag_uuid, g_uuid FROM workbench_tag_folder_members '
                                           'WHERE tag_uuid=?', (identity,)).fetchall()
                data.update(fields)
                conn.execute('INSERT INTO workbench_tag_meta VALUES (?,?) ON CONFLICT(tag_uuid) DO UPDATE SET data=excluded.data', (identity, json.dumps(data, ensure_ascii=False)))
                conn.executemany('INSERT OR IGNORE INTO workbench_tag_folder_members (tag_uuid, g_uuid) VALUES (?,?)', members)
        return {'resource_id': 'tag:' + identity}

    def apply_category(self, conn, payload):
        entity, operation = payload['entity'], payload.get('operation')
        table, key = ('tag_groups', 'p_uuid') if entity == 'group' else ('tag_subgroups', 'g_uuid')
        identity = payload.get(key) or (str(uuid.uuid4()) if operation == 'create' else None)
        if not identity:
            raise ValueError('需要稳定的分类 ID')
        if operation == 'create':
            name = self.require_text(payload.get('name'), '分类名称').strip()
            old = conn.execute(f'SELECT * FROM {table} WHERE {key}=?', (identity,)).fetchone()
            if old:
                if old['name'] != name:
                    raise ValueError('分类 ID 已存在')
                return {key: identity}
            values = {'name': name, 'color': payload.get('color', ''), 'create_time': payload.get('create_time', time.time_ns()//1_000_000), key: identity}
            if entity == 'subgroup':
                parent = self.find(conn, 'tag_groups', 'p_uuid', payload.get('p_uuid'))
                values.update(group_id=parent['id_index'], p_uuid=parent['p_uuid'])
            conn.execute(f'INSERT INTO {table} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})', list(values.values()))
        elif operation in ('edit', 'move'):
            old = self.find(conn, table, key, identity)
            values = {}
            for field in ('name', 'color'):
                if field in payload:
                    values[field] = self.require_text(payload[field], '分类名称').strip() if field == 'name' else payload[field]
            if entity == 'subgroup' and payload.get('p_uuid'):
                parent = self.find(conn, 'tag_groups', 'p_uuid', payload['p_uuid'])
                values.update(group_id=parent['id_index'], p_uuid=parent['p_uuid'])
            if values and any(old[k] != v for k, v in values.items()):
                conn.execute(f'UPDATE {table} SET '+','.join(f'{k}=?' for k in values)+f' WHERE {key}=?', [*values.values(), identity])
        elif operation == 'delete':
            if entity == 'group':
                count = conn.execute('SELECT count(*) FROM tag_subgroups WHERE p_uuid=?', (identity,)).fetchone()[0]
            else:
                count = conn.execute('SELECT count(*) FROM tag_tags WHERE g_uuid=?', (identity,)).fetchone()[0]
            if count and payload.get('delete_contents') is not True:
                raise ValueError('分类仍有成员，请先移动成员或明确删除其中的资料')
            if count:
                condition = 'g_uuid IN (SELECT g_uuid FROM tag_subgroups WHERE p_uuid=?)' if entity == 'group' else 'g_uuid=?'
                conn.execute('DELETE FROM workbench_tag_meta WHERE tag_uuid IN (SELECT t_uuid FROM tag_tags WHERE '+condition+')', (identity,))
                conn.execute('DELETE FROM tag_tags WHERE '+condition, (identity,))
                if entity == 'group':
                    conn.execute('DELETE FROM tag_subgroups WHERE p_uuid=?', (identity,))
            conn.execute(f'DELETE FROM {table} WHERE {key}=?', (identity,))
        else:
            raise ValueError('未知的分类操作')
        return {key: identity}


def release_string_caches():
    """Drop the derived 「串行」 caches (called when they go idle, or on demand)."""
    _STRING_CACHE['layout'] = None
    _STRING_CACHE['revision'] = None
    _STRING_CACHE['used'] = 0.0
