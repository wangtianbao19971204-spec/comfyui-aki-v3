import argparse
import copy
import hashlib
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


PROMPT_SELECTOR_DIR = Path(__file__).resolve().parents[1]
PLUGIN_DIR = PROMPT_SELECTOR_DIR.parent
sys.path.insert(0, str(PROMPT_SELECTOR_DIR))

from anima_tag_classifier import (  # noqa: E402
    LEGACY_TARGETS,
    SECTION_TARGETS,
    SOURCE_ADULT_LOWER,
    SOURCE_ADULT_UPPER,
    SOURCE_REGULAR,
    load_contract,
    root_for_target,
)


ANIMA_ROOTS = (
    "Anima/姿势",
    "Anima/角色",
    "Anima/服装",
    "Anima/背景",
)

REFERENCE_SOURCES = (
    SOURCE_REGULAR,
    SOURCE_ADULT_UPPER,
    SOURCE_ADULT_LOWER,
)


# These are coherent old buckets. They may be renamed or moved as a unit only
# when the per-prompt classifier does not find a conflicting primary root.
STABLE_CATEGORY_TARGETS = {
    "Anima/背景/正常/单纯场景": "Anima/背景/正常/单纯场景",
    "Anima/背景/正常/幻想童话": "Anima/背景/正常/幻想童话",
    "Anima/背景/正常/恐怖扭曲": "Anima/背景/正常/恐怖扭曲",
    "Anima/背景/正常/室内": "Anima/背景/正常/室内",
    "Anima/背景/正常/室外": "Anima/背景/正常/室外与自然",
    "Anima/背景/正常/未来科幻": "Anima/服装/正常/幻想与主题/未来科幻",
    "Anima/背景/R18/触手": "Anima/姿势/R18/重口/异种互动/触手",
    "Anima/服装/魔法少女": "Anima/服装/正常/幻想与主题/魔法少女",
    "Anima/服装/兔女郎": "Anima/服装/正常/幻想与主题/兔女郎",
    "Anima/服装/舞娘": "Anima/服装/正常/幻想与主题/舞娘",
    "Anima/服装/泳装": "Anima/服装/R18/内衣与泳装/泳装",
    "Anima/服装/正常/常规职业": "Anima/服装/正常/制服与职业/职业制服",
    "Anima/服装/正常/冬装": "Anima/服装/正常/日常与季节/冬装",
    "Anima/服装/正常/服装组件": "Anima/服装/正常/组件与配饰",
    "Anima/服装/正常/军装": "Anima/服装/正常/制服与职业/军装",
    "Anima/服装/正常/另类服装": "Anima/服装/正常/幻想与主题/特殊服装",
    "Anima/服装/正常/日本": "Anima/服装/正常/地域与时代/日本",
    "Anima/服装/正常/日常服": "Anima/服装/正常/日常与季节/日常服",
    "Anima/服装/正常/室内服（运动服、睡衣、正常内衣等）": "Anima/服装/正常/日常与季节/室内服",
    "Anima/服装/正常/夏装": "Anima/服装/正常/日常与季节/夏装",
    "Anima/服装/正常/校服": "Anima/服装/正常/制服与职业/校服",
    "Anima/服装/正常/游戏服装": "Anima/服装/正常/幻想与主题/游戏服装",
    "Anima/服装/正常/中东": "Anima/服装/正常/地域与时代/中东",
    "Anima/服装/正常/中国": "Anima/服装/正常/地域与时代/中国",
    "Anima/服装/正常/中近世纪": "Anima/服装/正常/地域与时代/中近世纪",
    "Anima/服装/正常/中外经典": "Anima/角色/正常/种族与形态/魔物与人外",
    "Anima/服装/furry特辑": "Anima/角色/正常/种族与形态/动物娘化",
    "Anima/服装/R18/恶堕之后": "Anima/服装/R18/暴露与改造/恶堕服装",
    "Anima/服装/R18/幻想改造": "Anima/服装/R18/暴露与改造/幻想改造",
    "Anima/服装/R18/节日献礼": "Anima/姿势/R18/情境/节庆献礼",
    "Anima/服装/R18/连体胶衣胶质服装": "Anima/服装/R18/材质与紧身/连体胶衣",
    "Anima/服装/R18/赛车女郎": "Anima/服装/正常/制服与职业/运动服",
    "Anima/服装/R18/职业改造": "Anima/服装/R18/暴露与改造/职业改造",
    "Anima/角色/非常规职业": "Anima/服装/正常/制服与职业/职业制服",
    "Anima/角色/魔法特辑": "Anima/服装/正常/幻想与主题/魔法少女",
    "Anima/角色/野族传说": "Anima/服装/正常/幻想与主题/野族服装",
    "Anima/角色/运动人员": "Anima/服装/正常/制服与职业/运动服",
    "Anima/角色/正常/单机角色": "Anima/角色/正常/作品角色/单机角色",
    "Anima/角色/正常/动漫角色": "Anima/角色/正常/作品角色/动漫角色",
    "Anima/角色/正常/动物娘化": "Anima/角色/正常/种族与形态/动物娘化",
    "Anima/角色/正常/端游角色": "Anima/角色/正常/作品角色/端游角色",
    "Anima/角色/正常/类人种族": "Anima/角色/正常/种族与形态/类人种族",
    "Anima/角色/正常/明日方舟角色": "Anima/角色/正常/作品角色/手游角色",
    "Anima/角色/正常/其他手游角色": "Anima/角色/正常/作品角色/手游角色",
    "Anima/角色/正常/人工造物": "Anima/角色/正常/种族与形态/人工造物",
    "Anima/角色/正常/人物转化": "Anima/角色/正常/外观与转化/人物转化",
    "Anima/角色/正常/网络角色": "Anima/角色/正常/作品角色/网络角色",
    "Anima/角色/正常/文化作品角色": "Anima/角色/正常/作品角色/文化作品角色",
    "Anima/角色/R18/扶她": "Anima/角色/R18/成人身份/扶她",
    "Anima/角色/R18/哥布林": "Anima/姿势/R18/重口/异种互动/人形魔物",
    "Anima/角色/R18/另类捆绑": "Anima/姿势/R18/拘束/捆绑姿势",
    "Anima/角色/R18/史莱姆": "Anima/姿势/R18/重口/异种互动/史莱姆",
    "Anima/角色/R18/伪娘男娘": "Anima/角色/R18/成人身份/伪娘与男娘",
    "Anima/角色/R18/重口/兽人": "Anima/姿势/R18/重口/异种互动/人形魔物",
    "Anima/角色/R18/重口/刑罚": "Anima/姿势/R18/重口/暴力/暴虐与过激",
    "Anima/角色/R18/cosplay": "Anima/服装/R18/Cosplay与角色服装",
    "Anima/姿势/正常/多人互动": "Anima/姿势/正常/多人互动",
    "Anima/姿势/正常/情感动作": "Anima/姿势/正常/表情与情绪",
    "Anima/姿势/正常/战斗华丽": "Anima/姿势/正常/战斗与动态",
    "Anima/姿势/R18/百合": "Anima/姿势/R18/多人互动/百合",
    "Anima/姿势/R18/暴露露出": "Anima/姿势/R18/单人表现/暴露",
    "Anima/姿势/R18/背身展示": "Anima/姿势/R18/身体构图/背身",
    "Anima/姿势/R18/催眠": "Anima/姿势/R18/情境/催眠",
    "Anima/姿势/R18/调戏猥亵": "Anima/姿势/R18/双人互动/调戏与猥亵",
    "Anima/姿势/R18/多p轮奸": "Anima/姿势/R18/多人互动/多人强制",
    "Anima/姿势/R18/攻守反转特辑（四爱/男m）": "Anima/姿势/R18/双人互动/攻守反转",
    "Anima/姿势/R18/后入背后位": "Anima/姿势/R18/体位/后入与背后位",
    "Anima/姿势/R18/拘束凌辱": "Anima/姿势/R18/拘束/拘束凌辱",
    "Anima/姿势/R18/口交（类口交/颜射）": "Anima/姿势/R18/非插入互动/口交与颜射",
    "Anima/姿势/R18/口交（类口交颜射）": "Anima/姿势/R18/非插入互动/口交与颜射",
    "Anima/姿势/R18/捆绑位置": "Anima/姿势/R18/拘束/捆绑位置",
    "Anima/姿势/R18/捆绑用具": "Anima/姿势/R18/拘束/捆绑用具",
    "Anima/姿势/R18/捆绑姿势": "Anima/姿势/R18/拘束/捆绑姿势",
    "Anima/姿势/R18/露出": "Anima/姿势/R18/单人表现/暴露",
    "Anima/姿势/R18/骑乘位": "Anima/姿势/R18/体位/骑乘位",
    "Anima/姿势/R18/裙底小穴臀部": "Anima/姿势/R18/身体构图/臀裆部",
    "Anima/姿势/R18/乳交": "Anima/姿势/R18/非插入互动/乳交",
    "Anima/姿势/R18/事后": "Anima/姿势/R18/双人互动/事后",
    "Anima/姿势/R18/手交": "Anima/姿势/R18/非插入互动/手交",
    "Anima/姿势/R18/双飞多飞": "Anima/姿势/R18/多人互动/双飞与多人",
    "Anima/姿势/R18/睡奸": "Anima/姿势/R18/双人互动/睡眠侵犯",
    "Anima/姿势/R18/素股": "Anima/姿势/R18/非插入互动/身体摩擦",
    "Anima/姿势/R18/素股摩擦腋下": "Anima/姿势/R18/非插入互动/身体摩擦",
    "Anima/姿势/R18/偷窥直视": "Anima/姿势/R18/双人互动/偷窥与直视",
    "Anima/姿势/R18/腿": "Anima/姿势/R18/身体构图/腿足",
    "Anima/姿势/R18/协作侍奉": "Anima/姿势/R18/多人互动/协作侍奉",
    "Anima/姿势/R18/胁迫强制": "Anima/姿势/R18/双人互动/胁迫与强制",
    "Anima/姿势/R18/胸腹部": "Anima/姿势/R18/身体构图/胸腹部",
    "Anima/姿势/R18/隐秘处展示自拍直播": "Anima/姿势/R18/单人表现/隐秘展示与直播",
    "Anima/姿势/R18/诱惑": "Anima/姿势/R18/单人表现/诱惑",
    "Anima/姿势/R18/站立位": "Anima/姿势/R18/体位/站立位",
    "Anima/姿势/R18/正逆火车便当": "Anima/姿势/R18/体位/火车便当",
    "Anima/姿势/R18/正身位": "Anima/姿势/R18/体位/正身位",
    "Anima/姿势/R18/种付位": "Anima/姿势/R18/体位/种付位",
    "Anima/姿势/R18/重口/暴虐": "Anima/姿势/R18/重口/暴力/暴虐与过激",
    "Anima/姿势/R18/重口/虫": "Anima/姿势/R18/重口/异种互动/昆虫",
    "Anima/姿势/R18/重口/狗": "Anima/姿势/R18/重口/异种互动/兽类",
    "Anima/姿势/R18/重口/过激": "Anima/姿势/R18/重口/暴力/暴虐与过激",
    "Anima/姿势/R18/重口/机械": "Anima/姿势/R18/重口/机械",
    "Anima/姿势/R18/重口/截肢人棍": "Anima/姿势/R18/重口/暴力/截肢与人棍",
    "Anima/姿势/R18/重口/马": "Anima/姿势/R18/重口/异种互动/兽类",
    "Anima/姿势/R18/重口/排泄物": "Anima/姿势/R18/重口/排泄物",
    "Anima/姿势/R18/重口/杀害": "Anima/姿势/R18/重口/暴力/杀害",
    "Anima/姿势/R18/重口/秀色": "Anima/姿势/R18/重口/暴力/食人",
    "Anima/姿势/R18/自慰": "Anima/姿势/R18/单人表现/自慰",
    "Anima/姿势/R18/足底展示": "Anima/姿势/R18/身体构图/腿足",
    "Anima/姿势/R18/足交": "Anima/姿势/R18/非插入互动/足交",
    "Anima/姿势/R18/坐身位": "Anima/姿势/R18/体位/坐身位",
    "Anima/姿势/R18/NTR": "Anima/姿势/R18/情境/NTR",
    "Anima/姿势/R18/RBQ": "Anima/姿势/R18/拘束/肉便器",
}


MIXED_ANIMA_CATEGORIES = {
    "Anima/背景/正常/人物环境",
    "Anima/背景/R18/色色场景",
    "Anima/服装/正常/其他",
    "Anima/服装/R18/宠物调教",
    "Anima/角色/正常/人物形象",
    "Anima/角色/正常/其他",
    "Anima/角色/R18/非原创人物",
    "Anima/角色/R18/魔物娘",
    "Anima/角色/R18/其他异种",
    "Anima/角色/R18/人外",
    "Anima/角色/R18/重口",
    "Anima/姿势/R18/另类日常",
    "Anima/姿势/R18/伪娘男娘特辑",
    "Anima/姿势/R18/futa特辑",
}


OBSOLETE_EMPTY_ANIMA_CATEGORIES = {
    "Anima/姿势/NTR",
}


AUDITED_PROMPT_TARGETS = {
    # The legacy source section says "未来科幻", but the reusable content is
    # Chinese buildings, sunset and sky. Keep the reviewed semantic destination.
    "c52dce4b-e781-56d2-a240-ab8aa87f4fd2": "Anima/背景/正常/城市与日常",
}


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def normalized_source_hash(value):
    return str(value or "").strip().lower()


def source_context_from_category(category_name):
    normalized = str(category_name or "").replace("／", "/")
    for source in REFERENCE_SOURCES:
        prefix = source + "/"
        if normalized.startswith(prefix):
            return source, normalized[len(prefix):].split("/", 1)[0]
    return "", ""


def is_reference_category(category_name):
    return bool(source_context_from_category(category_name)[0])


def is_eligible_category(category_name):
    return str(category_name or "").startswith("Anima/") or is_reference_category(category_name)


def all_canonical_categories(contract):
    result = set()
    for names in contract.get("canonical_categories", {}).values():
        result.update(names)
    return result


def stable_target_for(category_name, canonical_categories):
    if category_name in canonical_categories:
        return category_name
    if category_name in ANIMA_ROOTS:
        return category_name
    if category_name in STABLE_CATEGORY_TARGETS:
        return STABLE_CATEGORY_TARGETS[category_name]
    if category_name in LEGACY_TARGETS:
        return LEGACY_TARGETS[category_name]
    source, section = source_context_from_category(category_name)
    if source and section:
        return SECTION_TARGETS.get((source, section), "")
    return ""


def review_target_for(decision, current_category, contract, mixed=False):
    review_categories = contract["non_anima_contracts"]["review_categories"]
    if decision.get("target") == review_categories[0]:
        return review_categories[0]
    if mixed or current_category in MIXED_ANIMA_CATEGORIES:
        return review_categories[1]
    return review_categories[2]


def decide_destination(decision, current_category, contract, canonical_categories):
    eligible = is_eligible_category(current_category)
    if not eligible:
        return current_category, "unrelated_category_unchanged"

    status = str(decision.get("status") or "review")
    if status == "quarantine":
        return decision["target"], "safety_quarantine"
    if status == "excluded":
        return decision["target"], "non_anima_excluded"
    audited_target = AUDITED_PROMPT_TARGETS.get(str(decision.get("prompt_id") or ""))
    if audited_target:
        return audited_target, "audited_prompt_override"
    if current_category in canonical_categories:
        return current_category, "canonical_category_preserved"
    if status == "auto":
        return decision["target"], "classifier_auto"

    fallback = stable_target_for(current_category, canonical_categories)
    if fallback:
        fallback_root = root_for_target(fallback + ("/" if fallback in ANIMA_ROOTS else ""))
        suggested_root = str(decision.get("root") or "")
        if fallback_root and suggested_root and fallback_root != suggested_root:
            if current_category.startswith("Anima/"):
                return (
                    review_target_for(decision, current_category, contract, mixed=True),
                    "stable_category_root_conflict",
                )
            return current_category, "reference_root_conflict_unchanged"
        reason = "stable_anima_category" if current_category.startswith("Anima/") else "stable_reference_section"
        return fallback, reason

    if current_category.startswith("Anima/"):
        return (
            review_target_for(decision, current_category, contract, mixed=True),
            "mixed_or_low_confidence_anima",
        )
    return current_category, "reference_review_unchanged"


def deterministic_category_id(name):
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
    return f"cat-anima-{digest}"


def build_canonical_order(contract, populated_names):
    order = []
    canonical = contract.get("canonical_categories", {})
    for root_name, key in (
        ("Anima/姿势", "pose"),
        ("Anima/角色", "character"),
        ("Anima/服装", "clothing"),
        ("Anima/背景", "background"),
    ):
        order.append(root_name)
        order.extend(canonical.get(key, []))
    order = [name for name in order if name in populated_names or name in ANIMA_ROOTS]
    known = set(order)
    order.extend(sorted(name for name in populated_names if name.startswith("Anima/") and name not in known))
    return order


def build_migration(data, report, contract):
    categories = data.get("categories")
    decisions = report.get("decisions")
    if not isinstance(categories, list) or not isinstance(decisions, list):
        raise ValueError("data.json 或分类报告结构无效")

    decision_by_id = {}
    for decision in decisions:
        prompt_id = str(decision.get("prompt_id") or "")
        if not prompt_id or prompt_id in decision_by_id:
            raise ValueError(f"分类报告含空或重复 prompt_id: {prompt_id!r}")
        decision_by_id[prompt_id] = decision

    canonical_categories = all_canonical_categories(contract)
    allowed_anima_categories = canonical_categories | set(ANIMA_ROOTS)
    original_metadata = {}
    original_name_counts = Counter()
    original_prompt_ids = []
    prompt_fingerprints = {}
    buckets = defaultdict(list)
    moves = []
    reason_counts = Counter()
    moved_from_counts = Counter()
    moved_to_counts = Counter()

    for category in categories:
        category_name = str(category.get("name") or "")
        original_name_counts[category_name] += 1
        original_metadata.setdefault(category_name, category)
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            if not prompt_id:
                raise ValueError(f"分类 {category_name!r} 中有空 prompt_id")
            if prompt_id in prompt_fingerprints:
                raise ValueError(f"data.json 中有重复 prompt_id: {prompt_id}")
            original_prompt_ids.append(prompt_id)
            prompt_fingerprints[prompt_id] = sha256_bytes(
                json.dumps(prompt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )
            decision = decision_by_id.get(prompt_id)
            if decision is None:
                raise ValueError(f"分类报告缺少 prompt_id: {prompt_id}")
            report_category = str(decision.get("current_category") or "")
            if report_category != category_name:
                raise ValueError(
                    f"分类报告目录不匹配: {prompt_id} 报告={report_category!r} 当前={category_name!r}"
                )
            target, reason = decide_destination(
                decision,
                category_name,
                contract,
                canonical_categories,
            )
            if not target:
                raise ValueError(f"prompt_id {prompt_id} 生成了空目标分类")
            if target.startswith("Anima/") and target not in allowed_anima_categories:
                raise ValueError(f"分类器生成了分类契约之外的 Anima 目标: {target}")
            buckets[target].append(prompt)
            reason_counts[reason] += 1
            if target != category_name:
                moved_from_counts[category_name] += 1
                moved_to_counts[target] += 1
                moves.append({
                    "prompt_id": prompt_id,
                    "alias": str(prompt.get("alias") or ""),
                    "from": category_name,
                    "to": target,
                    "reason": reason,
                    "classifier_status": decision.get("status"),
                    "confidence": decision.get("confidence"),
                    "margin": decision.get("margin"),
                    "reference_source": decision.get("reference_source", ""),
                    "reference_section": decision.get("reference_section", ""),
                })

    if set(decision_by_id) != set(original_prompt_ids):
        extra = sorted(set(decision_by_id) - set(original_prompt_ids))[:5]
        raise ValueError(f"分类报告包含当前数据不存在的 prompt_id: {extra}")

    populated_names = {name for name, prompts in buckets.items() if prompts}
    populated_names.update(ANIMA_ROOTS)
    canonical_order = build_canonical_order(contract, populated_names)
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")

    def make_category(name):
        existing = original_metadata.get(name)
        if existing is not None:
            category = copy.copy(existing)
            category["prompts"] = buckets.get(name, [])
            if category["prompts"] != existing.get("prompts", []) or original_name_counts[name] > 1:
                category["updated_at"] = now
            return category
        return {
            "id": deterministic_category_id(name),
            "name": name,
            "updated_at": now,
            "prompts": buckets.get(name, []),
        }

    first_anima_index = next(
        (index for index, category in enumerate(categories) if str(category.get("name") or "").startswith("Anima/")),
        len(categories),
    )
    new_categories = []
    inserted_anima = False
    emitted_names = set()

    for index, category in enumerate(categories):
        name = str(category.get("name") or "")
        if not inserted_anima and index == first_anima_index:
            for anima_name in canonical_order:
                if anima_name not in emitted_names:
                    new_categories.append(make_category(anima_name))
                    emitted_names.add(anima_name)
            inserted_anima = True
        if name.startswith("Anima/"):
            continue
        if name in emitted_names:
            continue
        prompts = buckets.get(name, [])
        keep_empty = not is_reference_category(name)
        if prompts or keep_empty:
            new_categories.append(make_category(name))
            emitted_names.add(name)

    if not inserted_anima:
        for anima_name in canonical_order:
            if anima_name not in emitted_names:
                new_categories.append(make_category(anima_name))
                emitted_names.add(anima_name)

    for name in sorted(populated_names - emitted_names):
        new_categories.append(make_category(name))
        emitted_names.add(name)

    category_structure_changed = [
        (str(category.get("id") or ""), str(category.get("name") or ""))
        for category in categories
    ] != [
        (str(category.get("id") or ""), str(category.get("name") or ""))
        for category in new_categories
    ]
    if moves or category_structure_changed:
        migrated = copy.copy(data)
        migrated["last_modified"] = now
        migrated["categories"] = new_categories
    else:
        migrated = data
        new_categories = categories

    new_prompt_ids = []
    new_fingerprints = {}
    for category in new_categories:
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            new_prompt_ids.append(prompt_id)
            new_fingerprints[prompt_id] = sha256_bytes(
                json.dumps(prompt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )

    invariant_checks = {
        "prompt_count_preserved": len(new_prompt_ids) == len(original_prompt_ids),
        "prompt_ids_preserved": Counter(new_prompt_ids) == Counter(original_prompt_ids),
        "prompt_payloads_preserved": new_fingerprints == prompt_fingerprints,
        "category_names_unique": len({category["name"] for category in new_categories}) == len(new_categories),
        "category_ids_unique": len({category["id"] for category in new_categories}) == len(new_categories),
        "only_contract_anima_categories": all(
            not category["name"].startswith("Anima/") or category["name"] in allowed_anima_categories
            for category in new_categories
        ),
    }
    if not all(invariant_checks.values()):
        raise ValueError(f"迁移不变量检查失败: {invariant_checks}")

    before_root_counts = Counter()
    after_root_counts = Counter()
    for category in categories:
        name = str(category.get("name") or "")
        root = root_for_target(name + "/")
        if root:
            before_root_counts[root] += len(category.get("prompts", []))
    for category in new_categories:
        name = str(category.get("name") or "")
        root = root_for_target(name + "/")
        if root:
            after_root_counts[root] += len(category.get("prompts", []))

    duplicate_names_before = {
        name: count for name, count in original_name_counts.items() if count > 1
    }
    summary = {
        "prompt_count": len(original_prompt_ids),
        "moved_prompts": len(moves),
        "unchanged_prompts": len(original_prompt_ids) - len(moves),
        "categories_before": len(categories),
        "categories_after": len(new_categories),
        "duplicate_category_names_before": duplicate_names_before,
        "duplicate_category_names_after": 0,
        "anima_categories_before": sum(1 for category in categories if str(category.get("name") or "").startswith("Anima/")),
        "anima_categories_after": sum(1 for category in new_categories if str(category.get("name") or "").startswith("Anima/")),
        "anima_prompt_counts_before": dict(before_root_counts),
        "anima_prompt_counts_after": dict(after_root_counts),
        "review_prompt_counts_after": {
            name: len(buckets.get(name, []))
            for name in contract["non_anima_contracts"]["review_categories"]
            + [
                contract["non_anima_contracts"]["excluded_category"],
                contract["non_anima_contracts"]["safety_quarantine_category"],
            ]
            if buckets.get(name)
        },
        "reason_counts": dict(reason_counts.most_common()),
        "top_moved_from": dict(moved_from_counts.most_common(60)),
        "top_moved_to": dict(moved_to_counts.most_common(80)),
        "invariants": invariant_checks,
    }
    return migrated, summary, moves


def atomic_write_json(path, value):
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handle, temporary_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
    return sha256_bytes(serialized), len(serialized)


def main():
    parser = argparse.ArgumentParser(description="Apply a hash-locked WeiLin -> Anima semantic migration.")
    parser.add_argument(
        "--data",
        type=Path,
        default=PLUGIN_DIR / "user_data" / "prompt_selector" / "data.json",
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-sha256", default="")
    args = parser.parse_args()

    source_bytes = args.data.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    report_bytes = args.report.read_bytes()
    report_hash = sha256_bytes(report_bytes)
    report = json.loads(report_bytes)
    report_source_hash = normalized_source_hash(report.get("source_data", {}).get("sha256"))
    if report_source_hash != source_hash:
        raise SystemExit(
            f"拒绝迁移：分类报告基于 {report_source_hash}，当前 data.json 为 {source_hash}。请重跑审计。"
        )
    if args.expected_sha256 and normalized_source_hash(args.expected_sha256) != source_hash:
        raise SystemExit(
            f"拒绝迁移：命令要求 {normalized_source_hash(args.expected_sha256)}，当前 data.json 为 {source_hash}。"
        )

    data = json.loads(source_bytes)
    contract = load_contract()
    migrated, summary, moves = build_migration(data, report, contract)
    mode = "apply" if args.apply else "dry_run"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = args.data.parent / "classification_reports"
    if args.output is None:
        args.output = report_dir / f"anima-semantic-migration-{mode}-{timestamp}.json"
    args.output.parent.mkdir(parents=True, exist_ok=True)

    backup_path = None
    result_hash = sha256_bytes(
        json.dumps(migrated, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )
    result_size = None
    if args.apply:
        live_hash = sha256_bytes(args.data.read_bytes())
        if live_hash != source_hash:
            raise SystemExit(
                f"拒绝写入：迁移计算期间 data.json 已从 {source_hash} 变为 {live_hash}。"
            )
        backup_dir = report_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"data-before-anima-semantic-{timestamp}-{source_hash[:12]}.json"
        backup_path.write_bytes(source_bytes)
        result_hash, result_size = atomic_write_json(args.data, migrated)
        written = json.loads(args.data.read_bytes())
        written_ids = [
            str(prompt.get("id") or "")
            for category in written.get("categories", [])
            for prompt in category.get("prompts", [])
        ]
        original_ids = [
            str(prompt.get("id") or "")
            for category in data.get("categories", [])
            for prompt in category.get("prompts", [])
        ]
        if Counter(written_ids) != Counter(original_ids):
            raise RuntimeError("写入后 prompt_id 校验失败；请立即使用备份恢复。")

    migration_report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "contract_version": contract.get("contract_version"),
        "source_data": {
            "path": str(args.data),
            "sha256": source_hash,
            "classification_report": str(args.report),
            "classification_report_sha256": report_hash,
        },
        "result_data": {
            "sha256": result_hash,
            "bytes": result_size,
            "backup": str(backup_path) if backup_path else "",
        },
        "summary": summary,
        "moves": moves,
        "reverse_moves": [
            {
                "prompt_id": move["prompt_id"],
                "from": move["to"],
                "to": move["from"],
            }
            for move in moves
        ],
    }
    args.output.write_text(
        json.dumps(migration_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(json.dumps({
        "mode": mode,
        "report": str(args.output),
        "source_sha256": source_hash,
        "result_sha256": result_hash,
        "backup": str(backup_path) if backup_path else "",
        "summary": summary,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
