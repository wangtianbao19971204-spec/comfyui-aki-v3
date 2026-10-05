#!/usr/bin/env python3
"""Assemble the fixed 4,300-row high-frequency translation review delivery.

The safe import is the only source allowed to populate ``final_translation_cn``.
All other translation sources are review evidence.  This keeps the workbook useful
without silently promoting model/API candidates into Gallery autocomplete.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence


ALLOWED_CATEGORIES = {0, 3, 4}
TARGET_REQUIRED = {
    "rank",
    "tag",
    "category",
    "category_name",
    "post_count",
    "classification_source",
}
OUTPUT_COLUMNS = (
    "rank",
    "tag",
    "category",
    "category_name",
    "post_count",
    "candidate_translation_cn",
    "final_translation_cn",
    "review_status",
    "source",
    "confidence",
    "qa_reason",
    "weilin_group",
    "weilin_subgroup",
    "weilin_paths",
    "classification_source",
)
TRANSLATION_COLUMNS = (
    "final_translation_cn",
    "proposed_correction_cn",
    "translation_cn",
    "proposed_translation_cn",
    "review_translation_candidate",
    "auto_import_translation",
    "reconstructed_translation",
    "bangumi_translation_cn",
    "simplified_chinese_name",
    "baseline_translation",
    "qwen_translation",
    "weilin_name_head",
    "candidate_translation_cn",
    "candidate_cn",
    "cn_name",
    "zh_cn",
)
CONFIDENCE_COLUMNS = (
    "confidence",
    "qwen_confidence",
    "baseline_safety",
    "decision_confidence",
)
REASON_COLUMNS = (
    "qa_reason",
    "decision_reason",
    "final_reason",
    "reason",
    "baseline_reason",
)
STATUS_COLUMNS = (
    "review_status",
    "final_status",
    "final_action",
    "decision",
    "status",
)
PRESERVE_MARKERS = (
    "preserve_original",
    "keep_original",
    "retain_original",
    "保留原文",
)
REJECT_MARKERS = (
    "reject",
    "blocked",
    "unsafe",
    "conflict",
    "no_candidate",
    "missing_candidate",
)
_HAN_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DeliveryError(RuntimeError):
    """Raised before incomplete or unsafe delivery files are published."""


def _normal(value: object) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def _tag_key(value: object) -> str:
    tag = _normal(value).casefold().replace(" ", "_")
    tag = re.sub(r"_+", "_", tag)
    if not tag or _CONTROL_RE.search(tag):
        raise DeliveryError("invalid empty/control tag")
    return tag


def _translation(value: object) -> str:
    text = _normal(value)
    if not text or _CONTROL_RE.search(text) or not _HAN_RE.search(text):
        return ""
    if len(text) > 160 or len(text.encode("utf-8")) > 512:
        return ""
    return text


def _read_csv(path: Path, label: str) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        raise DeliveryError(f"{label} is missing: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        headers = list(reader.fieldnames or [])
        if not headers:
            raise DeliveryError(f"{label} has no header: {path}")
        return headers, [dict(row) for row in reader]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_spec(value: str, field: str) -> tuple[str, Path]:
    name, separator, raw_path = value.partition("=")
    if not separator or not name.strip() or not raw_path.strip():
        raise DeliveryError(f"{field} must use NAME=PATH")
    return name.strip(), Path(raw_path).expanduser().resolve()


def _first(row: Mapping[str, object], columns: Sequence[str]) -> str:
    for column in columns:
        value = _normal(row.get(column))
        if value:
            return value
    return ""


def _status_text(row: Mapping[str, object]) -> str:
    return " ".join(_normal(row.get(column)).casefold() for column in STATUS_COLUMNS)


def _is_preserve(row: Mapping[str, object]) -> bool:
    status = _status_text(row)
    return any(marker in status for marker in PRESERVE_MARKERS)


def _is_rejected(row: Mapping[str, object]) -> bool:
    status = _status_text(row)
    return any(marker in status for marker in REJECT_MARKERS)


def _candidate_from_row(row: Mapping[str, object]) -> str:
    if _is_preserve(row) or _is_rejected(row):
        return ""
    for column in TRANSLATION_COLUMNS:
        candidate = _translation(row.get(column))
        if candidate:
            return candidate
    return ""


def _confidence(row: Mapping[str, object]) -> str:
    value = _first(row, CONFIDENCE_COLUMNS).casefold()
    if value in {"h", "high", "safe", "approved", "verified"} or value.startswith("high"):
        return "H"
    if value in {"m", "medium", "review"} or value.startswith("medium"):
        return "M"
    if value in {"l", "low", "unsafe"} or value.startswith("low"):
        return "L"
    return "U"


def _reason(row: Mapping[str, object], fallback: str) -> str:
    return _first(row, REASON_COLUMNS) or fallback


def _load_targets(path: Path, expected_rows: int) -> list[dict[str, str]]:
    headers, rows = _read_csv(path, "targets")
    missing = sorted(TARGET_REQUIRED.difference(headers))
    if missing:
        raise DeliveryError(f"targets missing columns: {', '.join(missing)}")
    if len(rows) != expected_rows:
        raise DeliveryError(f"targets have {len(rows)} rows; expected {expected_rows}")
    seen: set[str] = set()
    for expected_rank, row in enumerate(rows, start=1):
        try:
            rank = int(_normal(row["rank"]))
            category = int(_normal(row["category"]))
            int(_normal(row["post_count"]))
        except ValueError as exc:
            raise DeliveryError("target numeric metadata is invalid") from exc
        if rank != expected_rank:
            raise DeliveryError("target ranks must be contiguous and ordered")
        if category not in ALLOWED_CATEGORIES:
            raise DeliveryError(f"forbidden target category {category}: {row['tag']}")
        key = _tag_key(row["tag"])
        if key in seen:
            raise DeliveryError(f"duplicate target: {row['tag']}")
        seen.add(key)
    return rows


def _load_safe(path: Path, targets: Mapping[str, Mapping[str, str]]) -> dict[str, dict[str, str]]:
    headers, rows = _read_csv(path, "safe import")
    required = {"tag", "category", "post_count", "translation_cn"}
    missing = sorted(required.difference(headers))
    if missing:
        raise DeliveryError(f"safe import missing columns: {', '.join(missing)}")
    safe: dict[str, dict[str, str]] = {}
    for row in rows:
        key = _tag_key(row["tag"])
        target = targets.get(key)
        if not target:
            raise DeliveryError(f"safe import contains non-target tag: {row['tag']}")
        if int(_normal(row["category"])) != int(_normal(target["category"])):
            raise DeliveryError(f"safe category mismatch: {row['tag']}")
        value = _translation(row["translation_cn"])
        if not value:
            raise DeliveryError(f"safe translation is invalid: {row['tag']}")
        previous = safe.get(key)
        if previous and previous["translation_cn"] != value:
            raise DeliveryError(f"safe translation conflict: {row['tag']}")
        safe[key] = {**row, "translation_cn": value}
    return safe


def _load_safe_sources(path: Path) -> dict[str, str]:
    headers, rows = _read_csv(path, "safe review")
    if "tag" not in headers:
        raise DeliveryError("safe review missing tag")
    result: dict[str, str] = {}
    for row in rows:
        key = _tag_key(row["tag"])
        source = _normal(row.get("chosen_source"))
        if source:
            result[key] = source
    return result


def _load_candidates(
    specs: Iterable[tuple[str, Path]], targets: Mapping[str, Mapping[str, str]]
) -> tuple[dict[str, dict[str, str]], list[dict[str, object]]]:
    chosen: dict[str, dict[str, str]] = {}
    reports: list[dict[str, object]] = []
    for source, path in specs:
        headers, rows = _read_csv(path, f"candidate {source}")
        if "tag" not in headers:
            raise DeliveryError(f"candidate {source} missing tag")
        accepted = 0
        ignored = 0
        for row in rows:
            try:
                key = _tag_key(row.get("tag"))
            except DeliveryError:
                ignored += 1
                continue
            if key not in targets or key in chosen:
                ignored += 1
                continue
            candidate = _candidate_from_row(row)
            if not candidate:
                ignored += 1
                continue
            chosen[key] = {
                "translation": candidate,
                "source": source,
                "confidence": _confidence(row),
                "reason": _reason(row, "候选仅供审核，未进入安全写入包。"),
            }
            accepted += 1
        reports.append(
            {
                "source": source,
                "path": str(path),
                "sha256": _sha256(path),
                "rows": len(rows),
                "selected": accepted,
                "ignored": ignored,
            }
        )
    return chosen, reports


def _load_preserve(paths: Iterable[Path], targets: Mapping[str, Mapping[str, str]]) -> set[str]:
    preserved: set[str] = set()
    for path in paths:
        headers, rows = _read_csv(path, "preserve-original")
        if "tag" not in headers:
            raise DeliveryError(f"preserve-original file missing tag: {path}")
        for row in rows:
            key = _tag_key(row.get("tag"))
            if key in targets and _is_preserve(row):
                preserved.add(key)
    return preserved


def _write_csv_exclusive(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(str(path), flags, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_json_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(str(path), flags, 0o644)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def build(arguments: argparse.Namespace) -> dict[str, object]:
    target_path = Path(arguments.targets).expanduser().resolve()
    safe_path = Path(arguments.safe_import).expanduser().resolve()
    safe_review_path = Path(arguments.safe_review).expanduser().resolve()
    output_path = Path(arguments.output).expanduser().resolve()
    report_path = Path(arguments.report).expanduser().resolve()
    if output_path == report_path:
        raise DeliveryError("output and report paths must differ")
    if output_path.exists() or report_path.exists():
        raise DeliveryError("refusing to overwrite an existing delivery artifact")

    targets = _load_targets(target_path, arguments.expected_rows)
    target_map = {_tag_key(row["tag"]): row for row in targets}
    safe = _load_safe(safe_path, target_map)
    safe_sources = _load_safe_sources(safe_review_path)
    candidate_specs = [_parse_spec(value, "--candidate") for value in arguments.candidate]
    candidates, candidate_reports = _load_candidates(candidate_specs, target_map)
    preserve_paths = [Path(value).expanduser().resolve() for value in arguments.preserve]
    preserved = _load_preserve(preserve_paths, target_map)

    rows: list[dict[str, object]] = []
    status_counts: Counter[str] = Counter()
    for target in targets:
        key = _tag_key(target["tag"])
        category = int(_normal(target["category"]))
        safe_row = safe.get(key)
        candidate = candidates.get(key)
        if safe_row:
            candidate_cn = safe_row["translation_cn"]
            final_cn = candidate_cn
            status = "safe_import"
            source = safe_sources.get(key, "audited_safe_pack")
            confidence = "H"
            qa_reason = "已逐条审校或通过安全来源规则，可写入搜索联想；不覆盖已有翻译。"
        elif key in preserved:
            candidate_cn = ""
            final_cn = ""
            status = "preserve_original"
            source = "entity_name_audit"
            confidence = "H"
            qa_reason = "正式名称保留原文，不写入伪中文翻译。"
        elif candidate:
            candidate_cn = candidate["translation"]
            final_cn = ""
            status = "proper_name_review" if category in {3, 4} else "general_review"
            source = candidate["source"]
            confidence = candidate["confidence"]
            qa_reason = candidate["reason"]
        else:
            candidate_cn = ""
            final_cn = ""
            status = "proper_name_review" if category in {3, 4} else "missing_candidate"
            source = ""
            confidence = "U"
            qa_reason = (
                "作品/角色专名缺少可安全写入的明确简体中文名，等待人工复核。"
                if category in {3, 4}
                else "暂无通过格式与语义检查的中文候选。"
            )
        status_counts[status] += 1
        rows.append(
            {
                "rank": int(_normal(target["rank"])),
                "tag": _normal(target["tag"]),
                "category": category,
                "category_name": _normal(target["category_name"]),
                "post_count": int(_normal(target["post_count"])),
                "candidate_translation_cn": candidate_cn,
                "final_translation_cn": final_cn,
                "review_status": status,
                "source": source,
                "confidence": confidence,
                "qa_reason": qa_reason,
                "weilin_group": _normal(target.get("weilin_group")) or "Gallery 通用",
                "weilin_subgroup": _normal(target.get("weilin_subgroup")) or "未命中 WeiLin",
                "weilin_paths": _normal(target.get("weilin_paths_json")) or "[]",
                "classification_source": _normal(target.get("classification_source")),
            }
        )

    if len(rows) != arguments.expected_rows or len(safe) != status_counts["safe_import"]:
        raise DeliveryError("delivery row-count invariant failed")
    if any(int(row["category"]) not in ALLOWED_CATEGORIES for row in rows):
        raise DeliveryError("forbidden artist/meta category reached delivery")

    _write_csv_exclusive(output_path, rows)
    report: dict[str, object] = {
        "schema_version": 1,
        "policy": {
            "expected_rows": arguments.expected_rows,
            "artist_allowed": False,
            "meta_allowed": False,
            "non_safe_candidates_auto_imported": False,
            "safe_import_is_only_final_translation_source": True,
        },
        "inputs": {
            "targets": {"path": str(target_path), "sha256": _sha256(target_path)},
            "safe_import": {"path": str(safe_path), "sha256": _sha256(safe_path)},
            "safe_review": {"path": str(safe_review_path), "sha256": _sha256(safe_review_path)},
            "candidates": candidate_reports,
            "preserve": [
                {"path": str(path), "sha256": _sha256(path)} for path in preserve_paths
            ],
        },
        "results": {
            "review_rows": len(rows),
            "safe_import_rows": len(safe),
            "preserve_original_rows": len(preserved.difference(safe)),
            "status_counts": dict(sorted(status_counts.items())),
            "candidate_rows_selected": len(candidates),
            "output": {"path": str(output_path), "sha256": _sha256(output_path)},
        },
    }
    _write_json_exclusive(report_path, report)
    report["results"]["report"] = {"path": str(report_path), "sha256": _sha256(report_path)}
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", required=True)
    parser.add_argument("--safe-import", required=True)
    parser.add_argument("--safe-review", required=True)
    parser.add_argument("--candidate", action="append", default=[], help="NAME=PATH; repeatable, first source wins")
    parser.add_argument("--preserve", action="append", default=[], help="preserve-original CSV; repeatable")
    parser.add_argument("--output", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--expected-rows", type=int, default=4300)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        report = build(arguments)
    except (DeliveryError, OSError, csv.Error, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
