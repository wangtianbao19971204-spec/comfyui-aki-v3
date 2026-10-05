import csv
import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = PLUGIN_ROOT / "tools" / "merge_highfreq_translation_candidates.py"
SPEC = importlib.util.spec_from_file_location("highfreq_candidate_merge", TOOL_PATH)
merger = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(merger)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, fields, rows) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _fixture(tmp_path: Path):
    gallery = tmp_path / "gallery.sqlite"
    connection = sqlite3.connect(gallery)
    connection.execute(
        """
        CREATE TABLE hot_tags (
            tag TEXT PRIMARY KEY,
            category INTEGER NOT NULL,
            post_count INTEGER NOT NULL,
            translation_cn TEXT
        )
        """
    )
    connection.executemany(
        "INSERT INTO hot_tags(tag, category, post_count, translation_cn) VALUES (?, ?, ?, ?)",
        [
            ("general_alpha", 0, 100, None),
            ("copyright_beta_(anime)", 3, 90, None),
            ("character_gamma", 4, 80, "已有角色译名"),
            ("official_delta", 3, 70, None),
        ],
    )
    connection.commit()
    connection.close()

    targets = tmp_path / "targets.csv"
    target_fields = list(merger.TARGET_COPY_COLUMNS) + ["translation_cn"]
    target_rows = []
    for rank, (tag, category, category_name, post_count) in enumerate(
        [
            ("general_alpha", 0, "general", 100),
            ("copyright_beta_(anime)", 3, "copyright", 90),
            ("character_gamma", 4, "character", 80),
            ("official_delta", 3, "copyright", 70),
        ],
        start=1,
    ):
        row = {field: "" for field in target_fields}
        row.update(
            {
                "rank": rank,
                "tag": tag,
                "category": category,
                "category_name": category_name,
                "post_count": post_count,
                "gallery_category_cn": {0: "通用", 3: "作品", 4: "角色"}[category],
                "classification_source": "gallery_category_fallback",
                "weilin_group": "Gallery 通用",
                "weilin_subgroup": "未命中 WeiLin",
                "weilin_match_count": 0,
                "weilin_paths_json": "[]",
            }
        )
        target_rows.append(row)
    _write_csv(targets, target_fields, target_rows)

    curated = tmp_path / "curated.csv"
    _write_csv(
        curated,
        ("tag", "category", "post_count", "translation_cn", "confidence", "review_status"),
        [
            {
                "tag": "general_alpha",
                "category": 0,
                "post_count": 100,
                "translation_cn": "通用阿尔法",
                "confidence": "H",
            },
            {
                "tag": "copyright_beta_(anime)",
                "category": 3,
                "post_count": 90,
                "translation_cn": "贝塔动画",
                "confidence": "H",
            },
            {
                "tag": "copyright_beta_(anime)",
                "category": 3,
                "post_count": 90,
                "translation_cn": "贝塔(动画)",
                "confidence": "H",
            },
            {
                "tag": "character_gamma",
                "category": 4,
                "post_count": 80,
                "translation_cn": "伽马角色",
                "confidence": "H",
            },
            {
                "tag": "official_delta",
                "category": 3,
                "post_count": 70,
                "translation_cn": "",
                "confidence": "H",
                "review_status": "keep_original",
            },
            {
                "tag": "general_alpha",
                "category": 1,
                "post_count": 100,
                "translation_cn": "不应接受",
                "confidence": "H",
            },
        ],
    )

    qwen = tmp_path / "qwen14.csv"
    _write_csv(
        qwen,
        ("tag", "category", "post_count", "translation_cn", "confidence"),
        [
            {
                "tag": "general_alpha",
                "category": 0,
                "post_count": 100,
                "translation_cn": "通用阿尔法",
                "confidence": "H",
            },
            {
                "tag": "copyright_beta_(anime)",
                "category": 3,
                "post_count": 90,
                "translation_cn": "贝塔(动漫)",
                "confidence": "H",
            },
            {
                "tag": "official_delta",
                "category": 3,
                "post_count": 70,
                "translation_cn": "official delta",
                "confidence": "H",
            },
        ],
    )
    return gallery, targets, curated, qwen


def _build(tmp_path: Path, fixture, name="build"):
    gallery, targets, curated, qwen = fixture
    directory = tmp_path / name
    return merger.merge_translation_candidates(
        targets_path=targets,
        gallery_db_path=gallery,
        candidates=(("curated_fallback", curated), ("qwen14", qwen)),
        review_output_path=directory / "review.csv",
        import_output_path=directory / "import.csv",
        report_path=directory / "report.json",
        expected_target_count=4,
    )


def test_review_keeps_exact_target_rows_and_import_is_safe_subset(tmp_path: Path):
    fixture = _fixture(tmp_path)
    inputs = fixture
    before = {path: _sha256(path) for path in inputs}
    report = _build(tmp_path, fixture)

    with Path(report["outputs"]["review"]["path"]).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        review = {row["tag"]: row for row in csv.DictReader(handle)}
    with Path(report["outputs"]["import"]["path"]).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        import_rows = list(csv.DictReader(handle))

    assert len(review) == 4
    assert review["general_alpha"]["review_status"] == "accepted_authoritative"
    assert review["general_alpha"]["agreement_count"] == "2"
    assert review["general_alpha"]["chosen_source"] == "curated_fallback"
    assert review["general_alpha"]["weilin_subgroup"] == "未命中 WeiLin"
    assert review["copyright_beta_(anime)"]["review_status"] == "needs_review_conflict"
    assert review["copyright_beta_(anime)"]["distinct_translation_count"] == "2"
    assert review["character_gamma"]["review_status"] == "blocked_existing_translation"
    assert review["character_gamma"]["translation_cn"] == ""
    assert review["official_delta"]["review_status"] == "keep_original"
    assert review["official_delta"]["translation_cn"] == ""
    assert import_rows == [
        {
            "tag": "general_alpha",
            "category": "0",
            "post_count": "100",
            "translation_cn": "通用阿尔法",
        }
    ]
    assert report["database_mutated"] is False
    assert report["inputs_unchanged"] is True
    assert report["results"]["review_rows"] == 4
    assert report["results"]["import_rows"] == 1
    assert report["results"]["conflicts"] == 1
    rejection_reasons = {row["reason"] for row in report["rejections"]}
    assert "qualifier_group_lost" in rejection_reasons
    assert "forbidden_artist_meta_category" in rejection_reasons
    assert "translation_no_han" in rejection_reasons
    for path in inputs:
        assert _sha256(path) == before[path]


def test_qualifier_groups_are_balanced_preserved_and_may_add_context():
    assert merger._validate_translation("plain_character", "角色名(作品名)") == (
        "角色名(作品名)",
        "accepted",
    )
    assert merger._validate_translation("work_(anime)", "作品动画") == (
        None,
        "qualifier_group_lost",
    )
    assert merger._validate_translation("work_(anime)", "作品(动画") == (
        None,
        "unbalanced_parentheses",
    )
    assert merger._validate_translation("work_(anime)", "作品()") == (
        None,
        "empty_qualifier_group",
    )


def test_pipeline_decisions_express_preapproval_and_keep_original():
    headers = ["tag", "proposed_translation", "decision", "decision_bucket"]
    assert merger._find_column(headers, merger.TRANSLATION_COLUMNS) == "proposed_translation"
    assert merger._is_preapproved(
        {"decision": "auto_accept_strict"}, headers
    ) is True
    assert merger._is_keep_original(
        {"decision_bucket": "preserve_original"}, headers
    ) is True
    assert merger._is_keep_original(
        {"decision": "retain_original_symbolic"}, headers
    ) is True
    assert merger._source_family("qwen14_full") == "qwen14"
    assert merger._source_family("qwen14_proper") == "qwen14"


def test_unverified_proper_name_consensus_remains_review_only():
    evidence = [
        {
            "source": "inventory_pipeline",
            "family": "inventory_pipeline",
            "priority": 70,
            "confidence": "H",
            "confidence_rank": 3,
            "decision": "translation",
            "preapproved": False,
            "translation_cn": "奇迹",
            "translation_key": "奇迹",
            "row": 2,
        },
        {
            "source": "qwen14",
            "family": "qwen14",
            "priority": 55,
            "confidence": "H",
            "confidence_rank": 3,
            "decision": "translation",
            "preapproved": False,
            "translation_cn": "奇迹",
            "translation_key": "奇迹",
            "row": 2,
        },
    ]
    decision = merger._decide(
        {"tag": "marvel", "category": "3"}, evidence, ""
    )
    assert decision["review_status"] == "needs_review_proper_name_consensus"
    assert decision["review_status"] not in merger.AUTO_IMPORT_STATUSES


def test_forbidden_target_category_fails_closed(tmp_path: Path):
    fixture = _fixture(tmp_path)
    gallery, targets, curated, _qwen = fixture
    rows = list(csv.DictReader(targets.open("r", encoding="utf-8-sig", newline="")))
    rows[0]["category"] = "1"
    invalid = tmp_path / "invalid_targets.csv"
    _write_csv(invalid, rows[0].keys(), rows)
    with pytest.raises(merger.CandidateMergeError, match="forbidden artist/meta"):
        merger.merge_translation_candidates(
            targets_path=invalid,
            gallery_db_path=gallery,
            candidates=(("curated", curated),),
            review_output_path=tmp_path / "review.csv",
            import_output_path=tmp_path / "import.csv",
            report_path=tmp_path / "report.json",
            expected_target_count=4,
        )


def test_existing_output_is_never_overwritten(tmp_path: Path):
    fixture = _fixture(tmp_path)
    output = tmp_path / "review.csv"
    output.write_text("sentinel", encoding="utf-8")
    gallery, targets, curated, _qwen = fixture
    with pytest.raises(merger.CandidateMergeError, match="refusing to overwrite"):
        merger.merge_translation_candidates(
            targets_path=targets,
            gallery_db_path=gallery,
            candidates=(("curated", curated),),
            review_output_path=output,
            import_output_path=tmp_path / "import.csv",
            report_path=tmp_path / "report.json",
            expected_target_count=4,
        )
    assert output.read_text(encoding="utf-8") == "sentinel"
    assert not (tmp_path / "import.csv").exists()
    assert not (tmp_path / "report.json").exists()


def test_review_and_import_outputs_are_deterministic(tmp_path: Path):
    fixture = _fixture(tmp_path)
    first = _build(tmp_path, fixture, "first")
    second = _build(tmp_path, fixture, "second")
    for output_name in ("review", "import"):
        assert Path(first["outputs"][output_name]["path"]).read_bytes() == Path(
            second["outputs"][output_name]["path"]
        ).read_bytes()
        assert (
            first["outputs"][output_name]["sha256"]
            == second["outputs"][output_name]["sha256"]
        )
