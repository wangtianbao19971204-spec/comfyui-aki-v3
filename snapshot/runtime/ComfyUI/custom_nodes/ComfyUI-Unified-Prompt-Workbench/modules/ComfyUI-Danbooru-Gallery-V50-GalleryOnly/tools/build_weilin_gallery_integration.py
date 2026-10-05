#!/usr/bin/env python3
"""Build a read-only, auditable WeiLin -> Gallery integration bundle.

This command never imports data and never modifies any SQLite database.  It
emits three new artifacts:

* an importer-compatible CSV containing only exact three-way translation
  consensus (WeiLin tag taxonomy, WeiLin Danbooru database, and an existing
  triple-consensus CSV);
* a JSONL taxonomy snapshot that retains WeiLin ``raw_text`` verbatim,
  including long prompt phrases;
* a deterministic JSON report with source hashes and rejection counts.

Gallery tag identity, category, post count, and existing translations are
authoritative.  Artist rows are excluded.  No fuzzy matching, identity merge,
long-prompt truncation, or in-place overwrite is performed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, IO, Mapping, MutableMapping, Optional, Sequence, Set, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GALLERY_DB = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"

WEILIN_UPSTREAM_URL = "https://github.com/weilin9999/WeiLin-Comfyui-Tools-Prompt"
WEILIN_DATA_LICENSE = "MIT"

ARTIST_CATEGORY = 1
ALLOWED_CATEGORIES = frozenset((0, 3, 4, 5))
MAX_TAG_BYTES = 256
MAX_TRANSLATION_CHARACTERS = 24
MAX_TRANSLATION_BYTES = 192
LONG_TEXT_CHARACTERS = 120
LONG_TEXT_WORDS = 6

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_SUSPICIOUS_RE = re.compile(
    r"(?:\{\\\|@\s*(?:info|label)|whatsthis|\ufffd|<\s*/?\s*(?:script|style))",
    re.IGNORECASE,
)
_PROMPT_SEPARATOR_RE = re.compile(r"[,，;；\r\n]")
_WORD_SPLIT_RE = re.compile(r"[\s,，;；]+")
_SCOPE_SEPARATORS_RE = re.compile(r"[\s_\-]+")

# Exact normalized group/subgroup labels only.  Substring matching would risk
# hiding legitimate categories such as "artist reference pose".
ARTIST_SCOPE_LABELS = frozenset(
    {
        "artist",
        "artists",
        "artistname",
        "artistnames",
        "author",
        "authors",
        "creator",
        "creators",
        "illustrator",
        "illustrators",
        "艺术家",
        "画师",
        "绘师",
        "作者",
        "创作者",
        "插画师",
        "原画师",
        "绘图师",
        "艺术家风格",
        "一键画师串",
    }
)
ARTIST_SUBGROUP_IDS = frozenset((77, 493))


class WeiLinIntegrationBuildError(RuntimeError):
    """Raised before a complete integration bundle can be published."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _lexists(path: Path) -> bool:
    return os.path.lexists(str(path))


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    left = Path(left).expanduser().resolve()
    right = Path(right).expanduser().resolve()
    if str(left).casefold() == str(right).casefold():
        return True
    try:
        return _lexists(left) and _lexists(right) and os.path.samefile(left, right)
    except OSError:
        return False


def _validate_distinct_paths(named_paths: Sequence[Tuple[str, Path]]) -> None:
    resolved = [(name, Path(path).expanduser().resolve()) for name, path in named_paths]
    for index, (left_name, left_path) in enumerate(resolved):
        for right_name, right_path in resolved[index + 1 :]:
            if _paths_refer_to_same_file(left_path, right_path):
                raise WeiLinIntegrationBuildError(
                    "{} and {} must be distinct files (resolved path/hard-link collision)".format(
                        left_name, right_name
                    )
                )


def _ensure_outputs_absent(named_outputs: Sequence[Tuple[str, Path]]) -> None:
    existing = ["{}={}".format(name, path) for name, path in named_outputs if _lexists(path)]
    if existing:
        raise WeiLinIntegrationBuildError(
            "refusing to overwrite existing artifact(s): {}".format(", ".join(existing))
        )


def _require_input_files(named_inputs: Sequence[Tuple[str, Path]]) -> None:
    missing = ["{}={}".format(name, path) for name, path in named_inputs if not path.is_file()]
    if missing:
        raise WeiLinIntegrationBuildError(
            "required input file(s) do not exist: {}".format(", ".join(missing))
        )


def _new_temporary_text(path: Path, *, encoding: str) -> Tuple[IO[str], Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding=encoding,
        newline="",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    )
    return handle, Path(handle.name)


def _finish_temporary(handle: IO[str]) -> None:
    handle.flush()
    os.fsync(handle.fileno())
    handle.close()


def _publish_bundle_no_replace(
    artifacts: Sequence[Tuple[Path, Path]],
    *,
    all_named_paths: Sequence[Tuple[str, Path]],
    named_outputs: Sequence[Tuple[str, Path]],
) -> None:
    """Publish complete temp files atomically without replacing a target.

    A same-directory hard link is an atomic, no-replace publication primitive
    on the supported filesystems.  Keeping each temp link until every target
    is published also permits safe rollback if a later publication races.
    """

    _validate_distinct_paths(all_named_paths)
    _ensure_outputs_absent(named_outputs)
    published: list[Tuple[Path, Path]] = []
    try:
        for temporary, target in artifacts:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise WeiLinIntegrationBuildError(
                    "refusing to overwrite artifact created during build: {}".format(target)
                ) from exc
            except OSError as exc:
                raise WeiLinIntegrationBuildError(
                    "could not atomically publish {}: {}".format(target, exc)
                ) from exc
            published.append((temporary, target))
    except Exception:
        for temporary, target in reversed(published):
            try:
                if _lexists(target) and os.path.samefile(temporary, target):
                    target.unlink()
            except OSError:
                pass
        raise
    finally:
        for temporary, _target in artifacts:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass


def normalize_tag(value: object) -> str:
    tag = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return _WHITESPACE_RE.sub("_", tag)


def normalize_translation(value: object) -> str:
    translation = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE_RE.sub(" ", translation)


def _scope_label(value: object) -> str:
    label = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return _SCOPE_SEPARATORS_RE.sub("", label)


def _artist_scope_reason(
    group_name: object,
    subgroup_name: object,
    subgroup_id: object = None,
) -> Optional[str]:
    try:
        if int(subgroup_id) in ARTIST_SUBGROUP_IDS:
            return "artist_subgroup"
    except (TypeError, ValueError):
        pass
    if _scope_label(group_name) in ARTIST_SCOPE_LABELS:
        return "artist_group"
    if _scope_label(subgroup_name) in ARTIST_SCOPE_LABELS:
        return "artist_subgroup"
    return None


def is_prompt_phrase(raw_text: object) -> bool:
    """Classify composite/long prompt text without changing the original."""

    if not isinstance(raw_text, str):
        return False
    normalized = unicodedata.normalize("NFKC", raw_text)
    if len(normalized) > LONG_TEXT_CHARACTERS:
        return True
    if _PROMPT_SEPARATOR_RE.search(normalized):
        return True
    words = [part for part in _WORD_SPLIT_RE.split(normalized.strip()) if part]
    return len(words) > LONG_TEXT_WORDS


def validate_short_chinese(value: object) -> Tuple[Optional[str], str]:
    translation = normalize_translation(value)
    if not translation:
        return None, "empty_translation"
    if len(translation) > MAX_TRANSLATION_CHARACTERS:
        return None, "translation_too_long"
    if len(translation.encode("utf-8")) > MAX_TRANSLATION_BYTES:
        return None, "translation_too_many_bytes"
    if _CONTROL_RE.search(translation):
        return None, "translation_control_character"
    if not _HAN_RE.search(translation):
        return None, "translation_no_han"
    if _KANA_RE.search(translation):
        return None, "translation_contains_kana"
    if _HANGUL_RE.search(translation):
        return None, "translation_contains_hangul"
    if _LATIN_RE.search(translation):
        return None, "translation_contains_latin"
    if _SUSPICIOUS_RE.search(translation):
        return None, "translation_suspicious_artifact"
    if "_" in translation:
        return None, "translation_source_separator_leaked"
    if _PROMPT_SEPARATOR_RE.search(translation):
        return None, "translation_looks_like_phrase"
    for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
        if translation.count(opening) != translation.count(closing):
            return None, "translation_unbalanced_brackets"
    return translation, "accepted"


def _readonly_connection(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30.0
        )
    except sqlite3.Error as exc:
        raise WeiLinIntegrationBuildError(
            "could not open SQLite input read-only {}: {}".format(path, exc)
        ) from exc
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _require_columns(
    connection: sqlite3.Connection, table: str, required: Set[str]
) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info({})".format(table))}
    missing = required - columns
    if missing:
        raise WeiLinIntegrationBuildError(
            "{} is missing columns: {}".format(table, ", ".join(sorted(missing)))
        )


def _input_record(path: Path, sha256: str, **metadata: object) -> Dict[str, object]:
    return {
        "path": str(path),
        "sha256": sha256,
        "size_bytes": path.stat().st_size,
        "read_only": True,
        **metadata,
    }


def _load_gallery_database(
    path: Path, sha256: str
) -> Tuple[Dict[str, Dict[str, object]], Dict[str, object]]:
    connection = _readonly_connection(path)
    try:
        _require_columns(
            connection,
            "hot_tags",
            {"tag", "category", "post_count", "translation_cn"},
        )
        tags: Dict[str, Dict[str, object]] = {}
        categories = Counter()
        for row in connection.execute(
            "SELECT tag, category, post_count, translation_cn FROM hot_tags ORDER BY tag"
        ):
            exact_tag = str(row["tag"] or "")
            tag = normalize_tag(exact_tag)
            if not tag or len(tag.encode("utf-8")) > MAX_TAG_BYTES:
                raise WeiLinIntegrationBuildError(
                    "Gallery contains an invalid tag identity: {!r}".format(exact_tag)
                )
            if tag in tags:
                raise WeiLinIntegrationBuildError(
                    "Gallery contains a normalized tag collision: {}".format(tag)
                )
            try:
                category = int(row["category"])
            except (TypeError, ValueError) as exc:
                raise WeiLinIntegrationBuildError(
                    "Gallery contains an invalid category for {}".format(exact_tag)
                ) from exc
            tags[tag] = {
                "exact_tag": exact_tag,
                "category": category,
                "post_count": int(row["post_count"] or 0),
                "translation_cn": normalize_translation(row["translation_cn"]),
            }
            categories[str(category)] += 1
        query_only = bool(connection.execute("PRAGMA query_only").fetchone()[0])
        return tags, _input_record(
            path,
            sha256,
            query_only=query_only,
            table="hot_tags",
            rows=len(tags),
            rows_by_category=dict(sorted(categories.items())),
        )
    finally:
        connection.close()


def _danbooru_translation_head(value: object) -> str:
    """Return WeiLin's leading Chinese label before optional work metadata."""

    translation = normalize_translation(value)
    if not translation:
        return ""
    return translation.split("-", 1)[0].strip()


def _load_weilin_danbooru_database(
    path: Path, sha256: str
) -> Tuple[
    Dict[str, Set[str]],
    Dict[str, Set[int]],
    Dict[str, object],
]:
    connection = _readonly_connection(path)
    translations: MutableMapping[str, Set[str]] = defaultdict(set)
    categories: MutableMapping[str, Set[int]] = defaultdict(set)
    stats = Counter()
    try:
        _require_columns(
            connection,
            "danbooru_tag",
            {"tag", "color_id", "translate"},
        )
        for row in connection.execute(
            "SELECT id_index, tag, color_id, translate FROM danbooru_tag ORDER BY id_index"
        ):
            stats["rows"] += 1
            tag = normalize_tag(row["tag"])
            if not tag or len(tag.encode("utf-8")) > MAX_TAG_BYTES:
                stats["invalid_tag"] += 1
                continue
            translations[tag].add(_danbooru_translation_head(row["translate"]))
            try:
                categories[tag].add(int(row["color_id"]))
            except (TypeError, ValueError):
                stats["invalid_category"] += 1
        stats["normalized_tags"] = len(translations)
        stats["translation_conflicts"] = sum(
            1 for values in translations.values() if len(values) != 1
        )
        stats["category_conflicts"] = sum(1 for values in categories.values() if len(values) != 1)
        query_only = bool(connection.execute("PRAGMA query_only").fetchone()[0])
        metadata = _input_record(
            path,
            sha256,
            query_only=query_only,
            table="danbooru_tag",
            stats=dict(sorted(stats.items())),
        )
        return dict(translations), dict(categories), metadata
    finally:
        connection.close()


def _find_csv_column(headers: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    normalized = {
        unicodedata.normalize("NFKC", str(header)).strip().casefold().replace("-", "_"): header
        for header in headers
    }
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def _load_triple_consensus(
    path: Path, sha256: str
) -> Tuple[Dict[str, Set[str]], Dict[str, Set[int]], Dict[str, object]]:
    translations: MutableMapping[str, Set[str]] = defaultdict(set)
    categories: MutableMapping[str, Set[int]] = defaultdict(set)
    stats = Counter()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = reader.fieldnames or []
        tag_column = _find_csv_column(headers, ("tag", "name"))
        translation_column = _find_csv_column(
            headers,
            ("translation_cn", "cn_name", "zh_cn", "chinese", "translation"),
        )
        category_column = _find_csv_column(headers, ("category", "type"))
        if not tag_column or not translation_column:
            raise WeiLinIntegrationBuildError(
                "triple consensus CSV requires tag and translation columns"
            )
        for row in reader:
            stats["rows"] += 1
            tag = normalize_tag(row.get(tag_column))
            if not tag or len(tag.encode("utf-8")) > MAX_TAG_BYTES:
                stats["invalid_tag"] += 1
                continue
            translations[tag].add(normalize_translation(row.get(translation_column)))
            if category_column:
                try:
                    categories[tag].add(int(str(row.get(category_column) or "").strip()))
                except ValueError:
                    stats["invalid_category"] += 1
    stats["normalized_tags"] = len(translations)
    stats["translation_conflicts"] = sum(1 for values in translations.values() if len(values) != 1)
    stats["category_conflicts"] = sum(1 for values in categories.values() if len(values) != 1)
    return (
        dict(translations),
        dict(categories),
        _input_record(path, sha256, stats=dict(sorted(stats.items()))),
    )


def _stream_weilin_taxonomy(
    *,
    path: Path,
    sha256: str,
    gallery: Mapping[str, Mapping[str, object]],
    danbooru_categories: Mapping[str, Set[int]],
    handle: IO[str],
) -> Tuple[
    Dict[str, Set[str]],
    Set[str],
    Dict[str, object],
    Dict[str, int],
]:
    descriptions: MutableMapping[str, Set[str]] = defaultdict(set)
    artist_scoped_tags: Set[str] = set()
    taxonomy_stats = Counter()
    connection = _readonly_connection(path)
    try:
        _require_columns(
            connection,
            "tag_groups",
            {"id_index", "name", "p_uuid"},
        )
        _require_columns(
            connection,
            "tag_subgroups",
            {"id_index", "group_id", "name", "p_uuid", "g_uuid"},
        )
        _require_columns(
            connection,
            "tag_tags",
            {"id_index", "subgroup_id", "text", "desc", "t_uuid", "g_uuid"},
        )
        group_rows = int(connection.execute("SELECT COUNT(*) FROM tag_groups").fetchone()[0])
        subgroup_rows = int(connection.execute("SELECT COUNT(*) FROM tag_subgroups").fetchone()[0])
        query = """
            SELECT
                t.id_index AS row_id,
                t.text AS raw_text,
                t.desc AS description,
                t.t_uuid AS t_uuid,
                t.g_uuid AS tag_g_uuid,
                s.id_index AS subgroup_id,
                s.name AS subgroup_name,
                s.p_uuid AS subgroup_uuid,
                s.g_uuid AS subgroup_g_uuid,
                g.id_index AS group_id,
                g.name AS group_name,
                g.p_uuid AS group_uuid
            FROM tag_tags AS t
            LEFT JOIN tag_subgroups AS s ON s.id_index = t.subgroup_id
            LEFT JOIN tag_groups AS g ON g.id_index = s.group_id
            ORDER BY t.id_index
        """
        for row in connection.execute(query):
            taxonomy_stats["source_rows"] += 1
            raw_text = row["raw_text"]
            tag = normalize_tag(raw_text)
            phrase = is_prompt_phrase(raw_text)
            gallery_row = gallery.get(tag)
            scope_reason = _artist_scope_reason(
                row["group_name"], row["subgroup_name"], row["subgroup_id"]
            )
            if scope_reason:
                taxonomy_stats[scope_reason + "_excluded"] += 1
                taxonomy_stats["artist_rows_excluded"] += 1
                if tag:
                    artist_scoped_tags.add(tag)
                continue
            if gallery_row is not None and int(gallery_row["category"]) == ARTIST_CATEGORY:
                taxonomy_stats["gallery_artist_rows_excluded"] += 1
                taxonomy_stats["artist_rows_excluded"] += 1
                continue
            # Gallery cannot classify tags it does not know yet.  WeiLin's own
            # Danbooru color/category is therefore a second conservative
            # artist guard for taxonomy-only rows.
            if ARTIST_CATEGORY in danbooru_categories.get(tag, set()):
                taxonomy_stats["weilin_danbooru_artist_rows_excluded"] += 1
                taxonomy_stats["artist_rows_excluded"] += 1
                continue

            taxonomy_row = {
                "source": "weilin_tag_tags",
                "row_id": row["row_id"],
                "group_id": row["group_id"],
                "group": row["group_name"],
                "group_uuid": row["group_uuid"],
                "subgroup_id": row["subgroup_id"],
                "subgroup": row["subgroup_name"],
                "subgroup_uuid": row["subgroup_uuid"],
                "subgroup_g_uuid": row["subgroup_g_uuid"],
                "t_uuid": row["t_uuid"],
                "g_uuid": row["tag_g_uuid"],
                # Deliberately use the raw SQLite value.  Do not strip,
                # normalize, truncate, split, or otherwise rewrite it.
                "raw_text": raw_text,
                "description": row["description"],
                "kind": "prompt_phrase" if phrase else "atomic_tag",
                "is_long_text": phrase,
            }
            handle.write(json.dumps(taxonomy_row, ensure_ascii=False, sort_keys=True) + "\n")
            taxonomy_stats["rows_written"] += 1
            taxonomy_stats[taxonomy_row["kind"] + "_rows"] += 1

            if phrase:
                taxonomy_stats["translation_long_text_excluded"] += 1
                continue
            if not tag or len(tag.encode("utf-8")) > MAX_TAG_BYTES:
                taxonomy_stats["translation_invalid_tag_excluded"] += 1
                continue
            descriptions[tag].add(normalize_translation(row["description"]))

        query_only = bool(connection.execute("PRAGMA query_only").fetchone()[0])
        metadata = _input_record(
            path,
            sha256,
            query_only=query_only,
            tables=("tag_groups", "tag_subgroups", "tag_tags"),
            tag_group_rows=group_rows,
            tag_subgroup_rows=subgroup_rows,
            tag_tag_rows=int(taxonomy_stats["source_rows"]),
        )
        taxonomy_stats["normalized_atomic_tags"] = len(descriptions)
        taxonomy_stats["atomic_description_conflicts"] = sum(
            1 for values in descriptions.values() if len(values) != 1
        )
        return (
            dict(descriptions),
            artist_scoped_tags,
            metadata,
            dict(sorted(taxonomy_stats.items())),
        )
    finally:
        connection.close()


def _single_value(values: Optional[Set[str]]) -> Optional[str]:
    if not values or len(values) != 1:
        return None
    return next(iter(values))


def _decide_translations(
    *,
    gallery: Mapping[str, Mapping[str, object]],
    weilin_descriptions: Mapping[str, Set[str]],
    artist_scoped_tags: Set[str],
    danbooru_translations: Mapping[str, Set[str]],
    danbooru_categories: Mapping[str, Set[int]],
    consensus_translations: Mapping[str, Set[str]],
    consensus_categories: Mapping[str, Set[int]],
) -> Tuple[list[Dict[str, object]], Dict[str, int]]:
    accepted: list[Dict[str, object]] = []
    decisions = Counter()
    for tag in sorted(weilin_descriptions):
        gallery_row = gallery.get(tag)
        if tag in artist_scoped_tags:
            decisions["artist_scope_excluded"] += 1
            continue
        if gallery_row is None:
            decisions["no_gallery_match"] += 1
            continue
        category = int(gallery_row["category"])
        if category == ARTIST_CATEGORY:
            decisions["gallery_artist_excluded"] += 1
            continue
        if category not in ALLOWED_CATEGORIES:
            decisions["unsupported_gallery_category"] += 1
            continue
        if normalize_translation(gallery_row["translation_cn"]):
            decisions["gallery_translation_already_present"] += 1
            continue

        description_values = weilin_descriptions[tag]
        if len(description_values) != 1:
            decisions["weilin_taxonomy_translation_conflict"] += 1
            continue
        taxonomy_translation = _single_value(description_values)
        if not taxonomy_translation:
            decisions["weilin_taxonomy_translation_empty"] += 1
            continue

        danbooru_values = danbooru_translations.get(tag)
        if not danbooru_values:
            decisions["weilin_danbooru_missing"] += 1
            continue
        if len(danbooru_values) != 1:
            decisions["weilin_danbooru_translation_conflict"] += 1
            continue
        danbooru_translation = _single_value(danbooru_values)
        if not danbooru_translation:
            decisions["weilin_danbooru_translation_empty"] += 1
            continue
        danbooru_category_values = danbooru_categories.get(tag, set())
        if len(danbooru_category_values) != 1:
            decisions["weilin_danbooru_category_conflict"] += 1
            continue
        if next(iter(danbooru_category_values)) != category:
            decisions["weilin_danbooru_category_mismatch"] += 1
            continue
        if danbooru_translation != taxonomy_translation:
            decisions["weilin_sources_disagree"] += 1
            continue

        consensus_values = consensus_translations.get(tag)
        if not consensus_values:
            decisions["triple_consensus_missing"] += 1
            continue
        if len(consensus_values) != 1:
            decisions["triple_consensus_translation_conflict"] += 1
            continue
        consensus_translation = _single_value(consensus_values)
        consensus_category_values = consensus_categories.get(tag, set())
        if consensus_category_values:
            if len(consensus_category_values) != 1:
                decisions["triple_consensus_category_conflict"] += 1
                continue
            if next(iter(consensus_category_values)) != category:
                decisions["triple_consensus_category_mismatch"] += 1
                continue
        if consensus_translation != taxonomy_translation:
            decisions["triple_consensus_disagrees"] += 1
            continue

        safe_translation, safety_decision = validate_short_chinese(taxonomy_translation)
        if safe_translation is None:
            decisions[safety_decision] += 1
            continue
        accepted.append(
            {
                "tag": gallery_row["exact_tag"],
                "category": category,
                "post_count": int(gallery_row["post_count"]),
                "translation_cn": safe_translation,
            }
        )
        decisions["accepted"] += 1

    accepted.sort(key=lambda row: (-int(row["post_count"]), str(row["tag"])))
    return accepted, dict(sorted(decisions.items()))


def build_weilin_gallery_integration(
    *,
    gallery_db_path: Path,
    weilin_tags_db_path: Path,
    weilin_danbooru_db_path: Path,
    triple_consensus_path: Path,
    output_path: Path,
    taxonomy_path: Path,
    report_path: Path,
) -> Dict[str, object]:
    gallery_db_path = gallery_db_path.expanduser().resolve()
    weilin_tags_db_path = weilin_tags_db_path.expanduser().resolve()
    weilin_danbooru_db_path = weilin_danbooru_db_path.expanduser().resolve()
    triple_consensus_path = triple_consensus_path.expanduser().resolve()
    output_path = output_path.expanduser().resolve()
    taxonomy_path = taxonomy_path.expanduser().resolve()
    report_path = report_path.expanduser().resolve()

    named_inputs = [
        ("gallery_db", gallery_db_path),
        ("weilin_tags_db", weilin_tags_db_path),
        ("weilin_danbooru_db", weilin_danbooru_db_path),
        ("triple_consensus", triple_consensus_path),
    ]
    named_outputs = [
        ("output", output_path),
        ("taxonomy", taxonomy_path),
        ("report", report_path),
    ]
    all_named_paths = [*named_inputs, *named_outputs]
    _require_input_files(named_inputs)
    _validate_distinct_paths(all_named_paths)
    _ensure_outputs_absent(named_outputs)

    input_hashes = {name: file_sha256(path) for name, path in named_inputs}
    temporary_paths: list[Path] = []
    try:
        gallery, gallery_metadata = _load_gallery_database(
            gallery_db_path, input_hashes["gallery_db"]
        )
        danbooru_translations, danbooru_categories, danbooru_metadata = (
            _load_weilin_danbooru_database(
                weilin_danbooru_db_path, input_hashes["weilin_danbooru_db"]
            )
        )
        consensus_translations, consensus_categories, consensus_metadata = (
            _load_triple_consensus(
                triple_consensus_path, input_hashes["triple_consensus"]
            )
        )

        taxonomy_handle, taxonomy_temporary = _new_temporary_text(
            taxonomy_path, encoding="utf-8"
        )
        temporary_paths.append(taxonomy_temporary)
        try:
            (
                weilin_descriptions,
                artist_scoped_tags,
                weilin_tags_metadata,
                taxonomy_stats,
            ) = _stream_weilin_taxonomy(
                path=weilin_tags_db_path,
                sha256=input_hashes["weilin_tags_db"],
                gallery=gallery,
                danbooru_categories=danbooru_categories,
                handle=taxonomy_handle,
            )
            _finish_temporary(taxonomy_handle)
        except Exception:
            if not taxonomy_handle.closed:
                taxonomy_handle.close()
            raise

        accepted, decisions = _decide_translations(
            gallery=gallery,
            weilin_descriptions=weilin_descriptions,
            artist_scoped_tags=artist_scoped_tags,
            danbooru_translations=danbooru_translations,
            danbooru_categories=danbooru_categories,
            consensus_translations=consensus_translations,
            consensus_categories=consensus_categories,
        )

        output_handle, output_temporary = _new_temporary_text(
            output_path, encoding="utf-8-sig"
        )
        temporary_paths.append(output_temporary)
        writer = csv.DictWriter(
            output_handle,
            fieldnames=("tag", "category", "post_count", "translation_cn"),
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(accepted)
        _finish_temporary(output_handle)

        hashes_after = {name: file_sha256(path) for name, path in named_inputs}
        changed = [
            name for name in input_hashes if hashes_after[name] != input_hashes[name]
        ]
        if changed:
            raise WeiLinIntegrationBuildError(
                "input changed while building; refusing artifacts: {}".format(
                    ", ".join(changed)
                )
            )

        taxonomy_sha256 = file_sha256(taxonomy_temporary)
        output_sha256 = file_sha256(output_temporary)
        report: Dict[str, object] = {
            "schema_version": 1,
            "tool": "build_weilin_gallery_integration.py",
            "database_mutated": False,
            "inputs_unchanged": True,
            "source": {
                "name": "WeiLin ComfyUI Tools Prompt data",
                "upstream_url": WEILIN_UPSTREAM_URL,
                "license": WEILIN_DATA_LICENSE,
            },
            "policy": {
                "gallery_identity_category_and_existing_translation_are_authoritative": True,
                "consensus_rule": (
                    "normalized tag identity plus exact normalized Chinese agreement across "
                    "WeiLin tag_tags.desc, WeiLin danbooru_tag.translate Chinese head, and "
                    "the supplied triple-consensus CSV"
                ),
                "allowed_gallery_categories": sorted(ALLOWED_CATEGORIES),
                "artist_allowed": False,
                "artist_gallery_category": ARTIST_CATEGORY,
                "artist_group_and_subgroup_labels_excluded": sorted(ARTIST_SCOPE_LABELS),
                "artist_subgroup_ids_excluded": sorted(ARTIST_SUBGROUP_IDS),
                "weilin_danbooru_artist_category_excluded": True,
                "long_text_preserved_verbatim_in_taxonomy": True,
                "long_text_allowed_in_translation_pack": False,
                "prompt_phrase_rule": {
                    "more_than_characters": LONG_TEXT_CHARACTERS,
                    "more_than_words": LONG_TEXT_WORDS,
                    "prompt_separators": [",", "，", ";", "；", "CR", "LF"],
                },
                "maximum_translation_characters": MAX_TRANSLATION_CHARACTERS,
                "short_chinese_required": True,
                "fuzzy_matching": False,
                "identity_merge": False,
                "overwrite_existing_artifacts": False,
                "sqlite_access": "mode=ro plus PRAGMA query_only",
            },
            "inputs": {
                "gallery_db": gallery_metadata,
                "weilin_tags_db": weilin_tags_metadata,
                "weilin_danbooru_db": danbooru_metadata,
                "triple_consensus": consensus_metadata,
            },
            "decisions": decisions,
            "taxonomy": {
                "path": str(taxonomy_path),
                "format": "jsonl",
                "sha256": taxonomy_sha256,
                "stats": taxonomy_stats,
            },
            "output": {
                "path": str(output_path),
                "format": "csv-utf-8-sig",
                "sha256": output_sha256,
                "rows": len(accepted),
                "categories": dict(
                    sorted(Counter(str(row["category"]) for row in accepted).items())
                ),
            },
        }

        report_handle, report_temporary = _new_temporary_text(
            report_path, encoding="utf-8"
        )
        temporary_paths.append(report_temporary)
        report_handle.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
        _finish_temporary(report_handle)

        _publish_bundle_no_replace(
            (
                (output_temporary, output_path),
                (taxonomy_temporary, taxonomy_path),
                (report_temporary, report_path),
            ),
            all_named_paths=all_named_paths,
            named_outputs=named_outputs,
        )
        temporary_paths.clear()
        return report
    finally:
        for temporary in temporary_paths:
            try:
                if temporary.exists():
                    temporary.unlink()
            except OSError:
                pass


# A concise alias is convenient for callers and keeps the public API parallel
# with the other pack builders in this plugin.
build_integration_pack = build_weilin_gallery_integration


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gallery-db", type=Path, default=DEFAULT_GALLERY_DB)
    parser.add_argument("--weilin-tags-db", type=Path, required=True)
    parser.add_argument("--weilin-danbooru-db", type=Path, required=True)
    parser.add_argument("--triple-consensus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--taxonomy", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = build_weilin_gallery_integration(
            gallery_db_path=args.gallery_db,
            weilin_tags_db_path=args.weilin_tags_db,
            weilin_danbooru_db_path=args.weilin_danbooru_db,
            triple_consensus_path=args.triple_consensus,
            output_path=args.output,
            taxonomy_path=args.taxonomy,
            report_path=args.report,
        )
    except WeiLinIntegrationBuildError as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
