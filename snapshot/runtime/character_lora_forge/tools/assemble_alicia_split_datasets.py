from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from collections import Counter
from datetime import datetime
from pathlib import Path


CAMPAIGN = Path(
    r"G:\ComfyUI-aki-v3\character_lora_forge\characters\alicia_bell\runs\20260818_20x200_campaign"
)
CORE_MANIFEST = CAMPAIGN / "final_training_200" / "final_manifest.json"
REVIEW_ROOT = CAMPAIGN / "split_lora_selection" / "reviews"
OUTPUT_ROOT = CAMPAIGN / "final_training_split_200"
FORMS = {
    "ordinary": {
        "trigger": "alcbo7yo260822",
        "review": REVIEW_ROOT / "ordinary_additional_100.json",
    },
    "morning_star": {
        "trigger": "alcbm7yo260822",
        "review": REVIEW_ROOT / "morning_star_additional_100.json",
    },
}
HOSIERY_PHRASE = (
    "very sheer ivory pantyhose covering both legs and feet, "
    "warm skin tone visible through the fabric"
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def replace_trigger(caption: str, trigger: str) -> str:
    tail = caption.split(",", 1)[1].strip() if "," in caption else caption.strip()
    return f"{trigger}, {tail}"


def normalize_hosiery(caption: str) -> str:
    patterns = (
        r"very sheer plain ivory stockings(?: and wine-red high heels)?",
        r"plain sheer ivory stockings",
        r"sheer plain ivory stockings",
        r"very sheer ivory stockings",
        r"sheer ivory stockings",
        r"ivory pantyhose",
    )
    # A single substitution pass prevents replacement text from matching a
    # later alias and recursively duplicating the fixed contract phrase.
    normalized = re.sub(
        "(?:" + "|".join(patterns) + ")",
        HOSIERY_PHRASE,
        caption,
        flags=re.IGNORECASE,
    )
    matches = list(re.finditer(re.escape(HOSIERY_PHRASE), normalized, flags=re.IGNORECASE))
    for duplicate in reversed(matches[1:]):
        normalized = normalized[: duplicate.start()] + normalized[duplicate.end() :]
    normalized = re.sub(r",\s*,", ",", normalized)
    leg_visible = re.search(
        r"full[- ]body|head[- ]to[- ]heel|waist[- ]to[- ]feet|lower[- ]body|full[- ]length",
        normalized,
        flags=re.IGNORECASE,
    )
    if leg_visible and HOSIERY_PHRASE.lower() not in normalized.lower():
        normalized = f"{normalized.rstrip('. ')}, {HOSIERY_PHRASE}"
    return normalized


def validate_additional(sidecar: dict, form: str, trigger: str, core_hashes: set[str]) -> list[dict]:
    records = sidecar.get("selected_records", [])
    if len(records) != 100:
        raise RuntimeError(f"{form}: expected 100 additional records, found {len(records)}")
    counts = Counter(record["round_id"] for record in records)
    expected = {f"R{index:02d}": 5 for index in range(1, 21)}
    if counts != expected:
        raise RuntimeError(f"{form}: invalid per-round counts: {dict(counts)}")
    hashes = [record["sha256"].upper() for record in records]
    if len(set(hashes)) != len(hashes):
        raise RuntimeError(f"{form}: duplicate SHA256 in additional selection")
    overlap = core_hashes.intersection(hashes)
    if overlap:
        raise RuntimeError(f"{form}: additional selection overlaps core hashes: {sorted(overlap)[:3]}")
    for record in records:
        source = Path(record["source_path"])
        if not source.is_file():
            raise RuntimeError(f"{form}: missing source image: {source}")
        if sha256_file(source) != record["sha256"].upper():
            raise RuntimeError(f"{form}: source hash mismatch: {source}")
        if not record["caption"].startswith(f"{trigger},"):
            raise RuntimeError(f"{form}: caption trigger mismatch: {record['source_name']}")
    return records


def assemble_form(form: str, core_records: list[dict], additional: list[dict], trigger: str) -> dict:
    destination_root = OUTPUT_ROOT / form
    dataset = destination_root / "dataset"
    if dataset.exists() and any(dataset.iterdir()):
        raise RuntimeError(f"Refusing to overwrite non-empty dataset: {dataset}")
    dataset.mkdir(parents=True, exist_ok=True)

    combined = []
    for record in core_records:
        combined.append({
            "round_id": record["round_id"],
            "source_path": record["final_image_path"],
            "source_name": Path(record["final_image_path"]).name,
            "sha256": record["sha256"].upper(),
            "caption": record["caption"],
            "source_kind": "audited_mixed_core",
        })
    for record in additional:
        combined.append({
            "round_id": record["round_id"],
            "source_path": record["source_path"],
            "source_name": record["source_name"],
            "sha256": record["sha256"].upper(),
            "caption": record["caption"],
            "source_kind": "split_additional_review",
            "selection_reason": record["selection_reason"],
        })
    combined.sort(key=lambda item: (item["round_id"], item["source_kind"], item["source_name"]))
    hashes = [record["sha256"] for record in combined]
    if len(combined) != 200 or len(set(hashes)) != 200:
        raise RuntimeError(f"{form}: combined set must contain 200 unique records")

    round_ordinals: Counter[str] = Counter()
    output_records = []
    for record in combined:
        round_ordinals[record["round_id"]] += 1
        ordinal = round_ordinals[record["round_id"]]
        stem = f"{trigger}_{form}_{record['round_id']}_{ordinal:02d}"
        source = Path(record["source_path"])
        image_path = dataset / f"{stem}{source.suffix.lower()}"
        caption_path = dataset / f"{stem}.txt"
        shutil.copy2(source, image_path)
        caption = replace_trigger(record["caption"], trigger)
        if form == "morning_star":
            caption = normalize_hosiery(caption)
        caption_path.write_text(caption.rstrip(". ") + ".\n", encoding="utf-8")
        output_records.append({
            **record,
            "final_stem": stem,
            "final_image_path": str(image_path.resolve()),
            "final_caption_path": str(caption_path.resolve()),
            "caption": caption.rstrip(". ") + ".",
        })

    manifest = {
        "schema_version": 1,
        "status": "assembled_pending_global_audit",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "form": form,
        "trigger_token": trigger,
        "counts": {
            "images": len(list(dataset.glob("*.png"))),
            "captions": len(list(dataset.glob("*.txt"))),
            "core": sum(record["source_kind"] == "audited_mixed_core" for record in output_records),
            "additional": sum(record["source_kind"] == "split_additional_review" for record in output_records),
            "unique_sha256": len(set(hashes)),
        },
        "per_round_counts": dict(sorted(round_ordinals.items())),
        "hosiery_caption_policy": HOSIERY_PHRASE if form == "morning_star" else None,
        "dataset_path": str(dataset.resolve()),
        "records": output_records,
    }
    manifest_path = destination_root / "selection_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--form", choices=tuple(FORMS))
    args = parser.parse_args()
    core_manifest = json.loads(CORE_MANIFEST.read_text(encoding="utf-8"))
    summaries = {}
    forms = {args.form: FORMS[args.form]} if args.form else FORMS
    for form, config in forms.items():
        core = [record for record in core_manifest["records"] if record["form"] == form]
        if len(core) != 100:
            raise RuntimeError(f"{form}: expected 100 audited core records, found {len(core)}")
        core_hashes = {record["sha256"].upper() for record in core}
        sidecar = json.loads(config["review"].read_text(encoding="utf-8"))
        additional = validate_additional(sidecar, form, config["trigger"], core_hashes)
        manifest = assemble_form(form, core, additional, config["trigger"])
        summaries[form] = manifest["counts"]
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
