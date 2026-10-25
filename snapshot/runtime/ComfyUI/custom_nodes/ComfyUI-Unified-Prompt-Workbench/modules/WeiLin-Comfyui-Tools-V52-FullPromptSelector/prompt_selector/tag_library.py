"""Stable, transactional access to the existing WeiLin Tag dictionary."""
from array import array
from contextlib import closing, contextmanager
from pathlib import Path
import json
import logging
import os
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

# Tag 面板的首次筛选/搜索原本每次都要整表处理 29.8 万行：形状筛选逐行算逗号数表达式，
# 主题/收藏组在 9.9 万条 meta JSON 上逐行 json_each，搜索一次要跑 3 次 count + 最多 3 次
# 排序查询。这里改成“表达式索引 + 派生表 + 单遍排序”，一次性构建放在 server ready 之后的
# Tag warm 线程里：版本号记在 workbench_tag_read_meta，失败不写版本、下次 warm/请求自动
# 重试；未构建/构建失败/被禁用时 page() 仍走原 SQL（结果语义一致，只是慢）。
READ_INDEX_VERSION = 1
READ_INDEX_DISABLED_LOGGED = False
READ_SCOPE_INDEX = 'workbench_tag_read_scope'
READ_SHAPE_INDEX = 'workbench_tag_read_shape'
READ_THEME_TABLE = 'workbench_tag_themes'
READ_THEME_INDEX = 'workbench_tag_themes_value'
READ_COLLECTION_TABLE = 'workbench_tag_collections'
READ_COLLECTION_INDEX = 'workbench_tag_collections_value'
READ_META_TABLE = 'workbench_tag_read_meta'
# 查询与索引必须共用同一段表达式文本，否则 SQLite 不会选中表达式索引。
SHAPE_COMMAS = ("(length(t.text)-length(replace(t.text,',',''))) + "
                "(length(t.text)-length(replace(t.text,'，','')))")
SHAPE_COMMAS_RAW = ("(length(text)-length(replace(text,',',''))) + "
                    "(length(text)-length(replace(text,'，','')))")
SCOPE_FOLDER = "COALESCE(t.g_uuid,'')"
SCOPE_FOLDER_RAW = "COALESCE(g_uuid,'')"
_READ_INDEX_BUILDING = set()
_READ_INDEX_BUILDING_LOCK = threading.Lock()


def _log_read_index_disabled():
    global READ_INDEX_DISABLED_LOGGED
    if not READ_INDEX_DISABLED_LOGGED:
        READ_INDEX_DISABLED_LOGGED = True
        logger.info("[Workbench] Tag 读取索引已禁用 (UW_DISABLE_TAG_READ_INDEX=1)")


# 子串搜索/自动补全：LIKE '%term%' 用不上索引，一次只能全表扫 29.8 万行 / 9760 万字符
# （q=hair 约 185 ms、空结果约 340 ms）。这里把 lower(text)/lower(desc) 的 trigram FTS5
# 放进可随时删除重建的 PROMPT_STORE_DIR/cache/tag_search.v1.db（不往用户 tags 库塞
# ~288 MB 索引，避免拖慢 dao.py 的启动期 integrity_check），用户库只加一张很小的变更
# 日志表 + 3 个触发器；搜索前把日志增量回放进 cache。trigram 只覆盖 ≥3 字符查询，
# 1–2 字符/带过滤的查询仍走原 SQL。日志积压过多时直接重建 cache。
SEARCH_INDEX_VERSION = 1
SEARCH_INDEX_DISABLED_LOGGED = False
SEARCH_CACHE_TABLE = 'tag_search'
SEARCH_META_TABLE = 'search_meta'
SEARCH_JOURNAL_TABLE = 'workbench_tag_search_journal'
SEARCH_SCHEMA_TABLE = 'workbench_tag_search_meta'
SEARCH_TRIGGERS = ('workbench_tag_search_insert', 'workbench_tag_search_update', 'workbench_tag_search_delete')
SEARCH_MIN_QUERY = 3
SEARCH_REBUILD_PENDING = 5000
SEARCH_APPLY_BATCH = 500
# 同步/重建与内存顺序表的进程级状态（按 tags 库路径区分）。
_SEARCH_CACHE_FILE = None
_SEARCH_ORDER = {}
_SEARCH_BUILDING = set()
_SEARCH_BUILDING_LOCK = threading.Lock()
_SEARCH_ORDER_LOCK = threading.Lock()


def _log_search_index_disabled():
    global SEARCH_INDEX_DISABLED_LOGGED
    if not SEARCH_INDEX_DISABLED_LOGGED:
        SEARCH_INDEX_DISABLED_LOGGED = True
        logger.info("[Workbench] Tag 搜索索引已禁用 (UW_DISABLE_TAG_SEARCH_INDEX=1)")


def _search_cache_enabled():
    return os.environ.get('UW_DISABLE_TAG_SEARCH_INDEX') != '1'


def _search_cache_path():
    """Lazy: partial-source harnesses may import this module without the prompt store."""
    global _SEARCH_CACHE_FILE
    if _SEARCH_CACHE_FILE is None:
        try:
            from . import prompt_selector as prompt_store
        except ImportError:
            return None
        _SEARCH_CACHE_FILE = Path(prompt_store.PROMPT_STORE_DIR) / 'cache' / 'tag_search.v1.db'
    return _SEARCH_CACHE_FILE


# SQLite 的 LIKE / lower() 只折叠 ASCII 字母；cache 里的文本与查询用同一套折叠，
# 因此 trigram 短语命中与旧 LIKE 子串命中逐条等价（含中文/下划线/空格/大小写）。
_ASCII_FOLD = str.maketrans({chr(code): chr(code + 32) for code in range(ord('A'), ord('Z') + 1)})


def _ascii_fold(value):
    return str(value).translate(_ASCII_FOLD)


def _category_lock():
    """Lazy so partial-source harnesses that drop module-level calls still work."""
    lock = globals().get('_CATEGORY_LOCK')
    if lock is None:
        lock = threading.RLock()
        globals()['_CATEGORY_LOCK'] = lock
    return lock


# 目录树（区域/子夹/计数 + 「tags 串」分流）只有几百条，重算却要把 29 万行分组一遍；
# 按 tags 库 revision 存一份 JSON，重启后连 532MB 库的冷读都省掉。版本/规则不符或
# 文件损坏时整体忽略并重算，写盘走 daemon 线程 + 临时文件替换，失败只警告。
# 改 categories() 的返回结构时把 _CATEGORY_CACHE_FORMAT +1，旧文件随之作废。
_CATEGORY_CACHE_FILE = None
_CATEGORY_CACHE_FORMAT = 1
_CATEGORY_CACHE_DISABLED_LOGGED = False


def _category_cache_path():
    """Lazy: partial-source harnesses may import this module without the prompt store."""
    global _CATEGORY_CACHE_FILE
    if _CATEGORY_CACHE_FILE is None:
        from . import prompt_selector as prompt_store
        _CATEGORY_CACHE_FILE = Path(prompt_store.PROMPT_STORE_DIR) / 'cache' / 'tag_categories.v1.json'
    return _CATEGORY_CACHE_FILE


def _category_cache_rules():
    return {'format': _CATEGORY_CACHE_FORMAT, 'string_flags': STRING_FLAGS_VERSION,
            'word_min': STRING_WORD_MIN, 'ratio_limit': STRING_GROUP_RATIO,
            'string_bucket': SHOW_STRING_BUCKET}


def _category_cache_enabled():
    if os.environ.get('UW_DISABLE_TAG_CATEGORY_CACHE') != '1':
        return True
    global _CATEGORY_CACHE_DISABLED_LOGGED
    if not _CATEGORY_CACHE_DISABLED_LOGGED:
        _CATEGORY_CACHE_DISABLED_LOGGED = True
        logger.info("[Workbench] Tag 目录缓存已禁用 (UW_DISABLE_TAG_CATEGORY_CACHE=1)")
    return False


def _read_category_cache(revision):
    if not _category_cache_enabled():
        return None
    try:
        path = _category_cache_path()
        document = json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return None
    except Exception as error:  # noqa: BLE001 - a bad cache must never block the panel
        logger.warning("[Workbench] Tag 目录缓存无法读取，将重算: %s", error)
        return None
    if not isinstance(document, dict) or document.get('rules') != _category_cache_rules() \
            or document.get('revision') != revision:
        return None
    payload = document.get('payload')
    if not isinstance(payload, dict) or payload.get('revision') != revision:
        return None
    logger.info("[Workbench] Tag 目录缓存已加载（%s）", revision)
    return payload


def _write_category_cache(payload):
    if not _category_cache_enabled():
        return
    try:
        path = _category_cache_path()
        text = json.dumps({'rules': _category_cache_rules(), 'revision': payload['revision'],
                           'payload': payload}, ensure_ascii=False)
    except Exception as error:  # noqa: BLE001
        logger.warning("[Workbench] Tag 目录缓存无法序列化: %s", error)
        return

    def writer():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.parent / (path.name + '.' + uuid.uuid4().hex + '.tmp')
            temporary.write_text(text, encoding='utf-8')
            os.replace(temporary, path)
            logger.info("[Workbench] Tag 目录缓存已写入（%s，%.1f KB）", payload['revision'],
                        len(text.encode('utf-8')) / 1024.0)
        except Exception as error:  # noqa: BLE001 - cache write is best effort
            logger.warning("[Workbench] Tag 目录缓存写入失败: %s", error)

    threading.Thread(target=writer, name="uw-tag-category-cache", daemon=True).start()


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
                payload = _read_category_cache(revision)
                if payload is None:
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
                    _write_category_cache(payload)
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

    ID_ORDER = 'SELECT t.id_index FROM tag_tags t'

    @staticmethod
    def _read_index_meta(conn):
        """Return the built read-index version, or None when the structures are absent/incomplete."""
        try:
            row = conn.execute(
                f'SELECT (SELECT version FROM {READ_META_TABLE} WHERE id=1), '
                "(SELECT count(*) FROM sqlite_master WHERE type='table' AND name IN (?,?,?)), "
                "(SELECT count(*) FROM sqlite_master WHERE type='index' AND name IN (?,?,?,?))",
                (READ_THEME_TABLE, READ_COLLECTION_TABLE, READ_META_TABLE,
                 READ_SCOPE_INDEX, READ_SHAPE_INDEX, READ_THEME_INDEX, READ_COLLECTION_INDEX)).fetchone()
        except sqlite3.OperationalError:
            return None
        return row[0] if row is not None and row[1] == 3 and row[2] == 4 else None

    def read_index_ready(self, conn):
        """Cheap per-request check: derived read structures exist and match the current code version."""
        if os.environ.get('UW_DISABLE_TAG_READ_INDEX') == '1':
            _log_read_index_disabled()
            return False
        return self._read_index_meta(conn) == READ_INDEX_VERSION

    def prepare_read_index(self):
        """Build the expression indexes and the theme/collection derived tables once.

        Runs from the post-ready Tag warm thread (or from a background retry thread); the whole
        build is one transaction, so a failure leaves the previous schema version in place and the
        next request/warm simply tries again.  Tag writes stay untouched: the expression indexes
        are maintained by SQLite itself and the derived tables only gain three triggers each.
        """
        with _SCHEMA_LOCK, self.connection() as conn:
            if self._read_index_meta(conn) == READ_INDEX_VERSION:
                return False
            logger.info("[Workbench] 正在建立 Tag 读取索引（一次性处理 29.8 万行）…")
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                for event in ('insert', 'update', 'delete'):
                    conn.execute(f'DROP TRIGGER IF EXISTS workbench_tag_themes_{event}')
                    conn.execute(f'DROP TRIGGER IF EXISTS workbench_tag_collections_{event}')
                for name in (READ_THEME_TABLE, READ_COLLECTION_TABLE, READ_META_TABLE):
                    conn.execute(f'DROP TABLE IF EXISTS {name}')
                for name in (READ_SCOPE_INDEX, READ_SHAPE_INDEX):
                    conn.execute(f'DROP INDEX IF EXISTS {name}')
                conn.execute(f'CREATE INDEX {READ_SCOPE_INDEX} ON tag_tags({SCOPE_FOLDER_RAW}, {SHAPE_COMMAS_RAW}, create_time)')
                conn.execute(f'CREATE INDEX {READ_SHAPE_INDEX} ON tag_tags({SHAPE_COMMAS_RAW})')
                conn.execute(f'CREATE TABLE {READ_THEME_TABLE} '
                             '(tag_uuid TEXT NOT NULL, theme TEXT NOT NULL, PRIMARY KEY (tag_uuid, theme))')
                conn.execute(f'CREATE INDEX {READ_THEME_INDEX} ON {READ_THEME_TABLE}(theme)')
                conn.execute(f'CREATE TABLE {READ_COLLECTION_TABLE} '
                             '(tag_uuid TEXT NOT NULL, collection_id TEXT NOT NULL, PRIMARY KEY (tag_uuid, collection_id))')
                conn.execute(f'CREATE INDEX {READ_COLLECTION_INDEX} ON {READ_COLLECTION_TABLE}(collection_id)')
                conn.execute(f'CREATE TABLE {READ_META_TABLE} (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)')
                # GROUP BY 去重：历史 SQL 写入或旧维护工具可能留下重复的 themes/collection_ids，
                # 同一语句里重复插入会在 upsert 路径下把约束错误抛给调用方，派生表只需要集合。
                theme_rows = (f'SELECT tag_uuid, value FROM workbench_tag_meta, json_each('
                              "CASE WHEN json_type(data,'$.themes')='array' THEN json_extract(data,'$.themes') "
                              "ELSE '[]' END) WHERE type='text' AND value IS NOT NULL GROUP BY tag_uuid, value")
                collection_rows = (f'SELECT tag_uuid, value FROM workbench_tag_meta, '
                                   "json_each(json_extract(data,'$.collection_ids')) "
                                   "WHERE type='text' AND value IS NOT NULL GROUP BY tag_uuid, value")
                conn.execute(f'INSERT INTO {READ_THEME_TABLE} (tag_uuid, theme) {theme_rows}')
                conn.execute(f'INSERT INTO {READ_COLLECTION_TABLE} (tag_uuid, collection_id) {collection_rows}')
                for event, source in (('insert', 'NEW'), ('update', 'NEW'), ('delete', 'OLD')):
                    theme_insert = '' if event == 'delete' else (
                        f'INSERT OR IGNORE INTO {READ_THEME_TABLE} (tag_uuid, theme) '
                        f'SELECT {source}.tag_uuid, value FROM json_each('
                        f"CASE WHEN json_type({source}.data,'$.themes')='array' "
                        f"THEN json_extract({source}.data,'$.themes') ELSE '[]' END) "
                        "WHERE type='text' AND value IS NOT NULL GROUP BY value;")
                    collection_insert = '' if event == 'delete' else (
                        f'INSERT OR IGNORE INTO {READ_COLLECTION_TABLE} (tag_uuid, collection_id) '
                        f'SELECT {source}.tag_uuid, value FROM json_each('
                        f"json_extract({source}.data,'$.collection_ids')) "
                        "WHERE type='text' AND value IS NOT NULL GROUP BY value;")
                    conn.execute(f'''CREATE TRIGGER workbench_tag_themes_{event}
                        AFTER {event.upper()} ON workbench_tag_meta BEGIN
                        DELETE FROM {READ_THEME_TABLE} WHERE tag_uuid = {source}.tag_uuid;
                        {theme_insert}
                        END''')
                    conn.execute(f'''CREATE TRIGGER workbench_tag_collections_{event}
                        AFTER {event.upper()} ON workbench_tag_meta BEGIN
                        DELETE FROM {READ_COLLECTION_TABLE} WHERE tag_uuid = {source}.tag_uuid;
                        {collection_insert}
                        END''')
                conn.execute(f'INSERT INTO {READ_META_TABLE} VALUES (1, ?)', (READ_INDEX_VERSION,))
            logger.info("[Workbench] Tag 读取索引已建立（V%d：2 个表达式索引 + 主题/收藏组派生表）。", READ_INDEX_VERSION)
            return True

    def warm_read_index(self):
        """Build the read index if needed; never raise (the Tag panel must open regardless)."""
        if os.environ.get('UW_DISABLE_TAG_READ_INDEX') == '1':
            _log_read_index_disabled()
            return False
        try:
            self.prepare_read_index()
        except Exception as error:  # noqa: BLE001 - a failed build only costs speed
            logger.warning("[Workbench] Tag 读取索引建立失败，继续使用旧查询: %s", error)
            return False
        with self.connection() as conn:
            return self._read_index_meta(conn) == READ_INDEX_VERSION

    def _schedule_read_index_build(self):
        """Single-flight background build for requests that arrive before the warm-up finished."""
        if os.environ.get('UW_DISABLE_TAG_READ_INDEX') == '1':
            _log_read_index_disabled()
            return
        key = str(self.path)
        with _READ_INDEX_BUILDING_LOCK:
            if key in _READ_INDEX_BUILDING:
                return
            _READ_INDEX_BUILDING.add(key)

        def build():
            try:
                self.prepare_read_index()
            except Exception as error:  # noqa: BLE001
                logger.warning("[Workbench] Tag 读取索引建立失败，继续使用旧查询: %s", error)
            finally:
                with _READ_INDEX_BUILDING_LOCK:
                    _READ_INDEX_BUILDING.discard(key)

        threading.Thread(target=build, name='uw-tag-read-index', daemon=True).start()

    # ------------------------------------------------------------------
    # 子串搜索索引：trigram FTS5 cache + tags 库变更日志
    # ------------------------------------------------------------------

    @staticmethod
    def _search_expression(forms):
        """FTS5 MATCH query: lower() 后的 trigram 短语 = 旧 LIKE 的 ASCII 大小写折叠子串。"""
        parts = ['tag_text : "' + _ascii_fold(form).replace('"', '""') + '"' for form in forms]
        parts.append('tag_desc : "' + _ascii_fold(forms[0]).replace('"', '""') + '"')
        return ' OR '.join(parts)

    @staticmethod
    def _search_cache_meta(cache_path):
        if not cache_path or not os.path.isfile(cache_path):
            return None
        try:
            connection = sqlite3.connect(cache_path, timeout=10)
            try:
                row = connection.execute('SELECT format, applied_seq, built_revision FROM ' + SEARCH_META_TABLE +
                                         ' WHERE id=1').fetchone()
            finally:
                connection.close()
        except sqlite3.Error:
            return None
        if row is None or row[0] != SEARCH_INDEX_VERSION:
            return None
        return {'applied_seq': row[1], 'built_revision': row[2]}

    @staticmethod
    def _search_schema_version(conn):
        try:
            row = conn.execute('SELECT version FROM ' + SEARCH_SCHEMA_TABLE + ' WHERE id=1').fetchone()
            missing = conn.execute(
                "SELECT count(*) FROM sqlite_master WHERE type='trigger' AND name IN (?,?,?)",
                SEARCH_TRIGGERS).fetchone()[0]
        except sqlite3.OperationalError:
            return None
        if row is None or missing != len(SEARCH_TRIGGERS):
            return None
        return row[0]

    def _prepare_search_schema(self, conn):
        """Create the tiny change journal + triggers in the tags DB; a version bump recreates them."""
        if self._search_schema_version(conn) == SEARCH_INDEX_VERSION:
            return
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            for name in SEARCH_TRIGGERS:
                conn.execute(f'DROP TRIGGER IF EXISTS {name}')
            conn.execute(f'DROP TABLE IF EXISTS {SEARCH_JOURNAL_TABLE}')
            conn.execute(f'DROP TABLE IF EXISTS {SEARCH_SCHEMA_TABLE}')
            conn.execute(f'''CREATE TABLE {SEARCH_JOURNAL_TABLE} (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id_index INTEGER NOT NULL,
                operation TEXT NOT NULL, tag_text TEXT, tag_desc TEXT)''')
            conn.execute(f'CREATE TABLE {SEARCH_SCHEMA_TABLE} (id INTEGER PRIMARY KEY, version INTEGER NOT NULL)')
            conn.execute(f'INSERT INTO {SEARCH_SCHEMA_TABLE} VALUES (1, ?)', (SEARCH_INDEX_VERSION,))
            for index, (event, source) in enumerate((('insert', 'NEW'), ('update', 'NEW'), ('delete', 'OLD'))):
                if event == 'delete':
                    body = (f'INSERT INTO {SEARCH_JOURNAL_TABLE} (id_index, operation, tag_text, tag_desc) '
                            f"VALUES ({source}.id_index, 'delete', NULL, NULL);")
                else:
                    body = (f'INSERT INTO {SEARCH_JOURNAL_TABLE} (id_index, operation, tag_text, tag_desc) '
                            f"VALUES ({source}.id_index, 'upsert', lower({source}.text), lower({source}.desc));")
                conn.execute(f'CREATE TRIGGER {SEARCH_TRIGGERS[index]} AFTER {event.upper()} ON tag_tags '
                             f'BEGIN {body} END')

    def _build_search_cache(self):
        """Snapshot the tags DB into a fresh trigram FTS cache file, then atomically replace it."""
        path = _search_cache_path()
        if path is None:
            raise RuntimeError('Tag 搜索缓存目录不可用')
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / (path.name + '.' + uuid.uuid4().hex + '.tmp')
        if temporary.exists():
            temporary.unlink()
        started = time.perf_counter()
        main = sqlite3.connect(self.path, timeout=60)
        try:
            main.execute('ATTACH DATABASE ? AS search_cache', (str(temporary),))
            main.execute('PRAGMA search_cache.journal_mode=OFF')
            main.execute('PRAGMA search_cache.synchronous=OFF')
            main.execute('BEGIN')
            seq = main.execute('SELECT COALESCE(MAX(seq),0) FROM ' + SEARCH_JOURNAL_TABLE).fetchone()[0]
            revision = main.execute('SELECT value FROM workbench_tag_revision WHERE id=1').fetchone()[0]
            rows = main.execute('SELECT count(*) FROM tag_tags').fetchone()[0]
            main.execute(f'CREATE VIRTUAL TABLE search_cache.{SEARCH_CACHE_TABLE} USING fts5('
                         "tag_text, tag_desc, content='', contentless_delete=1, tokenize='trigram case_sensitive 1')")
            main.execute(f'CREATE TABLE search_cache.{SEARCH_META_TABLE} (id INTEGER PRIMARY KEY, '
                         'format INTEGER NOT NULL, applied_seq INTEGER NOT NULL, built_revision INTEGER NOT NULL, '
                         'rows INTEGER NOT NULL)')
            main.execute(f'INSERT INTO search_cache.{SEARCH_META_TABLE} VALUES (1, ?, ?, ?, ?)',
                         (SEARCH_INDEX_VERSION, seq, revision, rows))
            main.execute(f'INSERT INTO search_cache.{SEARCH_CACHE_TABLE}(rowid, tag_text, tag_desc) '
                         "SELECT id_index, COALESCE(lower(text),''), COALESCE(lower(desc),'') FROM tag_tags")
            main.commit()
            main.execute('DETACH DATABASE search_cache')
        except Exception:
            try:
                main.close()
            except sqlite3.Error:
                pass
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
        main.close()
        writer = sqlite3.connect(str(temporary), timeout=60)
        try:
            writer.execute('PRAGMA journal_mode=DELETE')
            writer.execute('PRAGMA synchronous=NORMAL')
        finally:
            writer.close()
        try:
            os.replace(temporary, path)
        except OSError:
            # 目标文件正被一个搜索连接占用：保留旧 cache，清掉临时文件，下次再试。
            try:
                temporary.unlink()
            except OSError:
                pass
            raise
        # 快照里已经包含 seq 之前的全部变更，清掉避免下次重复回放（崩溃时重复回放也是幂等的）。
        with self.connection() as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute(f'DELETE FROM {SEARCH_JOURNAL_TABLE} WHERE seq <= ?', (seq,))
        logger.info("[Workbench] Tag 搜索索引已建立（%d 行，%.1f s，%.1f MB）",
                    rows, time.perf_counter() - started, path.stat().st_size / 1048576.0)

    def _search_sync(self, force_rebuild=False):
        """Apply the change journal to the cache; rebuild it when missing/stale/too far behind."""
        if not _search_cache_enabled():
            _log_search_index_disabled()
            return False
        path = _search_cache_path()
        if path is None:
            return False
        meta = None if force_rebuild else self._search_cache_meta(path)
        try:
            with self.connection() as conn:
                if self._search_schema_version(conn) != SEARCH_INDEX_VERSION:
                    return False
                revision = conn.execute('SELECT value FROM workbench_tag_revision WHERE id=1').fetchone()[0]
                pending = conn.execute(f'SELECT count(*) FROM {SEARCH_JOURNAL_TABLE}').fetchone()[0]
        except sqlite3.OperationalError:
            return False
        if meta is None or meta['built_revision'] > revision or pending > SEARCH_REBUILD_PENDING:
            self._build_search_cache()
            return True
        applied = meta['applied_seq']
        while True:
            with self.connection() as conn:
                rows = conn.execute(f'SELECT seq, id_index, operation, tag_text, tag_desc FROM {SEARCH_JOURNAL_TABLE} '
                                    'WHERE seq > ? ORDER BY seq LIMIT ?', (applied, SEARCH_APPLY_BATCH)).fetchall()
                if not rows:
                    if applied:
                        with conn:
                            conn.execute('BEGIN IMMEDIATE')
                            conn.execute(f'DELETE FROM {SEARCH_JOURNAL_TABLE} WHERE seq <= ?', (applied,))
                    return True
                last = rows[-1][0]
            cache = sqlite3.connect(path, timeout=30)
            try:
                cache.execute('PRAGMA synchronous=NORMAL')
                with cache:
                    for _seq, id_index, operation, tag_text, tag_desc in rows:
                        cache.execute(f'DELETE FROM {SEARCH_CACHE_TABLE} WHERE rowid=?', (id_index,))
                        if operation == 'upsert':
                            cache.execute(f'INSERT INTO {SEARCH_CACHE_TABLE}(rowid, tag_text, tag_desc) '
                                          'VALUES (?,?,?)', (id_index, tag_text or '', tag_desc or ''))
                    cache.execute(f'UPDATE {SEARCH_META_TABLE} SET applied_seq=? WHERE id=1', (last,))
            finally:
                cache.close()
            with self.connection() as conn, conn:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute(f'DELETE FROM {SEARCH_JOURNAL_TABLE} WHERE seq <= ?', (last,))
            applied = last
            logger.info("[Workbench] Tag 搜索索引增量同步 %d 条（seq ≤ %d）", len(rows), last)

    def prepare_search_index(self):
        """Ensure journal/triggers exist and the FTS cache matches the tags DB (rebuild if needed)."""
        if not _search_cache_enabled():
            _log_search_index_disabled()
            return False
        if _search_cache_path() is None:
            return False
        with _SCHEMA_LOCK, self.connection() as conn:
            previous = self._search_schema_version(conn)
            self._prepare_search_schema(conn)
        if previous != SEARCH_INDEX_VERSION:
            _SEARCH_ORDER.pop(str(self.path), None)
            self._search_sync(force_rebuild=True)
        else:
            self._search_sync()
        return True

    def warm_search_index(self):
        """Post-ready warm: build/sync the FTS cache and the in-memory create_time order."""
        if not _search_cache_enabled():
            _log_search_index_disabled()
            return False
        if _search_cache_path() is None:
            return False
        key = str(self.path)
        with _SEARCH_BUILDING_LOCK:
            if key in _SEARCH_BUILDING:
                return False
            _SEARCH_BUILDING.add(key)
        try:
            started = time.perf_counter()
            self.prepare_search_index()
            with self.connection() as conn:
                order = self._remember_search_order(conn)
            ready = self._search_cache_meta(_search_cache_path()) is not None
        except Exception as error:  # noqa: BLE001 - a failed warm-up only costs speed
            logger.warning("[Workbench] Tag 搜索索引预热失败，将在首次搜索时重试: %s", error)
            return False
        finally:
            with _SEARCH_BUILDING_LOCK:
                _SEARCH_BUILDING.discard(key)
        logger.info("[Workbench] Tag 搜索索引已就绪（%.1f s，内存顺序 %d 条）",
                    time.perf_counter() - started, len(order))
        return ready

    def _schedule_search_index_sync(self):
        """Single-flight background sync/rebuild for requests that arrive while the cache is stale."""
        if not _search_cache_enabled():
            _log_search_index_disabled()
            return
        if _search_cache_path() is None:
            return
        key = str(self.path)
        with _SEARCH_BUILDING_LOCK:
            if key in _SEARCH_BUILDING:
                return

        def run():
            try:
                self.warm_search_index()
            except Exception as error:  # noqa: BLE001
                logger.warning("[Workbench] Tag 搜索索引同步失败，继续用旧查询: %s", error)

        threading.Thread(target=run, name='uw-tag-search-index', daemon=True).start()

    @staticmethod
    def _build_search_order(conn):
        return array('i', (row[0] for row in conn.execute(
            'SELECT id_index FROM tag_tags ORDER BY create_time DESC, id_index')))

    def _search_order(self, conn):
        """In-memory create_time/id_index order, rebuilt only when tag_tags changes (text revision)."""
        key = str(self.path)
        text_revision = self.text_revision_of(conn)
        with _SEARCH_ORDER_LOCK:
            cached = _SEARCH_ORDER.get(key)
        if cached is None or cached[0] != text_revision:
            return None
        return cached[1]

    def _remember_search_order(self, conn):
        key = str(self.path)
        text_revision = self.text_revision_of(conn)
        with _SEARCH_ORDER_LOCK:
            cached = _SEARCH_ORDER.get(key)
            if cached is not None and cached[0] == text_revision:
                return cached[1]
        order = self._build_search_order(conn)
        with _SEARCH_ORDER_LOCK:
            _SEARCH_ORDER[key] = (text_revision, order)
        return order

    def _search_fast_numbers(self, conn, query, forms, offset, limit):
        """FTS cache path for a plain ``q`` search; returns (total, ordered ids) or None to fall back."""
        if not _search_cache_enabled() or len(query) < SEARCH_MIN_QUERY:
            return None
        if not all(ord(value[-1]) < 0x10ffff for value in forms):
            return None
        path = _search_cache_path()
        if path is None or not os.path.isfile(path):
            self._schedule_search_index_sync()
            return None
        try:
            revision = conn.execute('SELECT value FROM workbench_tag_revision WHERE id=1').fetchone()[0]
            if conn.execute(f'SELECT 1 FROM {SEARCH_JOURNAL_TABLE} LIMIT 1').fetchone() is not None:
                self._schedule_search_index_sync()
                return None
        except sqlite3.OperationalError:
            self._schedule_search_index_sync()
            return None
        order = self._search_order(conn)
        if order is None:
            self._schedule_search_index_sync()
            return None
        try:
            cache = sqlite3.connect(path, timeout=10)
            try:
                meta = cache.execute('SELECT format, applied_seq, built_revision FROM ' + SEARCH_META_TABLE +
                                     ' WHERE id=1').fetchone()
                if meta is None or meta[0] != SEARCH_INDEX_VERSION or meta[2] > revision:
                    self._schedule_search_index_sync()
                    return None
                candidates = [row[0] for row in cache.execute(
                    f'SELECT rowid FROM {SEARCH_CACHE_TABLE} WHERE {SEARCH_CACHE_TABLE} MATCH ?',
                    (self._search_expression(forms),))]
            finally:
                cache.close()
        except sqlite3.Error as error:
            logger.warning("[Workbench] Tag 搜索索引读取失败，回退旧查询: %s", error)
            self._schedule_search_index_sync()
            return None
        total = len(candidates)
        if total == 0:
            return 0, array('i')
        # 三层顺序与旧实现一致：精确（按 text,id_index）→ 前缀（按 text,id_index）→ 其余（create_time DESC,id_index）。
        exact_match = 't.text IN (' + ','.join('?' for _ in forms) + ')'
        range_condition = '(' + ' OR '.join(['(t.text>=? AND t.text<?)'] * len(forms)) + ')'
        range_args = [bound for value in forms for bound in (value, value[:-1] + chr(ord(value[-1]) + 1))]
        exact_count = conn.execute('SELECT count(*) FROM tag_tags t WHERE ' + exact_match, forms).fetchone()[0]
        prefix_count = conn.execute('SELECT count(*) FROM tag_tags t WHERE ' + range_condition + ' AND NOT ' +
                                    exact_match, [*range_args, *forms]).fetchone()[0]
        rest_count = total - exact_count - prefix_count
        if rest_count < 0:
            logger.warning("[Workbench] Tag 搜索索引与 tags 库不一致（total=%d, exact=%d, prefix=%d），重建索引",
                           total, exact_count, prefix_count)
            self._schedule_search_index_sync()
            return None
        numbers = array('i')
        skip = offset

        def take(fetch, count):
            nonlocal skip
            if skip >= count:
                skip -= count
                return
            take_count = min(limit - len(numbers), count - skip)
            numbers.extend(fetch(skip, take_count))
            skip = 0

        take(lambda off, count: (row[0] for row in conn.execute(
            'SELECT t.id_index FROM tag_tags t WHERE ' + exact_match +
            ' ORDER BY t.text,t.id_index LIMIT ? OFFSET ?', [*forms, count, off])), exact_count)
        if len(numbers) < limit:
            take(lambda off, count: (row[0] for row in conn.execute(
                'SELECT t.id_index FROM tag_tags t WHERE ' + range_condition + ' AND NOT ' + exact_match +
                ' ORDER BY t.text,t.id_index LIMIT ? OFFSET ?', [*range_args, *forms, count, off])), prefix_count)
        if len(numbers) < limit and rest_count > 0:
            need = limit - len(numbers)
            excluded = {row[0] for row in conn.execute(
                'SELECT t.id_index FROM tag_tags t WHERE ' + range_condition, range_args)}
            candidate_set = set(candidates)
            for id_index in order:
                if id_index in excluded or id_index not in candidate_set:
                    continue
                if skip:
                    skip -= 1
                    continue
                numbers.append(id_index)
                need -= 1
                if need == 0:
                    break
        return total, numbers

    def _page_clauses(self, conn, query, forms, subgroup, group, favorite, collection, known_collections,
                      shape, scope, theme, indexed):
        """WHERE clauses shared by the fast path and the original fallback path.

        ``indexed`` switches theme/collection/area to the derived tables and the shape test to
        the exact expression the indexes were built on; every other clause keeps its historical
        wording so both paths return the same rows (verified by tests/test_tag_read_speed.py).
        """
        clauses, args = [], []
        # 正文形状：基础 tag 是单个词，其它是所长法典里的 tags 串（属提示词片段）。
        if shape:
            if shape == 'atomic':
                clauses.append(f'{SHAPE_COMMAS}=0')
            elif shape == 'group':
                clauses.append(f'{SHAPE_COMMAS} BETWEEN 1 AND 2')
            elif shape == 'string':
                clauses.append(f'{SHAPE_COMMAS}>=3')
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
            if indexed:
                # Resolve the (small) folder list first so the clause can use the folder index;
                # the historical subquery form could not combine with the scope index.
                folders = [row[0] for row in conn.execute(
                    'SELECT g_uuid FROM tag_subgroups WHERE p_uuid=?', (group,)) if row[0] is not None]
                if folders:
                    placeholders = ','.join('?' for _ in folders)
                    clauses.append(f'(t.g_uuid IN ({placeholders}) OR t.t_uuid IN '
                                   f'(SELECT tag_uuid FROM workbench_tag_folder_members '
                                   f'WHERE g_uuid IN ({placeholders})))')
                    args.extend([*folders, *folders])
                else:
                    clauses.append('0')
            else:
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
            if indexed:
                clauses.append(f'EXISTS (SELECT 1 FROM {READ_THEME_TABLE} '
                               'WHERE tag_uuid=t.t_uuid AND theme=?)')
                args.append(theme)
            else:
                clauses.append("t.t_uuid IN (SELECT tag_uuid FROM workbench_tag_meta WHERE EXISTS "
                               "(SELECT 1 FROM json_each(CASE WHEN json_type(data,'$.themes')='array' "
                               "THEN json_extract(data,'$.themes') ELSE '[]' END) WHERE value=?))")
                args.append(theme)
        if collection:
            if collection == 'default':
                placeholders = ','.join('?' for _ in known_collections) or 'NULL'
                if indexed:
                    clauses.append(f"(EXISTS (SELECT 1 FROM {READ_COLLECTION_TABLE} "
                                   "WHERE tag_uuid=t.t_uuid AND collection_id='default') OR NOT EXISTS "
                                   f'(SELECT 1 FROM {READ_COLLECTION_TABLE} '
                                   'WHERE tag_uuid=t.t_uuid AND collection_id IN (' + placeholders + ')))')
                else:
                    clauses.append("(t.t_uuid IN (SELECT tag_uuid FROM workbench_tag_meta WHERE EXISTS "
                                   "(SELECT 1 FROM json_each(json_extract(data,'$.collection_ids')) WHERE value='default')) "
                                   "OR t.t_uuid NOT IN (SELECT tag_uuid FROM workbench_tag_meta WHERE EXISTS "
                                   "(SELECT 1 FROM json_each(json_extract(data,'$.collection_ids')) "
                                   'WHERE value IN (' + placeholders + '))))')
                args.extend(known_collections)
            else:
                if indexed:
                    clauses.append(f'EXISTS (SELECT 1 FROM {READ_COLLECTION_TABLE} '
                                   'WHERE tag_uuid=t.t_uuid AND collection_id=?)')
                else:
                    clauses.append("t.t_uuid IN (SELECT tag_uuid FROM workbench_tag_meta WHERE EXISTS "
                                   "(SELECT 1 FROM json_each(json_extract(data,'$.collection_ids')) WHERE value=?))")
                args.append(collection)
        return clauses, args

    def _ordered_numbers(self, conn, where, args, offset, limit):
        rows = conn.execute(self.ID_ORDER + where + ' ORDER BY t.create_time DESC,t.id_index LIMIT ? OFFSET ?',
                            [*args, limit, offset]).fetchall()
        return array('i', (row[0] for row in rows))

    def _rows_by_numbers(self, conn, row_numbers):
        if not len(row_numbers):
            return []
        placeholders = ','.join('?' for _ in row_numbers)
        fetched = conn.execute(self.SELECT + f' WHERE t.id_index IN ({placeholders})',
                               list(row_numbers)).fetchall()
        by_number = {row['id_index']: row for row in fetched}
        return [by_number[number] for number in row_numbers if number in by_number]

    def _page_row_numbers(self, conn, query, forms, where, args, cache_key, offset, limit, indexed, fast_text,
                          plain_search):
        """Return ``(total, id_index array)`` for one page, honouring the historical slice cache."""
        cached = _PAGE_CACHE.get(cache_key)
        if cached is None:
            if len(_PAGE_CACHE) >= _PAGE_CACHE_LIMIT:
                _PAGE_CACHE.clear()
            cached = [None, {}]
            _PAGE_CACHE[cache_key] = cached
        total, cached_slices = cached
        row_numbers = cached_slices.get((offset, limit))
        if row_numbers is not None:
            return total, row_numbers
        if plain_search:
            fast = self._search_fast_numbers(conn, query, forms, offset, limit)
            if fast is not None:
                total, row_numbers = fast
                cached[0] = total
                if len(cached_slices) >= _PAGE_SLICE_LIMIT:
                    cached_slices.clear()
                cached_slices[(offset, limit)] = row_numbers
                return total, row_numbers
        if indexed and fast_text and query and all(ord(value[-1]) < 0x10ffff for value in forms):
            # 单遍：窗口函数顺便给出 total，排序键直接复刻旧的三段（精确/前缀/其余）顺序。
            # 只有 scope/形状这类可走索引的过滤才划算；无过滤的整库搜索仍用旧的分层查询。
            row_numbers, window_total = self._indexed_text_numbers(conn, forms, where, args, offset, limit)
            if total is None:
                total = cached[0] = (window_total if window_total is not None else
                                     conn.execute('SELECT count(*) FROM tag_tags t' + where, args).fetchone()[0])
        else:
            if total is None:
                total = cached[0] = conn.execute('SELECT count(*) FROM tag_tags t' + where, args).fetchone()[0]
            if query:
                row_numbers = self._legacy_text_numbers(conn, forms, where, args, total, offset, limit)
            else:
                row_numbers = self._ordered_numbers(conn, where, args, offset, limit)
        if len(cached_slices) >= _PAGE_SLICE_LIMIT:
            cached_slices.clear()
        cached_slices[(offset, limit)] = row_numbers
        return total, row_numbers

    def _legacy_text_numbers(self, conn, forms, where, args, total, offset, limit):
        """Original text-search tiering: exact matches first, then prefix, then the rest."""
        exact_match = 't.text IN (' + ','.join('?' for _ in forms) + ')'
        range_condition = '(' + ' OR '.join(['(t.text>=? AND t.text<?)'] * len(forms)) + ')'
        range_args = [bound for value in forms for bound in (value, value[:-1] + chr(ord(value[-1]) + 1))]
        tiers = [
            (exact_match, forms, 't.text,t.id_index'),
            (range_condition + ' AND NOT ' + exact_match, [*range_args, *forms], 't.text,t.id_index'),
            ('NOT ' + range_condition, range_args, 't.create_time DESC,t.id_index'),
        ]
        exact = conn.execute('SELECT count(*) FROM tag_tags t' + where + ' AND ' + tiers[0][0],
                             [*args, *tiers[0][1]]).fetchone()[0]
        prefix = conn.execute('SELECT count(*) FROM tag_tags t' + where + ' AND ' + tiers[1][0],
                              [*args, *tiers[1][1]]).fetchone()[0]
        numbers, skip = array('i'), offset
        for (condition, extra, order), count in zip(tiers, (exact, prefix, total - exact - prefix)):
            if skip >= count:
                skip -= count
                continue
            rows = conn.execute(self.ID_ORDER + where + ' AND ' + condition +
                                ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
                                [*args, *extra, limit - len(numbers), skip]).fetchall()
            numbers.extend(row[0] for row in rows)
            skip = 0
            if len(numbers) >= limit:
                break
        return numbers

    def _indexed_text_numbers(self, conn, forms, where, args, offset, limit):
        """One scan instead of the old 3 counts + 3 ordered queries.

        The ORDER BY reproduces the historical tier order exactly: exact matches by text,
        then prefix matches by text, then everything else by create_time.
        """
        exact_match = 't.text IN (' + ','.join('?' for _ in forms) + ')'
        range_condition = '(' + ' OR '.join(['(t.text>=? AND t.text<?)'] * len(forms)) + ')'
        range_args = [bound for value in forms for bound in (value, value[:-1] + chr(ord(value[-1]) + 1))]
        tier = f'CASE WHEN {exact_match} THEN 0 WHEN {range_condition} THEN 1 ELSE 2 END'
        tier_args = [*forms, *range_args]
        sql = ('SELECT id_index, total FROM (SELECT t.id_index AS id_index, '
               'count(*) OVER () AS total, t.text AS text_value, t.create_time AS create_time, '
               f'{tier} AS tier FROM tag_tags t' + where + ') '
               'ORDER BY tier, CASE WHEN tier<2 THEN text_value END, '
               'CASE WHEN tier=2 THEN create_time END DESC, id_index LIMIT ? OFFSET ?')
        rows = conn.execute(sql, [*tier_args, *args, limit, offset]).fetchall()
        if rows:
            return array('i', (row['id_index'] for row in rows)), rows[0]['total']
        return array('i'), None

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
        with self.connection() as conn:
            conn.execute('BEGIN')
            revision = self.revision_of(conn)
            indexed = self.read_index_ready(conn)
            if not indexed:
                self._schedule_read_index_build()
            clauses, args = self._page_clauses(conn, query, forms, subgroup, group, favorite, collection,
                                               known_collections, shape, scope, theme, indexed)
            if scope or subgroup.startswith(STRING_AREA_PREFIX) or subgroup == STRING_LOOSE_UUID:
                # 分流按"法典最小组（子夹）"整组判定，所以这里用留存子夹名单过滤；
                # 派生表给出每组的精确词数统计（见 string_layout）。
                layout = self.string_layout(conn, self.text_revision_of(conn))
                kept = layout['kept']
                in_kept = (f"{SCOPE_FOLDER} IN ({','.join('?' for _ in kept)})" if kept else '0')
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
            plain_search = bool(query) and not (subgroup or group or favorite or collection or theme or
                                                scope or shape)
            # 单遍窗口查询只在有筛选时用（无筛选的 q 走 FTS cache）：group/favorite 这类
            # 可索引筛选放进窗口查询后是 0.3–70 ms，比旧的三段扫描快一个数量级。
            indexed_text = bool(query) and bool(scope or shape or subgroup or group or favorite)
            total, row_numbers = self._page_row_numbers(conn, query, forms, where, args, cache_key,
                                                        offset, limit, indexed, indexed_text, plain_search)
            rows = self._rows_by_numbers(conn, row_numbers)
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
