"""Read-only federation between Danbooru Gallery and the WeiLin tag catalog.

WeiLin stores both atomic booru tags and very long prompt presets.  This module
keeps those two concepts separate: atomic rows may be linked to a Gallery tag,
while prompt presets are always returned as their untouched ``raw_text``.  No
WeiLin row is copied into the runtime Gallery database by this bridge.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
CUSTOM_NODES_ROOT = PLUGIN_ROOT.parent
WEILIN_PLUGIN_ROOT = CUSTOM_NODES_ROOT / "WeiLin-Comfyui-Tools-V52-FullPromptSelector"
DEFAULT_WEILIN_TAGS_DB = WEILIN_PLUGIN_ROOT / "user_data" / "userdatas_zh_CN_tags.db"
DEFAULT_WEILIN_DANBOORU_DB = (
    WEILIN_PLUGIN_ROOT / "user_data" / "userdatas_zh_CN_danbooru.db"
)
DEFAULT_GALLERY_DB = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"

WEILIN_SOURCE_URL = "https://github.com/weilin9999/WeiLin-Comfyui-Tools-Prompt"
WEILIN_LICENSE = "MIT"
MAX_PAGE_SIZE = 50
MAX_QUERY_CHARS = 256
PROMPT_LENGTH_THRESHOLD = 120
PROMPT_WORD_THRESHOLD = 6

# WeiLin's current public taxonomy identifies these as artist/style prompt
# buckets.  Name checks below keep the exclusion fail-closed if ids move in a
# future source snapshot.
ARTIST_SUBGROUP_IDS = frozenset((77, 493))
ARTIST_SUBGROUP_MARKERS = ("艺术家", "画师")

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_WEIGHT_RE = re.compile(r"(?:^|[,\s])(?:BREAK|AND)\b|\([^\n]{1,100}:\s*-?\d+(?:\.\d+)?\)", re.I)


class WeiLinCatalogError(RuntimeError):
    """Raised for unavailable, incompatible, or unsafe WeiLin catalog data."""


def _clean_path(path: Path) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.casefold() not in {".db", ".sqlite", ".sqlite3"}:
        raise WeiLinCatalogError("catalog database must be a SQLite file")
    if not resolved.is_file():
        raise WeiLinCatalogError("catalog database is unavailable: {}".format(resolved))
    return resolved


def _open_readonly(path: Path) -> sqlite3.Connection:
    resolved = _clean_path(path)
    connection = sqlite3.connect(
        resolved.as_uri() + "?mode=ro",
        uri=True,
        timeout=10.0,
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute('PRAGMA table_info("{}")'.format(table))}


def _require_columns(
    connection: sqlite3.Connection, table: str, expected: Iterable[str]
) -> None:
    actual = _columns(connection, table)
    missing = sorted(set(expected) - actual)
    if missing:
        raise WeiLinCatalogError(
            "{} is missing required columns: {}".format(table, ", ".join(missing))
        )


def classify_weilin_text(raw_text: object) -> str:
    """Classify without ever normalizing or changing the returned source text."""

    text = str(raw_text or "")
    classification_text = text.strip()
    if (
        classification_text.endswith((",", "，"))
        and classification_text.count(",") + classification_text.count("，") == 1
    ):
        classification_text = classification_text[:-1].rstrip()
    words = [part for part in _WHITESPACE_RE.split(classification_text) if part]
    if (
        len(classification_text) > PROMPT_LENGTH_THRESHOLD
        or len(words) > PROMPT_WORD_THRESHOLD
        or "," in classification_text
        or "，" in classification_text
        or ";" in classification_text
        or "；" in classification_text
        or "\n" in classification_text
        or "\r" in classification_text
        or _WEIGHT_RE.search(classification_text)
    ):
        return "prompt_phrase"
    return "atomic_tag"


def normalize_atomic_candidate(raw_text: object) -> Optional[str]:
    """Return a conservative booru key, or ``None`` for prompt-like content."""

    original = str(raw_text or "")
    if classify_weilin_text(original) != "atomic_tag":
        return None
    normalized = unicodedata.normalize("NFKC", original).strip()
    if not normalized or _CONTROL_RE.search(normalized):
        return None
    if normalized.endswith(",") and normalized.count(",") == 1:
        normalized = normalized[:-1].rstrip()
    normalized = normalized.replace(r"\(", "(").replace(r"\)", ")")
    if any(mark in normalized for mark in (",", ";", "\n", "\r")):
        return None
    normalized = _WHITESPACE_RE.sub("_", normalized).casefold()
    if not normalized or len(normalized.encode("utf-8")) > 256:
        return None
    return normalized


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _safe_positive_int(value: object, *, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(max(parsed, 1), maximum)


def _required_positive_int(value: object, field: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise WeiLinCatalogError("{} must be a positive integer".format(field)) from exc
    if parsed < 1 or parsed > 2_147_483_647:
        raise WeiLinCatalogError("{} must be a positive integer".format(field))
    return parsed


class WeiLinTagBridge:
    """Lazy, read-only catalog access with Gallery tag identity linking."""

    def __init__(
        self,
        *,
        tags_db_path: Path | str = DEFAULT_WEILIN_TAGS_DB,
        danbooru_db_path: Path | str = DEFAULT_WEILIN_DANBOORU_DB,
        gallery_db_path: Path | str = DEFAULT_GALLERY_DB,
    ) -> None:
        self.tags_db_path = Path(tags_db_path)
        self.danbooru_db_path = Path(danbooru_db_path)
        self.gallery_db_path = Path(gallery_db_path)
        self._facet_cache: Optional[
            Tuple[Tuple[Tuple[str, int, int], ...], Dict[str, object]]
        ] = None
        self._artist_cache: Optional[
            Tuple[Tuple[Tuple[str, int, int], ...], FrozenSet[str]]
        ] = None
        self._cache_lock = threading.Lock()

    @staticmethod
    def _database_signatures(path: Path) -> Tuple[Tuple[str, int, int], ...]:
        resolved = _clean_path(path)
        signatures: List[Tuple[str, int, int]] = []
        # A WAL commit can leave the main database's size and mtime unchanged.
        # Include an explicit absent/present signature for the WAL companion so
        # cache invalidation follows committed SQLite state.  SHM contains lock
        # and index state rather than committed rows and is intentionally not a
        # data-version input.
        for component, candidate in (
            ("main", resolved),
            ("wal", Path(str(resolved) + "-wal")),
        ):
            try:
                stat = candidate.stat()
                size = int(stat.st_size)
                # WeiLin may keep touching an empty WAL while idle.  It holds
                # no committed frames, so normalize it to the absent sentinel
                # to retain the facet cache without hiding real WAL commits.
                if component == "wal" and size == 0:
                    signatures.append((component, -1, -1))
                else:
                    signatures.append((component, size, int(stat.st_mtime_ns)))
            except FileNotFoundError:
                signatures.append((component, -1, -1))
        return tuple(signatures)

    def _signatures(self) -> Tuple[Tuple[str, int, int], ...]:
        signatures: List[Tuple[str, int, int]] = []
        for path in (self.tags_db_path, self.danbooru_db_path, self.gallery_db_path):
            signatures.extend(self._database_signatures(path))
        return tuple(signatures)

    @staticmethod
    def _validate_tags_schema(connection: sqlite3.Connection) -> None:
        _require_columns(connection, "tag_groups", ("id_index", "name", "color", "p_uuid"))
        _require_columns(
            connection,
            "tag_subgroups",
            ("id_index", "group_id", "name", "color", "p_uuid", "g_uuid"),
        )
        _require_columns(
            connection,
            "tag_tags",
            ("id_index", "subgroup_id", "text", "desc", "color", "t_uuid", "g_uuid"),
        )

    @staticmethod
    def _validate_danbooru_schema(connection: sqlite3.Connection) -> None:
        _require_columns(
            connection,
            "danbooru_tag",
            ("tag", "color_id", "translate", "hot", "aliases"),
        )

    @staticmethod
    def _validate_gallery_schema(connection: sqlite3.Connection) -> None:
        _require_columns(
            connection,
            "hot_tags",
            ("tag", "category", "post_count", "translation_cn"),
        )

    def status(self) -> Dict[str, object]:
        try:
            signatures = self._signatures()
            with _open_readonly(self.tags_db_path) as connection:
                self._validate_tags_schema(connection)
            with _open_readonly(self.danbooru_db_path) as connection:
                self._validate_danbooru_schema(connection)
            with _open_readonly(self.gallery_db_path) as connection:
                self._validate_gallery_schema(connection)
            return {
                "available": True,
                "source": "weilin",
                "source_url": WEILIN_SOURCE_URL,
                "license": WEILIN_LICENSE,
                "database_signatures": [
                    {"component": component, "bytes": size, "mtime_ns": mtime_ns}
                    for component, size, mtime_ns in signatures
                ],
            }
        except (OSError, sqlite3.Error, WeiLinCatalogError) as exc:
            return {
                "available": False,
                "source": "weilin",
                "source_url": WEILIN_SOURCE_URL,
                "license": WEILIN_LICENSE,
                "error": str(exc),
            }

    @staticmethod
    def _artist_subgroup_clause(alias: str = "s") -> str:
        return (
            f"{alias}.id_index NOT IN ({','.join('?' for _ in ARTIST_SUBGROUP_IDS)}) "
            f"AND COALESCE({alias}.name, '') NOT LIKE ? "
            f"AND COALESCE({alias}.name, '') NOT LIKE ?"
        )

    @staticmethod
    def _artist_subgroup_params() -> Tuple[object, ...]:
        return tuple(sorted(ARTIST_SUBGROUP_IDS)) + tuple(
            "%{}%".format(marker) for marker in ARTIST_SUBGROUP_MARKERS
        )

    def _authoritative_artist_tags(self) -> FrozenSet[str]:
        """Return exact artist keys from Gallery and WeiLin's Danbooru index.

        The set is registered as a deterministic SQLite callback on the WeiLin
        taxonomy connection.  This keeps artist exclusion *inside* the query,
        before counting or pagination, without attaching either source database
        writable or copying any WeiLin rows into Gallery.
        """

        signatures: List[Tuple[str, int, int]] = []
        for path in (self.gallery_db_path, self.danbooru_db_path):
            signatures.extend(self._database_signatures(path))
        signature_tuple = tuple(signatures)
        with self._cache_lock:
            if self._artist_cache and self._artist_cache[0] == signature_tuple:
                return self._artist_cache[1]

        artists: set[str] = set()
        with _open_readonly(self.gallery_db_path) as connection:
            self._validate_gallery_schema(connection)
            artists.update(
                str(row[0]).casefold()
                for row in connection.execute(
                    "SELECT tag FROM hot_tags WHERE category = 1"
                )
                if row[0]
            )
        with _open_readonly(self.danbooru_db_path) as connection:
            self._validate_danbooru_schema(connection)
            artists.update(
                str(row[0]).casefold()
                for row in connection.execute(
                    "SELECT tag FROM danbooru_tag WHERE color_id = 1"
                )
                if row[0]
            )
        frozen = frozenset(artists)
        with self._cache_lock:
            self._artist_cache = (signature_tuple, frozen)
        return frozen

    def _register_catalog_functions(self, connection: sqlite3.Connection) -> None:
        artist_tags = self._authoritative_artist_tags()

        def is_authoritative_artist(raw_text: object) -> int:
            candidate = normalize_atomic_candidate(raw_text)
            return int(bool(candidate and candidate in artist_tags))

        connection.create_function("weilin_kind", 1, classify_weilin_text, deterministic=True)
        connection.create_function(
            "weilin_is_artist", 1, is_authoritative_artist, deterministic=True
        )

    def facets(self) -> Dict[str, object]:
        signatures = self._signatures()
        with self._cache_lock:
            if self._facet_cache and self._facet_cache[0] == signatures:
                return self._facet_cache[1]

        with _open_readonly(self.tags_db_path) as connection:
            self._validate_tags_schema(connection)
            self._register_catalog_functions(connection)
            rows = connection.execute(
                """
                SELECT
                    g.id_index AS group_id,
                    g.name AS group_name,
                    g.color AS group_color,
                    g.p_uuid AS group_uuid,
                    s.id_index AS subgroup_id,
                    s.name AS subgroup_name,
                    s.color AS subgroup_color,
                    s.g_uuid AS subgroup_uuid,
                    COUNT(t.id_index) AS item_count,
                    SUM(CASE WHEN weilin_kind(t.text) = 'prompt_phrase' THEN 1 ELSE 0 END)
                        AS prompt_count
                FROM tag_groups g
                JOIN tag_subgroups s ON s.group_id = g.id_index
                LEFT JOIN tag_tags t ON t.subgroup_id = s.id_index
                WHERE {} AND weilin_is_artist(t.text) = 0
                GROUP BY g.id_index, s.id_index
                ORDER BY g.id_index, s.id_index
                """.format(self._artist_subgroup_clause("s")),
                self._artist_subgroup_params(),
            ).fetchall()

        groups: List[Dict[str, object]] = []
        group_lookup: Dict[int, Dict[str, object]] = {}
        total_items = 0
        total_prompts = 0
        for row in rows:
            group_id = int(row["group_id"])
            group = group_lookup.get(group_id)
            if group is None:
                group = {
                    "id": group_id,
                    "name": str(row["group_name"] or ""),
                    "color": str(row["group_color"] or ""),
                    "uuid": str(row["group_uuid"] or ""),
                    "item_count": 0,
                    "prompt_count": 0,
                    "subgroups": [],
                }
                group_lookup[group_id] = group
                groups.append(group)
            item_count = int(row["item_count"] or 0)
            prompt_count = int(row["prompt_count"] or 0)
            group["item_count"] = int(group["item_count"]) + item_count
            group["prompt_count"] = int(group["prompt_count"]) + prompt_count
            group["subgroups"].append(
                {
                    "id": int(row["subgroup_id"]),
                    "name": str(row["subgroup_name"] or ""),
                    "color": str(row["subgroup_color"] or ""),
                    "uuid": str(row["subgroup_uuid"] or ""),
                    "item_count": item_count,
                    "prompt_count": prompt_count,
                }
            )
            total_items += item_count
            total_prompts += prompt_count

        result: Dict[str, object] = {
            "available": True,
            "source": "weilin",
            "source_url": WEILIN_SOURCE_URL,
            "license": WEILIN_LICENSE,
            "groups": groups,
            "summary": {
                "groups": len(groups),
                "subgroups": len(rows),
                "items": total_items,
                "atomic_tags": total_items - total_prompts,
                "prompt_phrases": total_prompts,
                "artist_subgroups_excluded": len(ARTIST_SUBGROUP_IDS),
            },
            "preservation": {
                "raw_text_unchanged": True,
                "prompt_text_truncated": False,
                "site_filters_accept_prompt_phrases": False,
            },
        }
        with self._cache_lock:
            self._facet_cache = (signatures, result)
        return result

    def _gallery_rows(self, tags: Sequence[str]) -> Mapping[str, sqlite3.Row]:
        if not tags:
            return {}
        with _open_readonly(self.gallery_db_path) as connection:
            self._validate_gallery_schema(connection)
            placeholders = ",".join("?" for _ in tags)
            rows = connection.execute(
                "SELECT tag,category,post_count,translation_cn FROM hot_tags "
                "WHERE tag IN ({})".format(placeholders),
                tuple(tags),
            ).fetchall()
        return {str(row["tag"]).casefold(): row for row in rows}

    def _danbooru_rows(self, tags: Sequence[str]) -> Mapping[str, sqlite3.Row]:
        if not tags:
            return {}
        with _open_readonly(self.danbooru_db_path) as connection:
            self._validate_danbooru_schema(connection)
            placeholders = ",".join("?" for _ in tags)
            rows = connection.execute(
                "SELECT tag,color_id,translate,hot,aliases FROM danbooru_tag "
                "WHERE tag IN ({})".format(placeholders),
                tuple(tags),
            ).fetchall()
        return {str(row["tag"]).casefold(): row for row in rows}

    def _enrich(self, rows: Sequence[sqlite3.Row]) -> List[Dict[str, object]]:
        candidates = [normalize_atomic_candidate(row["raw_text"]) for row in rows]
        distinct = sorted({candidate for candidate in candidates if candidate})
        gallery = self._gallery_rows(distinct)
        danbooru = self._danbooru_rows(distinct)

        results: List[Dict[str, object]] = []
        for row, candidate in zip(rows, candidates):
            gallery_row = gallery.get(candidate or "")
            danbooru_row = danbooru.get(candidate or "")
            # Gallery is authoritative for identity.  A WeiLin row that maps to
            # a known artist is not exposed through the integrated catalog.
            # WeiLin's Danbooru category is a second exact-key safety source.
            if (
                gallery_row is not None
                and int(gallery_row["category"]) == 1
            ) or (
                danbooru_row is not None
                and int(danbooru_row["color_id"]) == 1
            ):
                continue
            gallery_category = int(gallery_row["category"]) if gallery_row else None
            danbooru_category = int(danbooru_row["color_id"]) if danbooru_row else None
            site_filterable = bool(
                candidate
                and (
                    gallery_category in (0, 3, 4, 5)
                    or (gallery_row is None and danbooru_category in (0, 4))
                )
            )
            results.append(
                {
                    "id": int(row["item_id"]),
                    "t_uuid": str(row["t_uuid"] or ""),
                    "source": "weilin",
                    "kind": classify_weilin_text(row["raw_text"]),
                    "raw_text": str(row["raw_text"] or ""),
                    "raw_desc": str(row["raw_desc"] or ""),
                    "color": str(row["item_color"] or ""),
                    "group": {
                        "id": int(row["group_id"]),
                        "name": str(row["group_name"] or ""),
                        "uuid": str(row["group_uuid"] or ""),
                    },
                    "subgroup": {
                        "id": int(row["subgroup_id"]),
                        "name": str(row["subgroup_name"] or ""),
                        "uuid": str(row["subgroup_uuid"] or ""),
                    },
                    "gallery_tag": candidate if site_filterable else None,
                    "gallery_category": gallery_category,
                    "gallery_translation": (
                        str(gallery_row["translation_cn"] or "") or None
                        if gallery_row is not None
                        else None
                    ),
                    "post_count": int(gallery_row["post_count"]) if gallery_row else None,
                    "site_filterable": site_filterable,
                    "copy_text": str(row["raw_text"] or ""),
                }
            )
        return results

    def search(
        self,
        *,
        query: object = "",
        group_id: object = None,
        subgroup_id: object = None,
        kind: object = "all",
        page: object = 1,
        cursor: object = None,
        limit: object = 30,
    ) -> Dict[str, object]:
        page_value = _required_positive_int(page, "page")
        limit_value = _safe_positive_int(limit, default=30, maximum=MAX_PAGE_SIZE)
        cursor_value: Optional[int] = None
        if cursor not in (None, ""):
            cursor_value = _required_positive_int(cursor, "cursor")
        query_value = unicodedata.normalize("NFKC", str(query or "")).strip()
        if len(query_value) > MAX_QUERY_CHARS or _CONTROL_RE.search(query_value):
            raise WeiLinCatalogError("query is invalid or exceeds {} characters".format(MAX_QUERY_CHARS))
        kind_value = str(kind or "all").strip().casefold()
        if kind_value not in {"all", "atomic_tag", "prompt_phrase"}:
            raise WeiLinCatalogError("kind must be all, atomic_tag, or prompt_phrase")

        clauses = [self._artist_subgroup_clause("s")]
        params: List[object] = list(self._artist_subgroup_params())
        if query_value:
            pattern = "%{}%".format(_escape_like(query_value))
            clauses.append("(t.text LIKE ? ESCAPE '\\' OR t.desc LIKE ? ESCAPE '\\')")
            params.extend((pattern, pattern))
        if group_id not in (None, ""):
            parsed_group = _required_positive_int(group_id, "group_id")
            clauses.append("g.id_index = ?")
            params.append(parsed_group)
        if subgroup_id not in (None, ""):
            parsed_subgroup = _required_positive_int(subgroup_id, "subgroup_id")
            clauses.append("s.id_index = ?")
            params.append(parsed_subgroup)
        if kind_value != "all":
            clauses.append("weilin_kind(t.text) = ?")
            params.append(kind_value)

        # Cursor requests use stable keyset pagination.  ``page`` remains for
        # backwards compatibility and display only; legacy callers without a
        # cursor retain OFFSET semantics without the former silent page-1000
        # clamp.  The UI switches to cursor mode after its first page.
        clauses.append("weilin_is_artist(t.text) = 0")
        fetch_limit = limit_value + 1
        initial_offset = 0 if cursor_value is not None else (page_value - 1) * limit_value
        scan_after = cursor_value
        enriched: List[Dict[str, object]] = []
        with _open_readonly(self.tags_db_path) as connection:
            self._validate_tags_schema(connection)
            self._register_catalog_functions(connection)
            while len(enriched) < fetch_limit:
                scan_clauses = list(clauses)
                scan_params = list(params)
                if scan_after is not None:
                    scan_clauses.append("t.id_index > ?")
                    scan_params.append(scan_after)
                scan_params.extend((fetch_limit, initial_offset))
                rows = connection.execute(
                    """
                    SELECT
                        t.id_index AS item_id,
                        t.t_uuid AS t_uuid,
                        t.text AS raw_text,
                        t.desc AS raw_desc,
                        t.color AS item_color,
                        g.id_index AS group_id,
                        g.name AS group_name,
                        g.p_uuid AS group_uuid,
                        s.id_index AS subgroup_id,
                        s.name AS subgroup_name,
                        s.g_uuid AS subgroup_uuid
                    FROM tag_tags t
                    JOIN tag_subgroups s ON s.id_index = t.subgroup_id
                    JOIN tag_groups g ON g.id_index = s.group_id
                    WHERE {}
                    ORDER BY t.id_index
                    LIMIT ? OFFSET ?
                    """.format(" AND ".join(scan_clauses)),
                    tuple(scan_params),
                ).fetchall()
                initial_offset = 0
                if not rows:
                    break
                enriched_batch = self._enrich(rows)
                enriched.extend(enriched_batch)
                scan_after = int(rows[-1]["item_id"])
                if len(enriched_batch) != len(rows):
                    # An authoritative source changed after the SQL callback
                    # was registered.  Refresh it before scanning onward and
                    # keep filling until limit+1 final visible rows are known.
                    self._register_catalog_functions(connection)
                if len(rows) < fetch_limit:
                    break

        has_more = len(enriched) > limit_value
        items = enriched[:limit_value]
        next_cursor = str(items[-1]["id"]) if has_more and items else None
        return {
            "success": True,
            "source": "weilin",
            "query": query_value,
            "kind": kind_value,
            "page": page_value,
            "limit": limit_value,
            "has_more": has_more,
            "next_cursor": next_cursor,
            "items": items,
            "preservation": {
                "raw_text_unchanged": True,
                "prompt_text_truncated": False,
                "site_filters_accept_prompt_phrases": False,
            },
        }

    def get_item(self, t_uuid: object) -> Optional[Dict[str, object]]:
        uuid_value = str(t_uuid or "").strip()
        if not uuid_value or len(uuid_value) > 128 or _CONTROL_RE.search(uuid_value):
            raise WeiLinCatalogError("invalid t_uuid")
        params = list(self._artist_subgroup_params())
        params.append(uuid_value)
        with _open_readonly(self.tags_db_path) as connection:
            self._validate_tags_schema(connection)
            self._register_catalog_functions(connection)
            row = connection.execute(
                """
                SELECT
                    t.id_index AS item_id,
                    t.t_uuid AS t_uuid,
                    t.text AS raw_text,
                    t.desc AS raw_desc,
                    t.color AS item_color,
                    g.id_index AS group_id,
                    g.name AS group_name,
                    g.p_uuid AS group_uuid,
                    s.id_index AS subgroup_id,
                    s.name AS subgroup_name,
                    s.g_uuid AS subgroup_uuid
                FROM tag_tags t
                JOIN tag_subgroups s ON s.id_index = t.subgroup_id
                JOIN tag_groups g ON g.id_index = s.group_id
                WHERE {} AND weilin_is_artist(t.text) = 0 AND t.t_uuid = ?
                LIMIT 1
                """.format(self._artist_subgroup_clause("s")),
                tuple(params),
            ).fetchone()
        if row is None:
            return None
        enriched = self._enrich((row,))
        return enriched[0] if enriched else None


__all__ = [
    "WeiLinCatalogError",
    "WeiLinTagBridge",
    "classify_weilin_text",
    "normalize_atomic_candidate",
]
