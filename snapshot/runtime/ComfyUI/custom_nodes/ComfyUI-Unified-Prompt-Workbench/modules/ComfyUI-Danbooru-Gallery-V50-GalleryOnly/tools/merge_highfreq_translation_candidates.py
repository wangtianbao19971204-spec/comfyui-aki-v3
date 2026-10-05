#!/usr/bin/env python3
"""Merge high-frequency tag translations into an auditable review pack.

This tool is deliberately read-only with respect to the Gallery database.  It
keeps one review row for every target, emits an importer-compatible subset only
for safe automatic decisions, and records every conflict/rejection in JSON.
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
from typing import Dict, Iterable, Mapping, Optional, Sequence, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GALLERY_DB = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"
DEFAULT_TARGET_COUNT = 4300
ALLOWED_CATEGORIES = frozenset((0, 3, 4))
MAX_TRANSLATION_BYTES = 512
MAX_TRANSLATION_CHARACTERS = 96

TAG_COLUMNS = ("tag", "name")
TRANSLATION_COLUMNS = (
    "translation_cn",
    "cn_name",
    "zh_cn",
    "lang_zh",
    "chinese",
    "translation",
    "proposed_translation",
)
CONFIDENCE_COLUMNS = (
    "confidence",
    "translation_confidence",
    "score",
    "safe_for_direct_import",
)
KEEP_COLUMNS = (
    "keep_original",
    "decision",
    "decision_bucket",
    "status",
    "review_status",
)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_SUSPICIOUS_RE = re.compile(
    r"(?:<\s*/?\s*(?:script|style)|\ufffd|\bTAB\b|translation_cn\s*[:=])",
    re.IGNORECASE,
)

TARGET_COPY_COLUMNS = (
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
)
REVIEW_COLUMNS = TARGET_COPY_COLUMNS + (
    "translation_cn",
    "chosen_source",
    "supporting_sources",
    "confidence",
    "agreement_count",
    "candidate_count",
    "distinct_translation_count",
    "review_status",
    "qa_reasons",
    "candidate_evidence_json",
)
IMPORT_COLUMNS = ("tag", "category", "post_count", "translation_cn")
AUTO_IMPORT_STATUSES = frozenset(("accepted_consensus", "accepted_authoritative"))


class CandidateMergeError(RuntimeError):
    """Raised before an incomplete or unsafe review bundle is published."""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_tag(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    normalized = _WHITESPACE_RE.sub("_", normalized)
    if not normalized or _CONTROL_RE.search(normalized):
        raise CandidateMergeError("invalid empty/control tag")
    if len(normalized.encode("utf-8")) > 256:
        raise CandidateMergeError("tag exceeds 256 UTF-8 bytes")
    return normalized


def normalize_translation(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE_RE.sub(" ", normalized)


def _translation_key(value: str) -> str:
    return normalize_translation(value).casefold()


def _find_column(headers: Sequence[str], candidates: Sequence[str]) -> Optional[str]:
    normalized = {
        unicodedata.normalize("NFKC", str(header)).strip().casefold(): header
        for header in headers
    }
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def _readonly_connection(path: Path) -> sqlite3.Connection:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise CandidateMergeError("Gallery database is missing: {}".format(resolved))
    try:
        connection = sqlite3.connect(
            resolved.as_uri() + "?mode=ro", uri=True, timeout=30.0
        )
    except sqlite3.Error as exc:
        raise CandidateMergeError(
            "could not open Gallery database read-only: {}".format(exc)
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
        raise CandidateMergeError(
            "{} is missing columns: {}".format(table, ", ".join(missing))
        )


def _parse_named_path(value: str, field: str) -> Tuple[str, Path]:
    name, separator, raw_path = str(value).partition("=")
    name = name.strip()
    if not separator or not name or not raw_path.strip():
        raise CandidateMergeError("{} must use NAME=PATH".format(field))
    if _CONTROL_RE.search(name):
        raise CandidateMergeError("{} source name contains control characters".format(field))
    return name, Path(raw_path.strip()).expanduser().resolve()


def _parse_priority(value: str) -> Tuple[str, int]:
    name, separator, raw_priority = str(value).partition("=")
    if not separator or not name.strip():
        raise CandidateMergeError("--source-priority must use NAME=INTEGER")
    try:
        priority = int(raw_priority)
    except ValueError as exc:
        raise CandidateMergeError("source priority must be an integer") from exc
    if priority < 0 or priority > 1000:
        raise CandidateMergeError("source priority must be between 0 and 1000")
    return name.strip().casefold(), priority


def _default_priority(source_name: str) -> int:
    name = source_name.casefold()
    if any(marker in name for marker in ("curated", "verified", "manual", "reviewed")):
        return 100
    if "wikidata" in name:
        return 95
    if "weilin" in name:
        return 90
    if "boorutagcart" in name or "booru_tag_cart" in name:
        return 75
    if "qwen14" in name:
        return 55
    if "qwen4" in name:
        return 50
    if "qwen" in name or "llm" in name:
        return 45
    return 25


def _source_family(source_name: str) -> str:
    """Collapse duplicate files from the same model/source into one vote."""

    name = source_name.casefold()
    for marker in ("qwen14", "qwen4", "qwen30", "wikidata", "weilin", "boorutagcart"):
        if marker in name:
            return marker
    return name


def _confidence(value: object, priority: int) -> Tuple[str, int]:
    text = str(value or "").strip().casefold()
    if text in {"h", "high", "高", "approved", "verified", "yes", "true"} or text.startswith("high"):
        return "H", 3
    if text in {"m", "medium", "中", "review"} or text.startswith("medium"):
        return "M", 2
    if text in {"l", "low", "低", "no", "false"} or text.startswith("low"):
        return "L", 1
    try:
        numeric = float(text)
    except ValueError:
        numeric = -1.0
    if numeric >= 0.85:
        return "H", 3
    if numeric >= 0.60:
        return "M", 2
    if numeric >= 0:
        return "L", 1
    if priority >= 90:
        return "H", 3
    if priority >= 70:
        return "M", 2
    return "U", 0


def _is_keep_original(row: Mapping[str, object], headers: Sequence[str]) -> bool:
    truthy = {"1", "true", "yes", "y", "keep", "keep_original", "original", "保留原文"}
    for candidate in KEEP_COLUMNS:
        column = _find_column(headers, (candidate,))
        if column:
            value = str(row.get(column) or "").strip().casefold()
            if value in truthy or value.startswith(("retain_original", "preserve_original")):
                return True
    return False


def _is_preapproved(row: Mapping[str, object], headers: Sequence[str]) -> bool:
    safe_column = _find_column(headers, ("safe_for_direct_import",))
    if safe_column and str(row.get(safe_column) or "").strip().casefold() in {
        "1", "true", "yes", "y", "approved"
    }:
        return True
    for name in ("decision", "review_status", "status"):
        column = _find_column(headers, (name,))
        if not column:
            continue
        value = str(row.get(column) or "").strip().casefold()
        if value in {"accepted", "approved", "verified", "auto_accept_strict"}:
            return True
    return False


def _parenthetical_groups(value: object) -> Tuple[Optional[list[str]], str]:
    text = unicodedata.normalize("NFKC", str(value or ""))
    stack: list[int] = []
    groups: list[str] = []
    for index, character in enumerate(text):
        if character == "(":
            stack.append(index)
        elif character == ")":
            if not stack:
                return None, "unbalanced_parentheses"
            opening = stack.pop()
            if not stack:
                content = text[opening + 1 : index].strip()
                if not content:
                    return None, "empty_qualifier_group"
                groups.append(content)
    if stack:
        return None, "unbalanced_parentheses"
    return groups, "accepted"


def _validate_translation(tag: str, value: object) -> Tuple[Optional[str], str]:
    translation = normalize_translation(value)
    if not translation:
        return None, "empty_translation"
    if _CONTROL_RE.search(translation):
        return None, "translation_control_character"
    if len(translation) > MAX_TRANSLATION_CHARACTERS:
        return None, "translation_too_long"
    if len(translation.encode("utf-8")) > MAX_TRANSLATION_BYTES:
        return None, "translation_too_many_bytes"
    if not _HAN_RE.search(translation):
        return None, "translation_no_han"
    if _KANA_RE.search(translation):
        return None, "translation_contains_kana"
    if _HANGUL_RE.search(translation):
        return None, "translation_contains_hangul"
    if _SUSPICIOUS_RE.search(translation):
        return None, "translation_suspicious_artifact"

    source_groups, source_reason = _parenthetical_groups(tag)
    if source_groups is None:
        return None, "source_{}".format(source_reason)
    translation_groups, translation_reason = _parenthetical_groups(translation)
    if translation_groups is None:
        return None, translation_reason
    # Keep every source qualifier group.  Extra groups are allowed because an
    # authoritative Chinese character/work name may add a disambiguating work
    # qualifier (for example, 诗怀雅(明日方舟)).
    if len(translation_groups) < len(source_groups):
        return None, "qualifier_group_lost"
    return translation, "accepted"


def _load_targets(path: Path, expected_count: int) -> list[Dict[str, str]]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise CandidateMergeError("target CSV is missing: {}".format(resolved))
    rows: list[Dict[str, str]] = []
    identities = set()
    with resolved.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or ())
        required = {"rank", "tag", "category", "post_count"}
        missing = sorted(required - set(headers))
        if missing:
            raise CandidateMergeError("target CSV is missing columns: {}".format(", ".join(missing)))
        for expected_rank, raw in enumerate(reader, start=1):
            row = {str(key): str(value or "") for key, value in raw.items()}
            try:
                rank = int(row["rank"])
                category = int(row["category"])
                int(row["post_count"])
            except ValueError as exc:
                raise CandidateMergeError("target row has invalid numeric metadata") from exc
            if rank != expected_rank:
                raise CandidateMergeError("target ranks must be contiguous and ordered")
            if category not in ALLOWED_CATEGORIES:
                raise CandidateMergeError(
                    "target {} uses forbidden artist/meta/unknown category {}".format(
                        row["tag"], category
                    )
                )
            identity = normalize_tag(row["tag"])
            if identity in identities:
                raise CandidateMergeError("duplicate normalized target: {}".format(identity))
            identities.add(identity)
            row["_identity"] = identity
            rows.append(row)
    if len(rows) != expected_count:
        raise CandidateMergeError(
            "target CSV has {} rows; exactly {} are required".format(len(rows), expected_count)
        )
    return rows


def _load_gallery_state(
    path: Path, targets: Sequence[Mapping[str, str]]
) -> Dict[str, Dict[str, object]]:
    state: Dict[str, Dict[str, object]] = {}
    with _readonly_connection(path) as connection:
        _require_columns(
            connection, "hot_tags", ("tag", "category", "post_count", "translation_cn")
        )
        for row in connection.execute(
            "SELECT tag, category, post_count, translation_cn FROM hot_tags"
        ):
            identity = normalize_tag(row["tag"])
            state[identity] = {
                "tag": str(row["tag"]),
                "category": int(row["category"]),
                "post_count": int(row["post_count"]),
                "translation_cn": normalize_translation(row["translation_cn"]),
            }
    for target in targets:
        identity = target["_identity"]
        gallery = state.get(identity)
        if gallery is None:
            raise CandidateMergeError("target is absent from Gallery database: {}".format(target["tag"]))
        if int(target["category"]) != gallery["category"]:
            raise CandidateMergeError("target category drift for {}".format(target["tag"]))
        if int(target["post_count"]) != gallery["post_count"]:
            raise CandidateMergeError("target post_count drift for {}".format(target["tag"]))
    return state


def _load_candidates(
    *,
    sources: Sequence[Tuple[str, Path]],
    priorities: Mapping[str, int],
    target_by_identity: Mapping[str, Mapping[str, str]],
) -> Tuple[Dict[str, list[Dict[str, object]]], Dict[str, object], list[Dict[str, object]]]:
    accepted: Dict[str, list[Dict[str, object]]] = defaultdict(list)
    source_reports: Dict[str, object] = {}
    rejections: list[Dict[str, object]] = []
    seen_source_names = set()
    for source_name, path in sources:
        source_key = source_name.casefold()
        if source_key in seen_source_names:
            raise CandidateMergeError("duplicate candidate source name: {}".format(source_name))
        seen_source_names.add(source_key)
        if not path.is_file():
            raise CandidateMergeError("candidate CSV is missing: {}".format(path))
        priority = priorities.get(source_key, _default_priority(source_name))
        stats = Counter()
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            headers = list(reader.fieldnames or ())
            tag_column = _find_column(headers, TAG_COLUMNS)
            translation_column = _find_column(headers, TRANSLATION_COLUMNS)
            confidence_column = _find_column(headers, CONFIDENCE_COLUMNS)
            if not tag_column:
                raise CandidateMergeError("{} has no tag column".format(path))
            if not translation_column and not any(_find_column(headers, (name,)) for name in KEEP_COLUMNS):
                raise CandidateMergeError("{} has neither translation nor keep_original status".format(path))
            category_column = _find_column(headers, ("category", "type"))
            for row_number, row in enumerate(reader, start=2):
                stats["rows"] += 1
                raw_tag = row.get(tag_column)
                try:
                    identity = normalize_tag(raw_tag)
                except CandidateMergeError:
                    reason = "invalid_tag"
                    identity = ""
                else:
                    target = target_by_identity.get(identity)
                    if target is None:
                        reason = "not_in_target_pack"
                    elif category_column and str(row.get(category_column) or "").strip():
                        try:
                            candidate_category = int(str(row.get(category_column)).strip())
                        except ValueError:
                            reason = "invalid_candidate_category"
                        else:
                            if candidate_category not in ALLOWED_CATEGORIES:
                                reason = "forbidden_artist_meta_category"
                            elif candidate_category != int(target["category"]):
                                reason = "candidate_category_mismatch"
                            else:
                                reason = ""
                    else:
                        reason = ""
                if reason:
                    stats["rejected_{}".format(reason)] += 1
                    rejections.append(
                        {"source": source_name, "row": row_number, "tag": str(raw_tag or ""), "reason": reason}
                    )
                    continue

                keep_original = _is_keep_original(row, headers)
                raw_translation = row.get(translation_column) if translation_column else ""
                confidence, confidence_rank = _confidence(
                    row.get(confidence_column) if confidence_column else "", priority
                )
                preapproved = _is_preapproved(row, headers)
                if keep_original:
                    accepted[identity].append(
                        {
                            "source": source_name,
                            "family": _source_family(source_name),
                            "priority": priority,
                            "confidence": confidence,
                            "confidence_rank": confidence_rank,
                            "decision": "keep_original",
                            "preapproved": False,
                            "translation_cn": "",
                            "row": row_number,
                        }
                    )
                    stats["accepted_keep_original"] += 1
                    continue
                translation, validation = _validate_translation(str(target["tag"]), raw_translation)
                if translation is None:
                    stats["rejected_{}".format(validation)] += 1
                    rejections.append(
                        {
                            "source": source_name,
                            "row": row_number,
                            "tag": str(target["tag"]),
                            "reason": validation,
                            "candidate": str(raw_translation or ""),
                        }
                    )
                    continue
                accepted[identity].append(
                    {
                        "source": source_name,
                        "family": _source_family(source_name),
                        "priority": priority,
                        "confidence": confidence,
                        "confidence_rank": confidence_rank,
                        "decision": "translation",
                        "preapproved": preapproved,
                        "translation_cn": translation,
                        "translation_key": _translation_key(translation),
                        "row": row_number,
                    }
                )
                stats["accepted_translation"] += 1
        source_reports[source_name] = {
            "path": str(path),
            "sha256": file_sha256(path),
            "priority": priority,
            "stats": dict(sorted(stats.items())),
        }
    return dict(accepted), source_reports, rejections


def _decide(
    target: Mapping[str, str],
    evidence: Sequence[Mapping[str, object]],
    existing_translation: str,
) -> Dict[str, object]:
    public_evidence = [
        {
            "source": item["source"],
            "family": item["family"],
            "priority": item["priority"],
            "confidence": item["confidence"],
            "decision": item["decision"],
            "preapproved": bool(item.get("preapproved")),
            "translation_cn": item["translation_cn"],
            "row": item["row"],
        }
        for item in evidence
    ]
    if existing_translation:
        return {
            "translation_cn": "",
            "chosen_source": "",
            "supporting_sources": "",
            "confidence": "",
            "agreement_count": 0,
            "candidate_count": len(evidence),
            "distinct_translation_count": 0,
            "review_status": "blocked_existing_translation",
            "qa_reasons": "Gallery已有翻译，禁止覆盖",
            "evidence": public_evidence,
            "conflict": None,
        }

    groups: Dict[str, list[Mapping[str, object]]] = defaultdict(list)
    keep_rows = []
    for item in evidence:
        if item["decision"] == "keep_original":
            keep_rows.append(item)
        else:
            groups[str(item["translation_key"])].append(item)
    if not groups:
        if keep_rows:
            sources = sorted(
                {str(item["source"]) for item in keep_rows},
                key=lambda name: (-max(int(x["priority"]) for x in keep_rows if x["source"] == name), name.casefold()),
            )
            families = {str(item["family"]) for item in keep_rows}
            best = max(keep_rows, key=lambda item: (int(item["priority"]), int(item["confidence_rank"]), -int(item["row"])))
            return {
                "translation_cn": "",
                "chosen_source": best["source"],
                "supporting_sources": ";".join(sources),
                "confidence": best["confidence"],
                "agreement_count": len(families),
                "candidate_count": len(evidence),
                "distinct_translation_count": 0,
                "review_status": "keep_original",
                "qa_reasons": "明确保留原始tag，不写入中文翻译",
                "evidence": public_evidence,
                "conflict": None,
            }
        return {
            "translation_cn": "",
            "chosen_source": "",
            "supporting_sources": "",
            "confidence": "",
            "agreement_count": 0,
            "candidate_count": 0,
            "distinct_translation_count": 0,
            "review_status": "missing_candidate",
            "qa_reasons": "没有通过QA的候选",
            "evidence": public_evidence,
            "conflict": None,
        }

    ranked_groups = []
    for key, items in groups.items():
        sources = {str(item["source"]) for item in items}
        families = {str(item["family"]) for item in items}
        best = max(
            items,
            key=lambda item: (
                int(item["priority"]), int(item["confidence_rank"]), -int(item["row"])
            ),
        )
        ranked_groups.append(
            {
                "key": key,
                "items": items,
                "sources": sources,
                "families": families,
                "best": best,
                "rank": (
                    len(families),
                    max(int(item["priority"]) for item in items),
                    max(int(item["confidence_rank"]) for item in items),
                ),
            }
        )
    ranked_groups.sort(
        key=lambda group: (
            -group["rank"][0], -group["rank"][1], -group["rank"][2], group["key"]
        )
    )
    chosen = ranked_groups[0]
    best = chosen["best"]
    sources = sorted(
        chosen["sources"],
        key=lambda name: (
            -max(int(item["priority"]) for item in chosen["items"] if item["source"] == name),
            name.casefold(),
        ),
    )
    conflict = len(ranked_groups) > 1 or bool(keep_rows)
    if conflict:
        review_status = "needs_review_conflict"
        qa_reasons = "存在竞争译名或keep_original意见，不自动导入"
    elif bool(best.get("preapproved")) or (
        int(best["priority"]) >= 90 and str(best["confidence"]) != "L"
    ):
        review_status = "accepted_authoritative"
        qa_reasons = "候选已预审或来自单一高优先级来源并通过QA"
    elif len(chosen["families"]) >= 2 and int(target["category"]) in (3, 4):
        review_status = "needs_review_proper_name_consensus"
        qa_reasons = "作品/角色正式名虽有普通来源共识，但缺少权威来源，需人工复核"
    elif len(chosen["families"]) >= 2:
        review_status = "accepted_consensus"
        qa_reasons = "至少两个独立候选来源一致"
    else:
        review_status = "needs_review_single"
        qa_reasons = "仅单一普通来源，需人工复核"
    conflict_record = None
    if conflict:
        conflict_record = {
            "tag": target["tag"],
            "choices": [
                {
                    "translation_cn": group["best"]["translation_cn"],
                    "sources": sorted(group["sources"]),
                    "source_families": sorted(group["families"]),
                    "agreement_count": len(group["families"]),
                    "maximum_priority": group["rank"][1],
                }
                for group in ranked_groups
            ],
            "keep_original_sources": sorted({str(item["source"]) for item in keep_rows}),
            "keep_original_source_families": sorted(
                {str(item["family"]) for item in keep_rows}
            ),
        }
    return {
        "translation_cn": best["translation_cn"],
        "chosen_source": best["source"],
        "supporting_sources": ";".join(sources),
        "confidence": best["confidence"],
        "agreement_count": len(chosen["families"]),
        "candidate_count": len(evidence),
        "distinct_translation_count": len(ranked_groups),
        "review_status": review_status,
        "qa_reasons": qa_reasons,
        "evidence": public_evidence,
        "conflict": conflict_record,
    }


def _validate_output_paths(inputs: Sequence[Path], outputs: Sequence[Path]) -> None:
    resolved_inputs = [Path(path).expanduser().resolve() for path in inputs]
    resolved_outputs = [Path(path).expanduser().resolve() for path in outputs]
    if len({str(path).casefold() for path in resolved_outputs}) != len(resolved_outputs):
        raise CandidateMergeError("output paths must be distinct")
    for output in resolved_outputs:
        if os.path.lexists(str(output)):
            raise CandidateMergeError("refusing to overwrite existing artifact: {}".format(output))
        if any(str(output).casefold() == str(path).casefold() for path in resolved_inputs):
            raise CandidateMergeError("output path collides with an input")


def _temporary_text(path: Path, encoding: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding=encoding, newline="", dir=path.parent,
        prefix=path.name + ".", suffix=".tmp", delete=False,
    )
    return handle, Path(handle.name)


def _publish_bundle(artifacts: Sequence[Tuple[Path, Path]]) -> None:
    published: list[Tuple[Path, Path]] = []
    try:
        for temporary, target in artifacts:
            try:
                os.link(temporary, target)
            except FileExistsError as exc:
                raise CandidateMergeError("refusing to overwrite raced output: {}".format(target)) from exc
            published.append((temporary, target))
    except Exception:
        for temporary, target in reversed(published):
            try:
                if target.exists() and os.path.samefile(temporary, target):
                    target.unlink()
            except OSError:
                pass
        raise
    finally:
        for temporary, _target in artifacts:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


def merge_translation_candidates(
    *,
    targets_path: Path | str,
    gallery_db_path: Path | str,
    candidates: Sequence[Tuple[str, Path | str]],
    review_output_path: Path | str,
    import_output_path: Path | str,
    report_path: Path | str,
    expected_target_count: int = DEFAULT_TARGET_COUNT,
    source_priorities: Optional[Mapping[str, int]] = None,
) -> Dict[str, object]:
    if expected_target_count < 1:
        raise CandidateMergeError("expected_target_count must be positive")
    targets_file = Path(targets_path).expanduser().resolve()
    gallery_db = Path(gallery_db_path).expanduser().resolve()
    source_paths = [(name, Path(path).expanduser().resolve()) for name, path in candidates]
    if not source_paths:
        raise CandidateMergeError("at least one candidate CSV is required")
    review_output = Path(review_output_path).expanduser().resolve()
    import_output = Path(import_output_path).expanduser().resolve()
    report_output = Path(report_path).expanduser().resolve()
    inputs = [targets_file, gallery_db] + [path for _name, path in source_paths]
    outputs = [review_output, import_output, report_output]
    _validate_output_paths(inputs, outputs)
    for path in inputs:
        if not path.is_file():
            raise CandidateMergeError("required input is missing: {}".format(path))
    input_hashes_before = {str(path): file_sha256(path) for path in inputs}

    targets = _load_targets(targets_file, expected_target_count)
    gallery = _load_gallery_state(gallery_db, targets)
    target_by_identity = {row["_identity"]: row for row in targets}
    priorities = {str(key).casefold(): int(value) for key, value in (source_priorities or {}).items()}
    evidence_by_tag, source_reports, rejections = _load_candidates(
        sources=source_paths, priorities=priorities, target_by_identity=target_by_identity
    )

    review_rows = []
    import_rows = []
    status_counts = Counter()
    conflicts = []
    for target in targets:
        identity = target["_identity"]
        decision = _decide(
            target,
            evidence_by_tag.get(identity, ()),
            str(gallery[identity]["translation_cn"] or ""),
        )
        status_counts[str(decision["review_status"])] += 1
        if decision["conflict"] is not None:
            conflicts.append(decision["conflict"])
        review_row = {column: target.get(column, "") for column in TARGET_COPY_COLUMNS}
        review_row.update(
            {
                "translation_cn": decision["translation_cn"],
                "chosen_source": decision["chosen_source"],
                "supporting_sources": decision["supporting_sources"],
                "confidence": decision["confidence"],
                "agreement_count": decision["agreement_count"],
                "candidate_count": decision["candidate_count"],
                "distinct_translation_count": decision["distinct_translation_count"],
                "review_status": decision["review_status"],
                "qa_reasons": decision["qa_reasons"],
                "candidate_evidence_json": json.dumps(
                    decision["evidence"], ensure_ascii=False, separators=(",", ":")
                ),
            }
        )
        review_rows.append(review_row)
        if decision["review_status"] in AUTO_IMPORT_STATUSES:
            import_rows.append(
                {
                    "tag": target["tag"],
                    "category": target["category"],
                    "post_count": target["post_count"],
                    "translation_cn": decision["translation_cn"],
                }
            )

    input_hashes_after = {str(path): file_sha256(path) for path in inputs}
    if input_hashes_after != input_hashes_before:
        raise CandidateMergeError("an input changed while the review bundle was built")

    review_handle, review_temp = _temporary_text(review_output, "utf-8-sig")
    import_handle, import_temp = _temporary_text(import_output, "utf-8-sig")
    report_temp = None
    try:
        review_writer = csv.DictWriter(review_handle, fieldnames=REVIEW_COLUMNS)
        review_writer.writeheader()
        review_writer.writerows(review_rows)
        review_handle.flush()
        os.fsync(review_handle.fileno())
        review_handle.close()

        import_writer = csv.DictWriter(import_handle, fieldnames=IMPORT_COLUMNS)
        import_writer.writeheader()
        import_writer.writerows(import_rows)
        import_handle.flush()
        os.fsync(import_handle.fileno())
        import_handle.close()

        report = {
            "schema_version": 1,
            "database_mutated": False,
            "inputs_unchanged": True,
            "policy": {
                "expected_target_rows": expected_target_count,
                "allowed_categories": [0, 3, 4],
                "artist_allowed": False,
                "meta_allowed": False,
                "overwrite_existing_translation": False,
                "translation_requires_han_or_explicit_keep_original": True,
                "source_qualifier_groups_must_be_preserved": True,
                "extra_disambiguation_groups_allowed": True,
                "conflicts_auto_imported": False,
                "auto_import_statuses": sorted(AUTO_IMPORT_STATUSES),
                "selection_order": [
                    "independent source agreement DESC",
                    "source priority DESC",
                    "confidence DESC",
                    "normalized translation ASC",
                ],
            },
            "inputs": {
                "targets": {"path": str(targets_file), "sha256": input_hashes_before[str(targets_file)]},
                "gallery_db": {
                    "path": str(gallery_db), "sha256": input_hashes_before[str(gallery_db)], "read_only": True
                },
                "candidates": source_reports,
            },
            "results": {
                "review_rows": len(review_rows),
                "import_rows": len(import_rows),
                "review_status_counts": dict(sorted(status_counts.items())),
                "candidate_rejections": len(rejections),
                "conflicts": len(conflicts),
            },
            "outputs": {
                "review": {"path": str(review_output), "rows": len(review_rows), "sha256": file_sha256(review_temp)},
                "import": {"path": str(import_output), "rows": len(import_rows), "sha256": file_sha256(import_temp)},
            },
            "conflicts": conflicts,
            "rejections": rejections,
        }
        report_handle, report_temp = _temporary_text(report_output, "utf-8")
        json.dump(report, report_handle, ensure_ascii=False, indent=2, sort_keys=True)
        report_handle.write("\n")
        report_handle.flush()
        os.fsync(report_handle.fileno())
        report_handle.close()
        _validate_output_paths(inputs, outputs)
        _publish_bundle(
            ((review_temp, review_output), (import_temp, import_output), (report_temp, report_output))
        )
        return report
    except Exception:
        for handle in (review_handle, import_handle):
            if not handle.closed:
                handle.close()
        for temporary in (review_temp, import_temp, report_temp):
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
        raise


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--gallery-db", type=Path, default=DEFAULT_GALLERY_DB)
    parser.add_argument("--candidate", action="append", required=True, help="NAME=PATH; repeatable")
    parser.add_argument(
        "--source-priority", action="append", default=[], help="NAME=INTEGER; repeatable"
    )
    parser.add_argument("--review-output", type=Path, required=True)
    parser.add_argument("--import-output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--expected-target-count", type=int, default=DEFAULT_TARGET_COUNT)
    arguments = parser.parse_args(argv)
    sources = [_parse_named_path(value, "--candidate") for value in arguments.candidate]
    priorities = dict(_parse_priority(value) for value in arguments.source_priority)
    report = merge_translation_candidates(
        targets_path=arguments.targets,
        gallery_db_path=arguments.gallery_db,
        candidates=sources,
        review_output_path=arguments.review_output,
        import_output_path=arguments.import_output,
        report_path=arguments.report,
        expected_target_count=arguments.expected_target_count,
        source_priorities=priorities,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
