#!/usr/bin/env python3
"""Build auditable CSVs from licensed public tag-translation snapshots.

This helper does no network access and never writes the live tag database.  It
converts a downloaded NEXTAltair Parquet snapshot and/or a curated JSON mapping
to the generic CSV accepted by ``import_tag_translations.py``.
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
from typing import Dict, Iterable, Mapping, MutableMapping, Sequence, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"
TYPE_TO_CATEGORY = {
    "general": 0,
    "artist": 1,
    "copyright": 3,
    "character": 4,
    "meta": 5,
}
ALLOWED_TRANSLATION_CATEGORIES = frozenset((0, 3, 4, 5))
NEXTALTAIR_ALLOWED_TYPES = frozenset(("general", "copyright", "character", "meta"))
NEXTALTAIR_MIN_POST_COUNT = 100
NEXTALTAIR_MAX_TRANSLATION_LENGTH = 64
LOCAL_POLICY_REJECTIONS = (
    "missing_local_tag",
    "artist_local_category",
    "disallowed_local_category",
)
_WHITESPACE_RE = re.compile(r"\s+")
_ESCAPED_PARENS_RE = re.compile(r"\\([()])")
_PARENS_RE = re.compile(r"[()（）]")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")


def normalize_tag(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    value = _ESCAPED_PARENS_RE.sub(r"\1", value)
    return _WHITESPACE_RE.sub("_", value)


def normalize_translation(value: object) -> str:
    return _WHITESPACE_RE.sub(
        " ", unicodedata.normalize("NFKC", str(value or "")).strip()
    )


def looks_chinese(value: str) -> bool:
    return bool(_HAN_RE.search(value)) and not _KANA_RE.search(value) and not _HANGUL_RE.search(value)


def _strict_nextaltair_translation(value: object) -> str:
    translation = normalize_translation(value)
    if (
        not translation
        or len(translation) > NEXTALTAIR_MAX_TRANSLATION_LENGTH
        or _PARENS_RE.search(translation)
        or not looks_chinese(translation)
    ):
        return ""
    return translation


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_local_metadata(db_path: Path) -> Dict[str, Tuple[int, int]]:
    if not db_path.is_file():
        raise FileNotFoundError("tag database not found: {}".format(db_path))
    connection = sqlite3.connect(
        db_path.resolve().as_uri() + "?mode=ro",
        uri=True,
        timeout=30.0,
    )
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        if not bool(connection.execute("PRAGMA query_only").fetchone()[0]):
            raise RuntimeError("failed to enable SQLite query_only mode")
        metadata = {
            str(tag): (int(category), int(post_count))
            for tag, category, post_count in connection.execute(
                "SELECT tag, category, post_count FROM hot_tags"
            )
        }
        return metadata
    finally:
        connection.close()


def _increment(counter: MutableMapping[str, int] | None, reason: str) -> None:
    if counter is not None:
        counter[reason] = int(counter.get(reason, 0)) + 1


def _rejection_counter(*extra_reasons: str) -> Counter[str]:
    return Counter({reason: 0 for reason in (*LOCAL_POLICY_REJECTIONS, *extra_reasons)})


def load_nextaltair(
    parquet_dir: Path,
    local_metadata: Mapping[str, Tuple[int, int]] | None = None,
    rejection_counts: MutableMapping[str, int] | None = None,
) -> Dict[str, Tuple[str, int, int]]:
    try:
        import pyarrow.dataset as dataset
    except ImportError as error:
        raise RuntimeError("pyarrow is required to read NEXTAltair Parquet files") from error

    files = sorted(parquet_dir.glob("*.parquet"))
    if not files:
        raise ValueError("no Parquet files found in {}".format(parquet_dir))
    table = dataset.dataset([str(path) for path in files], format="parquet").to_table(
        columns=["tag", "type_name", "count", "lang_zh"]
    )
    output: Dict[str, Tuple[str, int, int]] = {}
    if local_metadata is None:
        raise ValueError("local metadata is required")
    for row in table.to_pylist():
        type_name = str(row.get("type_name") or "").casefold()
        tag = normalize_tag(row.get("tag"))
        if not tag or len(tag.encode("utf-8")) > 256:
            _increment(rejection_counts, "invalid_tag")
            continue
        local = local_metadata.get(tag)
        if local is None:
            _increment(rejection_counts, "missing_local_tag")
            continue
        local_category, _local_post_count = local
        if local_category == 1:
            _increment(rejection_counts, "artist_local_category")
            continue
        if local_category not in ALLOWED_TRANSLATION_CATEGORIES:
            _increment(rejection_counts, "disallowed_local_category")
            continue
        if type_name == "artist":
            _increment(rejection_counts, "source_artist_category")
            continue
        category = TYPE_TO_CATEGORY.get(type_name)
        if type_name not in NEXTALTAIR_ALLOWED_TYPES or category is None:
            _increment(rejection_counts, "disallowed_source_category")
            continue
        if category != local_category:
            _increment(rejection_counts, "source_category_mismatch")
            continue
        post_count = max(0, int(row.get("count") or 0))
        if post_count < NEXTALTAIR_MIN_POST_COUNT:
            _increment(rejection_counts, "low_post_count")
            continue
        translations = []
        for raw in row.get("lang_zh") or []:
            value = _strict_nextaltair_translation(raw)
            if value and value not in translations:
                translations.append(value)
        if len(translations) != 1:
            _increment(rejection_counts, "invalid_or_ambiguous_translation")
            continue
        previous = output.get(tag)
        if previous is None:
            output[tag] = (translations[0], local_category, post_count)
            continue
        if post_count > previous[2]:
            output[tag] = (translations[0], local_category, post_count)
    return output


def load_curated_json(
    json_path: Path,
    local_metadata: Mapping[str, Tuple[int, int]],
    rejection_counts: MutableMapping[str, int] | None = None,
) -> Dict[str, Tuple[str, int, int]]:
    raw = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("curated JSON must be an object mapping tags to translations")
    output: Dict[str, Tuple[str, int, int]] = {}
    for raw_tag, raw_translation in raw.items():
        tag = normalize_tag(raw_tag)
        translation = normalize_translation(raw_translation)
        if not tag or not translation or not looks_chinese(translation):
            _increment(rejection_counts, "invalid_tag_or_translation")
            continue
        if len(tag.encode("utf-8")) > 256 or len(translation.encode("utf-8")) > 512:
            _increment(rejection_counts, "length_limit")
            continue
        local = local_metadata.get(tag)
        if local is None:
            _increment(rejection_counts, "missing_local_tag")
            continue
        category, post_count = local
        if category == 1:
            _increment(rejection_counts, "artist_local_category")
            continue
        if category not in ALLOWED_TRANSLATION_CATEGORIES:
            _increment(rejection_counts, "disallowed_local_category")
            continue
        output[tag] = (translation, category, post_count)
    return output


def _atomic_write_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as destination:
            temporary = Path(destination.name)
            writer = csv.DictWriter(
                destination,
                fieldnames=("tag", "category", "post_count", "translation_cn"),
            )
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _atomic_write_report(path: Path, report: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as destination:
            temporary = Path(destination.name)
            destination.write(rendered)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_pack(
    path: Path,
    rows: Mapping[str, Tuple[str, int, int]],
    local_metadata: Mapping[str, Tuple[int, int]],
) -> Dict[str, object]:
    # Final output boundary: every emitted tag must exist exactly in hot_tags,
    # whose category is authoritative.  Source/default categories cannot turn
    # an artist, unknown tag, or unsupported category into an eligible row.
    rejected = _rejection_counter("source_category_mismatch")
    serialized_rows = []
    for tag in sorted(rows):
        local = local_metadata.get(tag)
        if local is None:
            rejected["missing_local_tag"] += 1
            continue
        local_category, _local_post_count = local
        if local_category == 1:
            rejected["artist_local_category"] += 1
            continue
        if local_category not in ALLOWED_TRANSLATION_CATEGORIES:
            rejected["disallowed_local_category"] += 1
            continue
        translation, source_category, post_count = rows[tag]
        if source_category != local_category:
            rejected["source_category_mismatch"] += 1
            continue
        serialized_rows.append(
            {
                "tag": tag,
                "category": local_category,
                "post_count": post_count,
                "translation_cn": translation,
            }
        )
    _atomic_write_csv(path, serialized_rows)
    return {
        "path": str(path.resolve()),
        "rows": len(serialized_rows),
        "sha256": _sha256(path),
        "rejections": dict(sorted(rejected.items())),
    }


def _resolved_path_key(path: Path) -> str:
    return str(path.resolve()).casefold()


def _same_existing_path(left: Path, right: Path) -> bool:
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def validate_artifact_paths(
    destinations: Mapping[str, Path], inputs: Mapping[str, Path]
) -> None:
    """Reject direct, symlink, case-folded, and existing hard-link collisions."""

    destination_items = list(destinations.items())
    for index, (name, path) in enumerate(destination_items):
        if path.exists() and path.is_dir():
            raise ValueError("{} output path is a directory: {}".format(name, path))
        for other_name, other_path in destination_items[:index]:
            if (
                _resolved_path_key(path) == _resolved_path_key(other_path)
                or _same_existing_path(path, other_path)
            ):
                raise ValueError(
                    "{} and {} output paths must be distinct".format(other_name, name)
                )
        for input_name, input_path in inputs.items():
            if (
                _resolved_path_key(path) == _resolved_path_key(input_path)
                or _same_existing_path(path, input_path)
            ):
                raise ValueError(
                    "{} output path must not overwrite {} input".format(
                        name, input_name
                    )
                )


def build_packs(
    output_dir: Path,
    *,
    db_path: Path = DEFAULT_DB,
    nextaltair_dir: Path | None = None,
    curated_json: Path | None = None,
    report_path: Path | None = None,
) -> Dict[str, object]:
    if not db_path.is_file():
        raise FileNotFoundError("tag database not found: {}".format(db_path))
    if nextaltair_dir is None and curated_json is None:
        raise ValueError("at least one public source input is required")

    inputs: Dict[str, Path] = {"database": db_path}
    destinations: Dict[str, Path] = {}
    if nextaltair_dir is not None:
        if not nextaltair_dir.is_dir():
            raise ValueError("NEXTAltair directory not found: {}".format(nextaltair_dir))
        parquet_files = sorted(nextaltair_dir.glob("*.parquet"))
        if not parquet_files:
            raise ValueError("no Parquet files found in {}".format(nextaltair_dir))
        inputs["NEXTAltair directory"] = nextaltair_dir
        for index, parquet_file in enumerate(parquet_files):
            inputs["NEXTAltair parquet {}".format(index)] = parquet_file
        destinations["nextaltair CSV"] = output_dir / "nextaltair_lang_zh.csv"
    if curated_json is not None:
        if not curated_json.is_file():
            raise ValueError("curated JSON not found: {}".format(curated_json))
        inputs["curated JSON"] = curated_json
        destinations["curated CSV"] = output_dir / "curated_tag_translations.csv"
    if report_path is not None:
        destinations["report"] = report_path
    validate_artifact_paths(destinations, inputs)

    local_metadata = load_local_metadata(db_path)
    next_rows: Dict[str, Tuple[str, int, int]] = {}
    staged_rows: Dict[str, Dict[str, Tuple[str, int, int]]] = {}
    source_rejections: Dict[str, Dict[str, int]] = {}
    if nextaltair_dir is not None:
        next_rejections = _rejection_counter(
            "source_artist_category",
            "disallowed_source_category",
            "source_category_mismatch",
        )
        next_rows = load_nextaltair(
            nextaltair_dir,
            local_metadata=local_metadata,
            rejection_counts=next_rejections,
        )
        staged_rows["nextaltair"] = next_rows
        source_rejections["nextaltair"] = dict(sorted(next_rejections.items()))
    if curated_json is not None:
        curated_rejections = _rejection_counter()
        curated_rows = load_curated_json(
            curated_json,
            local_metadata=local_metadata,
            rejection_counts=curated_rejections,
        )
        staged_rows["curated"] = curated_rows
        source_rejections["curated"] = dict(sorted(curated_rejections.items()))

    # Parse and validate every source before creating any output artifact.
    result: Dict[str, object] = {
        "database": {
            "path": str(db_path.resolve()),
            "read_only": True,
            "query_only": True,
            "hot_tags_rows": len(local_metadata),
        },
        "outputs": {},
        "local_metadata_rows": len(local_metadata),
        "source_rejections": source_rejections,
    }
    for name, rows in staged_rows.items():
        result["outputs"][name] = write_pack(
            destinations["{} CSV".format(name)], rows, local_metadata
        )
    return result


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--nextaltair-dir", type=Path)
    parser.add_argument("--curated-json", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    report = build_packs(
        args.output_dir,
        db_path=args.db,
        nextaltair_dir=args.nextaltair_dir,
        curated_json=args.curated_json,
        report_path=args.report,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        _atomic_write_report(args.report, report)
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
