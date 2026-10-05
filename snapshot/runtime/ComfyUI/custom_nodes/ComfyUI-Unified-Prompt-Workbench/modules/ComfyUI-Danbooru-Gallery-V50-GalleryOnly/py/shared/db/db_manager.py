"""
Database manager for hot tags cache
Manages SQLite database for offline tag autocomplete
"""

import aiosqlite
import os
import time
import json
import re
import unicodedata
from typing import List, Dict, Optional, Tuple
from pathlib import Path

# Logger导入
from ...utils.logger import get_logger
logger = get_logger(__name__)


_DELIVERY_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_DELIVERY_GUARD_ENV = "DANBOORU_GALLERY_DELIVERY_TEST"
_DELIVERY_CONFIG_ENV = "DANBOORU_GALLERY_TEST_CONFIG"
_TAG_DB_OVERRIDE_ENV = "DANBOORU_GALLERY_TAG_DB_PATH"
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_DELIVERY_RUNTIME_BASE = (_PLUGIN_ROOT / "tests" / ".runtime").resolve()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _delivery_enabled() -> bool:
    return str(os.environ.get(_DELIVERY_GUARD_ENV, "") or "").strip().lower() in _DELIVERY_TRUE_VALUES


def _delivery_tag_db_override() -> Optional[Path]:
    """Resolve the isolated tag DB declared by the delivery runner.

    The environment override is intentionally ignored during normal ComfyUI
    operation.  When the delivery guard is enabled, however, the override and
    its matching test config are mandatory and must both resolve underneath
    ``tests/.runtime``.  This makes a missing or forged delivery configuration
    fail closed instead of silently opening the user's live tag database.
    """

    if not _delivery_enabled():
        return None

    raw_override = str(os.environ.get(_TAG_DB_OVERRIDE_ENV, "") or "").strip()
    if not raw_override:
        raise RuntimeError(
            f"{_TAG_DB_OVERRIDE_ENV} is required when {_DELIVERY_GUARD_ENV} is enabled"
        )
    override = Path(raw_override).expanduser()
    if not override.is_absolute():
        raise RuntimeError(f"{_TAG_DB_OVERRIDE_ENV} must be an absolute path")
    override = override.resolve()

    raw_config = str(os.environ.get(_DELIVERY_CONFIG_ENV, "") or "").strip()
    if not raw_config:
        raise RuntimeError(
            f"{_DELIVERY_CONFIG_ENV} is required when {_DELIVERY_GUARD_ENV} is enabled"
        )
    config_path = Path(raw_config).expanduser()
    if not config_path.is_absolute():
        raise RuntimeError(f"{_DELIVERY_CONFIG_ENV} must be an absolute path")
    config_path = config_path.resolve()
    if not _is_relative_to(config_path, _DELIVERY_RUNTIME_BASE):
        raise RuntimeError("delivery test config escaped tests/.runtime")
    if not config_path.is_file():
        raise RuntimeError(f"delivery test config does not exist: {config_path}")

    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid delivery test config: {exc}") from exc
    if not isinstance(config, dict) or config.get("schemaVersion") != 1:
        raise RuntimeError("delivery test config schemaVersion must be 1")

    raw_runtime = str(config.get("runtimeRoot") or "").strip()
    runtime_root = Path(raw_runtime).expanduser()
    if not raw_runtime or not runtime_root.is_absolute():
        raise RuntimeError("delivery test runtimeRoot must be an absolute path")
    runtime_root = runtime_root.resolve()
    if not _is_relative_to(runtime_root, _DELIVERY_RUNTIME_BASE):
        raise RuntimeError("delivery test runtimeRoot escaped tests/.runtime")
    if not _is_relative_to(config_path, runtime_root):
        raise RuntimeError("delivery test config escaped its declared runtimeRoot")

    raw_declared_db = str(config.get("isolatedTagDatabase") or "").strip()
    declared_db = Path(raw_declared_db).expanduser()
    if not raw_declared_db or not declared_db.is_absolute():
        raise RuntimeError("delivery test isolatedTagDatabase must be an absolute path")
    declared_db = declared_db.resolve()
    if declared_db != override:
        raise RuntimeError(
            f"{_TAG_DB_OVERRIDE_ENV} does not match isolatedTagDatabase in the delivery config"
        )
    if not _is_relative_to(override, runtime_root):
        raise RuntimeError("delivery tag database escaped its declared runtimeRoot")
    if not override.is_file():
        raise RuntimeError(f"delivery tag database does not exist: {override}")
    return override


class TagDatabaseManager:
    """Manage hot tags database for offline autocomplete"""

    ARTIST_CATEGORY = 1

    def __init__(self, db_path: Optional[str] = None):
        delivery_override = _delivery_tag_db_override()
        if delivery_override is not None:
            if db_path is not None and Path(db_path).expanduser().resolve() != delivery_override:
                raise RuntimeError(
                    "explicit tag database path does not match the isolated delivery database"
                )
            db_path = str(delivery_override)
        elif db_path is None:
            # Default to py/shared/data/tags_cache.db
            # Current file: py/shared/db/db_manager.py
            current_dir = Path(__file__).parent  # py/shared/db
            shared_dir = current_dir.parent      # py/shared
            data_dir = shared_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "tags_cache.db")

        self.db_path = db_path
        self._connection = None

    async def get_connection(self) -> aiosqlite.Connection:
        """Get or create database connection"""
        if self._connection is None:
            self._connection = await aiosqlite.connect(self.db_path)
            self._connection.row_factory = aiosqlite.Row
        return self._connection

    async def close(self):
        """Close database connection"""
        if self._connection:
            await self._connection.close()
            self._connection = None

    async def initialize_database(self):
        """Create database tables if they don't exist"""
        conn = await self.get_connection()

        # Create hot_tags table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS hot_tags (
                tag TEXT PRIMARY KEY,
                category INTEGER NOT NULL,
                post_count INTEGER NOT NULL,
                translation_cn TEXT,
                last_updated INTEGER NOT NULL,
                aliases TEXT
            )
        """)

        # Create indexes for performance
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_post_count
            ON hot_tags(post_count DESC)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_category
            ON hot_tags(category)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_translation
            ON hot_tags(translation_cn)
        """)

        # Official Danbooru-style aliases are stored separately from the
        # historical ``hot_tags.aliases`` JSON field.  Keeping the relation in
        # its own table lets imports remain auditable and, importantly, never
        # requires rewriting or deleting a tag identity in ``hot_tags``.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tag_aliases (
                alias TEXT PRIMARY KEY COLLATE NOCASE,
                canonical_tag TEXT NOT NULL,
                relation_type TEXT NOT NULL DEFAULT 'official_alias',
                source_name TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                declared_license TEXT NOT NULL DEFAULT '',
                source_revision TEXT NOT NULL DEFAULT '',
                source_sha256 TEXT NOT NULL DEFAULT '',
                imported_at INTEGER NOT NULL
            )
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tag_aliases_canonical
            ON tag_aliases(canonical_tag COLLATE NOCASE)
        """)

        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tag_aliases_source_revision
            ON tag_aliases(source_name, source_revision)
        """)

        # Create FTS5 virtual table for full-text search (优化中文搜索性能)
        await conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS hot_tags_fts USING fts5(
                tag,
                translation_cn,
                content='hot_tags',
                content_rowid='rowid',
                tokenize='unicode61'
            )
        """)

        # Create triggers to keep FTS index in sync
        # Trigger for INSERT
        await conn.execute("""
            CREATE TRIGGER IF NOT EXISTS hot_tags_ai
            AFTER INSERT ON hot_tags BEGIN
                INSERT INTO hot_tags_fts(rowid, tag, translation_cn)
                VALUES (NEW.rowid, NEW.tag, NEW.translation_cn);
            END
        """)

        # Trigger for UPDATE
        await conn.execute("""
            CREATE TRIGGER IF NOT EXISTS hot_tags_au
            AFTER UPDATE ON hot_tags BEGIN
                UPDATE hot_tags_fts
                SET tag = NEW.tag, translation_cn = NEW.translation_cn
                WHERE rowid = NEW.rowid;
            END
        """)

        # Trigger for DELETE
        await conn.execute("""
            CREATE TRIGGER IF NOT EXISTS hot_tags_ad
            AFTER DELETE ON hot_tags BEGIN
                DELETE FROM hot_tags_fts WHERE rowid = OLD.rowid;
            END
        """)

        # Create sync_metadata table
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at INTEGER
            )
        """)

        await conn.commit()
        logger.info(f"✓ Database initialized at {self.db_path}")
        logger.info(f"✓ FTS5 full-text search enabled")

    async def insert_tag(self, tag: str, category: int, post_count: int,
                        translation_cn: Optional[str] = None,
                        aliases: Optional[List[str]] = None):
        """Insert or update a tag"""
        conn = await self.get_connection()

        aliases_json = json.dumps(aliases) if aliases else None
        current_time = int(time.time())
        # Artist names are searchable tags, but are deliberately excluded from
        # the Chinese translation layer.  Normalize before both INSERT and
        # UPDATE so a category migration to artist also clears stale data.
        if category == self.ARTIST_CATEGORY:
            translation_cn = None

        await conn.execute("""
            INSERT INTO hot_tags
            (tag, category, post_count, translation_cn, last_updated, aliases)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(tag) DO UPDATE SET
                category = excluded.category,
                post_count = excluded.post_count,
                translation_cn = CASE
                    WHEN excluded.category = 1 THEN NULL
                    ELSE COALESCE(
                        NULLIF(TRIM(excluded.translation_cn), ''),
                        hot_tags.translation_cn
                    )
                END,
                last_updated = excluded.last_updated,
                aliases = COALESCE(excluded.aliases, hot_tags.aliases)
        """, (tag, category, post_count, translation_cn, current_time, aliases_json))

    async def insert_tags_batch(self, tags: List[Dict]):
        """Insert multiple tags in batch"""
        conn = await self.get_connection()
        current_time = int(time.time())

        data = []
        for tag_info in tags:
            aliases_json = json.dumps(tag_info.get('aliases')) if tag_info.get('aliases') else None
            category = tag_info['category']
            translation_cn = tag_info.get('translation_cn')
            if category == self.ARTIST_CATEGORY:
                translation_cn = None
            data.append((
                tag_info['tag'],
                category,
                tag_info['post_count'],
                translation_cn,
                current_time,
                aliases_json
            ))

        await conn.executemany("""
            INSERT INTO hot_tags
            (tag, category, post_count, translation_cn, last_updated, aliases)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(tag) DO UPDATE SET
                category = excluded.category,
                post_count = excluded.post_count,
                translation_cn = CASE
                    WHEN excluded.category = 1 THEN NULL
                    ELSE COALESCE(
                        NULLIF(TRIM(excluded.translation_cn), ''),
                        hot_tags.translation_cn
                    )
                END,
                last_updated = excluded.last_updated,
                aliases = COALESCE(excluded.aliases, hot_tags.aliases)
        """, data)

        await conn.commit()

    async def insert_tag_aliases_batch(self, aliases: List[Dict]):
        """Insert or update auditable official alias relations in one batch.

        Alias rows may point at tags not present in ``hot_tags`` yet.  Search
        naturally starts returning them after the canonical tag is synced.
        No tag row or translation is modified by this operation.
        """
        if not aliases:
            return

        current_time = int(time.time())
        data = []
        for alias_info in aliases:
            alias = unicodedata.normalize(
                "NFKC", str(alias_info['alias']).strip()
            ).casefold()
            canonical_tag = unicodedata.normalize(
                "NFKC", str(alias_info['canonical_tag']).strip()
            ).casefold()
            if not alias or not canonical_tag:
                continue
            data.append((
                alias,
                canonical_tag,
                str(alias_info.get('relation_type') or 'official_alias'),
                str(alias_info.get('source_name') or ''),
                str(alias_info.get('source_url') or ''),
                str(alias_info.get('declared_license') or ''),
                str(alias_info.get('source_revision') or ''),
                str(alias_info.get('source_sha256') or ''),
                int(alias_info.get('imported_at') or current_time),
            ))

        if not data:
            return

        conn = await self.get_connection()
        await conn.executemany("""
            INSERT INTO tag_aliases (
                alias, canonical_tag, relation_type, source_name, source_url,
                declared_license, source_revision, source_sha256, imported_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(alias) DO UPDATE SET
                canonical_tag = excluded.canonical_tag,
                relation_type = excluded.relation_type,
                source_name = excluded.source_name,
                source_url = excluded.source_url,
                declared_license = excluded.declared_license,
                source_revision = excluded.source_revision,
                source_sha256 = excluded.source_sha256,
                imported_at = excluded.imported_at
        """, data)
        await conn.commit()

    @staticmethod
    def _decode_aliases(value: Optional[str]) -> List[str]:
        if not value:
            return []
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, list) else []
        except (TypeError, ValueError):
            return []

    @classmethod
    def _visible_translation(cls, category: int,
                             translation_cn: Optional[str]) -> Optional[str]:
        """Mask artist translations even in databases created before migration."""
        if category == cls.ARTIST_CATEGORY:
            return None
        return translation_cn

    @staticmethod
    def _escape_like(value: str) -> str:
        """Escape a user value for a literal SQLite ``LIKE`` expression."""
        return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    async def _search_english(self, query: str, limit: int) -> List[Dict]:
        """Search canonical tags and official aliases without changing identity."""
        if limit <= 0:
            return []

        conn = await self.get_connection()
        normalized_query = unicodedata.normalize("NFKC", query or "").strip().casefold()
        escaped_query = self._escape_like(normalized_query)
        fetch_limit = max(limit * 8, 32)

        direct_cursor = await conn.execute("""
            SELECT tag, category, post_count, translation_cn, aliases
            FROM hot_tags
            WHERE tag LIKE ? || '%' ESCAPE '\\' COLLATE NOCASE
            ORDER BY
                CASE WHEN tag = ? COLLATE NOCASE THEN 1 ELSE 0 END DESC,
                post_count DESC,
                tag ASC
            LIMIT ?
        """, (escaped_query, normalized_query, fetch_limit))
        direct_rows = await direct_cursor.fetchall()

        alias_rows = []
        # The empty prefix historically returned the hottest canonical tags.
        # Avoid flooding that result with every alias when no query is present.
        if normalized_query:
            alias_cursor = await conn.execute("""
                SELECT h.tag, h.category, h.post_count, h.translation_cn,
                       h.aliases,
                       COALESCE(
                           MAX(CASE WHEN a.alias = ? COLLATE NOCASE
                                    THEN a.alias END),
                           MIN(a.alias)
                       ) AS matched_alias,
                       MAX(CASE WHEN a.alias = ? COLLATE NOCASE
                                THEN 1 ELSE 0 END) AS alias_exact
                FROM tag_aliases a
                JOIN hot_tags h ON h.tag = a.canonical_tag
                WHERE a.alias LIKE ? || '%' ESCAPE '\\' COLLATE NOCASE
                GROUP BY h.tag, h.category, h.post_count,
                         h.translation_cn, h.aliases
                ORDER BY
                    alias_exact DESC,
                    h.post_count DESC,
                    matched_alias ASC
                LIMIT ?
            """, (
                normalized_query,
                normalized_query,
                escaped_query,
                fetch_limit,
            ))
            alias_rows = await alias_cursor.fetchall()

        # Deduplicate by canonical tag.  An official exact alias intentionally
        # resolves to its canonical target before an identically-named stale
        # tag row.  No row is deleted; the translation always comes from the
        # canonical ``hot_tags`` row selected for that result.
        candidates = {}
        for row in direct_rows:
            is_exact = row['tag'].casefold() == normalized_query
            sort_score = 100 if is_exact else 80
            candidates[row['tag']] = {
                'tag': row['tag'],
                'category': row['category'],
                'post_count': row['post_count'],
                'translation_cn': self._visible_translation(
                    row['category'], row['translation_cn']
                ),
                'aliases': self._decode_aliases(row['aliases']),
                'matched_alias': None,
                'match_score': 10,
                '_sort_score': sort_score,
            }

        for row in alias_rows:
            matched_alias = row['matched_alias']
            is_exact = matched_alias.casefold() == normalized_query
            sort_score = 110 if is_exact else 70
            existing = candidates.get(row['tag'])
            if existing is not None and existing['_sort_score'] >= sort_score:
                continue
            candidates[row['tag']] = {
                'tag': row['tag'],
                'category': row['category'],
                'post_count': row['post_count'],
                'translation_cn': self._visible_translation(
                    row['category'], row['translation_cn']
                ),
                'aliases': self._decode_aliases(row['aliases']),
                'matched_alias': matched_alias,
                'match_score': 10 if is_exact else 7,
                '_sort_score': sort_score,
            }

        ordered = sorted(
            candidates.values(),
            key=lambda item: (
                -item['_sort_score'],
                -item['post_count'],
                item['tag'],
            ),
        )[:limit]
        for item in ordered:
            item.pop('_sort_score', None)
        return ordered

    async def search_tags_by_prefix(self, prefix: str, limit: int = 10) -> List[Dict]:
        """Search tags by canonical prefix or official alias prefix."""
        results = await self._search_english(prefix, limit)
        # Preserve the legacy result shape while retaining the additive
        # ``matched_alias`` field for clients that want to explain the match.
        for result in results:
            result.pop('match_score', None)
        return results

    async def search_tags_by_translation(self, query: str, limit: int = 10) -> List[Dict]:
        """Search tags by Chinese translation (legacy method, use search_tags_optimized for better performance)"""
        conn = await self.get_connection()
        escaped_query = self._escape_like(str(query or ''))
        prefix_pattern = escaped_query + '%'
        contains_pattern = '%' + escaped_query + '%'

        # Search with different matching strategies
        cursor = await conn.execute("""
            SELECT tag, category, post_count, translation_cn, aliases,
                CASE
                    WHEN translation_cn = ? THEN 10
                    WHEN translation_cn LIKE ? ESCAPE '\\' THEN 8
                    WHEN translation_cn LIKE ? ESCAPE '\\' THEN 4
                    ELSE 2
                END as match_score
            FROM hot_tags
            WHERE translation_cn LIKE ? ESCAPE '\\'
              AND category != 1
            ORDER BY match_score DESC, post_count DESC
            LIMIT ?
        """, (query, prefix_pattern, contains_pattern, contains_pattern, limit))

        rows = await cursor.fetchall()

        results = []
        for row in rows:
            results.append({
                'tag': row['tag'],
                'category': row['category'],
                'post_count': row['post_count'],
                'translation_cn': self._visible_translation(
                    row['category'], row['translation_cn']
                ),
                'aliases': self._decode_aliases(row['aliases']),
                'match_score': row['match_score']
            })

        return results

    async def search_tags_optimized(self, query: str, limit: int = 10,
                                   search_type: str = "auto") -> List[Dict]:
        """
        Optimized tag search using FTS5 for fast queries

        Args:
            query: Search query (English prefix or Chinese text)
            limit: Maximum number of results
            search_type: "english", "chinese", or "auto" (auto-detect)

        Returns:
            List of matching tags with scores
        """
        conn = await self.get_connection()

        # Auto-detect search type
        if search_type == "auto":
            # Check if query contains Chinese characters
            has_chinese = any('\u4e00' <= char <= '\u9fff' for char in query)
            search_type = "chinese" if has_chinese else "english"

        if search_type == "english":
            return await self._search_english(query, limit)

        else:  # Chinese search using FTS5
            # Step 1: Try exact match first (highest priority)
            cursor = await conn.execute("""
                SELECT tag, category, post_count, translation_cn, aliases
                FROM hot_tags
                WHERE translation_cn = ?
                  AND category != 1
                ORDER BY post_count DESC
                LIMIT ?
            """, (query, limit))

            exact_matches = await cursor.fetchall()

            # Step 2: If not enough results, use FTS5 for fuzzy matching
            fts_results = []
            if len(exact_matches) < limit:
                remaining = limit - len(exact_matches)

                # Treat user text as one FTS5 phrase instead of executable
                # MATCH syntax.  Doubling quotes alone is insufficient:
                # parentheses, pipes, question marks, angle brackets, and
                # other punctuation in translated tags are FTS5 operators or
                # syntax and can otherwise raise sqlite3.OperationalError.
                fts_query = '"{}"'.format(str(query or '').replace('"', '""'))

                cursor = await conn.execute("""
                    SELECT h.tag, h.category, h.post_count, h.translation_cn, h.aliases,
                           f.rank as fts_rank
                    FROM hot_tags_fts f
                    JOIN hot_tags h ON f.rowid = h.rowid
                    WHERE hot_tags_fts MATCH ?
                      AND h.category != 1
                    ORDER BY f.rank, h.post_count DESC
                    LIMIT ?
                """, (fts_query, remaining))

                fts_results = await cursor.fetchall()

            # Merge results
            results = []
            seen_tags = set()

            # Add exact matches with highest score
            for row in exact_matches:
                tag = row['tag']
                if tag not in seen_tags:
                    results.append({
                        'tag': tag,
                        'category': row['category'],
                        'post_count': row['post_count'],
                        'translation_cn': self._visible_translation(
                            row['category'], row['translation_cn']
                        ),
                        'aliases': self._decode_aliases(row['aliases']),
                        'match_score': 10
                    })
                    seen_tags.add(tag)

            # Add FTS matches
            for row in fts_results:
                tag = row['tag']
                if tag not in seen_tags:
                    results.append({
                        'tag': tag,
                        'category': row['category'],
                        'post_count': row['post_count'],
                        'translation_cn': self._visible_translation(
                            row['category'], row['translation_cn']
                        ),
                        'aliases': self._decode_aliases(row['aliases']),
                        'match_score': 5  # Lower score for fuzzy matches
                    })
                    seen_tags.add(tag)

            return results[:limit]

    async def get_tag(self, tag: str) -> Optional[Dict]:
        """Get a specific tag"""
        conn = await self.get_connection()

        cursor = await conn.execute("""
            SELECT tag, category, post_count, translation_cn, aliases, last_updated
            FROM hot_tags
            WHERE tag = ?
        """, (tag,))

        row = await cursor.fetchone()
        if row:
            return {
                'tag': row['tag'],
                'category': row['category'],
                'post_count': row['post_count'],
                'translation_cn': self._visible_translation(
                    row['category'], row['translation_cn']
                ),
                'aliases': self._decode_aliases(row['aliases']),
                'last_updated': row['last_updated']
            }
        return None

    @staticmethod
    def _prepare_lookup_candidates(tags: List[str]):
        originals = []
        candidate_map = {}
        unique_candidates = []
        seen_candidates = set()

        for value in tags:
            if not isinstance(value, str):
                continue
            original = value.strip()
            if not original:
                continue
            normalized = unicodedata.normalize("NFKC", original).casefold()
            normalized = re.sub(r"\s+", " ", normalized)
            candidates = [normalized]
            underscored = normalized.replace(' ', '_')
            if underscored not in candidates:
                candidates.append(underscored)
            spaced = normalized.replace('_', ' ')
            if spaced not in candidates:
                candidates.append(spaced)
            originals.append(original)
            candidate_map[original] = candidates
            for candidate in candidates:
                if candidate not in seen_candidates:
                    seen_candidates.add(candidate)
                    unique_candidates.append(candidate)

        return originals, candidate_map, unique_candidates

    async def get_translations(self, tags: List[str]) -> Dict[str, str]:
        """Resolve exact tag translations without loading the whole database.

        The returned dictionary is keyed by the original input value. Both the
        canonical underscore form and the space-separated prompt form are
        checked so that Booru tags and Civitai prompt tokens can share the same
        local translation cache.
        """
        if not tags:
            return {}

        originals, candidate_map, unique_candidates = \
            self._prepare_lookup_candidates(tags)

        if not unique_candidates:
            return {}

        conn = await self.get_connection()
        direct_resolved = {}
        alias_resolved = {}
        # Stay below SQLite's host-parameter limit on older bundled builds.
        chunk_size = 400
        for offset in range(0, len(unique_candidates), chunk_size):
            chunk = unique_candidates[offset:offset + chunk_size]
            placeholders = ','.join('?' for _ in chunk)
            cursor = await conn.execute(f"""
                SELECT tag, translation_cn
                FROM hot_tags
                WHERE tag IN ({placeholders})
                  AND category != 1
                  AND translation_cn IS NOT NULL
                  AND LENGTH(TRIM(translation_cn)) > 0
            """, chunk)
            for row in await cursor.fetchall():
                direct_resolved[row['tag']] = row['translation_cn'].strip()

            cursor = await conn.execute(f"""
                SELECT a.alias, h.translation_cn
                FROM tag_aliases a
                JOIN hot_tags h ON h.tag = a.canonical_tag
                WHERE a.alias IN ({placeholders})
                  AND h.category != 1
                  AND h.translation_cn IS NOT NULL
                  AND LENGTH(TRIM(h.translation_cn)) > 0
            """, chunk)
            for row in await cursor.fetchall():
                alias_resolved[row['alias'].casefold()] = \
                    row['translation_cn'].strip()

        output = {}
        for original in originals:
            for candidate in candidate_map[original]:
                # An official alias resolves to its canonical tag even if an
                # old hot_tags row still exists under the alias spelling.
                translation = alias_resolved.get(candidate.casefold())
                if not translation:
                    translation = direct_resolved.get(candidate)
                if translation:
                    output[original] = translation
                    break
        return output

    async def get_categories(self, tags: List[str]) -> Dict[str, int]:
        """Resolve categories in bulk, including official alias inputs.

        The returned dictionary mirrors :meth:`get_translations`: keys are the
        original non-empty input strings and official aliases resolve to the
        canonical tag category.
        """
        if not tags:
            return {}

        originals, candidate_map, unique_candidates = \
            self._prepare_lookup_candidates(tags)
        if not unique_candidates:
            return {}

        conn = await self.get_connection()
        direct_resolved = {}
        alias_resolved = {}
        chunk_size = 400
        for offset in range(0, len(unique_candidates), chunk_size):
            chunk = unique_candidates[offset:offset + chunk_size]
            placeholders = ','.join('?' for _ in chunk)
            cursor = await conn.execute(f"""
                SELECT tag, category
                FROM hot_tags
                WHERE tag IN ({placeholders})
            """, chunk)
            for row in await cursor.fetchall():
                direct_resolved[row['tag']] = row['category']

            cursor = await conn.execute(f"""
                SELECT a.alias, h.category
                FROM tag_aliases a
                JOIN hot_tags h ON h.tag = a.canonical_tag
                WHERE a.alias IN ({placeholders})
            """, chunk)
            for row in await cursor.fetchall():
                alias_resolved[row['alias'].casefold()] = row['category']

        output = {}
        for original in originals:
            for candidate in candidate_map[original]:
                category = alias_resolved.get(candidate.casefold())
                if category is None:
                    category = direct_resolved.get(candidate)
                if category is not None:
                    output[original] = category
                    break
        return output

    async def get_tags_count(self) -> int:
        """Get total number of tags in database"""
        conn = await self.get_connection()
        cursor = await conn.execute("SELECT COUNT(*) FROM hot_tags")
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def get_all_tags(self, order_by_hot: bool = True) -> List[Dict]:
        """Get all tags from database"""
        conn = await self.get_connection()

        order_clause = "ORDER BY post_count DESC" if order_by_hot else ""
        cursor = await conn.execute(f"""
            SELECT tag, category, post_count, translation_cn, aliases
            FROM hot_tags
            {order_clause}
        """)

        rows = await cursor.fetchall()

        results = []
        for row in rows:
            results.append({
                'tag': row['tag'],
                'category': row['category'],
                'post_count': row['post_count'],
                'translation_cn': self._visible_translation(
                    row['category'], row['translation_cn']
                ),
                'aliases': self._decode_aliases(row['aliases'])
            })

        return results

    async def delete_old_tags(self, older_than_days: int = 90):
        """Delete tags that haven't been updated in X days"""
        conn = await self.get_connection()
        cutoff_time = int(time.time()) - (older_than_days * 86400)

        cursor = await conn.execute("""
            DELETE FROM hot_tags
            WHERE last_updated < ?
        """, (cutoff_time,))

        await conn.commit()
        return cursor.rowcount

    async def set_metadata(self, key: str, value: str):
        """Set metadata value"""
        conn = await self.get_connection()
        current_time = int(time.time())

        await conn.execute("""
            INSERT OR REPLACE INTO sync_metadata (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value, current_time))

        await conn.commit()

    async def get_metadata(self, key: str) -> Optional[str]:
        """Get metadata value"""
        conn = await self.get_connection()

        cursor = await conn.execute("""
            SELECT value FROM sync_metadata WHERE key = ?
        """, (key,))

        row = await cursor.fetchone()
        return row['value'] if row else None

    async def get_last_sync_time(self) -> int:
        """Get last sync timestamp"""
        value = await self.get_metadata('last_sync_time')
        return int(value) if value else 0

    async def set_last_sync_time(self, timestamp: Optional[int] = None):
        """Set last sync timestamp"""
        if timestamp is None:
            timestamp = int(time.time())
        await self.set_metadata('last_sync_time', str(timestamp))

    async def get_sync_progress(self) -> Dict:
        """Get current sync progress"""
        value = await self.get_metadata('sync_progress')
        return json.loads(value) if value else {}

    async def set_sync_progress(self, progress: Dict):
        """Set sync progress"""
        await self.set_metadata('sync_progress', json.dumps(progress))

    async def clear_sync_progress(self):
        """Clear sync progress"""
        conn = await self.get_connection()
        await conn.execute("DELETE FROM sync_metadata WHERE key = 'sync_progress'")
        await conn.commit()

    async def rebuild_fts_index(self):
        """
        Rebuild FTS5 index from existing data
        Useful for migrating existing databases to FTS5
        """
        conn = await self.get_connection()

        logger.info("Rebuilding FTS5 index...")

        # Clear existing FTS data
        await conn.execute("DELETE FROM hot_tags_fts")

        # Rebuild from hot_tags table
        await conn.execute("""
            INSERT INTO hot_tags_fts(rowid, tag, translation_cn)
            SELECT rowid, tag, translation_cn FROM hot_tags
        """)

        await conn.commit()

        # Get count
        cursor = await conn.execute("SELECT COUNT(*) FROM hot_tags_fts")
        row = await cursor.fetchone()
        count = row[0] if row else 0

        logger.info(f"✓ FTS5 index rebuilt with {count} entries")
        return count

    async def check_database_health(self) -> Tuple[bool, Optional[str]]:
        """
        Check database integrity and health

        Returns:
            Tuple[bool, Optional[str]]: (is_healthy, error_message)
        """
        try:
            conn = await self.get_connection()

            # Test 1: PRAGMA integrity_check
            cursor = await conn.execute("PRAGMA integrity_check")
            row = await cursor.fetchone()
            integrity_result = row[0] if row else None

            if integrity_result != "ok":
                return False, f"Database integrity check failed: {integrity_result}"

            # Test 2: Check if tables exist
            cursor = await conn.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name IN (
                    'hot_tags', 'hot_tags_fts', 'sync_metadata', 'tag_aliases'
                )
            """)
            tables = [row[0] for row in await cursor.fetchall()]

            required_tables = [
                'hot_tags', 'hot_tags_fts', 'sync_metadata', 'tag_aliases'
            ]
            missing_tables = [t for t in required_tables if t not in tables]

            if missing_tables:
                return False, f"Missing required tables: {', '.join(missing_tables)}"

            # Test 3: Try a simple query on each table
            try:
                await conn.execute("SELECT COUNT(*) FROM hot_tags")
                await conn.execute("SELECT COUNT(*) FROM hot_tags_fts")
                await conn.execute("SELECT COUNT(*) FROM sync_metadata")
                await conn.execute("SELECT COUNT(*) FROM tag_aliases")
            except Exception as e:
                return False, f"Query test failed: {str(e)}"

            # All tests passed
            return True, None

        except Exception as e:
            return False, f"Health check error: {str(e)}"

    async def recover_from_corruption(self) -> bool:
        """
        Attempt to recover from database corruption by removing the corrupted file

        Returns:
            bool: True if recovery was successful (file removed), False otherwise
        """
        try:
            # Close existing connection
            await self.close()

            # Check if database file exists
            db_file = Path(self.db_path)
            if not db_file.exists():
                logger.info("Database file does not exist, no recovery needed")
                return True

            # Try to remove the corrupted database file
            logger.info(f"Attempting to remove corrupted database: {self.db_path}")

            import time
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    os.remove(self.db_path)
                    logger.info("✓ Corrupted database file removed successfully")
                    return True
                except PermissionError:
                    if attempt < max_attempts - 1:
                        logger.info(f"File is busy, retrying... ({attempt + 1}/{max_attempts})")
                        time.sleep(1)
                    else:
                        logger.error("✗ Failed to remove database file (still in use)")
                        return False
                except Exception as e:
                    logger.error(f"✗ Failed to remove database file: {e}")
                    return False

            return False

        except Exception as e:
            logger.error(f"✗ Recovery failed: {e}")
            return False


# Global database manager instance
_db_manager = None


def get_db_manager() -> TagDatabaseManager:
    """Get global database manager instance"""
    global _db_manager
    if _db_manager is None:
        _db_manager = TagDatabaseManager()
    return _db_manager
