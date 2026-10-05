#!/usr/bin/env python3
"""Generate a reviewable Chinese translation CSV from a local model.

This command is deliberately read-only with respect to ``tags_cache.db``.  It
selects only short, untranslated, non-artist tags, keeps the bundled curated
translations ahead of the model, validates every generated value, and writes a
CSV that must still pass ``import_tag_translations.py`` before it can be used.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sqlite3
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db"
DEFAULT_ZH_DIR = PLUGIN_ROOT / "py" / "danbooru_gallery" / "zh_cn"
ALLOWED_CATEGORIES = frozenset({0, 3, 4, 5})
CATEGORY_NAMES = {0: "general", 1: "artist", 2: "unknown", 3: "copyright", 4: "character", 5: "meta"}
MODEL_REVISION = "408d9bc410a388e1d9aef112a2daba955b945255"
MODEL_URL = "https://huggingface.co/Helsinki-NLP/opus-mt-en-zh"

_WORD_RE = re.compile(r"[A-Za-z0-9]+(?:['’][A-Za-z0-9]+)?")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
_KANA_RE = re.compile(r"[\u3040-\u30ff\u31f0-\u31ff\uff66-\uff9f]")
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_LATIN_RESIDUE_RE = re.compile(r"[A-Za-z]{2,}")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SPACE_RE = re.compile(r"\s+")


class ArtifactPathError(ValueError):
    """Raised before an output path can overwrite an input or model asset."""


def _same_existing_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (FileNotFoundError, OSError, ValueError):
        return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_artifact_paths(
    artifacts: Mapping[str, Path],
    protected_paths: Mapping[str, Optional[Path]],
    *,
    protected_roots: Mapping[str, Optional[Path]] | None = None,
) -> Dict[str, Path]:
    """Resolve and separate generated artifacts from every declared input.

    Existing output/checkpoint files remain valid for the generators' resume
    workflows.  They may not, however, be the same file (including a hard-link
    alias) as another artifact or an input, nor may they live inside a model or
    bundled-source directory that the generator consumes.
    """

    resolved_artifacts = {
        name: Path(path).expanduser().resolve()
        for name, path in artifacts.items()
    }
    resolved_inputs = {
        name: Path(path).expanduser().resolve()
        for name, path in protected_paths.items()
        if path is not None
    }
    resolved_roots = {
        name: Path(path).expanduser().resolve()
        for name, path in (protected_roots or {}).items()
        if path is not None
    }

    artifact_items = list(resolved_artifacts.items())
    for index, (left_name, left_path) in enumerate(artifact_items):
        for right_name, right_path in artifact_items[index + 1:]:
            if left_path == right_path or _same_existing_file(left_path, right_path):
                raise ArtifactPathError(
                    "artifact paths {} and {} must be distinct files".format(
                        left_name, right_name
                    )
                )

        for input_name, input_path in resolved_inputs.items():
            if left_path == input_path or _same_existing_file(left_path, input_path):
                raise ArtifactPathError(
                    "artifact {} must not overwrite input {}".format(
                        left_name, input_name
                    )
                )

        for root_name, root_path in resolved_roots.items():
            if _is_relative_to(left_path, root_path):
                raise ArtifactPathError(
                    "artifact {} must not be written inside protected directory {}".format(
                        left_name, root_name
                    )
                )

    return resolved_artifacts


def normalize_tag(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return _SPACE_RE.sub("_", value)


def load_curated_translations(zh_dir: Path = DEFAULT_ZH_DIR) -> Dict[str, str]:
    """Load bundled files in their documented priority order."""

    mapping: Dict[str, str] = {}
    json_path = zh_dir / "all_tags_cn.json"
    if json_path.exists():
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        for tag, translation in payload.items():
            tag_key = normalize_tag(tag)
            value = str(translation or "").strip()
            if tag_key and value:
                mapping[tag_key] = value

    for filename, reverse in (("danbooru.csv", False), ("wai_characters.csv", True)):
        path = zh_dir / filename
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for row in csv.reader(handle):
                if len(row) < 2:
                    continue
                tag, translation = (row[1], row[0]) if reverse else (row[0], row[1])
                tag_key = normalize_tag(tag)
                value = str(translation or "").strip()
                if tag_key and value:
                    mapping.setdefault(tag_key, value)
    return mapping


def candidate_rejection_reason(tag: str, category: int, max_words: int, max_chars: int) -> Optional[str]:
    if category not in ALLOWED_CATEGORIES:
        return "disallowed_category"
    if not tag or len(tag) > max_chars:
        return "tag_length"
    if _CONTROL_RE.search(tag):
        return "control_character"
    words = _WORD_RE.findall(tag)
    if not words or len(words) > max_words:
        return "word_count"
    if tag.count("(") != tag.count(")"):
        return "unbalanced_parentheses"
    if re.search(r"https?://|www\.|(?:^|[_-])(?:url|uri)(?:$|[_-])", tag, re.I):
        return "url_like"
    return None


def source_phrase(tag: str) -> str:
    """Turn a canonical tag into a compact phrase without losing qualifiers."""

    phrase = tag.replace("_", " ")
    phrase = re.sub(r"\s+", " ", phrase).strip()
    return phrase


def validate_translation(tag: str, category: int, value: str, max_chars: int = 64) -> Tuple[Optional[str], str]:
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
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
    if _LATIN_RESIDUE_RE.search(value):
        return None, "latin_residue"
    if tag.count("(") != value.count("(") + value.count("（"):
        return None, "qualifier_lost"
    if value.casefold() == source_phrase(tag).casefold():
        return None, "unchanged"
    # Very long repeated fragments are a common failure mode on short inputs.
    compact = re.sub(r"[\s，,、;；]+", "", value)
    for size in range(2, min(9, len(compact) // 2 + 1)):
        fragment = compact[:size]
        if compact.count(fragment) >= 4:
            return None, "repetition"
    return value, "accepted"


def select_candidates(
    db_path: Path,
    curated: Mapping[str, str],
    max_words: int,
    max_tag_chars: int,
    limit: Optional[int] = None,
    allowed_categories: frozenset[int] = ALLOWED_CATEGORIES,
) -> Tuple[List[Dict[str, object]], Counter]:
    report = Counter()
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
        candidates: List[Dict[str, object]] = []
        for row in rows:
            tag = str(row["tag"])
            category = int(row["category"])
            report["database_missing"] += 1
            if category not in allowed_categories:
                report["skipped_disallowed_category"] += 1
                continue
            reason = candidate_rejection_reason(tag, category, max_words, max_tag_chars)
            if reason:
                report["skipped_" + reason] += 1
                continue
            if normalize_tag(tag) in curated:
                report["skipped_curated_fallback"] += 1
                continue
            candidates.append(
                {
                    "tag": tag,
                    "category": category,
                    "post_count": int(row["post_count"]),
                    "source_text": source_phrase(tag),
                }
            )
            if limit is not None and len(candidates) >= limit:
                break
        report["selected"] = len(candidates)
        return candidates, report
    finally:
        connection.close()


def batches(values: Sequence[Dict[str, object]], size: int) -> Iterable[Sequence[Dict[str, object]]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def generate(
    candidates: Sequence[Dict[str, object]],
    model_path: Path,
    device: str,
    batch_size: int,
    target_prefix: str = ">>zho_Hans<< ",
) -> Tuple[List[Dict[str, object]], Counter, List[Dict[str, object]]]:
    import torch
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True)
    model_kwargs = {"local_files_only": True}
    if device == "cuda":
        model_kwargs["dtype"] = torch.float16
    model = AutoModelForSeq2SeqLM.from_pretrained(str(model_path), **model_kwargs).to(device)
    model.eval()
    accepted: List[Dict[str, object]] = []
    rejected = Counter()
    rejection_examples: List[Dict[str, object]] = []

    with torch.inference_mode():
        for batch_number, group in enumerate(batches(candidates, batch_size), start=1):
            inputs = tokenizer(
                [target_prefix + str(item["source_text"]) for item in group],
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=128,
            ).to(device)
            generated = model.generate(
                **inputs,
                max_new_tokens=32,
                num_beams=4,
                no_repeat_ngram_size=2,
                repetition_penalty=1.2,
            )
            outputs = tokenizer.batch_decode(generated, skip_special_tokens=True)
            for item, raw_value in zip(group, outputs):
                value, reason = validate_translation(
                    str(item["tag"]), int(item["category"]), raw_value
                )
                if value is None:
                    rejected[reason] += 1
                    if len(rejection_examples) < 100:
                        rejection_examples.append(
                            {**item, "raw_translation": raw_value, "reason": reason}
                        )
                    continue
                accepted.append({**item, "translation_cn": value})
            if device == "cuda" and batch_number % 50 == 0:
                torch.cuda.empty_cache()
    return accepted, rejected, rejection_examples


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--max-words", type=int, default=6)
    parser.add_argument("--max-tag-chars", type=int, default=64)
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--categories",
        default="0,3,4,5",
        help="comma-separated category allow-list; artist/category 1 is always rejected",
    )
    parser.add_argument("--target-prefix", default=">>zho_Hans<< ")
    parser.add_argument("--model-url", default=MODEL_URL)
    parser.add_argument("--model-revision", default=MODEL_REVISION)
    parser.add_argument("--model-license", default="Apache-2.0")
    return parser.parse_args(argv)


def parse_categories(value: str) -> frozenset[int]:
    try:
        categories = frozenset(int(part.strip()) for part in value.split(",") if part.strip())
    except ValueError as exc:
        raise ValueError("--categories must contain comma-separated integers") from exc
    if not categories:
        raise ValueError("--categories must not be empty")
    if not categories.issubset(ALLOWED_CATEGORIES):
        raise ValueError("--categories may only contain 0, 3, 4, or 5; artist is forbidden")
    return categories


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        artifact_paths = validate_artifact_paths(
            {"output": args.output, "report": args.report},
            {"database": args.db},
            protected_roots={
                "model": args.model,
                "bundled_translation_sources": DEFAULT_ZH_DIR,
            },
        )
    except ArtifactPathError as exc:
        raise SystemExit(str(exc)) from exc
    args.output = artifact_paths["output"]
    args.report = artifact_paths["report"]
    if args.batch_size < 1 or args.batch_size > 512:
        raise SystemExit("--batch-size must be between 1 and 512")
    if not args.db.is_file():
        raise SystemExit("database not found: {}".format(args.db))
    if not args.model.is_dir():
        raise SystemExit("model snapshot not found: {}".format(args.model))
    try:
        allowed_categories = parse_categories(args.categories)
    except ValueError as exc:
        raise SystemExit(str(exc))
    if not args.target_prefix or len(args.target_prefix) > 64:
        raise SystemExit("--target-prefix must contain 1 to 64 characters")

    curated = load_curated_translations()
    candidates, selection = select_candidates(
        args.db,
        curated,
        args.max_words,
        args.max_tag_chars,
        args.limit,
        allowed_categories,
    )
    started = time.perf_counter()
    accepted, rejected, rejection_examples = generate(
        candidates, args.model, args.device, args.batch_size, args.target_prefix
    )
    elapsed = time.perf_counter() - started

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("tag", "category", "post_count", "translation_cn"),
        )
        writer.writeheader()
        for row in accepted:
            writer.writerow(
                {
                    "tag": row["tag"],
                    "category": row["category"],
                    "post_count": row["post_count"],
                    "translation_cn": row["translation_cn"],
                }
            )

    category_counts = Counter(CATEGORY_NAMES[int(row["category"])] for row in accepted)
    report = {
        "source": {
            "model_url": args.model_url,
            "model_revision": args.model_revision,
            "declared_license": args.model_license,
            "model_snapshot": str(args.model.resolve()),
            "target_prefix": args.target_prefix,
        },
        "input": {
            "database": str(args.db.resolve()),
            "database_sha256": file_sha256(args.db),
            "max_words": args.max_words,
            "max_tag_chars": args.max_tag_chars,
            "artist_allowed": False,
            "allowed_categories": sorted(allowed_categories),
        },
        "run": {
            "device": args.device,
            "batch_size": args.batch_size,
            "elapsed_seconds": round(elapsed, 3),
        },
        "selection": dict(selection),
        "accepted": len(accepted),
        "accepted_by_category": dict(sorted(category_counts.items())),
        "rejected": dict(sorted(rejected.items())),
        "rejection_examples": rejection_examples,
        "output_csv": str(args.output.resolve()),
        "output_sha256": file_sha256(args.output),
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
