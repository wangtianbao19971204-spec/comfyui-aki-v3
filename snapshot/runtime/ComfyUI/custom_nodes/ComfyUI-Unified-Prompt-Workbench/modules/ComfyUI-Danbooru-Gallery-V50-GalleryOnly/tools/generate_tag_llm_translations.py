#!/usr/bin/env python3
"""Generate a checkpointed, reviewable tag-translation pack with a local GGUF LLM.

The script never writes the SQLite database.  It selects only untranslated,
short, non-artist tags and writes a CSV for the guarded importer.  Results are
checkpointed after every batch so an interrupted generation can resume safely.
"""

from __future__ import annotations

import argparse
import csv
import ctypes
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from generate_tag_machine_translations import (
    ALLOWED_CATEGORIES,
    ArtifactPathError,
    CATEGORY_NAMES,
    DEFAULT_DB_PATH,
    DEFAULT_ZH_DIR,
    candidate_rejection_reason,
    file_sha256,
    load_curated_translations,
    normalize_tag,
    validate_artifact_paths,
)


_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")

SYSTEM_PROMPT = """你是 Danbooru 标签中文本地化审校员。输入是 JSON 数组，每项含 id、tag、category、licensed_reference。
只输出一个 JSON 对象：键必须是输入 id；每个值必须严格是“H/M/L|简体中文短译名”，例如 {"0":"H|鸣潮"}。不得解释、遗漏、增加键或改写 tag。
规则：
1. artist 永不处理（输入不会包含 artist）。general 用准确简短的常用中文，不做逐字硬译。
2. copyright 和 character 必须优先采用作品/角色在中文社区的官方或公认名称；未知专名可以音译或保留必要缩写，但严禁把罗马音按普通英语词义直译，也严禁猜成另一个作品或角色。
3. meta 译成清楚的界面/审核含义。必要的品牌名、缩写和数字可以保留。
4. licensed_reference 是有许可证的候选参考，但可能为空、缺名或机器直译；正确就采用，错误就纠正，不确定就保守音译并标 L。
5. tag 括号内是作品、版本、服装或形态限定：每一组括号都必须保留并翻译，绝不能删除限定、人物名或合并不同 tag。
6. H=官方/公认名称或含义确定；M=合理准确的翻译/音译；L=专名未知、参考可疑或存在歧义。不要把不确定结果标为 H。
7. translation_cn 必须是单个短译名且至少含一个汉字；不要注释、备选、句号、尖括号或单词 TAB。"""


def select_candidates(
    db_path: Path,
    curated: Mapping[str, str],
    max_words: int,
    max_tag_chars: int,
    limit: Optional[int],
    candidate_tags: Optional[Sequence[str]] = None,
) -> Tuple[List[Dict[str, object]], Counter]:
    counts = Counter()
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            SELECT tag, category, post_count
            FROM hot_tags
            WHERE NULLIF(TRIM(translation_cn), '') IS NULL
            ORDER BY post_count DESC, tag ASC
            """
        )
        selected: List[Dict[str, object]] = []

        if candidate_tags is None:
            ordered_rows: Iterable[sqlite3.Row] = rows
        else:
            missing_by_tag: Dict[str, sqlite3.Row] = {}
            for row in rows:
                counts["database_missing"] += 1
                missing_by_tag[str(row["tag"])] = row

            ordered_candidate_rows: List[sqlite3.Row] = []
            seen_candidate_tags = set()
            for raw_tag in candidate_tags:
                tag = str(raw_tag or "").strip()
                if not tag:
                    counts["skipped_candidate_empty"] += 1
                    continue
                if tag in seen_candidate_tags:
                    counts["skipped_candidate_duplicate"] += 1
                    continue
                seen_candidate_tags.add(tag)
                counts["candidate_requested"] += 1
                row = missing_by_tag.get(tag)
                if row is None:
                    counts["skipped_candidate_not_missing_or_absent"] += 1
                    continue
                ordered_candidate_rows.append(row)
            ordered_rows = ordered_candidate_rows

        for row in ordered_rows:
            tag = str(row["tag"])
            category = int(row["category"])
            if candidate_tags is None:
                counts["database_missing"] += 1
            reason = candidate_rejection_reason(tag, category, max_words, max_tag_chars)
            if reason:
                counts["skipped_" + reason] += 1
                continue
            if normalize_tag(tag) in curated:
                counts["skipped_curated_fallback"] += 1
                continue
            selected.append(
                {
                    "tag": tag,
                    "category": category,
                    "post_count": int(row["post_count"]),
                }
            )
            if limit is not None and len(selected) >= limit:
                break
        counts["selected"] = len(selected)
        return selected, counts
    finally:
        connection.close()


def load_candidate_tags(path: Path) -> Tuple[List[str], Counter]:
    """Load an exact, ordered candidate whitelist from a CSV file."""

    if not path.is_file():
        raise ValueError("candidate CSV not found: {}".format(path))
    tags: List[str] = []
    counts = Counter()
    seen = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if "tag" not in (reader.fieldnames or ()):
            raise ValueError("candidate CSV must contain a tag column")
        for row in reader:
            counts["input_rows"] += 1
            tag = str(row.get("tag") or "").strip()
            if not tag:
                counts["empty_tags"] += 1
                continue
            if tag in seen:
                counts["duplicate_tags"] += 1
                continue
            seen.add(tag)
            tags.append(tag)
    counts["unique_tags"] = len(tags)
    return tags, counts


def candidate_csv_provenance(path: Path, counts: Mapping[str, int]) -> Dict[str, object]:
    """Return the candidate-input fields embedded in the final audit report."""

    return {
        "candidate_csv": str(path.resolve()),
        "candidate_csv_sha256": file_sha256(path),
        "candidate_csv_input_rows": int(counts.get("input_rows", 0)),
        "candidate_csv_unique_tags": int(counts.get("unique_tags", 0)),
        "candidate_csv_duplicate_tags": int(counts.get("duplicate_tags", 0)),
        "candidate_csv_empty_tags": int(counts.get("empty_tags", 0)),
    }


def validate_translation(tag: str, value: object, max_chars: int = 64) -> Tuple[Optional[str], str]:
    if not isinstance(value, str):
        return None, "not_string"
    value = unicodedata.normalize("NFKC", value).strip().strip('"“”')
    value = _SPACE_RE.sub(" ", value)
    if not value:
        return None, "empty"
    if len(value) > max_chars:
        return None, "translation_length"
    if _CONTROL_RE.search(value):
        return None, "control_character"
    if not _HAN_RE.search(value):
        return None, "no_han"
    if _KANA_RE.search(value):
        return None, "contains_kana"
    if _HANGUL_RE.search(value):
        return None, "contains_hangul"
    normalized_tag = unicodedata.normalize("NFKC", tag)
    if (
        normalized_tag.count("(") != value.count("(")
        or normalized_tag.count(")") != value.count(")")
        or value.count("(") != value.count(")")
    ):
        return None, "qualifier_lost"
    if re.search(r"(?:<|>|\bTAB\b)", value, flags=re.IGNORECASE):
        return None, "format_marker"
    if re.search(r"(?:解释|译名|翻译)[:：]", value):
        return None, "explanatory_text"
    return value, "accepted"


def parse_translation_decision(
    tag: str, value: object, max_chars: int = 64
) -> Tuple[Optional[str], Optional[str], str]:
    if isinstance(value, Mapping):
        if set(value) != {"translation_cn", "confidence"}:
            return None, None, "decision_keys"
        raw_translation = value.get("translation_cn")
        confidence = str(value.get("confidence") or "").strip().upper()
    elif isinstance(value, str):
        raw_value = value.strip()
        prefix_match = re.fullmatch(
            r"<?([HMLhml])>?\s*[|｜:：]\s*(.+)", raw_value
        )
        suffix_match = re.fullmatch(
            r"(.+?)(?:\t|\s*[|｜]\s*|\s*<TAB>\s*)(?:<?([HMLhml])>?)",
            raw_value,
            flags=re.IGNORECASE,
        )
        if prefix_match:
            confidence = prefix_match.group(1).upper()
            raw_translation = prefix_match.group(2)
        elif suffix_match:
            raw_translation = suffix_match.group(1)
            confidence = suffix_match.group(2).upper()
        else:
            return None, None, "decision_format"
    else:
        return None, None, "decision_type"
    if confidence not in {"H", "M", "L"}:
        return None, None, "confidence"
    translation, reason = validate_translation(
        tag, raw_translation, max_chars=max_chars
    )
    return translation, confidence, reason


def load_references(path: Optional[Path]) -> Dict[str, str]:
    if path is None:
        return {}
    if not path.is_file():
        raise ValueError("reference CSV not found: {}".format(path))
    output: Dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"tag", "translation_cn"}.issubset(reader.fieldnames or ()):
            raise ValueError("reference CSV must contain tag and translation_cn columns")
        for row in reader:
            tag = normalize_tag(row.get("tag"))
            translation = str(row.get("translation_cn") or "").strip()
            if tag and translation and tag not in output:
                output[tag] = translation
    return output


def load_existing_output(path: Path) -> Tuple[set[str], int]:
    if not path.exists() or path.stat().st_size == 0:
        return set(), 0
    tags = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            tag = str(row.get("tag") or "").strip()
            if tag:
                tags.add(tag)
    return tags, len(tags)


def preload_windows_dlls(runtime: Path) -> List[object]:
    if sys.platform != "win32":
        return []
    torch_lib = Path(sys.executable).parent / "Lib" / "site-packages" / "torch" / "lib"
    llama_lib = runtime / "llama_cpp" / "lib"
    os.add_dll_directory(str(torch_lib))
    os.add_dll_directory(str(llama_lib))
    handles: List[object] = []
    for name in ("ggml-base.dll", "ggml-cpu.dll", "ggml-cuda.dll", "ggml.dll", "llama.dll"):
        path = llama_lib / name
        if path.exists():
            handles.append(ctypes.WinDLL(str(path)))
    return handles


def append_rows(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("tag", "category", "post_count", "translation_cn", "confidence"),
        )
        if needs_header:
            writer.writeheader()
        writer.writerows(rows)
        handle.flush()


def append_jsonl(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def request_batch(llm, rows: Sequence[Mapping[str, object]], max_tokens: int) -> Dict[str, object]:
    payload = [
        {
            "id": str(index),
            "tag": row["tag"],
            "category": CATEGORY_NAMES[int(row["category"])],
            "licensed_reference": row.get("reference_translation") or "",
        }
        for index, row in enumerate(rows)
    ]
    response = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        top_p=0.9,
        seed=42,
        max_tokens=max_tokens,
    )
    content = response["choices"][0]["message"]["content"]
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("model response is not a JSON object")
    expected = {str(index) for index in range(len(rows))}
    if set(parsed) != expected:
        missing = sorted(expected - set(parsed))[:10]
        extra = sorted(set(parsed) - expected)[:10]
        raise ValueError("response key mismatch: missing={} extra={}".format(missing, extra))
    return parsed


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--llama-runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--errors", type=Path, required=True)
    parser.add_argument("--reference-csv", type=Path)
    parser.add_argument(
        "--candidate-csv",
        type=Path,
        help="CSV with a tag column; restrict generation to its exact tag order",
    )
    parser.add_argument("--model-repo", default="Qwen/Qwen3-14B-GGUF")
    parser.add_argument("--model-revision", default="530227a7d994db8eca5ab5ced2fb692b614357fd")
    parser.add_argument("--model-license", default="Apache-2.0")
    parser.add_argument("--accept-confidence", default="HM")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--n-ctx", type=int, default=8192)
    parser.add_argument("--max-tokens", type=int, default=3072)
    parser.add_argument("--max-words", type=int, default=6)
    parser.add_argument("--max-tag-chars", type=int, default=64)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--cpu", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        artifact_paths = validate_artifact_paths(
            {
                "output": args.output,
                "report": args.report,
                "errors": args.errors,
            },
            {
                "database": args.db,
                "model": args.model,
                "reference_csv": args.reference_csv,
                "candidate_csv": args.candidate_csv,
            },
            protected_roots={
                "llama_runtime": args.llama_runtime,
                "bundled_translation_sources": DEFAULT_ZH_DIR,
            },
        )
    except ArtifactPathError as exc:
        raise SystemExit(str(exc)) from exc
    args.output = artifact_paths["output"]
    args.report = artifact_paths["report"]
    args.errors = artifact_paths["errors"]
    if not args.db.is_file() or not args.model.is_file():
        raise SystemExit("database or model file not found")
    if not args.llama_runtime.is_dir():
        raise SystemExit("isolated llama runtime not found")
    if not 1 <= args.batch_size <= 256:
        raise SystemExit("--batch-size must be between 1 and 256")
    accepted_confidence = set(args.accept_confidence.upper()) & {"H", "M", "L"}
    if not accepted_confidence:
        raise SystemExit("--accept-confidence must contain H, M, or L")

    curated = load_curated_translations()
    references = load_references(args.reference_csv)
    candidate_tags: Optional[List[str]] = None
    candidate_csv_counts = Counter()
    if args.candidate_csv is not None:
        candidate_tags, candidate_csv_counts = load_candidate_tags(args.candidate_csv)
    candidates, selection = select_candidates(
        args.db,
        curated,
        args.max_words,
        args.max_tag_chars,
        args.limit,
        candidate_tags=candidate_tags,
    )
    existing_tags, resumed_rows = load_existing_output(args.output)
    pending = [row for row in candidates if str(row["tag"]) not in existing_tags]
    for row in pending:
        row["reference_translation"] = references.get(normalize_tag(row["tag"]), "")

    sys.path.insert(0, str(args.llama_runtime.resolve()))
    dll_handles = preload_windows_dlls(args.llama_runtime.resolve())
    from llama_cpp import Llama

    started = time.perf_counter()
    llm = Llama(
        model_path=str(args.model),
        n_ctx=args.n_ctx,
        n_gpu_layers=0 if args.cpu else -1,
        n_batch=1024,
        verbose=False,
    )
    accepted = Counter()
    rejected = Counter()
    generated_this_run = 0
    queue: List[Sequence[Dict[str, object]]] = [
        pending[index : index + args.batch_size]
        for index in range(0, len(pending), args.batch_size)
    ]
    total_pending = len(pending)

    try:
        while queue:
            group = queue.pop(0)
            try:
                values = request_batch(llm, group, args.max_tokens)
            except Exception as exc:
                if len(group) > 1:
                    midpoint = len(group) // 2
                    queue[0:0] = [group[:midpoint], group[midpoint:]]
                    append_jsonl(
                        args.errors,
                        {"type": "batch_split", "size": len(group), "error": str(exc)},
                    )
                    continue
                rejected["model_error"] += 1
                append_jsonl(args.errors, {"type": "model_error", **group[0], "error": str(exc)})
                continue

            output_rows: List[Dict[str, object]] = []
            for index, row in enumerate(group):
                translation, confidence, reason = parse_translation_decision(
                    str(row["tag"]), values[str(index)]
                )
                if translation is None or confidence not in accepted_confidence:
                    rejection_reason = reason if translation is None else "low_confidence"
                    rejected[rejection_reason] += 1
                    append_jsonl(
                        args.errors,
                        {
                            "type": "rejected",
                            **row,
                            "value": values[str(index)],
                            "translation_cn": translation,
                            "confidence": confidence,
                            "reason": rejection_reason,
                        },
                    )
                    continue
                accepted["{}_{}".format(CATEGORY_NAMES[int(row["category"])], confidence)] += 1
                output_rows.append(
                    {
                        "tag": row["tag"],
                        "category": row["category"],
                        "post_count": row["post_count"],
                        "translation_cn": translation,
                        "confidence": confidence,
                    }
                )
            append_rows(args.output, output_rows)
            generated_this_run += len(group)
            elapsed = time.perf_counter() - started
            rate = generated_this_run / elapsed if elapsed else 0.0
            print(
                json.dumps(
                    {
                        "processed": generated_this_run,
                        "pending_at_start": total_pending,
                        "accepted": sum(accepted.values()),
                        "rejected": sum(rejected.values()),
                        "tags_per_second": round(rate, 2),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
    finally:
        llm.close()
        del dll_handles

    elapsed = time.perf_counter() - started
    model_hash = file_sha256(args.model)
    output_tags, output_rows = load_existing_output(args.output)
    source_report = {
        "model_file": str(args.model.resolve()),
        "model_sha256": model_hash,
        "model_repo": args.model_repo,
        "model_revision": args.model_revision,
        "model_license_from_gguf": args.model_license,
        "generator": "local deterministic LLM pass",
        "reference_csv": str(args.reference_csv.resolve()) if args.reference_csv else None,
        "reference_sha256": file_sha256(args.reference_csv) if args.reference_csv else None,
        "reference_rows": len(references),
    }
    if args.candidate_csv is not None:
        source_report.update(candidate_csv_provenance(args.candidate_csv, candidate_csv_counts))
    report = {
        "source": source_report,
        "input": {
            "database": str(args.db.resolve()),
            "database_sha256": file_sha256(args.db),
            "artist_allowed": False,
            "max_words": args.max_words,
            "max_tag_chars": args.max_tag_chars,
        },
        "selection": dict(selection),
        "resume": {"rows_before_run": resumed_rows},
        "run": {
            "cpu": bool(args.cpu),
            "batch_size": args.batch_size,
            "n_ctx": args.n_ctx,
            "accept_confidence": sorted(accepted_confidence),
            "elapsed_seconds": round(elapsed, 3),
            "processed_this_run": generated_this_run,
            "accepted_this_run_by_category": dict(sorted(accepted.items())),
            "rejected_this_run": dict(sorted(rejected.items())),
        },
        "output": {
            "csv": str(args.output.resolve()),
            "rows": output_rows,
            "unique_tags": len(output_tags),
            "sha256": file_sha256(args.output),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
