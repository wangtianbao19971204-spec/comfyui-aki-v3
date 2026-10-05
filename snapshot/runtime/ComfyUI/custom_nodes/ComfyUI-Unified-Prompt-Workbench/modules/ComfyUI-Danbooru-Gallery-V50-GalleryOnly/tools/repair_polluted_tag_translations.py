#!/usr/bin/env python3
"""Audit and conservatively clear obviously polluted non-artist translations.

Safety properties:

* ``--db`` is mandatory and dry-run is the default.
* Applying to the plugin's live database needs both ``--apply`` and
  ``--allow-live-db``.  A staging/custom database only needs ``--apply``.
* Apply mode creates and verifies an online SQLite backup before taking a
  write lock, then records every cleared value in ``tag_translation_history``.
* Artist rows are outside this tool's scope; use ``repair_artist_translations``.
* A Latin-only value is not bad by itself.  Brands/acronyms such as VOCALOID,
  BDSM and JOJO remain untouched unless another explicit corruption rule fires.
* Han translations whose qualifier-parenthesis count differs are audit-only.

Automatic clearing is limited to control characters, Kana, Hangul, an exact
unresolved tag string containing underscore-plus-parentheses, an unrelated
translation that resolves exactly to a different live tag, or a small explicit
allow-list of independently verified cross-title collisions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import unicodedata
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIVE_DB = (PLUGIN_ROOT / "py" / "shared" / "data" / "tags_cache.db").resolve()

ARTIST_CATEGORY = 1
CHANGE_TYPE = "clear_polluted_translation"
MAX_SAMPLES = 50

_WHITESPACE_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_HAN_RE = re.compile(
    "[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
    "\U00020000-\U0002a6df\U0002a700-\U0002b73f]"
)
# Letter/iteration/prolongation ranges, deliberately excluding U+30FB KATAKANA
# MIDDLE DOT.  Chinese name translations commonly use ``・`` as a separator;
# punctuation alone is not evidence that the value is Japanese text.
_KANA_RE = re.compile(
    r"[\u3041-\u3096\u309d-\u309f\u30a1-\u30fa\u30fc-\u30ff"
    r"\u31f0-\u31ff\uff66-\uff9f]"
)
_HANGUL_RE = re.compile(r"[\u1100-\u11ff\u3130-\u318f\uac00-\ud7af]")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_WEAK_TOKENS = frozenset(
    ("a", "an", "and", "character", "for", "from", "in", "no", "of", "on", "series", "the", "to", "ver", "version", "with")
)

# Exact, independently verified corrections only.  These pairs are deliberately
# keyed by both the canonical tag and the bad value, so a future legitimate
# translation can never be cleared merely because its tag appears here.
_KNOWN_CROSS_TITLE_COLLISIONS = frozenset(
    {
        (
            "august_von_parseval_(azur_lane)",
            "八月冯帕斯瓦尔（蔚蓝车道）",
        ),
        (
            "august_von_parseval_(the_conquered_unhulde)_(azur_lane)",
            "august_von_parseval（被征服的_unhulde）（蔚蓝车道）",
        ),
        ("blue_poison_(arknights)", "蓝色毒药（方舟）"),
        (
            "blue_poison_(shoal_beat)_(arknights)",
            "蓝色毒药_(shoal_beat)_(arknights)",
        ),
        ("chihaya_anon", "千早爱音（偶像大师）"),
        ("cure_dream", "菱川六花（光之美少女）"),
        ("daiba_nana", "大场奈奈（偶像大师 百万现场）"),
        ("dendra_(pokemon)", "丹帝（宝可梦）"),
        ("dusk_(arknights)", "黄昏（方舟）"),
        (
            "dusk_(everything_is_a_miracle)_(arknights)",
            "黄昏（一切都是奇迹）（明日方舟）",
        ),
        ("feater_(arknights)", "羽毛（方舟）"),
        ("fujima_sakura", "藤间樱（偶像大师 闪耀色彩）"),
        ("friedrich_der_grosse_(azur_lane)", "Friedrich_der_Grosse_(蔚蓝海岸)"),
        ("graf_eisen", "维塔（魔法少女奈叶）"),
        ("honolulu_(summer_accident?!)_(azur_lane)", "檀香山（夏季事故？！）（蔚蓝车道）"),
        ("hung_(arknights)", "挂（方舟）"),
        ("jervis_(kancolle)", "杰维斯（拳皇）"),
        ("kaban_(kemono_friends)", "薮猫（兽娘动物园）"),
        ("kagamine_rin_(append)", "镜音连-Append（Vocaloid）"),
        ("kazuha's_friend_(genshin_impact)", "枫原万叶（原神）"),
        ("klaudia_valentz", "科洛蒂娅·巴兰茨（碧蓝航线）"),
        ("kokoro_(hakui_koyori)", "博衣小夜璃（Hololive）"),
        ("lapis_lazuli_(houseki_no_kuni)", "磷叶石（宝石之国）"),
        ("le_malin_(sleepy_sunday)_(azur_lane)", "le_malin（沉睡的星期天）（蔚蓝车道）"),
        ("le_temeraire_(azur_lane)", "le_temeraire_(蔚蓝海岸)"),
        ("lyn_(blade_&_soul)", "剑灵"),
        ("lyra_(pokemon)", "莉拉（宝可梦）"),
        ("maestrale_(kancolle)", "东北风（舰队Collection）"),
        ("miriam_(pokemon)", "迷布莉姆（宝可梦）"),
        ("mococo_abyssgard", "莫可可深渊花园（命运方舟）"),
        (
            "mococo_abyssgard_(1st_costume)",
            "莫可可深渊花园（初始服装）（命运方舟）",
        ),
        ("momo_(nikki)", "莫莫（NIKKE: 胜利女神）"),
        ("mutsu-no-kami_yoshiyuki", "陆奥守吉行（碧蓝幻想）"),
        ("ne-class_heavy_cruiser", "NE级重巡洋舰（碧蓝航线）"),
        (
            "new_jersey_(exhilarating_steps!)_(azur_lane)",
            "新泽西（令人振奋的步伐！）（蔚蓝泳道）",
        ),
        ("one_piece", "一拳超人"),
        ("prinz_eugen_(final_lap)_(azur_lane)", "欧根亲王（最后一圈）（蔚蓝车道）"),
        ("raora_panthera", "拉欧拉·潘特拉(（Arknights）"),
        ("rika_(pokemon)", "莉佳（宝可梦）"),
        ("rukkhadevata_(genshin_impact)", "流浪者（原神）"),
        ("saint-louis_(azur_lane)", "圣路易斯"),
        ("serena_(pokemon)", "小遥（宝可梦）"),
        (
            "shizuka_rin_(1st_costume)",
            "静香凛（第一套服装）（偶像大师 闪耀色彩）",
        ),
        ("takasaki_yu", "高咲侑（偶像大师 Shiny Colors）"),
        ("todo_yurika", "藤堂百合香（偶像大师）"),
        ("toyama_kasumi", "户山香橙（偶像大师 闪耀色彩）"),
        ("tsukimura_temari", "月村手毬（魔法少女奈叶）"),
        ("ulrich_von_hutten_(azur_lane)", "ulrich_von_hutten（蔚蓝海岸）"),
        ("utage_(arknights)", "使用_(arknights)"),
        ("vittorio_veneto_(azur_lane)", "维托里奥·威尼托（蔚蓝海岸）"),
        ("white_heart_(neptunia)", "白心（明日方舟）"),
        ("white_len_(tsukihime)", "白莲（明日方舟）"),
        ("wild_tiger", "白虎（兽娘动物园）"),
        ("swire_(arknights)", "太古_(arknights)"),
        ("xiao_(genshin_impact)", "魈_(原神冲击)"),
    }
)


class PollutionRepairError(RuntimeError):
    """Raised when audit or repair cannot be completed safely."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _paths_refer_to_same_file(left: Path, right: Path) -> bool:
    left = Path(left).expanduser().resolve()
    right = Path(right).expanduser().resolve()
    if str(left).casefold() == str(right).casefold():
        return True
    try:
        return left.exists() and right.exists() and os.path.samefile(left, right)
    except OSError:
        return False


def _validate_distinct_paths(named_paths: Sequence[Tuple[str, Path]]) -> None:
    resolved = [(name, Path(path).expanduser().resolve()) for name, path in named_paths]
    for index, (left_name, left_path) in enumerate(resolved):
        for right_name, right_path in resolved[index + 1 :]:
            if _paths_refer_to_same_file(left_path, right_path):
                if "database" in {left_name, right_name}:
                    artifact_name = (
                        right_name if left_name == "database" else left_name
                    )
                    raise PollutionRepairError(
                        "{} path resolves to target database or an existing hard link".format(
                            artifact_name
                        )
                    )
                raise PollutionRepairError(
                    "{} and {} must be distinct files "
                    "(resolved path/hard-link collision)".format(left_name, right_name)
                )


def _normalized_tag(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip().casefold()
    return _WHITESPACE_RE.sub("_", value)


def _normalized_text(value: object) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).strip()
    return _WHITESPACE_RE.sub(" ", value)


_NORMALIZED_KNOWN_CROSS_TITLE_COLLISIONS = frozenset(
    (_normalized_tag(tag), _normalized_text(translation))
    for tag, translation in _KNOWN_CROSS_TITLE_COLLISIONS
)


def _is_known_cross_title_collision(tag: object, translation: object) -> bool:
    return (
        _normalized_tag(tag),
        _normalized_text(translation),
    ) in _NORMALIZED_KNOWN_CROSS_TITLE_COLLISIONS


def _meaningful_tokens(tag: str) -> Set[str]:
    return {
        token
        for token in _TOKEN_RE.findall(tag.casefold())
        if len(token) >= 2 and token not in _WEAK_TOKENS
    }


def _tags_related(source: str, target: str) -> bool:
    source_tokens = _meaningful_tokens(source)
    target_tokens = _meaningful_tokens(target)
    if source_tokens and target_tokens and source_tokens.intersection(target_tokens):
        return True
    source_without_qualifier = source.split("_(", 1)[0]
    target_without_qualifier = target.split("_(", 1)[0]
    return bool(source_without_qualifier) and source_without_qualifier == target_without_qualifier


def _readonly_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _integrity_result(connection: sqlite3.Connection) -> str:
    return "\n".join(str(row[0]) for row in connection.execute("PRAGMA integrity_check"))


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?", (name,)
    ).fetchone() is not None


def _validate_schema(connection: sqlite3.Connection) -> None:
    columns = {str(row[1]) for row in connection.execute("PRAGMA table_info(hot_tags)")}
    missing = sorted({"tag", "category", "translation_cn"} - columns)
    if missing:
        raise PollutionRepairError(
            "hot_tags is missing required columns: {}".format(", ".join(missing))
        )
    fts_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='hot_tags_fts'"
    ).fetchone()
    fts_sql = str(fts_row[0] or "") if fts_row else ""
    if "VIRTUAL TABLE" not in fts_sql.upper() or "FTS5" not in fts_sql.upper():
        raise PollutionRepairError("hot_tags_fts is missing or is not FTS5")
    if not _table_exists(connection, "hot_tags_fts_docsize"):
        raise PollutionRepairError("hot_tags_fts_docsize is required for real FTS row auditing")
    if _table_exists(connection, "tag_translation_history"):
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(tag_translation_history)")
        }
        required = {
            "tag", "category", "old_translation_cn", "new_translation_cn",
            "change_type", "reason", "run_id", "changed_at_utc",
        }
        if not required.issubset(columns):
            raise PollutionRepairError(
                "existing tag_translation_history has an incompatible schema: {}".format(
                    ", ".join(sorted(required - columns))
                )
            )


def _history_count(connection: sqlite3.Connection) -> int:
    if not _table_exists(connection, "tag_translation_history"):
        return 0
    return int(connection.execute("SELECT COUNT(*) FROM tag_translation_history").fetchone()[0])


def _fingerprint_rows(rows: Iterable[Sequence[object]]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        for value in row:
            encoded = str(value if value is not None else "<NULL>").encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
    return digest.hexdigest()


def _translation_fingerprint(connection: sqlite3.Connection, *, artist: bool) -> str:
    operator = "=" if artist else "<>"
    return _fingerprint_rows(
        connection.execute(
            "SELECT tag, category, translation_cn FROM hot_tags "
            "WHERE category {} ? AND translation_cn IS NOT NULL ORDER BY tag".format(operator),
            (ARTIST_CATEGORY,),
        )
    )


def _analysis_fingerprint(clear_rows: Sequence[Mapping[str, object]]) -> str:
    payload = [
        {
            "tag": row["tag"],
            "category": row["category"],
            "translation_cn": row["translation_cn"],
            "clear_reasons": row["clear_reasons"],
        }
        for row in clear_rows
    ]
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _parenthesis_shape(value: str) -> Tuple[int, int]:
    normalized = unicodedata.normalize("NFKC", value)
    return normalized.count("("), normalized.count(")")


def analyze_translations(connection: sqlite3.Connection) -> Dict[str, object]:
    """Classify current non-artist translations without modifying SQLite."""

    lookup: MutableMapping[str, List[str]] = defaultdict(list)
    for (tag,) in connection.execute("SELECT tag FROM hot_tags ORDER BY tag"):
        lookup[_normalized_tag(tag)].append(str(tag))

    clear_rows: List[Dict[str, object]] = []
    audit_rows: List[Dict[str, object]] = []
    preserved_non_han: List[Dict[str, object]] = []
    clear_reason_counts = Counter()
    audit_reason_counts = Counter()
    scanned = 0

    cursor = connection.execute(
        "SELECT tag, category, translation_cn FROM hot_tags "
        "WHERE category <> ? AND NULLIF(TRIM(COALESCE(translation_cn,'')), '') IS NOT NULL "
        "ORDER BY tag",
        (ARTIST_CATEGORY,),
    )
    for tag_value, category_value, translation_value in cursor:
        scanned += 1
        tag = str(tag_value)
        category = int(category_value)
        translation = str(translation_value)
        normalized_tag = _normalized_tag(tag)
        normalized_translation_as_tag = _normalized_tag(translation)
        normalized_translation = _normalized_text(translation)

        clear_reasons: List[str] = []
        audit_reasons: List[str] = []
        related_targets: List[str] = []
        unrelated_targets: List[str] = []

        if _CONTROL_RE.search(translation):
            clear_reasons.append("control_character")
        if _is_known_cross_title_collision(normalized_tag, normalized_translation):
            clear_reasons.append("known_cross_title_collision")
        if _KANA_RE.search(translation):
            clear_reasons.append("contains_kana")
        if _HANGUL_RE.search(translation):
            clear_reasons.append("contains_hangul")

        normalized_for_syntax = unicodedata.normalize("NFKC", translation)
        if (
            normalized_translation_as_tag == normalized_tag
            and "_" in normalized_for_syntax
            and "(" in normalized_for_syntax
            and ")" in normalized_for_syntax
        ):
            clear_reasons.append("unresolved_exact_tag_syntax")

        target_tags = [
            target for target in lookup.get(normalized_translation_as_tag, [])
            if _normalized_tag(target) != normalized_tag
        ]
        for target in target_tags:
            if _tags_related(normalized_tag, _normalized_tag(target)):
                related_targets.append(target)
            else:
                unrelated_targets.append(target)
        # Any related exact target makes this ambiguous rather than obvious;
        # e.g. vocaloid_(software) -> VOCALOID or a qualified tag -> base tag.
        if unrelated_targets and not related_targets:
            clear_reasons.append("translation_equals_unrelated_live_tag")
        elif related_targets:
            audit_reasons.append("translation_equals_related_live_tag")

        if _HAN_RE.search(normalized_translation):
            source_shape = _parenthesis_shape(tag)
            translation_shape = _parenthesis_shape(translation)
            if source_shape != translation_shape:
                audit_reasons.append("han_parenthesis_shape_mismatch")

        row = {
            "tag": tag,
            "category": category,
            "translation_cn": translation,
            "clear_reasons": sorted(set(clear_reasons)),
            "audit_reasons": sorted(set(audit_reasons)),
            "related_live_tags": sorted(set(related_targets)),
            "unrelated_live_tags": sorted(set(unrelated_targets)),
        }
        if clear_reasons:
            clear_rows.append(row)
            clear_reason_counts.update(set(clear_reasons))
        if audit_reasons:
            audit_rows.append(row)
            audit_reason_counts.update(set(audit_reasons))
        if (
            not clear_reasons
            and not _HAN_RE.search(normalized_translation)
            and not _KANA_RE.search(normalized_translation)
            and not _HANGUL_RE.search(normalized_translation)
        ):
            preserved_non_han.append(row)

    clear_rows.sort(key=lambda row: (str(row["tag"]), int(row["category"])))
    audit_rows.sort(key=lambda row: (str(row["tag"]), int(row["category"])))
    preserved_non_han.sort(key=lambda row: (str(row["tag"]), int(row["category"])))
    return {
        "scanned_nonartist_translated_rows": scanned,
        "clear_rows": clear_rows,
        "audit_rows": audit_rows,
        "preserved_non_han_rows": preserved_non_han,
        "clear_reason_counts": dict(sorted(clear_reason_counts.items())),
        "audit_reason_counts": dict(sorted(audit_reason_counts.items())),
        "analysis_sha256": _analysis_fingerprint(clear_rows),
    }


def _collect_metrics(connection: sqlite3.Connection) -> Dict[str, object]:
    total = int(connection.execute("SELECT COUNT(*) FROM hot_tags").fetchone()[0])
    translated = int(
        connection.execute(
            "SELECT COUNT(*) FROM hot_tags WHERE NULLIF(TRIM(COALESCE(translation_cn,'')),'') IS NOT NULL"
        ).fetchone()[0]
    )
    nonartist_values = int(
        connection.execute(
            "SELECT COUNT(*) FROM hot_tags WHERE category<>? AND translation_cn IS NOT NULL",
            (ARTIST_CATEGORY,),
        ).fetchone()[0]
    )
    artist_values = int(
        connection.execute(
            "SELECT COUNT(*) FROM hot_tags WHERE category=? AND translation_cn IS NOT NULL",
            (ARTIST_CATEGORY,),
        ).fetchone()[0]
    )
    fts_rows = int(connection.execute("SELECT COUNT(*) FROM hot_tags_fts_docsize").fetchone()[0])
    return {
        "total_tags": total,
        "translated_tags": translated,
        "nonartist_translation_values": nonartist_values,
        "artist_translation_values": artist_values,
        "nonartist_translation_values_sha256": _translation_fingerprint(connection, artist=False),
        "artist_translation_values_sha256": _translation_fingerprint(connection, artist=True),
        "history_rows": _history_count(connection),
        "fts_rows": fts_rows,
        "fts_count_source": "hot_tags_fts_docsize",
        "fts_matches_hot_tags": fts_rows == total,
        "integrity_check": _integrity_result(connection),
    }


def _inspect_database(path: Path) -> Tuple[Dict[str, object], Dict[str, object]]:
    connection = _readonly_connection(path)
    try:
        _validate_schema(connection)
        metrics = _collect_metrics(connection)
        if metrics["integrity_check"] != "ok":
            raise PollutionRepairError(
                "target integrity_check failed: {}".format(metrics["integrity_check"])
            )
        analysis = analyze_translations(connection)
        return metrics, analysis
    finally:
        connection.close()


def _unique_backup_path(
    db_path: Path,
    backup_dir: Optional[Path],
    run_id: str,
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> Path:
    directory = (backup_dir or db_path.parent).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = db_path.suffix or ".sqlite"
    stem = "{}.pre_polluted_translation_repair_{}_{}".format(
        db_path.stem, timestamp, run_id[-8:]
    )
    counter = 0
    while True:
        candidate = directory / (
            (stem + suffix)
            if not counter
            else "{}_{}{}".format(stem, counter, suffix)
        )
        if any(
            _paths_refer_to_same_file(candidate, protected)
            for _name, protected in protected_paths
        ):
            counter += 1
            continue
        try:
            descriptor = os.open(
                str(candidate), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            os.close(descriptor)
        except FileExistsError:
            counter += 1
            continue
        try:
            _validate_distinct_paths([("backup", candidate), *protected_paths])
        except Exception:
            candidate.unlink(missing_ok=True)
            raise
        return candidate


def _create_verified_backup(
    db_path: Path,
    backup_path: Path,
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> Dict[str, str]:
    _validate_distinct_paths(
        [("backup", backup_path), ("database", db_path), *protected_paths]
    )
    source = _readonly_connection(db_path)
    try:
        destination = sqlite3.connect(str(backup_path), timeout=30.0)
        try:
            source.backup(destination)
            destination.commit()
            integrity = _integrity_result(destination)
            if integrity != "ok":
                raise PollutionRepairError("backup integrity_check failed: {}".format(integrity))
        finally:
            destination.close()
    except Exception:
        try:
            backup_path.unlink()
        except OSError:
            pass
        raise
    finally:
        source.close()
    return {"path": str(backup_path), "sha256": _sha256(backup_path), "integrity_check": "ok"}


def _create_history_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS tag_translation_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag TEXT NOT NULL,
            category INTEGER NOT NULL,
            old_translation_cn TEXT,
            new_translation_cn TEXT,
            change_type TEXT NOT NULL,
            reason TEXT NOT NULL,
            run_id TEXT NOT NULL,
            changed_at_utc TEXT NOT NULL,
            UNIQUE(run_id, tag, change_type)
        )
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tag_translation_history_tag ON tag_translation_history(tag)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_tag_translation_history_run ON tag_translation_history(run_id)"
    )


def _apply_repair(
    db_path: Path,
    *,
    run_id: str,
    changed_at_utc: str,
    expected_metrics: Mapping[str, object],
    expected_analysis_sha256: str,
) -> Dict[str, int]:
    connection = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    try:
        _validate_schema(connection)
        if _integrity_result(connection) != "ok":
            raise PollutionRepairError("target integrity_check failed immediately before apply")
        connection.execute("BEGIN IMMEDIATE")
        try:
            current_metrics = _collect_metrics(connection)
            if current_metrics["nonartist_translation_values_sha256"] != expected_metrics[
                "nonartist_translation_values_sha256"
            ]:
                raise PollutionRepairError(
                    "target non-artist translations changed after backup; refusing to apply"
                )
            if current_metrics["artist_translation_values_sha256"] != expected_metrics[
                "artist_translation_values_sha256"
            ]:
                raise PollutionRepairError(
                    "target artist translations changed after backup; refusing to apply"
                )
            analysis = analyze_translations(connection)
            if analysis["analysis_sha256"] != expected_analysis_sha256:
                raise PollutionRepairError("pollution plan changed after backup; refusing to apply")

            clear_rows = list(analysis["clear_rows"])
            _create_history_table(connection)
            history_inserted = 0
            cleared = 0
            for row in clear_rows:
                reason = "automatic_clear:" + ",".join(row["clear_reasons"])
                connection.execute(
                    """
                    INSERT INTO tag_translation_history(
                        tag, category, old_translation_cn, new_translation_cn,
                        change_type, reason, run_id, changed_at_utc
                    ) VALUES (?, ?, ?, NULL, ?, ?, ?, ?)
                    """,
                    (
                        row["tag"], row["category"], row["translation_cn"],
                        CHANGE_TYPE, reason, run_id, changed_at_utc,
                    ),
                )
                history_inserted += 1
                cursor = connection.execute(
                    "UPDATE hot_tags SET translation_cn=NULL "
                    "WHERE tag=? AND category=? AND translation_cn=?",
                    (row["tag"], row["category"], row["translation_cn"]),
                )
                if int(cursor.rowcount) != 1:
                    raise PollutionRepairError(
                        "guarded update did not affect exactly one row: {}".format(row["tag"])
                    )
                cleared += 1

            connection.execute("INSERT INTO hot_tags_fts(hot_tags_fts) VALUES('rebuild')")
            after_metrics = _collect_metrics(connection)
            after_analysis = analyze_translations(connection)
            if after_analysis["clear_rows"]:
                raise PollutionRepairError("clearable polluted translations remain after repair")
            if after_metrics["total_tags"] != expected_metrics["total_tags"]:
                raise PollutionRepairError("hot_tags row count changed during repair")
            if after_metrics["artist_translation_values_sha256"] != expected_metrics[
                "artist_translation_values_sha256"
            ]:
                raise PollutionRepairError("artist translations changed during non-artist repair")
            if not after_metrics["fts_matches_hot_tags"]:
                raise PollutionRepairError("FTS rows do not match hot_tags after rebuild")
            if after_metrics["integrity_check"] != "ok":
                raise PollutionRepairError(
                    "post-repair integrity_check failed: {}".format(after_metrics["integrity_check"])
                )
            if history_inserted != cleared or cleared != len(clear_rows):
                raise PollutionRepairError("history/update count mismatch")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    finally:
        connection.close()
    return {
        "history_rows_inserted": history_inserted,
        "translation_values_cleared": cleared,
        "fts_rows_rebuilt": int(after_metrics["fts_rows"]),
    }


def _public_analysis(analysis: Mapping[str, object]) -> Dict[str, object]:
    clear_rows = list(analysis["clear_rows"])
    audit_rows = list(analysis["audit_rows"])
    preserved = list(analysis["preserved_non_han_rows"])
    return {
        "scanned_nonartist_translated_rows": analysis["scanned_nonartist_translated_rows"],
        "clear_candidates": len(clear_rows),
        "clear_reason_counts": analysis["clear_reason_counts"],
        "clear_samples": clear_rows[:MAX_SAMPLES],
        "audit_only_rows": len(audit_rows),
        "audit_reason_counts": analysis["audit_reason_counts"],
        "audit_samples": audit_rows[:MAX_SAMPLES],
        "preserved_non_han_rows": len(preserved),
        "preserved_non_han_samples": preserved[:MAX_SAMPLES],
        "analysis_sha256": analysis["analysis_sha256"],
    }


def repair_database(
    db_path: Path,
    *,
    apply: bool = False,
    backup_dir: Optional[Path] = None,
    allow_live_db: bool = False,
    review_path: Optional[Path] = None,
    report_path: Optional[Path] = None,
) -> Dict[str, object]:
    db_path = Path(db_path).resolve()
    if not db_path.is_file():
        raise PollutionRepairError("database does not exist or is not a file: {}".format(db_path))
    if apply and db_path == DEFAULT_LIVE_DB and not allow_live_db:
        raise PollutionRepairError(
            "refusing to apply to the plugin live database without allow_live_db=True"
        )

    named_artifacts: List[Tuple[str, Path]] = []
    if review_path is not None:
        review_path = Path(review_path).resolve()
        named_artifacts.append(("review", review_path))
    if report_path is not None:
        report_path = Path(report_path).resolve()
        named_artifacts.append(("report", report_path))
    _validate_distinct_paths([("database", db_path), *named_artifacts])

    started_at = _utc_now()
    run_id = "pollution-repair-{}".format(uuid.uuid4().hex)
    before, analysis = _inspect_database(db_path)
    if review_path is not None:
        _atomic_write_review(
            review_path,
            analysis,
            protected_paths=[
                ("database", db_path),
                *[(name, path) for name, path in named_artifacts if name != "review"],
            ],
        )
    public_analysis = _public_analysis(analysis)
    report: Dict[str, object] = {
        "tool": "repair_polluted_tag_translations",
        "mode": "apply" if apply else "dry-run",
        "applied": False,
        "db_path": str(db_path),
        "is_plugin_live_db": db_path == DEFAULT_LIVE_DB,
        "live_apply_guard": True,
        "run_id": run_id,
        "started_at_utc": started_at,
        "backup": None,
        "policy": {
            "artist_rows_in_scope": False,
            "latin_only_is_clear_reason": False,
            "han_parenthesis_mismatch_action": "audit_only",
            "fuzzy_tag_matching": False,
        },
        "before": before,
        "analysis": public_analysis,
        "planned_changes": {
            "history_rows_to_insert": public_analysis["clear_candidates"],
            "translation_values_to_clear": public_analysis["clear_candidates"],
            "fts_rows_to_rebuild": before["total_tags"],
        },
    }
    if not apply:
        projected = dict(before)
        projected["translated_tags"] = int(before["translated_tags"]) - int(
            public_analysis["clear_candidates"]
        )
        projected["nonartist_translation_values"] = int(
            before["nonartist_translation_values"]
        ) - int(public_analysis["clear_candidates"])
        projected["history_rows"] = int(before["history_rows"]) + int(
            public_analysis["clear_candidates"]
        )
        projected["fts_rows"] = before["total_tags"]
        projected["fts_matches_hot_tags"] = True
        projected["integrity_check"] = "not_run_dry_run_projection"
        report["changes"] = {
            "history_rows_inserted": 0,
            "translation_values_cleared": 0,
            "fts_rows_rebuilt": 0,
        }
        report["after"] = projected
        report["after_is_projection"] = True
        report["integrity"] = {"before": "ok", "backup": None, "after": None}
        report["completed_at_utc"] = _utc_now()
        return report

    backup_protected = [("database", db_path), *named_artifacts]
    backup_path = _unique_backup_path(
        db_path, backup_dir, run_id, protected_paths=backup_protected
    )
    backup = _create_verified_backup(
        db_path, backup_path, protected_paths=named_artifacts
    )
    report["backup"] = backup
    changes = _apply_repair(
        db_path,
        run_id=run_id,
        changed_at_utc=started_at,
        expected_metrics=before,
        expected_analysis_sha256=str(analysis["analysis_sha256"]),
    )
    after, after_analysis = _inspect_database(db_path)
    if after_analysis["clear_rows"]:
        raise PollutionRepairError("verification failed: clearable translations remain")
    if after["total_tags"] != before["total_tags"]:
        raise PollutionRepairError("verification failed: hot_tags row count changed")
    if after["artist_translation_values_sha256"] != before["artist_translation_values_sha256"]:
        raise PollutionRepairError("verification failed: artist rows changed")
    if not after["fts_matches_hot_tags"]:
        raise PollutionRepairError("verification failed: FTS row count differs from hot_tags")

    report["applied"] = True
    report["changes"] = changes
    report["after"] = after
    report["after_analysis"] = _public_analysis(after_analysis)
    report["after_is_projection"] = False
    report["integrity"] = {"before": "ok", "backup": "ok", "after": "ok"}
    report["completed_at_utc"] = _utc_now()
    return report


def _atomic_write_json(
    path: Path,
    payload: Mapping[str, object],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _validate_distinct_paths([("report", path), *protected_paths])
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _atomic_write_review(
    path: Path,
    analysis: Mapping[str, object],
    *,
    protected_paths: Sequence[Tuple[str, Path]] = (),
) -> None:
    rows: List[Dict[str, object]] = []
    for action, key in (
        ("clear", "clear_rows"),
        ("audit_only", "audit_rows"),
        ("preserve_non_han", "preserved_non_han_rows"),
    ):
        for source in analysis[key]:
            row = dict(source)
            row["action"] = action
            rows.append(row)
    rows.sort(key=lambda row: (str(row["action"]), str(row["tag"])))
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=path.name + ".", suffix=".tmp", delete=False,
        ) as handle:
            temporary = Path(handle.name)
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        _validate_distinct_paths([("review", path), *protected_paths])
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="explicit SQLite database to audit")
    parser.add_argument("--apply", action="store_true", help="backup and apply (default: dry-run)")
    parser.add_argument(
        "--allow-live-db", action="store_true",
        help="second confirmation required only when applying to the plugin live database",
    )
    parser.add_argument("--backup-dir", type=Path, help="backup destination used only with --apply")
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--review-jsonl", type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    try:
        db_path = Path(args.db).resolve()
        named_outputs = [
            (name, Path(path).resolve())
            for name, path in (
                ("report", args.json_report),
                ("review", args.review_jsonl),
            )
            if path is not None
        ]
        _validate_distinct_paths([("database", db_path), *named_outputs])
        report = repair_database(
            db_path,
            apply=bool(args.apply),
            backup_dir=args.backup_dir,
            allow_live_db=bool(args.allow_live_db),
            review_path=args.review_jsonl,
            report_path=args.json_report,
        )
        if args.json_report:
            backup_path = (
                Path(report["backup"]["path"])
                if isinstance(report.get("backup"), Mapping)
                else None
            )
            _atomic_write_json(
                args.json_report,
                report,
                protected_paths=[
                    ("database", db_path),
                    *(
                        [("review", Path(args.review_jsonl).resolve())]
                        if args.review_jsonl
                        else []
                    ),
                    *([("backup", backup_path)] if backup_path else []),
                ],
            )
    except Exception as exc:
        print(
            json.dumps(
                {"tool": "repair_polluted_tag_translations", "success": False, "error": str(exc)},
                ensure_ascii=False,
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
