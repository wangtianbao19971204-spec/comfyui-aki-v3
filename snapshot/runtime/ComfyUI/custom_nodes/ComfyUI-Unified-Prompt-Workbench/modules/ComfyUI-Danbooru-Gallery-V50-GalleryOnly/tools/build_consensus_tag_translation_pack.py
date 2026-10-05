#!/usr/bin/env python3
"""Build a conservative, reviewable translation pack from local candidates.

The command is deliberately a *builder*, not an importer:

* SQLite is opened read-only and is never modified.
* The database category and exact database tag are authoritative.
* Artist translations are always excluded.
* Existing non-empty translations always win.
* Copyright and character names require a trusted/authority source by default.
* General and meta tags require a licensed primary candidate plus exact
  agreement from multiple validator snapshots.
* Similar-looking tags are never fuzzy-matched or merged.  Alias handling is a
  separate, non-destructive layer.

All source snapshots are local files.  The output CSV is compatible with
``import_tag_translations.py``; the JSON report and JSONL review queue retain
the evidence used for every decision.
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
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"

ALLOWED_CATEGORIES = frozenset((0, 3, 4, 5))
PROPER_NAME_CATEGORIES = frozenset((3, 4))
DEFAULT_MIN_VALIDATORS = 2
MAX_TAG_BYTES = 256
MAX_TRANSLATION_BYTES = 512
MAX_REVIEW_EXAMPLES = 30

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*")
_SUSPICIOUS_RE = re.compile(
    r"(?:\{\\|@\s*(?:info|label)|whatsthis|\ufffd|<\s*/?\s*(?:script|style))",
    re.IGNORECASE,
)
_BRACKET_PAIRS = (("(", ")"), ("[", "]"), ("{", "}"))

TAG_COLUMNS = ("tag", "name")
TRANSLATION_COLUMNS = (
    "translation_cn",
    "cn_name",
    "zh_cn",
    "lang_zh",
    "chinese",
    "translation",
)
CATEGORY_COLUMNS = ("category", "type")


class ConsensusBuildError(RuntimeError):
    """Raised before a usable pack is emitted."""


@dataclass(frozen=True)
class SourceSpec:
    name: str
    path: Path
    role: str


@dataclass
class LoadedSource:
    spec: SourceSpec
    candidates: Dict[str, str]
    conflicts: Dict[str, List[str]]
    stats: Counter
    sha256: str


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    """Compare path identity, including case aliases and existing hard links."""

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
                raise ConsensusBuildError(
                    "{} and {} must be distinct files (resolved path/hard-link collision)".format(
                        left_name, right_name
                    )
                )


def _recheck_artifact_path(
    artifact_name: str,
    artifact_path: Path,
    protected_paths: Sequence[Tuple[str, Path]],
) -> None:
    _validate_distinct_paths(
        [(artifact_name, artifact_path), *protected_paths]
    )


def normalize_tag(value: object) -> str:
    tag = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return _WHITESPACE_RE.sub("_", tag)


def normalize_translation(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE_RE.sub(" ", value)


def _find_column(headers: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    normalized = {
        unicodedata.normalize("NFKC", str(header)).strip().casefold().replace("-", "_"): header
        for header in headers
    }
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def _source_latin_tokens(tag: str) -> Set[str]:
    return {token.casefold() for token in _LATIN_TOKEN_RE.findall(tag)}


def validate_translation(tag: str, value: object) -> Tuple[Optional[str], str]:
    """Apply format/identity checks without pretending to judge semantics."""

    translation = normalize_translation(value)
    if not translation:
        return None, "empty"
    if len(translation.encode("utf-8")) > MAX_TRANSLATION_BYTES:
        return None, "translation_too_long"
    if _CONTROL_RE.search(translation):
        return None, "control_character"
    if not _HAN_RE.search(translation):
        return None, "no_han"
    if _KANA_RE.search(translation):
        return None, "contains_kana"
    if _HANGUL_RE.search(translation):
        return None, "contains_hangul"
    if _SUSPICIOUS_RE.search(translation):
        return None, "suspicious_artifact"
    if "_" in translation:
        return None, "source_separator_leaked"

    normalized_source = unicodedata.normalize("NFKC", tag)
    for opening, closing in _BRACKET_PAIRS:
        source_shape = (normalized_source.count(opening), normalized_source.count(closing))
        translation_shape = (translation.count(opening), translation.count(closing))
        if source_shape[0] != source_shape[1]:
            return None, "source_brackets_unbalanced"
        if translation_shape[0] != translation_shape[1]:
            return None, "translation_brackets_unbalanced"
        if source_shape != translation_shape:
            return None, "qualifier_shape_mismatch"

    source_latin = _source_latin_tokens(normalized_source)
    leaked_latin = [
        token
        for token in _LATIN_TOKEN_RE.findall(translation)
        if token.casefold() not in source_latin
    ]
    if leaked_latin:
        return None, "unexplained_latin"
    return translation, "accepted"


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def load_database(path: Path) -> Tuple[Dict[str, Dict[str, object]], Dict[str, object]]:
    if not path.is_file():
        raise ConsensusBuildError("database does not exist: {}".format(path))
    connection = _readonly_connection(path)
    try:
        columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(hot_tags)")}
        required = {"tag", "category", "post_count", "translation_cn"}
        if not required.issubset(columns):
            raise ConsensusBuildError(
                "hot_tags is missing columns: {}".format(", ".join(sorted(required - columns)))
            )
        rows: Dict[str, Dict[str, object]] = {}
        categories = Counter()
        translated = Counter()
        for row in connection.execute(
            "SELECT tag, category, post_count, translation_cn FROM hot_tags"
        ):
            exact_tag = str(row["tag"])
            tag = normalize_tag(exact_tag)
            if not tag or len(tag.encode("utf-8")) > MAX_TAG_BYTES:
                raise ConsensusBuildError("invalid database tag: {!r}".format(exact_tag))
            if tag in rows:
                raise ConsensusBuildError("normalized database tag collision: {}".format(tag))
            category = int(row["category"])
            translation = normalize_translation(row["translation_cn"])
            rows[tag] = {
                "exact_tag": exact_tag,
                "category": category,
                "post_count": int(row["post_count"] or 0),
                "translation_cn": translation,
            }
            categories[str(category)] += 1
            if translation:
                translated[str(category)] += 1
        query_only = bool(connection.execute("PRAGMA query_only").fetchone()[0])
        return rows, {
            "path": str(path.resolve()),
            "sha256": file_sha256(path),
            "read_only": True,
            "query_only": query_only,
            "hot_tags_rows": len(rows),
            "rows_by_category": dict(sorted(categories.items())),
            "translated_by_category": dict(sorted(translated.items())),
        }
    finally:
        connection.close()


def _parse_category(value: object) -> Optional[int]:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    if not text:
        return None
    names = {"general": 0, "artist": 1, "copyright": 3, "character": 4, "meta": 5}
    if text.casefold() in names:
        return names[text.casefold()]
    try:
        return int(text)
    except ValueError:
        return None


def load_source(spec: SourceSpec, database: Mapping[str, Mapping[str, object]]) -> LoadedSource:
    path = spec.path.resolve()
    if not path.is_file():
        raise ConsensusBuildError("{} source does not exist: {}".format(spec.name, path))

    raw_candidates: MutableMapping[str, Set[str]] = defaultdict(set)
    stats = Counter()
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise ConsensusBuildError("{} has no CSV header".format(spec.name))
            tag_column = _find_column(reader.fieldnames, TAG_COLUMNS)
            translation_column = _find_column(reader.fieldnames, TRANSLATION_COLUMNS)
            category_column = _find_column(reader.fieldnames, CATEGORY_COLUMNS)
            if not tag_column or not translation_column:
                raise ConsensusBuildError(
                    "{} must contain tag/name and a translation column".format(spec.name)
                )
            for row in reader:
                stats["input_rows"] += 1
                tag = normalize_tag(row.get(tag_column))
                metadata = database.get(tag)
                if metadata is None:
                    stats["not_in_database"] += 1
                    continue
                category = int(metadata["category"])
                if category == 1:
                    stats["artist_blocked"] += 1
                    continue
                if category not in ALLOWED_CATEGORIES:
                    stats["category_blocked"] += 1
                    continue
                if metadata["translation_cn"]:
                    stats["existing_translation"] += 1
                    continue
                if category_column:
                    declared = _parse_category(row.get(category_column))
                    if declared is not None and declared != category:
                        stats["category_mismatch"] += 1
                        continue
                candidate, reason = validate_translation(tag, row.get(translation_column))
                if candidate is None:
                    stats["invalid_{}".format(reason)] += 1
                    continue
                raw_candidates[tag].add(candidate)
                stats["valid_rows"] += 1
    except (UnicodeError, csv.Error) as error:
        raise ConsensusBuildError("unable to parse {}: {}".format(spec.name, error)) from error

    candidates: Dict[str, str] = {}
    conflicts: Dict[str, List[str]] = {}
    for tag, values in raw_candidates.items():
        ordered = sorted(values)
        if len(ordered) == 1:
            candidates[tag] = ordered[0]
        else:
            conflicts[tag] = ordered
            stats["conflicting_tags"] += 1
    stats["usable_tags"] = len(candidates)
    return LoadedSource(
        spec=SourceSpec(spec.name, path, spec.role),
        candidates=candidates,
        conflicts=conflicts,
        stats=stats,
        sha256=file_sha256(path),
    )


def _atomic_csv(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8-sig", newline="", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(
                handle, fieldnames=("tag", "category", "post_count", "translation_cn")
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


def _atomic_json(
    path: Path,
    payload: Mapping[str, object],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
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


def _atomic_jsonl(
    path: Path,
    rows: Sequence[Mapping[str, object]],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
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


def _source_value_map(sources: Sequence[LoadedSource], tag: str) -> Dict[str, str]:
    return {
        source.spec.name: source.candidates[tag]
        for source in sources
        if tag in source.candidates
    }


def build_consensus_pack(
    *,
    db_path: Path,
    primary_specs: Sequence[SourceSpec],
    validator_specs: Sequence[SourceSpec],
    trusted_specs: Sequence[SourceSpec],
    output_path: Path,
    report_path: Path,
    review_path: Path,
    observer_specs: Sequence[SourceSpec] = (),
    min_validators: int = DEFAULT_MIN_VALIDATORS,
    allow_proper_name_consensus: bool = False,
) -> Dict[str, object]:
    if min_validators < 1:
        raise ConsensusBuildError("min_validators must be at least 1")
    if not primary_specs and not trusted_specs:
        raise ConsensusBuildError("at least one primary or trusted source is required")

    db_path = db_path.resolve()
    output_path = output_path.resolve()
    report_path = report_path.resolve()
    review_path = review_path.resolve()
    source_paths = [
        spec.path.resolve()
        for spec in (*primary_specs, *validator_specs, *trusted_specs, *observer_specs)
    ]
    named_inputs = [("database", db_path)] + [
        ("source:{}".format(spec.name), path)
        for spec, path in zip(
            (*primary_specs, *validator_specs, *trusted_specs, *observer_specs),
            source_paths,
        )
    ]
    named_artifacts = [
        ("output", output_path),
        ("report", report_path),
        ("review", review_path),
    ]
    _validate_distinct_paths([*named_inputs, *named_artifacts])
    source_names = [
        spec.name
        for spec in (*primary_specs, *validator_specs, *trusted_specs, *observer_specs)
    ]
    if len(set(source_names)) != len(source_names):
        raise ConsensusBuildError("source names must be unique")

    database, database_report = load_database(db_path)
    primary = [load_source(spec, database) for spec in primary_specs]
    validators = [load_source(spec, database) for spec in validator_specs]
    trusted = [load_source(spec, database) for spec in trusted_specs]
    observers = [load_source(spec, database) for spec in observer_specs]
    sources = [*primary, *validators, *trusted, *observers]
    decision_sources = [*primary, *validators, *trusted]

    candidate_tags: Set[str] = set()
    for source in (*primary, *trusted):
        candidate_tags.update(source.candidates)
        candidate_tags.update(source.conflicts)

    accepted: List[Dict[str, object]] = []
    accepted_evidence: List[Dict[str, object]] = []
    review: List[Dict[str, object]] = []
    decisions = Counter()
    category_counts = Counter()

    for tag in sorted(candidate_tags, key=lambda value: (-int(database[value]["post_count"]), value)):
        metadata = database[tag]
        category = int(metadata["category"])
        primary_values = _source_value_map(primary, tag)
        validator_values = _source_value_map(validators, tag)
        trusted_values = _source_value_map(trusted, tag)
        conflicts = {
            source.spec.name: source.conflicts[tag]
            for source in decision_sources
            if tag in source.conflicts
        }

        evidence = {
            "tag": str(metadata["exact_tag"]),
            "category": category,
            "post_count": int(metadata["post_count"]),
            "primary": primary_values,
            "validators": validator_values,
            "trusted": trusted_values,
            "observers": _source_value_map(observers, tag),
            "source_conflicts": conflicts,
        }

        trusted_unique = set(trusted_values.values())
        if any(name in conflicts for name in [s.spec.name for s in trusted]):
            reason = "trusted_source_conflict"
        elif len(trusted_unique) == 1:
            translation = next(iter(trusted_unique))
            reason = "accepted_trusted"
            accepted.append(
                {
                    "tag": metadata["exact_tag"],
                    "category": category,
                    "post_count": metadata["post_count"],
                    "translation_cn": translation,
                }
            )
            evidence.update({"decision": reason, "translation_cn": translation})
            accepted_evidence.append(evidence)
            decisions[reason] += 1
            category_counts[str(category)] += 1
            continue
        elif len(trusted_unique) > 1:
            reason = "trusted_source_conflict"
        elif category in PROPER_NAME_CATEGORIES and not allow_proper_name_consensus:
            reason = "proper_name_requires_trusted_source"
        elif any(name in conflicts for name in [s.spec.name for s in primary]):
            reason = "primary_source_conflict"
        else:
            primary_unique = set(primary_values.values())
            if not primary_unique:
                reason = "no_primary_candidate"
            elif len(primary_unique) > 1:
                reason = "primary_sources_disagree"
            else:
                translation = next(iter(primary_unique))
                agreeing = sorted(
                    name for name, value in validator_values.items() if value == translation
                )
                disagreeing = {
                    name: value for name, value in validator_values.items() if value != translation
                }
                if disagreeing:
                    reason = "validator_disagreement"
                elif len(agreeing) < min_validators:
                    reason = "insufficient_validator_agreement"
                else:
                    reason = "accepted_primary_consensus"
                    accepted.append(
                        {
                            "tag": metadata["exact_tag"],
                            "category": category,
                            "post_count": metadata["post_count"],
                            "translation_cn": translation,
                        }
                    )
                    evidence.update(
                        {
                            "decision": reason,
                            "translation_cn": translation,
                            "agreeing_validators": agreeing,
                        }
                    )
                    accepted_evidence.append(evidence)
                    decisions[reason] += 1
                    category_counts[str(category)] += 1
                    continue

        evidence["decision"] = reason
        review.append(evidence)
        decisions[reason] += 1

    accepted.sort(key=lambda row: (-int(row["post_count"]), str(row["tag"])))
    _atomic_csv(
        output_path,
        accepted,
        protected_paths=[*named_inputs, ("report", report_path), ("review", review_path)],
    )
    _atomic_jsonl(
        review_path,
        review,
        protected_paths=[*named_inputs, ("output", output_path), ("report", report_path)],
    )

    source_report = []
    for source in sources:
        source_report.append(
            {
                "name": source.spec.name,
                "role": source.spec.role,
                "path": str(source.spec.path),
                "sha256": source.sha256,
                "stats": dict(sorted(source.stats.items())),
            }
        )
    report: Dict[str, object] = {
        "schema_version": 1,
        "mode": "build_only",
        "database_mutated": False,
        "database": database_report,
        "policy": {
            "artist_allowed": False,
            "allowed_categories": sorted(ALLOWED_CATEGORIES),
            "existing_translations_preserved": True,
            "exact_database_tag_only": True,
            "fuzzy_identity_merge": False,
            "proper_name_categories": sorted(PROPER_NAME_CATEGORIES),
            "proper_name_consensus_allowed": bool(allow_proper_name_consensus),
            "min_validator_agreement": min_validators,
            "validator_disagreement_rejected": True,
            "bracket_shape_preserved": True,
            "observer_sources_are_non_voting": True,
        },
        "sources": source_report,
        "decisions": dict(sorted(decisions.items())),
        "output": {
            "path": str(output_path),
            "rows": len(accepted),
            "sha256": file_sha256(output_path),
            "category_counts": dict(sorted(category_counts.items())),
        },
        "review": {
            "path": str(review_path),
            "rows": len(review),
            "sha256": file_sha256(review_path),
            "reason_examples": review[:MAX_REVIEW_EXAMPLES],
        },
        "accepted_examples": accepted_evidence[:MAX_REVIEW_EXAMPLES],
    }
    _atomic_json(
        report_path,
        report,
        protected_paths=[*named_inputs, ("output", output_path), ("review", review_path)],
    )
    return report


def parse_source_spec(value: str, role: str) -> SourceSpec:
    if "=" not in value:
        raise argparse.ArgumentTypeError("source must use NAME=PATH syntax")
    name, raw_path = value.split("=", 1)
    name = unicodedata.normalize("NFKC", name).strip()
    if not name or _CONTROL_RE.search(name):
        raise argparse.ArgumentTypeError("source name is empty or invalid")
    path = Path(raw_path.strip()).expanduser()
    if not raw_path.strip():
        raise argparse.ArgumentTypeError("source path is empty")
    return SourceSpec(name=name, path=path, role=role)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--primary", action="append", default=[], metavar="NAME=PATH",
        help="licensed/reference candidate CSV (repeatable)",
    )
    parser.add_argument(
        "--validator", action="append", default=[], metavar="NAME=PATH",
        help="independent validator CSV (repeatable)",
    )
    parser.add_argument(
        "--trusted", action="append", default=[], metavar="NAME=PATH",
        help="authority-backed CSV eligible without model consensus (repeatable)",
    )
    parser.add_argument(
        "--observer", action="append", default=[], metavar="NAME=PATH",
        help="diagnostic-only CSV that is reported but never gets a vote (repeatable)",
    )
    parser.add_argument("--min-validators", type=int, default=DEFAULT_MIN_VALIDATORS)
    parser.add_argument(
        "--allow-proper-name-consensus", action="store_true",
        help="allow copyright/character model consensus (unsafe; off by default)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    args = parser.parse_args(argv)

    report = build_consensus_pack(
        db_path=args.db,
        primary_specs=[parse_source_spec(value, "primary") for value in args.primary],
        validator_specs=[parse_source_spec(value, "validator") for value in args.validator],
        trusted_specs=[parse_source_spec(value, "trusted") for value in args.trusted],
        output_path=args.output,
        report_path=args.report,
        review_path=args.review,
        observer_specs=[parse_source_spec(value, "observer") for value in args.observer],
        min_validators=args.min_validators,
        allow_proper_name_consensus=args.allow_proper_name_consensus,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
