from __future__ import annotations

import csv
import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PLUGIN_ROOT / "tools" / "build_wikidata_tag_translation_pack.py"
SPEC = importlib.util.spec_from_file_location(
    "build_wikidata_tag_translation_pack", MODULE_PATH
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _make_database(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.execute(
            """
            CREATE TABLE hot_tags(
                tag TEXT PRIMARY KEY,
                category INTEGER NOT NULL,
                post_count INTEGER NOT NULL,
                translation_cn TEXT
            )
            """
        )
        connection.executemany("INSERT INTO hot_tags VALUES (?, ?, ?, ?)", rows)
        connection.commit()
    finally:
        connection.close()


def _evidence(
    tag: str,
    description: str,
    translation: str,
    *,
    entity_id: str = "Q1",
    title: str | None = None,
    language: str = "zh-hans",
):
    title = title if title is not None else MODULE.tag_to_title(tag)
    return {
        "requested_title": MODULE.tag_to_title(tag),
        "entity": {
            "id": entity_id,
            "labels": {language: {"language": language, "value": translation}},
            "descriptions": {
                "en": {"language": "en", "value": description}
            },
            "sitelinks": {"enwiki": {"site": "enwiki", "title": title}},
            "lastrevid": 123,
        },
    }


class _FakeHTTPResponse:
    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_tag_to_title_preserves_identity_qualifier_and_normalizes_spacing():
    assert MODULE.tag_to_title("march_7th_(honkai:_star_rail)") == (
        "march 7th (honkai: star rail)"
    )
    assert MODULE.tag_to_title(r"alice_\(game\)") == "alice (game)"
    assert MODULE.tag_to_title("  one__piece  ") == "one piece"


def test_title_lookup_variants_are_finite_deterministic_and_case_only():
    assert MODULE.title_lookup_variants("zenless zone zero") == (
        "zenless zone zero",
        "Zenless Zone Zero",
    )
    assert MODULE.title_lookup_variants("reverse: 1999") == (
        "reverse: 1999",
        "Reverse: 1999",
    )
    assert MODULE.title_lookup_variants("bocchi the rock!") == (
        "bocchi the rock!",
        "Bocchi The Rock!",
        "Bocchi the Rock!",
    )
    for title in (
        "zenless zone zero",
        "reverse: 1999",
        "bocchi the rock!",
    ):
        original_key = MODULE.normalize_title(title)
        assert 1 <= len(MODULE.title_lookup_variants(title)) <= 3
        assert all(
            MODULE.normalize_title(variant) == original_key
            for variant in MODULE.title_lookup_variants(title)
        )


def test_candidate_reason_only_allows_short_copyright_and_character_tags():
    assert MODULE.candidate_reason("work_name", 3, 6, 64) == ""
    assert MODULE.candidate_reason("character_name", 4, 6, 64) == ""
    assert MODULE.candidate_reason("general_tag", 0, 6, 64) == (
        "disallowed_category"
    )
    assert MODULE.candidate_reason("artist_name", 1, 6, 64) == (
        "disallowed_category"
    )
    assert MODULE.candidate_reason("metadata_tag", 5, 6, 64) == (
        "disallowed_category"
    )
    assert MODULE.candidate_reason("one_two_three_four_five_six_seven", 4, 6, 64) == (
        "word_count"
    )
    assert MODULE.candidate_reason("x" * 65, 4, 6, 64) == "tag_length"


def test_select_candidates_excludes_artist_general_existing_and_is_read_only(
    tmp_path: Path,
):
    database = tmp_path / "folder with spaces" / "tags.db"
    _make_database(
        database,
        [
            ("copyright_work", 3, 100, None),
            ("character_name", 4, 90, None),
            ("blank_translation", 4, 80, "   "),
            ("general_tag", 0, 70, None),
            ("artist_name", 1, 60, None),
            ("meta_tag", 5, 50, None),
            ("already_translated", 4, 40, "已有译名"),
            ("one_two_three_four_five_six_seven", 4, 30, None),
            ("x" * 65, 3, 20, None),
        ],
    )
    before = database.read_bytes()

    rows, counts = MODULE.select_candidates(database)

    assert database.read_bytes() == before
    assert [row["tag"] for row in rows] == [
        "copyright_work",
        "character_name",
        "blank_translation",
    ]
    assert all(int(row["category"]) in {3, 4} for row in rows)
    assert counts == {
        "selected": 3,
        "skipped_disallowed_category": 3,
        "skipped_word_count": 1,
        "skipped_tag_length": 1,
    }

    limited_rows, limited_counts = MODULE.select_candidates(database, limit=2)
    assert [row["tag"] for row in limited_rows] == [
        "copyright_work",
        "character_name",
    ]
    assert limited_counts["selected"] == 2
    assert limited_counts["eligible_before_limit"] == 3
    assert limited_counts["skipped_limit"] == 1


def test_load_qualifier_translations_uses_only_safe_nonartist_database_rows(
    tmp_path: Path,
):
    database = tmp_path / "qualifiers.db"
    _make_database(
        database,
        [
            ("game", 0, 100, "游戏"),
            ("series", 3, 90, "系列"),
            ("artist_identity", 1, 80, "艺术家译名"),
            ("empty", 0, 70, "  "),
            ("kana", 0, 60, "ゲーム"),
            ("hangul", 0, 50, "게임"),
            ("parenthesized", 0, 40, "作品（系列）"),
            ("untranslated", 0, 30, None),
        ],
    )
    before = database.read_bytes()

    translations = MODULE.load_qualifier_translations(database)

    assert database.read_bytes() == before
    assert translations == {"game": "游戏", "series": "系列"}


def test_validate_entity_accepts_work_and_character_with_simplified_labels():
    work = _evidence(
        "wuthering_waves",
        "2024 action role-playing video game",
        "鸣潮",
        entity_id="Q117750031",
        title="Wuthering Waves",
    )
    character = _evidence(
        "march_7th_(honkai:_star_rail)",
        "fictional character in the video game Honkai: Star Rail",
        "三月七（崩坏：星穹铁道）",
        entity_id="Q123",
        title="March 7th (Honkai: Star Rail)",
        language="zh-cn",
    )

    assert MODULE.validate_entity("wuthering_waves", 3, work) == (
        "鸣潮",
        "accepted",
        "Q117750031",
    )
    assert MODULE.validate_entity(
        "march_7th_(honkai:_star_rail)", 4, character
    ) == ("三月七(崩坏:星穹铁道)", "accepted", "Q123")


def test_validate_entity_reconstructs_missing_qualifier_from_exact_db_mapping():
    evidence = _evidence(
        "march_7th_(honkai:_star_rail)",
        "fictional character in the video game Honkai: Star Rail",
        "三月七",
        entity_id="Q123",
        title="March 7th (Honkai: Star Rail)",
    )

    assert MODULE.validate_entity(
        "march_7th_(honkai:_star_rail)",
        4,
        evidence,
        {"honkai:_star_rail": "崩坏：星穹铁道"},
    ) == ("三月七(崩坏:星穹铁道)", "accepted_reconstructed", "Q123")


def test_validate_entity_reconstructs_multiple_qualifiers_in_source_order():
    evidence = _evidence(
        "alice_(game)_(school_uniform)",
        "fictional character in a video game",
        "爱丽丝",
        title="Alice (game) (school uniform)",
    )

    assert MODULE.validate_entity(
        "alice_(game)_(school_uniform)",
        4,
        evidence,
        {"school_uniform": "学校制服", "game": "游戏"},
    )[0:2] == ("爱丽丝(游戏)(学校制服)", "accepted_reconstructed")


@pytest.mark.parametrize(
    "unsafe_translation",
    [None, "", "ゲーム", "게임", "作品（系列）"],
)
def test_validate_entity_rejects_missing_or_unsafe_qualifier_mapping(
    unsafe_translation,
):
    evidence = _evidence(
        "alice_(game)",
        "fictional character in a video game",
        "爱丽丝",
        title="Alice (game)",
    )

    assert MODULE.validate_entity(
        "alice_(game)", 4, evidence, {"game": unsafe_translation}
    )[0:2] == (None, "qualifier_lost")


def test_validate_entity_never_fills_only_part_of_existing_label_qualifiers():
    evidence = _evidence(
        "alice_(game)_(series)",
        "fictional character in a video game series",
        "爱丽丝（游戏）",
        title="Alice (game) (series)",
    )

    assert MODULE.validate_entity(
        "alice_(game)_(series)",
        4,
        evidence,
        {"game": "游戏", "series": "系列"},
    )[0:2] == (None, "qualifier_lost")


@pytest.mark.parametrize(
    ("tag", "category", "evidence", "reason"),
    [
        (
            "bleach",
            3,
            _evidence("bleach", "chemical product that removes color", "漂白剂"),
            "category_mismatch",
        ),
        (
            "project_moon",
            3,
            _evidence(
                "project_moon",
                "Wikimedia disambiguation page",
                "月亮计划",
            ),
            "description_rejected",
        ),
        (
            "wuthering_waves",
            3,
            _evidence(
                "wuthering_waves",
                "2024 action role-playing video game",
                "鸣潮",
                title="A Different Game",
            ),
            "title_mismatch",
        ),
        (
            "wuthering_waves",
            0,
            _evidence(
                "wuthering_waves",
                "2024 action role-playing video game",
                "鸣潮",
            ),
            "disallowed_category",
        ),
        (
            "some_artist",
            1,
            _evidence("some_artist", "fictional character", "某艺术家"),
            "disallowed_category",
        ),
        (
            "alice",
            4,
            _evidence("alice", "Japanese manga series", "爱丽丝"),
            "category_mismatch",
        ),
        (
            "fictional_world",
            4,
            _evidence("fictional_world", "fictional universe", "虚构世界"),
            "category_mismatch",
        ),
        (
            "alice",
            4,
            _evidence("alice", "fictional character", "Alice"),
            "no_han",
        ),
    ],
)
def test_validate_entity_rejects_wrong_or_unsafe_entities(
    tag: str, category: int, evidence, reason: str
):
    translation, actual_reason, _entity_id = MODULE.validate_entity(
        tag, category, evidence
    )
    assert translation is None
    assert actual_reason == reason


def test_validate_entity_requires_every_parenthesis_group_to_remain_balanced():
    accepted = _evidence(
        "alice_(game)",
        "fictional character in a video game",
        "爱丽丝（游戏）",
        title="Alice (game)",
    )
    missing = _evidence(
        "alice_(game)",
        "fictional character in a video game",
        "爱丽丝",
        title="Alice (game)",
    )
    extra = _evidence(
        "alice",
        "fictional character in a video game",
        "爱丽丝（游戏）",
        title="Alice",
    )
    unbalanced = _evidence(
        "alice_(game)",
        "fictional character in a video game",
        "爱丽丝（游戏",
        title="Alice (game)",
    )
    empty = _evidence(
        "alice_(game)",
        "fictional character in a video game",
        "爱丽丝（）",
        title="Alice (game)",
    )

    assert MODULE.validate_entity("alice_(game)", 4, accepted)[0:2] == (
        "爱丽丝(游戏)",
        "accepted",
    )
    assert MODULE.validate_entity("alice_(game)", 4, missing)[1] == (
        "qualifier_lost"
    )
    assert MODULE.validate_entity("alice", 4, extra)[1] == "qualifier_lost"
    assert MODULE.validate_entity("alice_(game)", 4, unbalanced)[1] == (
        "qualifier_lost"
    )
    assert MODULE.validate_entity("alice_(game)", 4, empty)[1] == "qualifier_lost"


def test_fetch_entities_maps_only_exact_sitelink_titles_without_network(monkeypatch):
    captured = {}

    def fake_post(parameters):
        captured.update(parameters)
        return {
            "entities": {
                "Q1": _evidence(
                    "wuthering_waves",
                    "video game",
                    "鸣潮",
                    title="Wuthering Waves",
                )["entity"],
                "Q2": _evidence(
                    "other_game",
                    "video game",
                    "其他游戏",
                    title="Other Game",
                )["entity"],
            }
        }

    monkeypatch.setattr(MODULE, "_post_api", fake_post)
    rows = MODULE.fetch_entities(["wuthering waves", "missing work"])

    # wbgetentities defaults to not following redirects.  Omitting the boolean
    # parameter avoids an ambiguous non-empty value being interpreted as true.
    assert "redirects" not in captured
    # Wikidata rejects normalize when a request contains multiple titles.
    assert "normalize" not in captured
    assert captured["props"] == "labels|descriptions|sitelinks|info"
    assert [row["requested_title"] for row in rows] == [
        "wuthering waves",
        "missing work",
    ]
    assert rows[0]["entity"]["id"] == "Q1"
    assert rows[0]["lookup_status"] == "found"
    assert rows[1]["entity"] is None
    assert rows[1]["lookup_status"] == "not_found"


def test_fetch_entities_resolves_known_title_case_variants_and_records_evidence(
    monkeypatch,
):
    calls = []

    entities_by_lookup_title = {
        "Zenless Zone Zero": _evidence(
            "zenless_zone_zero",
            "action role-playing video game",
            "绝区零",
            entity_id="Q113203792",
            title="Zenless Zone Zero",
        )["entity"],
        "Reverse: 1999": _evidence(
            "reverse:_1999",
            "role-playing video game",
            "重返未来：1999",
            entity_id="Q123575132",
            title="Reverse: 1999",
        )["entity"],
        "Bocchi the Rock!": _evidence(
            "bocchi_the_rock!",
            "Japanese manga series",
            "孤独摇滚！",
            entity_id="Q96777579",
            title="Bocchi the Rock!",
        )["entity"],
    }

    def fake_post(parameters):
        lookup_titles = parameters["titles"].split("|")
        calls.append(lookup_titles)
        entities = {
            entity["id"]: entity
            for lookup_title in lookup_titles
            for entity in [entities_by_lookup_title.get(lookup_title)]
            if entity is not None
        }
        # An API response cannot widen acceptance: this deliberately returned
        # near-match has an extra qualifier and must never map to an original.
        entities["Q999"] = _evidence(
            "bocchi_the_rock!_(film)",
            "film",
            "孤独摇滚电影",
            entity_id="Q999",
            title="Bocchi the Rock! (film)",
        )["entity"]
        return {"entities": entities}

    monkeypatch.setattr(MODULE, "_post_api", fake_post)
    rows = MODULE.fetch_entities(
        ["zenless zone zero", "reverse: 1999", "bocchi the rock!"]
    )

    assert calls == [
        ["zenless zone zero", "reverse: 1999", "bocchi the rock!"],
        ["Zenless Zone Zero", "Reverse: 1999", "Bocchi The Rock!"],
        ["Bocchi the Rock!"],
    ]
    assert [row["entity"]["id"] for row in rows] == [
        "Q113203792",
        "Q123575132",
        "Q96777579",
    ]
    assert [row["lookup_variant"] for row in rows] == [
        "Zenless Zone Zero",
        "Reverse: 1999",
        "Bocchi the Rock!",
    ]
    assert rows[2]["lookup_variants_tried"] == [
        "bocchi the rock!",
        "Bocchi The Rock!",
        "Bocchi the Rock!",
    ]


def test_fetch_entities_rejects_non_exact_title_even_when_api_returns_it(
    monkeypatch,
):
    wrong = _evidence(
        "zenless_zone_zero_(soundtrack)",
        "soundtrack album",
        "绝区零原声带",
        entity_id="Q404",
        title="Zenless Zone Zero (soundtrack)",
    )["entity"]
    monkeypatch.setattr(MODULE, "_post_api", lambda _parameters: {"entities": {"Q404": wrong}})

    row = MODULE.fetch_entities(["zenless zone zero"])[0]

    assert row["requested_title"] == "zenless zone zero"
    assert row["lookup_status"] == "not_found"
    assert row["lookup_variant"] is None
    assert row["entity"] is None


def test_build_pack_with_no_candidates_creates_hashed_empty_cache_without_network(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    output = tmp_path / "artifacts" / "pack.csv"
    cache = tmp_path / "artifacts" / "cache.jsonl"
    report_path = tmp_path / "artifacts" / "report.json"
    _make_database(
        database,
        [
            ("artist_name", 1, 100, None),
            ("general_tag", 0, 90, None),
            ("translated_character", 4, 80, "已有译名"),
        ],
    )
    before = database.read_bytes()

    def fail_fetch(_titles):
        raise AssertionError("no network fetch should be attempted")

    monkeypatch.setattr(MODULE, "fetch_entities", fail_fetch)
    report = MODULE.build_pack(database, output, cache, report_path)

    assert database.read_bytes() == before
    assert cache.is_file() and cache.read_bytes() == b""
    assert report["source"]["snapshot_cache_sha256"] == MODULE.file_sha256(cache)
    assert report["fetch"] == {
        "unique_titles": 0,
        "cached_titles_before": 0,
        "new_titles": 0,
        "requests_made": 0,
        "request_interval_seconds": 1.0,
        "purged_unverified_null_cache_rows": 0,
        "purged_verified_not_found_cache_rows": 0,
    }
    with output.open(encoding="utf-8-sig", newline="") as handle:
        assert list(csv.DictReader(handle)) == []
    assert json.loads(report_path.read_text(encoding="utf-8")) == report


def test_build_pack_refuses_artifact_paths_that_can_overwrite_database(
    tmp_path: Path,
):
    database = tmp_path / "tags.db"
    _make_database(database, [("character_name", 4, 100, None)])
    before = database.read_bytes()

    with pytest.raises(ValueError, match="must not overwrite the database"):
        MODULE.build_pack(
            database,
            database,
            tmp_path / "cache.jsonl",
            tmp_path / "report.json",
        )

    assert database.read_bytes() == before


def test_build_pack_refuses_hardlinks_to_database_and_between_artifacts(
    tmp_path: Path,
):
    database = tmp_path / "tags.db"
    _make_database(database, [("character_name", 4, 100, None)])
    before = database.read_bytes()

    output = tmp_path / "database-hardlink.csv"
    os.link(database, output)
    with pytest.raises(ValueError, match="must not overwrite the database"):
        MODULE.build_pack(
            database,
            output,
            tmp_path / "cache.jsonl",
            tmp_path / "report.json",
        )
    assert database.read_bytes() == before

    cache = tmp_path / "shared-cache.jsonl"
    report = tmp_path / "shared-report.json"
    cache.write_text("sentinel", encoding="utf-8")
    os.link(cache, report)
    with pytest.raises(ValueError, match="hard-link collision"):
        MODULE.build_pack(
            database,
            tmp_path / "pack.csv",
            cache,
            report,
        )
    assert cache.read_text(encoding="utf-8") == "sentinel"


@pytest.mark.parametrize(
    ("status", "headers", "expected_delay"),
    [
        (429, {"Retry-After": "7"}, 7.0),
        (503, {}, 2.0),
        (504, {"Retry-After": "3"}, 3.0),
    ],
)
def test_post_api_retries_transient_http_errors_and_respects_retry_after(
    monkeypatch, status: int, headers, expected_delay: float
):
    responses = iter(
        [
            MODULE.urllib.error.HTTPError(
                MODULE.API_URL, status, "temporary", headers, None
            ),
            _FakeHTTPResponse({"entities": {}}),
        ]
    )
    sleeps = []

    def fake_urlopen(_request, timeout):
        assert timeout == 45
        response = next(responses)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(MODULE.time, "sleep", sleeps.append)

    assert MODULE._post_api({"action": "test"}, retries=2) == {"entities": {}}
    assert sleeps == [expected_delay]


def test_post_api_retries_json_maxlag_using_largest_server_hint(monkeypatch):
    responses = iter(
        [
            _FakeHTTPResponse(
                {
                    "error": {
                        "code": "maxlag",
                        "info": "Waiting for replication",
                        "lag": 6,
                    }
                },
                headers={"Retry-After": "4"},
            ),
            _FakeHTTPResponse({"entities": {}}),
        ]
    )
    sleeps = []
    monkeypatch.setattr(
        MODULE.urllib.request,
        "urlopen",
        lambda _request, timeout: next(responses),
    )
    monkeypatch.setattr(MODULE.time, "sleep", sleeps.append)

    assert MODULE._post_api({"action": "test"}, retries=2) == {"entities": {}}
    assert sleeps == [6.0]


def test_post_api_does_not_retry_non_transient_http_error(monkeypatch):
    error = MODULE.urllib.error.HTTPError(
        MODULE.API_URL, 400, "bad request", {}, None
    )
    sleeps = []

    def fail(_request, timeout):
        raise error

    monkeypatch.setattr(MODULE.urllib.request, "urlopen", fail)
    monkeypatch.setattr(MODULE.time, "sleep", sleeps.append)

    with pytest.raises(MODULE.urllib.error.HTTPError) as caught:
        MODULE._post_api({"action": "test"}, retries=6)
    assert caught.value.code == 400
    assert sleeps == []


def test_load_cache_repairs_only_a_truncated_final_json_line(tmp_path: Path):
    cache_path = tmp_path / "checkpoint.jsonl"
    first = {"requested_title": "first game", "entity": None}
    first_line = (
        json.dumps(first, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")
    cache_path.write_bytes(first_line + b'{"requested_title":"unfinished')

    loaded = MODULE.load_cache(cache_path)

    assert set(loaded) == {"first game"}
    assert cache_path.read_bytes() == first_line
    MODULE.append_cache(
        cache_path, [{"requested_title": "second game", "entity": None}]
    )
    assert set(MODULE.load_cache(cache_path)) == {"first game", "second game"}


def _fetched_rows(titles):
    translations = {
        "first game": "第一游戏",
        "second game": "第二游戏",
    }
    rows = []
    for title in titles:
        tag = title.replace(" ", "_")
        row = _evidence(
            tag,
            "video game",
            translations[title],
            title=title,
            entity_id="Q" + str(len(rows) + 1),
        )
        row.update(
            {
                "fetched_at_utc": "2026-01-01T00:00:00+00:00",
                "api_url": MODULE.API_URL,
                "lookup_status": "found",
            }
        )
        rows.append(row)
    return rows


def test_build_pack_throttles_between_successful_batches_after_checkpoint(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    output = tmp_path / "pack.csv"
    cache = tmp_path / "cache.jsonl"
    report_path = tmp_path / "report.json"
    _make_database(
        database,
        [
            ("first_game", 3, 100, None),
            ("second_game", 3, 90, None),
        ],
    )
    sleeps = []
    monkeypatch.setattr(MODULE, "fetch_entities", _fetched_rows)
    monkeypatch.setattr(MODULE.time, "sleep", sleeps.append)

    report = MODULE.build_pack(
        database,
        output,
        cache,
        report_path,
        batch_size=1,
        request_interval_seconds=2.5,
    )

    assert sleeps == [2.5]
    assert len(cache.read_text(encoding="utf-8").splitlines()) == 2
    assert report["fetch"] == {
        "unique_titles": 2,
        "cached_titles_before": 0,
        "new_titles": 2,
        "requests_made": 2,
        "request_interval_seconds": 2.5,
        "purged_unverified_null_cache_rows": 0,
        "purged_verified_not_found_cache_rows": 0,
    }
    assert report["output"]["rows"] == 2


def test_build_pack_resumes_from_completed_batches_after_later_failure(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    output = tmp_path / "pack.csv"
    cache = tmp_path / "cache.jsonl"
    report_path = tmp_path / "report.json"
    _make_database(
        database,
        [
            ("first_game", 3, 100, None),
            ("second_game", 3, 90, None),
        ],
    )
    first_run_calls = []

    def fail_second_batch(titles):
        first_run_calls.append(list(titles))
        if len(first_run_calls) == 2:
            raise RuntimeError("simulated later-batch failure")
        return _fetched_rows(titles)

    monkeypatch.setattr(MODULE, "fetch_entities", fail_second_batch)
    with pytest.raises(RuntimeError, match="later-batch failure"):
        MODULE.build_pack(
            database,
            output,
            cache,
            report_path,
            batch_size=1,
            request_interval_seconds=0,
        )
    assert first_run_calls == [["first game"], ["second game"]]
    assert set(MODULE.load_cache(cache)) == {"first game"}

    resumed_calls = []

    def resume_fetch(titles):
        resumed_calls.append(list(titles))
        return _fetched_rows(titles)

    monkeypatch.setattr(MODULE, "fetch_entities", resume_fetch)
    report = MODULE.build_pack(
        database,
        output,
        cache,
        report_path,
        batch_size=1,
        request_interval_seconds=0,
    )

    assert resumed_calls == [["second game"]]
    assert set(MODULE.load_cache(cache)) == {"first game", "second game"}
    assert report["fetch"]["cached_titles_before"] == 1
    assert report["fetch"]["new_titles"] == 1


def test_request_interval_is_configurable_from_cli():
    args = MODULE.parse_args(
        [
            "--output",
            "pack.csv",
            "--cache",
            "cache.jsonl",
            "--report",
            "report.json",
            "--request-interval-seconds",
            "2.75",
            "--refetch-null-cache",
        ]
    )
    assert args.request_interval_seconds == 2.75
    assert args.refetch_null_cache is True


def test_post_api_rejects_params_illegal_without_returning_fake_not_found(
    monkeypatch,
):
    sleeps = []
    monkeypatch.setattr(
        MODULE.urllib.request,
        "urlopen",
        lambda _request, timeout: _FakeHTTPResponse(
            {
                "error": {
                    "code": "params-illegal",
                    "info": (
                        "Normalize is only allowed if exactly one site and one "
                        "page have been given"
                    ),
                }
            }
        ),
    )
    monkeypatch.setattr(MODULE.time, "sleep", sleeps.append)

    with pytest.raises(MODULE.WikidataAPIError, match="params-illegal"):
        MODULE._post_api({"action": "wbgetentities"})
    assert sleeps == []


def test_refetch_null_cache_atomically_purges_legacy_ambiguous_rows(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    output = tmp_path / "pack.csv"
    cache = tmp_path / "cache.jsonl"
    report_path = tmp_path / "report.json"
    _make_database(
        database,
        [
            ("first_game", 3, 100, None),
            ("second_game", 3, 90, None),
        ],
    )
    database_before = database.read_bytes()
    MODULE.append_cache(
        cache,
        [
            {
                "requested_title": "first game",
                "entity": None,
                # Deliberately no lookup_status: legacy rows generated from an
                # API error are indistinguishable from old legitimate misses.
            },
            *_fetched_rows(["second game"]),
        ],
    )
    fetched = []

    def fetch_missing(titles):
        fetched.append(list(titles))
        return _fetched_rows(titles)

    monkeypatch.setattr(MODULE, "fetch_entities", fetch_missing)
    report = MODULE.build_pack(
        database,
        output,
        cache,
        report_path,
        batch_size=1,
        request_interval_seconds=0,
        refetch_null_cache=True,
    )

    assert database.read_bytes() == database_before
    assert fetched == [["first game"]]
    refreshed = MODULE.load_cache(cache)
    assert set(refreshed) == {"first game", "second game"}
    assert all(row["lookup_status"] == "found" for row in refreshed.values())
    assert len(cache.read_text(encoding="utf-8").splitlines()) == 2
    assert report["fetch"]["purged_unverified_null_cache_rows"] == 1
    assert report["fetch"]["purged_verified_not_found_cache_rows"] == 0
    assert report["fetch"]["cached_titles_before"] == 1
    assert report["fetch"]["new_titles"] == 1


def test_refetch_null_cache_retries_verified_not_found_and_preserves_found(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    output = tmp_path / "pack.csv"
    cache = tmp_path / "cache.jsonl"
    report_path = tmp_path / "report.json"
    _make_database(
        database,
        [
            ("zenless_zone_zero", 3, 100, None),
            ("already_found_game", 3, 90, None),
        ],
    )
    already_found = _evidence(
        "already_found_game",
        "video game",
        "已有游戏",
        entity_id="Q2",
        title="Already Found Game",
    )
    already_found.update(
        {
            "lookup_status": "found",
            "lookup_variant": "Already Found Game",
            "lookup_variants_tried": ["already found game", "Already Found Game"],
        }
    )
    MODULE.append_cache(
        cache,
        [
            {
                "requested_title": "zenless zone zero",
                "entity": None,
                "lookup_status": "not_found",
                "lookup_variant": None,
                "lookup_variants_tried": ["zenless zone zero"],
            },
            already_found,
        ],
    )
    fetched = []

    def fetch_missing(titles):
        fetched.append(list(titles))
        row = _evidence(
            "zenless_zone_zero",
            "action role-playing video game",
            "绝区零",
            entity_id="Q113203792",
            title="Zenless Zone Zero",
        )
        row.update(
            {
                "lookup_status": "found",
                "lookup_variant": "Zenless Zone Zero",
                "lookup_variants_tried": [
                    "zenless zone zero",
                    "Zenless Zone Zero",
                ],
            }
        )
        return [row]

    monkeypatch.setattr(MODULE, "fetch_entities", fetch_missing)
    report = MODULE.build_pack(
        database,
        output,
        cache,
        report_path,
        request_interval_seconds=0,
        refetch_null_cache=True,
    )

    assert fetched == [["zenless zone zero"]]
    refreshed = MODULE.load_cache(cache)
    assert set(refreshed) == {"zenless zone zero", "already found game"}
    assert refreshed["zenless zone zero"]["lookup_status"] == "found"
    assert refreshed["already found game"] == already_found
    assert report["fetch"]["purged_unverified_null_cache_rows"] == 0
    assert report["fetch"]["purged_verified_not_found_cache_rows"] == 1
    assert report["fetch"]["cached_titles_before"] == 1
    assert report["fetch"]["new_titles"] == 1


def test_build_pack_reports_qualifiers_reconstructed_from_same_read_only_db(
    tmp_path: Path, monkeypatch
):
    database = tmp_path / "tags.db"
    output = tmp_path / "pack.csv"
    cache = tmp_path / "cache.jsonl"
    report_path = tmp_path / "report.json"
    character_tag = "march_7th_(honkai:_star_rail)"
    _make_database(
        database,
        [
            (character_tag, 4, 100, None),
            ("honkai:_star_rail", 3, 90, "崩坏：星穹铁道"),
            ("artist_qualifier", 1, 80, "不得使用"),
        ],
    )
    database_before = database.read_bytes()
    cached = _evidence(
        character_tag,
        "fictional character in the video game Honkai: Star Rail",
        "三月七",
        entity_id="Q123",
        title="March 7th (Honkai: Star Rail)",
    )
    cached.update(
        {
            "fetched_at_utc": "2026-01-01T00:00:00+00:00",
            "api_url": MODULE.API_URL,
            "lookup_status": "found",
        }
    )
    MODULE.append_cache(cache, [cached])

    def no_fetch(_titles):
        raise AssertionError("cached evidence must not trigger a network fetch")

    monkeypatch.setattr(MODULE, "fetch_entities", no_fetch)
    report = MODULE.build_pack(database, output, cache, report_path)

    assert database.read_bytes() == database_before
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["tag"] == character_tag
    assert rows[0]["translation_cn"] == "三月七(崩坏:星穹铁道)"
    assert report["output"]["rows"] == 1
    assert report["output"]["reconstructed_rows"] == 1
    assert report["output"]["reconstructed_qualifiers"] == 1
    assert report["output"]["qualifier_translation_entries"] == 1
