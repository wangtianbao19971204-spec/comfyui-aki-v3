import csv
import http.client
import importlib.util
import json
from pathlib import Path

import pytest


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TOOL_PATH = PLUGIN_ROOT / "tools" / "fetch_bangumi_translation_candidates.py"
SPEC = importlib.util.spec_from_file_location("bangumi_candidate_fetcher", TOOL_PATH)
fetcher = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(fetcher)


def _write_targets(path: Path, rows) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("rank", "tag", "category", "category_name", "post_count"),
        )
        writer.writeheader()
        writer.writerows(rows)


def _alias(value: str):
    return [{"key": "别名", "value": [{"k": "罗马字", "v": value}]}]


def _character(entity_id: int, alias: str, chinese=None):
    infobox = _alias(alias)
    if chinese is not None:
        infobox.insert(0, {"key": "简体中文名", "value": chinese})
    return {"id": entity_id, "name": "日文名", "infobox": infobox}


class FixtureTransport:
    def __init__(self, responses, fail_key=None):
        self.responses = responses
        self.fail_key = fail_key
        self.requests = []

    def request_json(self, method, path, *, query, body):
        keyword = str((body or {}).get("keyword") or "")
        offset = int(query.get("offset") or 0)
        key = (method.upper(), path, keyword, offset)
        self.requests.append(key)
        if self.fail_key == key:
            raise fetcher.BangumiFetchError("fixture interruption")
        response = self.responses.get(key)
        if response is None:
            raise AssertionError("unexpected request: {!r}".format(key))
        return response


def _search(data):
    return {"total": len(data), "limit": 10, "offset": 0, "data": data}


def _build(tmp_path: Path, targets: Path, transport, name="build", expected=0):
    directory = tmp_path / name
    return fetcher.fetch_bangumi_candidates(
        targets_path=targets,
        candidates_output_path=directory / "candidates.csv",
        raw_cache_path=tmp_path / "raw.jsonl",
        report_path=directory / "report.json",
        transport=transport,
        expected_eligible_count=expected,
        page_size=10,
        max_results=10,
    )


def test_exact_subject_and_character_match_with_hard_category_exclusions(tmp_path: Path):
    targets = tmp_path / "targets.csv"
    _write_targets(
        targets,
        [
            {"rank": 1, "tag": "general_tag", "category": 0, "category_name": "general", "post_count": 100},
            {"rank": 2, "tag": "artist_name", "category": 1, "category_name": "artist", "post_count": 90},
            {"rank": 3, "tag": "sample_work_(anime)", "category": 3, "category_name": "copyright", "post_count": 80},
            {"rank": 4, "tag": "alice_example_(sample_work)", "category": 4, "category_name": "character", "post_count": 70},
        ],
    )
    subject = {
        "id": 11,
        "name": "サンプル",
        "name_cn": "示例作品",
        "infobox": _alias("Sample Work"),
    }
    character_search = _character(22, "Alice Example", "爱丽丝")
    character_detail = _character(22, "Alice Example", "爱丽丝")
    responses = {
        ("POST", "/v0/search/subjects", "sample work", 0): _search([subject]),
        ("POST", "/v0/search/characters", "alice example", 0): _search([character_search]),
        ("GET", "/v0/characters/22", "", 0): character_detail,
    }
    transport = FixtureTransport(responses)
    report = _build(tmp_path, targets, transport, expected=2)

    with Path(report["output"]["path"]).open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = {row["tag"]: row for row in csv.DictReader(handle)}
    assert set(rows) == {"sample_work_(anime)", "alice_example_(sample_work)"}
    subject_row = rows["sample_work_(anime)"]
    assert subject_row["translation_cn"] == "示例作品"
    assert subject_row["match_field"] == "infobox:别名/罗马字"
    assert subject_row["translation_scope"] == "name_head_only"
    assert subject_row["requires_qualifier_reconstruction"] == "yes"
    character_row = rows["alice_example_(sample_work)"]
    assert character_row["translation_cn"] == "爱丽丝"
    assert character_row["translation_cn"] == "爱丽丝"  # no invented work qualifier
    assert character_row["bangumi_url"] == "https://bgm.tv/character/22"
    assert character_row["match_field"] == "infobox:别名/罗马字"
    assert ("GET", "/v0/characters/22", "", 0) in transport.requests
    assert report["results"]["hard_exclusions"] == {
        "artist_hard_excluded": 1,
        "general_hard_excluded": 1,
    }
    assert report["database_mutated"] is False


def test_ambiguity_and_missing_chinese_are_rejected(tmp_path: Path):
    targets = tmp_path / "targets.csv"
    _write_targets(
        targets,
        [
            {"rank": 1, "tag": "ambiguous_work", "category": 3, "category_name": "copyright", "post_count": 40},
            {"rank": 2, "tag": "latin_only_work", "category": 3, "category_name": "copyright", "post_count": 30},
            {"rank": 3, "tag": "same_character", "category": 4, "category_name": "character", "post_count": 20},
            {"rank": 4, "tag": "no_cn_character", "category": 4, "category_name": "character", "post_count": 10},
        ],
    )
    responses = {
        ("POST", "/v0/search/subjects", "ambiguous work", 0): _search(
            [
                {"id": 1, "name": "Ambiguous Work", "name_cn": "作品甲", "infobox": []},
                {"id": 2, "name": "Ambiguous Work", "name_cn": "作品乙", "infobox": []},
            ]
        ),
        ("POST", "/v0/search/subjects", "latin only work", 0): _search(
            [{"id": 3, "name": "Latin Only Work", "name_cn": "Latin", "infobox": []}]
        ),
        ("POST", "/v0/search/characters", "same character", 0): _search(
            [_character(4, "Same Character", "同名甲"), _character(5, "Same Character", "同名乙")]
        ),
        ("GET", "/v0/characters/4", "", 0): _character(4, "Same Character", "同名甲"),
        ("GET", "/v0/characters/5", "", 0): _character(5, "Same Character", "同名乙"),
        ("POST", "/v0/search/characters", "no cn character", 0): _search(
            [_character(6, "No Cn Character")]
        ),
        ("GET", "/v0/characters/6", "", 0): _character(6, "No Cn Character"),
    }
    report = _build(tmp_path, targets, FixtureTransport(responses), expected=4)
    assert report["results"]["candidate_rows"] == 0
    assert report["results"]["decisions"] == {
        "ambiguous_exact_entity_match": 2,
        "exact_entity_without_simplified_chinese": 2,
    }
    assert {row["tag"] for row in report["rejections"]} == {
        "ambiguous_work",
        "latin_only_work",
        "same_character",
        "no_cn_character",
    }


def test_raw_jsonl_cache_resumes_after_interruption(tmp_path: Path):
    targets = tmp_path / "targets.csv"
    _write_targets(
        targets,
        [
            {"rank": 1, "tag": "first_work", "category": 3, "category_name": "copyright", "post_count": 2},
            {"rank": 2, "tag": "second_work", "category": 3, "category_name": "copyright", "post_count": 1},
        ],
    )
    first_entity = {"id": 10, "name": "First Work", "name_cn": "第一作品", "infobox": []}
    second_entity = {"id": 20, "name": "Second Work", "name_cn": "第二作品", "infobox": []}
    responses = {
        ("POST", "/v0/search/subjects", "first work", 0): _search([first_entity]),
        ("POST", "/v0/search/subjects", "second work", 0): _search([second_entity]),
    }
    interrupted = FixtureTransport(
        responses,
        fail_key=("POST", "/v0/search/subjects", "second work", 0),
    )
    with pytest.raises(fetcher.BangumiFetchError, match="fixture interruption"):
        _build(tmp_path, targets, interrupted, name="first", expected=2)
    raw = tmp_path / "raw.jsonl"
    assert len(raw.read_text(encoding="utf-8").splitlines()) == 1
    with raw.open("a", encoding="utf-8") as handle:
        handle.write("{truncated\n")

    resumed = FixtureTransport(responses)
    report = _build(tmp_path, targets, resumed, name="second", expected=2)
    assert resumed.requests == [
        ("POST", "/v0/search/subjects", "second work", 0)
    ]
    assert report["cache"]["cache_hits"] == 1
    assert report["cache"]["network_requests"] == 1
    assert report["cache"]["invalid_cache_lines_ignored"] == 1
    assert report["results"]["candidate_rows"] == 2


def test_user_agent_and_output_overwrite_guards(tmp_path: Path):
    with pytest.raises(fetcher.BangumiFetchError, match="User-Agent"):
        fetcher.HttpTransport(user_agent="")
    targets = tmp_path / "targets.csv"
    _write_targets(
        targets,
        [{"rank": 1, "tag": "work", "category": 3, "category_name": "copyright", "post_count": 1}],
    )
    output = tmp_path / "candidates.csv"
    output.write_text("sentinel", encoding="utf-8")
    with pytest.raises(fetcher.BangumiFetchError, match="refusing to overwrite"):
        fetcher.fetch_bangumi_candidates(
            targets_path=targets,
            candidates_output_path=output,
            raw_cache_path=tmp_path / "raw.jsonl",
            report_path=tmp_path / "report.json",
            transport=FixtureTransport({}),
            expected_eligible_count=1,
        )
    assert output.read_text(encoding="utf-8") == "sentinel"
    assert not (tmp_path / "report.json").exists()


def test_http_transport_retries_remote_disconnect(monkeypatch):
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"total":0,"data":[]}'

    def fake_urlopen(_request, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            raise http.client.RemoteDisconnected("fixture disconnect")
        return Response()

    monkeypatch.setattr(fetcher.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(fetcher.time, "sleep", lambda _seconds: None)
    transport = fetcher.HttpTransport(
        user_agent="fixture/1.0 (test)", min_interval=0, timeout=3, max_retries=1
    )
    result = transport.request_json(
        "POST", "/v0/search/subjects", query={"limit": 1}, body={"keyword": "x"}
    )
    assert result == {"total": 0, "data": []}
    assert calls == [3.0, 3.0]
