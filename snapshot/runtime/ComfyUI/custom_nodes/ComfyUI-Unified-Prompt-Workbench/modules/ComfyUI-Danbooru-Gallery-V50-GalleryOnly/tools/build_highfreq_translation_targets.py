#!/usr/bin/env python3
"""Build a read-only review pack of high-frequency untranslated Gallery tags.

The builder selects a deterministic, exact number of short Gallery tags and
classifies them with WeiLin's taxonomy when an atomic tag identity matches
exactly.  It never writes to either SQLite input.  The generated CSV keeps an
empty ``translation_cn`` column so a reviewed copy can later be consumed by
the Gallery translation importer.
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
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GALLERY_DB = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"
DEFAULT_WEILIN_TAGS_DB = (
    PLUGIN_ROOT.parent
    / "WeiLin-Comfyui-Tools-V52-FullPromptSelector"
    / "user_data"
    / "userdatas_zh_CN_tags.db"
)

DEFAULT_LIMIT = 4300
ALLOWED_CATEGORIES = frozenset((0, 3, 4))
CATEGORY_LABELS = {0: "通用", 3: "作品", 4: "角色"}
CATEGORY_NAMES = {0: "general", 3: "copyright", 4: "character"}
MAX_WORDS = 6
MAX_CHARACTERS = 64
PROMPT_LENGTH_THRESHOLD = 120
PROMPT_WORD_THRESHOLD = 6
ARTIST_SUBGROUP_IDS = frozenset((77, 493))
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

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019][A-Za-z0-9]+)?")
_URLISH_RE = re.compile(
    r"https?://|www\.|(?:^|[_-])(?:url|uri)(?:$|[_-])", re.IGNORECASE
)
_WEIGHT_RE = re.compile(
    r"(?:^|[,\s])(?:BREAK|AND)\b|\([^\n]{1,100}:\s*-?\d+(?:\.\d+)?\)", re.I
)
_SCOPE_SEPARATORS_RE = re.compile(r"[\s_\-]+")

CSV_FIELDS = (
    "rank",
    "tag",
    "category",
    "category_name",
    "post_count",
    "gallery_category_cn",
    "word_count",
    "character_count",
    "classification_source",
    "weilin_group_id",
    "weilin_group",
    "weilin_subgroup_id",
    "weilin_subgroup",
    "weilin_match_count",
    "weilin_paths_json",
    "translation_cn",
)


class HighFrequencyTargetBuildError(RuntimeError):
    """Raised before an incomplete or ambiguous target pack is published."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize_tag(value: object) -> str:
    tag = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return _WHITESPACE_RE.sub("_", tag)


def _scope_label(value: object) -> str:
    label = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return _SCOPE_SEPARATORS_RE.sub("", label)


def _is_artist_scope(group: object, subgroup: object, subgroup_id: object) -> bool:
    try:
        if int(subgroup_id) in ARTIST_SUBGROUP_IDS:
            return True
    except (TypeError, ValueError):
        pass
    return (
        _scope_label(group) in ARTIST_SCOPE_LABELS
        or _scope_label(subgroup) in ARTIST_SCOPE_LABELS
    )


def _atomic_weilin_identity(value: object) -> Optional[str]:
    """Mirror the runtime bridge's conservative atomic-tag normalization."""

    original = str(value or "")
    classified = original.strip()
    if classified.endswith((",", "，")) and classified.count(",") + classified.count("，") == 1:
        classified = classified[:-1].rstrip()
    words = [part for part in _WHITESPACE_RE.split(classified) if part]
    if (
        len(classified) > PROMPT_LENGTH_THRESHOLD
        or len(words) > PROMPT_WORD_THRESHOLD
        or any(separator in classified for separator in (",", "，", ";", "；", "\n", "\r"))
        or _WEIGHT_RE.search(classified)
    ):
        return None

    normalized = unicodedata.normalize("NFKC", original).strip()
    if not normalized or _CONTROL_RE.search(normalized):
        return None
    if normalized.endswith(",") and normalized.count(",") == 1:
        normalized = normalized[:-1].rstrip()
    normalized = normalized.replace(r"\(", "(").replace(r"\)", ")")
    if any(separator in normalized for separator in (",", ";", "\n", "\r")):
        return None
    normalized = _WHITESPACE_RE.sub("_", normalized).casefold()
    if not normalized or len(normalized.encode("utf-8")) > 256:
        return None
    return normalized


def _readonly_connection(path: Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise HighFrequencyTargetBuildError("required SQLite input is missing: {}".format(resolved))
    try:
        connection = sqlite3.connect(
            resolved.as_uri() + "?mode=ro", uri=True, timeout=30.0
        )
    except sqlite3.Error as exc:
        raise HighFrequencyTargetBuildError(
            "could not open SQLite input read-only {}: {}".format(resolved, exc)
        ) from exc
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _require_columns(
    connection: sqlite3.Connection, table: str, required: Iterable[str]
) -> None:
    columns = {
        str(row[1]) for row in connection.execute('PRAGMA table_info("{}")'.format(table))
    }
    missing = sorted(set(required) - columns)
    if missing:
        raise HighFrequencyTargetBuildError(
            "{} is missing columns: {}".format(table, ", ".join(missing))
        )


def _validate_paths(inputs: Sequence[Path], outputs: Sequence[Path]) -> None:
    resolved_inputs = [Path(path).expanduser().resolve() for path in inputs]
    resolved_outputs = [Path(path).expanduser().resolve() for path in outputs]
    if len({str(path).casefold() for path in resolved_outputs}) != len(resolved_outputs):
        raise HighFrequencyTargetBuildError("output paths must be distinct")
    for output in resolved_outputs:
        if os.path.lexists(str(output)):
            raise HighFrequencyTargetBuildError("refusing to overwrite existing artifact: {}".format(output))
        for input_path in resolved_inputs:
            if str(output).casefold() == str(input_path).casefold():
                raise HighFrequencyTargetBuildError("output path collides with a SQLite input")
            try:
                if output.exists() and input_path.exists() and os.path.samefile(output, input_path):
                    raise HighFrequencyTargetBuildError("output hard-link collides with a SQLite input")
            except OSError:
                pass


def _short_tag_shape(tag: str) -> Tuple[int, int]:
    normalized = unicodedata.normalize("NFKC", tag).strip()
    return len(_WORD_RE.findall(normalized)), len(normalized)


def _select_targets(path: Path, limit: int) -> Tuple[list[Dict[str, object]], Dict[str, object]]:
    decisions = Counter()
    category_candidates = Counter()
    inherited_aliases: Dict[str, str] = {}
    targets: list[Dict[str, object]] = []
    with _readonly_connection(path) as connection:
        _require_columns(
            connection, "hot_tags", ("tag", "category", "post_count", "translation_cn")
        )
        _require_columns(connection, "tag_aliases", ("alias", "canonical_tag"))
        for row in connection.execute(
            """
            SELECT a.alias, a.canonical_tag
            FROM tag_aliases AS a
            JOIN hot_tags AS c ON c.tag = a.canonical_tag
            WHERE TRIM(COALESCE(c.translation_cn, '')) <> ''
            ORDER BY a.alias, a.canonical_tag
            """
        ):
            inherited_aliases.setdefault(str(row["alias"]), str(row["canonical_tag"]))

        rows = connection.execute(
            """
            SELECT tag, category, post_count, translation_cn
            FROM hot_tags
            ORDER BY post_count DESC, tag ASC
            """
        )
        for row in rows:
            decisions["source_rows"] += 1
            tag = str(row["tag"] or "")
            try:
                category = int(row["category"])
            except (TypeError, ValueError):
                decisions["invalid_category"] += 1
                continue
            if category not in ALLOWED_CATEGORIES:
                if category == 1:
                    decisions["artist_category_excluded"] += 1
                elif category == 5:
                    decisions["meta_category_excluded"] += 1
                else:
                    decisions["other_category_excluded"] += 1
                continue
            category_candidates[str(category)] += 1
            if str(row["translation_cn"] or "").strip():
                decisions["already_translated"] += 1
                continue
            if not tag or _CONTROL_RE.search(tag):
                decisions["invalid_tag"] += 1
                continue
            word_count, character_count = _short_tag_shape(tag)
            if word_count < 1:
                decisions["no_alphanumeric_word"] += 1
                continue
            if word_count > MAX_WORDS:
                decisions["over_word_limit"] += 1
                continue
            if character_count > MAX_CHARACTERS:
                decisions["over_character_limit"] += 1
                continue
            if _URLISH_RE.search(tag):
                decisions["url_like_tag"] += 1
                continue
            if tag in inherited_aliases:
                decisions["canonical_translation_inheritable"] += 1
                continue
            targets.append(
                {
                    "tag": tag,
                    "category": category,
                    "post_count": int(row["post_count"] or 0),
                    "word_count": word_count,
                    "character_count": character_count,
                }
            )
            decisions["eligible"] += 1

    if len(targets) < limit:
        raise HighFrequencyTargetBuildError(
            "only {} eligible tags remain; exactly {} were requested".format(len(targets), limit)
        )
    selected = targets[:limit]
    decisions["selected"] = len(selected)
    decisions["eligible_below_cutoff"] = len(targets) - len(selected)
    return selected, {
        "decisions": dict(sorted(decisions.items())),
        "allowed_category_source_rows": dict(sorted(category_candidates.items())),
        "aliases_with_translated_canonical": len(inherited_aliases),
    }


def _load_weilin_paths(
    path: Path, selected: Sequence[Mapping[str, object]]
) -> Tuple[Dict[str, list[Dict[str, object]]], Dict[str, object]]:
    selected_by_identity = {_normalize_tag(row["tag"]): str(row["tag"]) for row in selected}
    matches: Dict[str, list[Dict[str, object]]] = {str(row["tag"]): [] for row in selected}
    stats = Counter()
    with _readonly_connection(path) as connection:
        _require_columns(connection, "tag_groups", ("id_index", "name"))
        _require_columns(connection, "tag_subgroups", ("id_index", "group_id", "name"))
        _require_columns(connection, "tag_tags", ("id_index", "subgroup_id", "text"))
        query = """
            SELECT t.id_index AS row_id, t.text AS raw_text,
                   s.id_index AS subgroup_id, s.name AS subgroup_name,
                   g.id_index AS group_id, g.name AS group_name
            FROM tag_tags AS t
            LEFT JOIN tag_subgroups AS s ON s.id_index = t.subgroup_id
            LEFT JOIN tag_groups AS g ON g.id_index = s.group_id
            ORDER BY t.id_index
        """
        for row in connection.execute(query):
            stats["source_rows"] += 1
            identity = _atomic_weilin_identity(row["raw_text"])
            if identity is None:
                stats["prompt_or_invalid_rows"] += 1
                continue
            gallery_tag = selected_by_identity.get(identity)
            if gallery_tag is None:
                continue
            if _is_artist_scope(row["group_name"], row["subgroup_name"], row["subgroup_id"]):
                stats["artist_scope_matches_excluded"] += 1
                continue
            path_record = {
                "row_id": int(row["row_id"]),
                "group_id": int(row["group_id"]) if row["group_id"] is not None else None,
                "group": str(row["group_name"] or ""),
                "subgroup_id": int(row["subgroup_id"]) if row["subgroup_id"] is not None else None,
                "subgroup": str(row["subgroup_name"] or ""),
            }
            existing_keys = {
                (item["group_id"], item["subgroup_id"]) for item in matches[gallery_tag]
            }
            key = (path_record["group_id"], path_record["subgroup_id"])
            if key not in existing_keys:
                matches[gallery_tag].append(path_record)
                stats["exact_taxonomy_paths"] += 1
            else:
                stats["duplicate_exact_path_rows"] += 1
    stats["selected_tags_with_exact_match"] = sum(bool(paths) for paths in matches.values())
    stats["selected_tags_without_exact_match"] = len(matches) - stats["selected_tags_with_exact_match"]
    stats["selected_tags_with_multiple_paths"] = sum(len(paths) > 1 for paths in matches.values())
    return matches, dict(sorted(stats.items()))


def _publish_no_replace(temporary: Path, target: Path) -> None:
    try:
        os.link(temporary, target)
    except FileExistsError as exc:
        raise HighFrequencyTargetBuildError(
            "refusing to overwrite artifact created during build: {}".format(target)
        ) from exc
    except OSError as exc:
        raise HighFrequencyTargetBuildError("could not publish {}: {}".format(target, exc)) from exc


def build_highfreq_translation_targets(
    *,
    gallery_db_path: Path | str,
    weilin_tags_db_path: Path | str,
    output_path: Path | str,
    report_path: Path | str,
    limit: int = DEFAULT_LIMIT,
) -> Dict[str, object]:
    if limit < 1:
        raise HighFrequencyTargetBuildError("limit must be positive")
    gallery_db = Path(gallery_db_path).expanduser().resolve()
    weilin_db = Path(weilin_tags_db_path).expanduser().resolve()
    output = Path(output_path).expanduser().resolve()
    report_file = Path(report_path).expanduser().resolve()
    _validate_paths((gallery_db, weilin_db), (output, report_file))
    if not gallery_db.is_file() or not weilin_db.is_file():
        raise HighFrequencyTargetBuildError("both SQLite inputs must exist")

    before_hashes = {"gallery_db": file_sha256(gallery_db), "weilin_tags_db": file_sha256(weilin_db)}
    selected, selection_stats = _select_targets(gallery_db, limit)
    matches, weilin_stats = _load_weilin_paths(weilin_db, selected)
    after_hashes = {"gallery_db": file_sha256(gallery_db), "weilin_tags_db": file_sha256(weilin_db)}
    if after_hashes != before_hashes:
        raise HighFrequencyTargetBuildError("an SQLite input changed while the read-only pack was built")

    output.parent.mkdir(parents=True, exist_ok=True)
    report_file.parent.mkdir(parents=True, exist_ok=True)
    output_handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8-sig", newline="", dir=output.parent,
        prefix=output.name + ".", suffix=".tmp", delete=False,
    )
    output_temp = Path(output_handle.name)
    report_temp: Optional[Path] = None
    published_output = False
    try:
        writer = csv.DictWriter(output_handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        group_counts = Counter()
        category_counts = Counter()
        for rank, target in enumerate(selected, start=1):
            tag = str(target["tag"])
            category = int(target["category"])
            paths = matches[tag]
            if paths:
                primary = paths[0]
                source = "weilin_exact_atomic"
            else:
                primary = {
                    "group_id": None,
                    "group": "Gallery {}".format(CATEGORY_LABELS[category]),
                    "subgroup_id": None,
                    "subgroup": "未命中 WeiLin",
                }
                source = "gallery_category_fallback"
            group_counts["{} / {}".format(primary["group"], primary["subgroup"])] += 1
            category_counts[str(category)] += 1
            writer.writerow(
                {
                    "rank": rank,
                    "tag": tag,
                    "category": category,
                    "category_name": CATEGORY_NAMES[category],
                    "post_count": target["post_count"],
                    "gallery_category_cn": CATEGORY_LABELS[category],
                    "word_count": target["word_count"],
                    "character_count": target["character_count"],
                    "classification_source": source,
                    "weilin_group_id": "" if primary["group_id"] is None else primary["group_id"],
                    "weilin_group": primary["group"],
                    "weilin_subgroup_id": "" if primary["subgroup_id"] is None else primary["subgroup_id"],
                    "weilin_subgroup": primary["subgroup"],
                    "weilin_match_count": len(paths),
                    "weilin_paths_json": json.dumps(paths, ensure_ascii=False, separators=(",", ":")),
                    "translation_cn": "",
                }
            )
        output_handle.flush()
        os.fsync(output_handle.fileno())
        output_handle.close()
        output_sha = file_sha256(output_temp)

        cutoff = selected[-1]
        report = {
            "schema_version": 1,
            "database_mutated": False,
            "inputs_unchanged": True,
            "policy": {
                "exact_target_count": limit,
                "allowed_categories": [0, 3, 4],
                "artist_allowed": False,
                "meta_allowed": False,
                "maximum_words": MAX_WORDS,
                "maximum_characters": MAX_CHARACTERS,
                "translated_alias_canonical_excluded": True,
                "selection_order": ["post_count DESC", "tag ASC"],
                "weilin_match": "conservative atomic identity exact match; no fuzzy matching",
                "fallback": "Gallery category / 未命中 WeiLin",
            },
            "inputs": {
                "gallery_db": {"path": str(gallery_db), "sha256": before_hashes["gallery_db"], "read_only": True},
                "weilin_tags_db": {"path": str(weilin_db), "sha256": before_hashes["weilin_tags_db"], "read_only": True},
            },
            "selection": {
                "rows": len(selected),
                "rows_by_gallery_category": dict(sorted(category_counts.items())),
                "cutoff": {"rank": limit, "post_count": cutoff["post_count"], "tag": cutoff["tag"]},
                **selection_stats,
            },
            "weilin_mapping": {
                "stats": weilin_stats,
                "rows_by_primary_path": dict(sorted(group_counts.items())),
            },
            "output": {"path": str(output), "rows": len(selected), "sha256": output_sha, "columns": list(CSV_FIELDS)},
        }
        report_handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=report_file.parent,
            prefix=report_file.name + ".", suffix=".tmp", delete=False,
        )
        report_temp = Path(report_handle.name)
        json.dump(report, report_handle, ensure_ascii=False, indent=2, sort_keys=True)
        report_handle.write("\n")
        report_handle.flush()
        os.fsync(report_handle.fileno())
        report_handle.close()

        _validate_paths((gallery_db, weilin_db), (output, report_file))
        _publish_no_replace(output_temp, output)
        published_output = True
        _publish_no_replace(report_temp, report_file)
        return report
    except Exception:
        if not output_handle.closed:
            output_handle.close()
        if published_output:
            try:
                if output.exists() and os.path.samefile(output, output_temp):
                    output.unlink()
            except OSError:
                pass
        raise
    finally:
        for temporary in (output_temp, report_temp):
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gallery-db", type=Path, default=DEFAULT_GALLERY_DB)
    parser.add_argument("--weilin-tags-db", type=Path, default=DEFAULT_WEILIN_TAGS_DB)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    arguments = parser.parse_args(argv)
    report = build_highfreq_translation_targets(
        gallery_db_path=arguments.gallery_db,
        weilin_tags_db_path=arguments.weilin_tags_db,
        output_path=arguments.output,
        report_path=arguments.report,
        limit=arguments.limit,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
