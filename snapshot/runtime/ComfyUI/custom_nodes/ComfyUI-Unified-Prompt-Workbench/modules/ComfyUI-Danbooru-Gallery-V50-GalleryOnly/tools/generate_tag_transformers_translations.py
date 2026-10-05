#!/usr/bin/env python3
"""Generate short-tag Chinese translations with a local batched Transformers model.

The command is offline and never mutates SQLite.  It checkpoints a guarded CSV
for ``import_tag_translations.py`` and a separate JSONL review queue.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

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
    parse_categories,
    validate_artifact_paths,
)


MODEL_REPO = "Qwen/Qwen3-4B-Instruct-2507"
MODEL_REVISION = "cdbee75f17c01a7cc42f958dc650907174af0554"
MODEL_LICENSE = "Apache-2.0"
SYSTEM_PROMPT = """你是 Danbooru 标签中文本地化审校员。只输出一行：简体中文短译名、一个实际制表符、H/M/L，例如“鸣潮\tH”。
H=官方/公认名称或含义确定；M=合理准确的翻译或音译；L=专名未知、参考译名可疑或存在歧义。不要把不确定结果标成 H。
general 要简短准确；copyright/character 必须优先官方或中文社区公认名，罗马音专名严禁按普通英文词义硬译；meta 译成清楚的界面含义。
输入可能带 licensed_reference，它只是有许可证的候选参考，可能正确、缺字或机器直译；正确就采用，错误就纠正，不确定就输出保守音译并标 L。
必要品牌、缩写、数字可保留，但译名至少含一个汉字。原 tag 每组括号限定都必须保留成一组中文括号并翻译，不得丢失人物名或合并身份。
不要输出解释、备选、引号、尖括号、单词 TAB 或句号。"""

_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")


def select_candidates(
    db_path: Path,
    curated: Mapping[str, str],
    max_words: int,
    max_tag_chars: int,
    limit: Optional[int],
    allowed_categories: frozenset[int] = ALLOWED_CATEGORIES,
) -> Tuple[List[Dict[str, object]], Counter]:
    counts = Counter()
    connection = sqlite3.connect(str(db_path))
    connection.row_factory = sqlite3.Row
    try:
        selected: List[Dict[str, object]] = []
        for row in connection.execute(
            """
            SELECT tag, category, post_count
            FROM hot_tags
            WHERE NULLIF(TRIM(translation_cn), '') IS NULL
            ORDER BY post_count DESC, tag ASC
            """
        ):
            tag = str(row["tag"])
            category = int(row["category"])
            counts["database_missing"] += 1
            if category not in allowed_categories:
                counts["skipped_disallowed_category"] += 1
                continue
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


def parse_model_output(tag: str, raw: object, max_chars: int = 64) -> Tuple[Optional[str], Optional[str], str]:
    if not isinstance(raw, str):
        return None, None, "not_string"
    raw = raw.strip()
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) != 1:
        return None, None, "line_count"
    match = re.fullmatch(
        r"(.+?)(?:\t|\s*[|｜]\s*|\s*<TAB>\s*)(?:<?([HMLhml])>?)",
        lines[0],
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None, "format"
    value = unicodedata.normalize("NFKC", match.group(1)).strip().strip('"“”《》')
    value = _SPACE_RE.sub(" ", value)
    confidence = match.group(2).upper()
    if not value:
        return None, confidence, "empty"
    if len(value) > max_chars:
        return None, confidence, "translation_length"
    if _CONTROL_RE.search(value):
        return None, confidence, "control_character"
    if not _HAN_RE.search(value):
        return None, confidence, "no_han"
    if _KANA_RE.search(value):
        return None, confidence, "contains_kana"
    if _HANGUL_RE.search(value):
        return None, confidence, "contains_hangul"
    if re.search(r"(?:<|>|\bTAB\b)", value, flags=re.IGNORECASE):
        return None, confidence, "format_marker"
    normalized_tag = unicodedata.normalize("NFKC", tag)
    if (
        normalized_tag.count("(") != value.count("(")
        or normalized_tag.count(")") != value.count(")")
        or value.count("(") != value.count(")")
    ):
        return None, confidence, "qualifier_lost"
    if re.search(r"(?:解释|译名|翻译)[:：]", value):
        return None, confidence, "explanatory_text"
    return value, confidence, "accepted"


def load_references(path: Optional[Path]) -> Dict[str, str]:
    if path is None:
        return {}
    if not path.is_file():
        raise ValueError("reference CSV not found: {}".format(path))
    output: Dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"tag", "translation_cn"}
        if not required.issubset(reader.fieldnames or ()):
            raise ValueError("reference CSV must contain tag and translation_cn columns")
        for row in reader:
            tag = normalize_tag(row.get("tag"))
            translation = str(row.get("translation_cn") or "").strip()
            if tag and translation and tag not in output:
                output[tag] = translation
    return output


def load_existing(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return {
            str(row.get("tag") or "").strip()
            for row in csv.DictReader(handle)
            if str(row.get("tag") or "").strip()
        }


def append_csv(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("tag", "category", "post_count", "translation_cn", "confidence"),
        )
        if header:
            writer.writeheader()
        writer.writerows(rows)
        handle.flush()


def append_jsonl(path: Path, row: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        handle.flush()


def make_prompts(tokenizer, rows: Sequence[Mapping[str, object]]) -> List[str]:
    prompts = []
    for row in rows:
        reference = str(row.get("reference_translation") or "").strip()
        user = "category={}\ntag={}\nlicensed_reference={}".format(
            CATEGORY_NAMES[int(row["category"])],
            row["tag"],
            reference if reference else "(none)",
        )
        prompts.append(
            tokenizer.apply_chat_template(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
        )
    return prompts


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review-queue", type=Path, required=True)
    parser.add_argument("--reference-csv", type=Path)
    parser.add_argument("--model-repo", default=MODEL_REPO)
    parser.add_argument("--model-revision", default=MODEL_REVISION)
    parser.add_argument("--model-license", default=MODEL_LICENSE)
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--max-new-tokens", type=int, default=40)
    parser.add_argument("--max-words", type=int, default=6)
    parser.add_argument("--max-tag-chars", type=int, default=64)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--accept-confidence", default="HM")
    parser.add_argument(
        "--categories",
        default="0,3,4,5",
        help="comma-separated category allow-list; artist/category 1 is always rejected",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        artifact_paths = validate_artifact_paths(
            {
                "output": args.output,
                "report": args.report,
                "review_queue": args.review_queue,
            },
            {
                "database": args.db,
                "reference_csv": args.reference_csv,
            },
            protected_roots={
                "model": args.model,
                "bundled_translation_sources": DEFAULT_ZH_DIR,
            },
        )
    except ArtifactPathError as exc:
        raise SystemExit(str(exc)) from exc
    args.output = artifact_paths["output"]
    args.report = artifact_paths["report"]
    args.review_queue = artifact_paths["review_queue"]
    if not args.db.is_file() or not args.model.is_dir():
        raise SystemExit("database or model snapshot not found")
    try:
        allowed_categories = parse_categories(args.categories)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if not 1 <= args.batch_size <= 256:
        raise SystemExit("--batch-size must be between 1 and 256")
    accepted_confidence = set(args.accept_confidence.upper()) & {"H", "M", "L"}
    if not accepted_confidence:
        raise SystemExit("--accept-confidence must contain H, M, or L")

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    curated = load_curated_translations()
    references = load_references(args.reference_csv)
    candidates, selection = select_candidates(
        args.db,
        curated,
        args.max_words,
        args.max_tag_chars,
        args.limit,
        allowed_categories,
    )
    existing = load_existing(args.output)
    pending = [row for row in candidates if str(row["tag"]) not in existing]
    for row in pending:
        row["reference_translation"] = references.get(normalize_tag(row["tag"]), "")
    tokenizer = AutoTokenizer.from_pretrained(str(args.model), local_files_only=True)
    tokenizer.padding_side = "left"
    if tokenizer.pad_token_id is None:
        tokenizer.pad_token_id = tokenizer.eos_token_id

    started = time.perf_counter()
    model = AutoModelForCausalLM.from_pretrained(
        str(args.model),
        local_files_only=True,
        dtype="auto",
        device_map="cuda",
        attn_implementation="sdpa",
        low_cpu_mem_usage=True,
    )
    model.eval()
    accepted = Counter()
    rejected = Counter()
    processed = 0

    with torch.inference_mode():
        for offset in range(0, len(pending), args.batch_size):
            rows = pending[offset : offset + args.batch_size]
            prompts = make_prompts(tokenizer, rows)
            inputs = tokenizer(
                prompts,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            ).to("cuda")
            generated = model.generate(
                **inputs,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                use_cache=True,
                pad_token_id=tokenizer.pad_token_id,
                eos_token_id=tokenizer.eos_token_id,
            )
            new_tokens = generated[:, inputs.input_ids.shape[1] :]
            outputs = tokenizer.batch_decode(new_tokens, skip_special_tokens=True)
            output_rows = []
            for row, raw in zip(rows, outputs):
                translation, confidence, reason = parse_model_output(str(row["tag"]), raw)
                if translation is None or confidence not in accepted_confidence:
                    key = reason if translation is None else "low_confidence"
                    rejected[key] += 1
                    append_jsonl(
                        args.review_queue,
                        {
                            "tag": row["tag"],
                            "category": row["category"],
                            "post_count": row["post_count"],
                            "raw": raw,
                            "translation_cn": translation,
                            "confidence": confidence,
                            "reason": key,
                        },
                    )
                    continue
                accepted[confidence] += 1
                output_rows.append(
                    {
                        "tag": row["tag"],
                        "category": row["category"],
                        "post_count": row["post_count"],
                        "translation_cn": translation,
                        "confidence": confidence,
                    }
                )
            append_csv(args.output, output_rows)
            processed += len(rows)
            elapsed = time.perf_counter() - started
            print(
                json.dumps(
                    {
                        "processed": processed,
                        "pending_at_start": len(pending),
                        "accepted": sum(accepted.values()),
                        "rejected": sum(rejected.values()),
                        "tags_per_second": round(processed / elapsed, 2),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    elapsed = time.perf_counter() - started
    output_tags = load_existing(args.output)
    report = {
        "source": {
            "repo": args.model_repo,
            "revision": args.model_revision,
            "license": args.model_license,
            "snapshot": str(args.model.resolve()),
            "reference_csv": str(args.reference_csv.resolve()) if args.reference_csv else None,
            "reference_sha256": file_sha256(args.reference_csv) if args.reference_csv else None,
            "reference_rows": len(references),
        },
        "input": {
            "database": str(args.db.resolve()),
            "database_sha256": file_sha256(args.db),
            "artist_allowed": False,
            "allowed_categories": sorted(allowed_categories),
            "max_words": args.max_words,
            "max_tag_chars": args.max_tag_chars,
        },
        "selection": dict(selection),
        "run": {
            "batch_size": args.batch_size,
            "max_new_tokens": args.max_new_tokens,
            "accept_confidence": sorted(accepted_confidence),
            "elapsed_seconds": round(elapsed, 3),
            "processed": processed,
            "accepted": dict(sorted(accepted.items())),
            "rejected": dict(sorted(rejected.items())),
        },
        "output": {
            "csv": str(args.output.resolve()),
            "rows": len(output_tags),
            "sha256": file_sha256(args.output),
        },
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
