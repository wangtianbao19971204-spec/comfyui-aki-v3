#!/usr/bin/env python3
"""Build a guarded translation CSV from the pinned BooruTagCart reference.

This command performs no network access and opens the live tag database in
read-only/query-only mode.  It only creates a reviewable CSV pack; it never
imports translations or mutates SQLite.
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
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"

SOURCE_REPOSITORY = "https://github.com/xhoxye/BooruTagCart"
SOURCE_REVISION = "18bd2b3d81aeceade9fd24559d8957dafa22e1a3"
SOURCE_SHA256 = "41869c065b0c067f2e5e88e2d1152a3509da53bfc71c87ab6a9beff1d1fca1a1"
SOURCE_LICENSE = "GPL-3.0"
SOURCE_PATH = "assets/danbooru_%E7%BF%BB%E8%AF%91%E5%8F%82%E8%80%83%E6%96%87%E6%A1%A3.csv"
SOURCE_BLOB_URL = "{}/blob/{}/{}".format(
    SOURCE_REPOSITORY, SOURCE_REVISION, SOURCE_PATH
)
SOURCE_RAW_URL = "https://raw.githubusercontent.com/xhoxye/BooruTagCart/{}/{}".format(
    SOURCE_REVISION, SOURCE_PATH
)

ALLOWED_CATEGORIES = frozenset((0, 3, 4, 5))
MAX_WORDS = 6
MAX_TAG_CHARS = 256
MAX_TRANSLATION_CHARS = 128
MAX_CSV_FIELD_BYTES = 1024 * 1024

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['\u2019][A-Za-z0-9]+)?")
_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")


class PackBuildError(RuntimeError):
    """Raised before output is produced when an input safety check fails."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    left = Path(left).expanduser().resolve()
    right = Path(right).expanduser().resolve()
    if str(left).casefold() == str(right).casefold():
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def _validate_distinct_paths(named_paths: Sequence[Tuple[str, Path]]) -> None:
    resolved = [(name, Path(path).expanduser().resolve()) for name, path in named_paths]
    for index, (left_name, left_path) in enumerate(resolved):
        for right_name, right_path in resolved[index + 1 :]:
            if _paths_refer_to_same_file(left_path, right_path):
                raise PackBuildError(
                    "{} and {} must be distinct files (resolved path/hard-link collision)".format(
                        left_name, right_name
                    )
                )


def _recheck_artifact_path(
    artifact_name: str,
    artifact_path: Path,
    protected_paths: Sequence[Tuple[str, Path]],
) -> None:
    _validate_distinct_paths([(artifact_name, artifact_path), *protected_paths])


def normalize_tag(value: object) -> str:
    tag = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return _WHITESPACE_RE.sub("_", tag)


def normalize_translation(value: object) -> str:
    translation = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE_RE.sub(" ", translation)


def tag_word_count(tag: str) -> int:
    return len(_WORD_RE.findall(tag))


def validate_candidate(tag: str, raw_candidate: object) -> Tuple[Optional[str], str]:
    candidate = normalize_translation(raw_candidate)
    if not candidate:
        return None, "empty"
    if len(candidate) > MAX_TRANSLATION_CHARS:
        return None, "translation_length"
    if _CONTROL_RE.search(candidate):
        return None, "control_character"
    if not _HAN_RE.search(candidate):
        return None, "no_han"
    if _KANA_RE.search(candidate):
        return None, "contains_kana"
    if _HANGUL_RE.search(candidate):
        return None, "contains_hangul"

    source = unicodedata.normalize("NFKC", tag)
    source_open = source.count("(")
    source_close = source.count(")")
    candidate_open = candidate.count("(")
    candidate_close = candidate.count(")")
    if source_open != source_close:
        return None, "source_parentheses_unbalanced"
    if (
        candidate_open != candidate_close
        or candidate_open != source_open
        or candidate_close != source_close
    ):
        return None, "qualifier_mismatch"
    return candidate, "accepted"


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30.0
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def load_live_metadata(db_path: Path) -> Tuple[Dict[str, Dict[str, object]], Dict[str, object]]:
    connection = _readonly_connection(db_path)
    try:
        columns = {
            str(row[1]) for row in connection.execute("PRAGMA table_info(hot_tags)")
        }
        required = {"tag", "category", "post_count", "translation_cn"}
        if not required.issubset(columns):
            raise PackBuildError(
                "hot_tags is missing columns: {}".format(
                    ", ".join(sorted(required - columns))
                )
            )

        metadata: Dict[str, Dict[str, object]] = {}
        categories = Counter()
        missing_allowed = Counter()
        for row in connection.execute(
            "SELECT tag, category, post_count, translation_cn FROM hot_tags"
        ):
            tag = normalize_tag(row["tag"])
            category = int(row["category"])
            translation = str(row["translation_cn"] or "").strip()
            if tag in metadata:
                raise PackBuildError("normalized live tag collision: {}".format(tag))
            metadata[tag] = {
                "category": category,
                "post_count": int(row["post_count"] or 0),
                "translated": bool(translation),
            }
            categories[str(category)] += 1
            if category in ALLOWED_CATEGORIES and not translation:
                missing_allowed[str(category)] += 1
        return metadata, {
            "read_only": True,
            "query_only": bool(connection.execute("PRAGMA query_only").fetchone()[0]),
            "hot_tags_rows": len(metadata),
            "rows_by_category": dict(sorted(categories.items())),
            "missing_allowed_by_category": dict(sorted(missing_allowed.items())),
        }
    finally:
        connection.close()


def _atomic_write_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8-sig",
            newline="",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(
                handle,
                fieldnames=("tag", "category", "post_count", "translation_cn"),
            )
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        _recheck_artifact_path("output", path, protected_paths)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _atomic_write_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _recheck_artifact_path("review", path, protected_paths)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _atomic_write_report(
    path: Path,
    report: Mapping[str, object],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        _recheck_artifact_path("report", path, protected_paths)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _review_entry(
    tag: str,
    metadata: Mapping[str, object],
    source_rows: Sequence[Mapping[str, object]],
    reason: str,
    *,
    valid_candidates: Sequence[str] = (),
    rejected_candidates: Sequence[Mapping[str, object]] = (),
) -> Dict[str, object]:
    return {
        "tag": tag,
        "category": int(metadata["category"]),
        "post_count": int(metadata["post_count"]),
        "reason": reason,
        "source_lines": [int(row["line"]) for row in source_rows],
        "raw_translations": [str(row["translation"]) for row in source_rows],
        "source_notes": [str(row["note"]) for row in source_rows],
        "valid_candidates": list(valid_candidates),
        "rejected_candidates": list(rejected_candidates),
    }


def build_pack(
    source_path: Path,
    db_path: Path,
    output_path: Path,
    report_path: Path,
    review_path: Path,
    *,
    expected_sha256: str = SOURCE_SHA256,
) -> Dict[str, object]:
    source_path = Path(source_path).expanduser().resolve()
    db_path = Path(db_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    report_path = Path(report_path).expanduser().resolve()
    review_path = Path(review_path).expanduser().resolve()

    if not source_path.is_file():
        raise PackBuildError("source CSV does not exist: {}".format(source_path))
    if not db_path.is_file():
        raise PackBuildError("tag database does not exist: {}".format(db_path))
    named_inputs = [("source", source_path), ("database", db_path)]
    named_artifacts = [
        ("output", output_path),
        ("report", report_path),
        ("review", review_path),
    ]
    _validate_distinct_paths([*named_inputs, *named_artifacts])

    actual_sha256 = file_sha256(source_path)
    if actual_sha256.casefold() != str(expected_sha256).strip().casefold():
        raise PackBuildError(
            "source SHA256 mismatch: expected {}, got {}".format(
                expected_sha256, actual_sha256
            )
        )

    live, database_report = load_live_metadata(db_path)
    row_counts = Counter()
    eligible_rows: Dict[str, List[Dict[str, object]]] = defaultdict(list)
    early_review: List[Dict[str, object]] = []

    previous_field_limit = csv.field_size_limit()
    csv.field_size_limit(MAX_CSV_FIELD_BYTES)
    try:
        with source_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            for line_number, row in enumerate(reader, start=1):
                row_counts["input_rows"] += 1
                if len(row) < 3:
                    row_counts["malformed_rows"] += 1
                    early_review.append(
                        {
                            "line": line_number,
                            "reason": "malformed_row",
                            "column_count": len(row),
                        }
                    )
                    continue
                tag = normalize_tag(row[0])
                raw_translation = str(row[1] or "").strip()
                note = " | ".join(str(value or "").strip() for value in row[2:])
                if not tag or len(tag) > MAX_TAG_CHARS or _CONTROL_RE.search(tag):
                    row_counts["invalid_tag_rows"] += 1
                    early_review.append(
                        {"line": line_number, "tag": tag, "reason": "invalid_tag"}
                    )
                    continue
                metadata = live.get(tag)
                if metadata is None:
                    row_counts["not_in_live_database_rows"] += 1
                    continue
                category = int(metadata["category"])
                if category == 1:
                    row_counts["artist_rows"] += 1
                    continue
                if category not in ALLOWED_CATEGORIES:
                    row_counts["disallowed_category_rows"] += 1
                    continue
                if bool(metadata["translated"]):
                    row_counts["existing_translation_rows"] += 1
                    continue
                row_counts["eligible_database_rows"] += 1
                eligible_rows[tag].append(
                    {
                        "line": line_number,
                        "translation": raw_translation,
                        "note": note,
                    }
                )
    except (UnicodeError, csv.Error) as error:
        raise PackBuildError("unable to parse source CSV: {}".format(error)) from error
    finally:
        csv.field_size_limit(previous_field_limit)

    accepted_rows: List[Dict[str, object]] = []
    review_rows = list(early_review)
    decision_counts = Counter()
    output_categories = Counter()
    for tag in sorted(eligible_rows):
        source_rows = eligible_rows[tag]
        metadata = live[tag]
        words = tag_word_count(tag)
        if words < 1 or words > MAX_WORDS:
            decision_counts["review_tag_word_count"] += 1
            review_rows.append(
                _review_entry(tag, metadata, source_rows, "tag_word_count")
            )
            continue

        valid_candidates: List[str] = []
        rejected_candidates: List[Dict[str, object]] = []
        for source_row in source_rows:
            raw_candidates = str(source_row["translation"]).split("|")
            for raw_candidate in raw_candidates:
                candidate, reason = validate_candidate(tag, raw_candidate)
                if candidate is not None:
                    if candidate not in valid_candidates:
                        valid_candidates.append(candidate)
                else:
                    rejected_candidates.append(
                        {
                            "line": int(source_row["line"]),
                            "candidate": str(raw_candidate).strip(),
                            "reason": reason,
                        }
                    )

        if len(valid_candidates) == 1:
            category = int(metadata["category"])
            accepted_rows.append(
                {
                    "tag": tag,
                    "category": category,
                    "post_count": int(metadata["post_count"]),
                    "translation_cn": valid_candidates[0],
                }
            )
            decision_counts["accepted_unique_candidate"] += 1
            output_categories[str(category)] += 1
        elif len(valid_candidates) > 1:
            decision_counts["review_ambiguous_candidates"] += 1
            review_rows.append(
                _review_entry(
                    tag,
                    metadata,
                    source_rows,
                    "ambiguous_candidates",
                    valid_candidates=valid_candidates,
                    rejected_candidates=rejected_candidates,
                )
            )
        else:
            decision_counts["review_no_valid_candidate"] += 1
            review_rows.append(
                _review_entry(
                    tag,
                    metadata,
                    source_rows,
                    "no_valid_candidate",
                    rejected_candidates=rejected_candidates,
                )
            )

    _atomic_write_csv(
        output_path,
        accepted_rows,
        protected_paths=[*named_inputs, ("report", report_path), ("review", review_path)],
    )
    _atomic_write_jsonl(
        review_path,
        review_rows,
        protected_paths=[*named_inputs, ("output", output_path), ("report", report_path)],
    )
    report: Dict[str, object] = {
        "schema_version": 1,
        "mode": "build_only",
        "database_mutated": False,
        "source": {
            "repository": SOURCE_REPOSITORY,
            "blob_url": SOURCE_BLOB_URL,
            "raw_url": SOURCE_RAW_URL,
            "revision": SOURCE_REVISION,
            "license": SOURCE_LICENSE,
            "path": str(source_path),
            "bytes": source_path.stat().st_size,
            "expected_sha256": str(expected_sha256).casefold(),
            "actual_sha256": actual_sha256,
            "has_header": False,
            "columns": ["tag", "translation", "description"],
        },
        "database": {
            "path": str(db_path),
            **database_report,
        },
        "policy": {
            "allowed_categories": sorted(ALLOWED_CATEGORIES),
            "artist_allowed": False,
            "existing_translations_preserved": True,
            "max_words": MAX_WORDS,
            "requires_han": True,
            "rejects_kana": True,
            "rejects_hangul": True,
            "requires_matching_parenthesis_groups": True,
            "candidate_separator": "|",
            "accepted_valid_candidate_count": 1,
        },
        "source_row_counts": dict(sorted(row_counts.items())),
        "decision_counts": dict(sorted(decision_counts.items())),
        "output": {
            "path": str(output_path),
            "rows": len(accepted_rows),
            "category_counts": dict(sorted(output_categories.items())),
            "sha256": file_sha256(output_path),
        },
        "review": {
            "path": str(review_path),
            "rows": len(review_rows),
            "sha256": file_sha256(review_path),
        },
    }
    _atomic_write_report(
        report_path,
        report,
        protected_paths=[*named_inputs, ("output", output_path), ("review", review_path)],
    )
    return report


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="pinned headerless source CSV")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_argument_parser().parse_args(argv)
    report = build_pack(
        args.source,
        args.db,
        args.output,
        args.report,
        args.review,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
