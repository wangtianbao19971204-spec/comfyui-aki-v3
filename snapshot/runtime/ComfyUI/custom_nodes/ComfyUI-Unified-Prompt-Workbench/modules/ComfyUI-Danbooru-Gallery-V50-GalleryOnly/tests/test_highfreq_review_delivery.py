from __future__ import annotations

import argparse
import csv
import importlib.util
import json
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "build_highfreq_review_delivery.py"
SPEC = importlib.util.spec_from_file_location("build_highfreq_review_delivery", MODULE_PATH)
assert SPEC and SPEC.loader
delivery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(delivery)


def _write_csv(path: Path, headers: list[str], rows: list[list[object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        writer.writerows(rows)


def test_build_keeps_review_candidates_out_of_safe_import(tmp_path: Path) -> None:
    targets = tmp_path / "targets.csv"
    safe = tmp_path / "safe.csv"
    safe_review = tmp_path / "safe_review.csv"
    candidate = tmp_path / "candidate.csv"
    preserve = tmp_path / "preserve.csv"
    output = tmp_path / "review.csv"
    report = tmp_path / "report.json"
    _write_csv(
        targets,
        [
            "rank", "tag", "category", "category_name", "post_count",
            "classification_source", "weilin_group", "weilin_subgroup",
            "weilin_paths_json",
        ],
        [
            [1, "safe_tag", 0, "general", 100, "fallback", "姿势", "手部", '["姿势/手部"]'],
            [2, "review_tag", 0, "general", 90, "fallback", "Gallery 通用", "未命中 WeiLin", "[]"],
            [3, "name_tag", 4, "character", 80, "fallback", "Gallery 角色", "未命中 WeiLin", "[]"],
            [4, "latin_title", 3, "copyright", 70, "fallback", "Gallery 版权", "未命中 WeiLin", "[]"],
        ],
    )
    _write_csv(
        safe,
        ["tag", "category", "post_count", "translation_cn"],
        [["safe_tag", 0, 100, "安全标签"]],
    )
    _write_csv(
        safe_review,
        ["tag", "chosen_source"],
        [["safe_tag", "manual_general"]],
    )
    _write_csv(
        candidate,
        ["tag", "category", "proposed_translation_cn", "confidence", "decision_reason"],
        [
            ["review_tag", 0, "候选标签", "H", "多源精确一致，但仍需人工审核。"],
            ["name_tag", 4, "候选角色", "M", "专名缺少权威确认。"],
        ],
    )
    _write_csv(
        preserve,
        ["tag", "final_action"],
        [["latin_title", "preserve_original_no_import"]],
    )

    result = delivery.build(
        argparse.Namespace(
            targets=str(targets),
            safe_import=str(safe),
            safe_review=str(safe_review),
            candidate=[f"consensus={candidate}"],
            preserve=[str(preserve)],
            output=str(output),
            report=str(report),
            expected_rows=4,
        )
    )
    with output.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_tag = {row["tag"]: row for row in rows}
    assert by_tag["safe_tag"]["review_status"] == "safe_import"
    assert by_tag["safe_tag"]["final_translation_cn"] == "安全标签"
    assert by_tag["review_tag"]["review_status"] == "general_review"
    assert by_tag["review_tag"]["candidate_translation_cn"] == "候选标签"
    assert by_tag["review_tag"]["final_translation_cn"] == ""
    assert by_tag["name_tag"]["review_status"] == "proper_name_review"
    assert by_tag["latin_title"]["review_status"] == "preserve_original"
    assert result["results"]["safe_import_rows"] == 1
    assert json.loads(report.read_text(encoding="utf-8"))["policy"][
        "non_safe_candidates_auto_imported"
    ] is False


def test_forbidden_artist_category_fails_closed(tmp_path: Path) -> None:
    targets = tmp_path / "targets.csv"
    _write_csv(
        targets,
        ["rank", "tag", "category", "category_name", "post_count", "classification_source"],
        [[1, "artist_name", 1, "artist", 100, "fallback"]],
    )
    try:
        delivery._load_targets(targets, 1)
    except delivery.DeliveryError as exc:
        assert "forbidden target category" in str(exc)
    else:
        raise AssertionError("artist target must be rejected")


def test_proposed_correction_is_shown_instead_of_rejected_old_translation() -> None:
    row = {
        "tag": "wrong_character",
        "translation_cn": "错误角色",
        "proposed_correction_cn": "正确角色",
        "decision": "remove",
    }
    assert delivery._candidate_from_row(row) == "正确角色"
