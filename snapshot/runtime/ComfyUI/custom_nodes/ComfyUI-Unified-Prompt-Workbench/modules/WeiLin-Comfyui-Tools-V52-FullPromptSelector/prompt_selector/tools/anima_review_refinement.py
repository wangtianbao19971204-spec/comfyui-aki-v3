import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
PROMPT_SELECTOR_DIR = TOOLS_DIR.parent
PLUGIN_DIR = PROMPT_SELECTOR_DIR.parent
for module_path in (PROMPT_SELECTOR_DIR, TOOLS_DIR):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

from anima_managed_completion import (  # noqa: E402
    ROOT_DEFAULTS,
    _capacity_target,
    _default_target,
    choose_managed_target,
)
from anima_second_pass import (  # noqa: E402
    canonical_targets,
    deterministic_category_id,
    root_from_category,
    source_context_from_category,
    strong_title_root,
)
from anima_tag_classifier import classify_prompt, load_contract, normalize_text  # noqa: E402


SAFETY_SOURCE = "待归类/Anima复核/年龄与安全风险"
STYLE_SOURCE = "待归类/Anima复核/画风质量镜头"
SAFETY_ROOT = "待归类/Anima复核/正太萝莉"
STYLE_ROOT = "待归类/Anima复核/画风质量镜头"

SAFETY_TARGETS = {
    "coercion": f"{SAFETY_ROOT}/明确风险/强制拘束与暴力",
    "penetration": f"{SAFETY_ROOT}/明确风险/插入与体位",
    "non_penetrative": f"{SAFETY_ROOT}/明确风险/口部与非插入行为",
    "other_act": f"{SAFETY_ROOT}/明确风险/其他性行为",
    "nudity": f"{SAFETY_ROOT}/明确风险/裸露与性化展示",
    "adult_relation": f"{SAFETY_ROOT}/边界复核/成人语境与年龄关系",
    "non_adult": f"{SAFETY_ROOT}/边界复核/非成人年龄设定",
}

STYLE_TARGETS = {
    "artist_style": f"{STYLE_ROOT}/画师与作品风格",
    "media_style": f"{STYLE_ROOT}/媒介与渲染风格",
    "quality": f"{STYLE_ROOT}/质量与正向参数",
    "negative": f"{STYLE_ROOT}/负面词与排除项",
    "camera": f"{STYLE_ROOT}/镜头构图与光影",
    "graphic": f"{STYLE_ROOT}/界面排版与画面特效",
    "other": f"{STYLE_ROOT}/综合画面控制",
}

MANUAL_RELEASE_TARGETS = {
    "8bd6318e-1a6c-54db-852a-2984b73a9e8c": "Anima/角色/正常/人物模板/可爱与Q版",
    "6ad15c70-f912-593c-aa49-4450a63f61ad": "Anima/背景/正常/城市与日常",
    "94f6937e-200f-5508-994a-f7ca6db5effa": "Anima/角色/正常/外观与转化/人物转化",
    "f051f7d1-5530-5aa1-8a07-378abc15258d": "Anima/姿势/正常/战斗与动态/高速与冲击",
    "8dc880e4-0628-5dcc-8198-d517a4e693ed": "Anima/姿势/正常/战斗与动态/枪械与远程",
    "51708c81-4c91-553e-850a-bf75641e6880": "Anima/姿势/正常/基础姿态/坐姿与跪姿/椅凳与座位",
    "0200d730-f796-53b3-9bfa-90601c7d93fe": "Anima/姿势/正常/基础姿态/手势与持物",
    "cd50c074-3c0b-590f-8913-03adda9e0517": "Anima/姿势/正常/表情与情绪/夸张颜艺/综合颜艺/眼神与视线",
    "12857830-7d8c-5294-9379-868f3e3f536e": "Anima/姿势/正常/多人互动/牵手与陪伴",
    "80525890-457c-5b1a-8385-bf173cada52f": "Anima/姿势/R18/身体构图/腿足/鞋袜与足部",
    "cd413a87-d72f-542f-9ad5-1337256634ee": "Anima/姿势/R18/身体构图/臀裆部",
    "34359ea5-a4e3-5f4f-b548-68d8882f0cb6": "Anima/姿势/正常/基础姿态/坐姿与跪姿/椅凳与座位",
    "0eacd424-afe4-5fd5-a7e2-17a3779812f7": "Anima/角色/正常/人物模板/通用人物模板/身份气质",
    "f7251d6d-b1af-53e0-88ba-d781a0ed13a3": "Anima/姿势/正常/战斗与动态/武器近战",
    "116aac04-30cf-5e17-955f-d3021f9aef56": "Anima/姿势/正常/表情与情绪/悲伤与哭泣",
    "380c8944-89d9-5539-a908-78b00420ff40": "Anima/姿势/正常/单人动作/生活动作",
    "c0bc7800-21c7-5bcb-92e9-36eb69809c91": "Anima/角色/正常/人物模板/通用人物模板/身份气质",
    "3767694c-5086-55b2-aab3-ea464d7078ff": "Anima/角色/正常/人物模板/通用人物模板/身份气质",
    "d3d4a72f-befa-51cb-a3b5-f2f0a78afad8": "Anima/姿势/正常/战斗与动态/综合战斗姿态",
    "e57c282d-4183-5a7b-b665-c0ad1299d2c9": "Anima/姿势/正常/战斗与动态/综合战斗姿态",
}


def _rx(pattern):
    return re.compile(pattern, re.IGNORECASE)


HARD_AGE_PATTERN = _rx(
    r"(?<![a-z])loli(?![a-z])|(?<![a-z])shota(?![a-z])|underage|"
    r"(?<![a-z])minor(?![a-z])|toddler|(?<![a-z])child(?:ren)?(?![a-z])|"
    r"(?<![a-z])baby(?![a-z])|little (?:girl|boy|child)|small child|"
    r"kindergarten|elementary school|middle school|幼女|幼童|未成年|"
    r"小女孩|小男孩|正太|萝莉|小学生|幼儿|婴儿|小孩姐"
)
SOFT_AGE_PATTERN = _rx(
    r"onee[-_ ]?shota|age difference|teen(?:ager)?|schoolgirl|schoolboy|"
    r"young (?:girl|boy)|年龄差|姐弟|母子|父女|师生|少女|少年|学生"
)
AGE_SOURCE_PATTERN = _rx(r"大车小孩特辑")
ADULT_SOURCE_PATTERN = _rx(r"色色|基础涩涩|群友色色|大车小孩")
COERCION_PATTERN = _rx(
    r"rape|gangbang|forced|forcefully|bondage|bdsm|bound|restrain|gagged|"
    r"shibari|torture|abuse|molest|tentacle sex|强奸|轮奸|强制|胁迫|"
    r"拘束|捆绑|调教|凌辱|侵犯|人棍|截肢|催眠|睡奸"
)
PENETRATION_PATTERN = _rx(
    r"(?<![a-z])sex(?![a-z])|vaginal|(?<![a-z])anal(?![a-z])|penetrat|"
    r"doggystyle|cowgirl|missionary|mating press|sex from behind|tentacle sex|"
    r"性交|性爱|做爱|后入|骑乘|插入|中出|种付|打桩|素股"
)
NON_PENETRATIVE_PATTERN = _rx(
    r"fellatio|blowjob|deepthroat|cunnilingus|handjob|footjob|paizuri|"
    r"masturbat|fingering|breast sucking|口交|乳交|手交|足交|自慰|"
    r"深喉|舔穴|舔阴|指交"
)
OTHER_ADULT_ACT_PATTERN = _rx(
    r"orgasm|(?<![a-z])cum(?![a-z])|cumshot|penis|pussy|vagina|clitoris|"
    r"urethra|sex toy|vibrator|insemination|阴茎|阴部|小穴|避孕套|射精|"
    r"深吻|激吻|夹头|勃起|揉胸|摸胸|抓胸|吸奶|舔乳"
)
NUDITY_PATTERN = _rx(
    r"(?<![a-z])nsfw(?![a-z])|(?<![a-z])nude(?![a-z])|naked|topless|"
    r"bottomless|nipples?|areola|no panties|no bra|see-through top|"
    r"covered pussy|visible vulva|erotic|seductive|prostitute|sexualized|"
    r"oppai|breasts exposed|露点|全裸|裸体|走光|露乳|性化|色情|"
    r"巨乳|爆乳|乳房|奶子|大奶"
)
MINOR_SEXUALIZATION_PATTERN = _rx(
    r"see[- ]?through|cleavage|small breasts?|covered breasts?|"
    r"crotch grab|grabbing crotch|hand on crotch|covering (?:own )?(?:chest|breasts?)|"
    r"透视|乳沟|小胸|抓裆|捂胸"
)
LOLITA_FASHION_PATTERN = _rx(
    r"(?<![a-z])lolita(?: fashion| outfit| clothes?| dress)?(?![a-z])|"
    r"gothic lolita|sweet lolita|classic lolita|ouji fashion|洛丽塔"
)

CHILD_BEARING_PATTERN = _rx(r"child[- ]bearing")

NEGATIVE_STYLE_PATTERN = _rx(
    r"negative|worst quality|low quality|bad anatomy|bad hands|extra limbs|"
    r"deformed|mutated|watermark|username|负面词|负面|排除|不要|禁止"
)
ARTIST_STYLE_PATTERN = _rx(
    r"artist:|画师|style of|artstyle|画风|风格|pixel art|watercolor|"
    r"oil painting|sketch|lineart|monochrome|3d|2d|浮世绘|像素|水彩|"
    r"油画|线稿|厚涂|赛璐璐|蒸汽波|漫画|动画"
)
MEDIA_STYLE_PATTERN = _rx(
    r"pixel art|watercolor|oil painting|sketch|lineart|monochrome|3d|2d|"
    r"flat color|cel shading|pastel|crayon|ink|charcoal|浮世绘|像素|水彩|"
    r"油画|线稿|厚涂|赛璐璐|彩铅|铅笔|水墨|漫画|动画|建模|渲染"
)
QUALITY_STYLE_PATTERN = _rx(
    r"masterpiece|best quality|high quality|very aesthetic|absurdres|highres|"
    r"ultra detailed|detailed|quality|aesthetic|质量|正向词|细节|高清|高分辨率"
)
CAMERA_STYLE_PATTERN = _rx(
    r"close[- ]?up|cowboy shot|wide shot|full body|upper body|from above|"
    r"from below|from side|pov|fisheye|lens|depth of field|bokeh|dutch angle|"
    r"panorama|lighting|backlight|rim light|underlighting|sidelight|shadow|"
    r"视角|镜头|特写|构图|景深|广角|俯视|仰视|光影|打光|逆光|侧光"
)
GRAPHIC_STYLE_PATTERN = _rx(
    r"magazine|poster|typography|text:|logo|interface|game ui|dialogue box|"
    r"fake screenshot|glitch|sticker|postcard|vhs|wanted poster|画面|海报|"
    r"杂志|界面|排版|贴纸|明信片|故障|分镜|屏幕|对话框"
)


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _prompt_body(prompt):
    return "\n".join(
        str(prompt.get(field) or "")
        for field in ("alias", "prompt", "description")
    )


def _prompt_tags(prompt):
    return "\n".join(str(tag or "") for tag in (prompt.get("tags") or []))


def safety_signals(prompt):
    body = _prompt_body(prompt)
    tags = _prompt_tags(prompt)
    age_body = CHILD_BEARING_PATTERN.sub("", body)
    hard_age = bool(HARD_AGE_PATTERN.search(age_body))
    soft_age = bool(SOFT_AGE_PATTERN.search(age_body))
    age_source = bool(AGE_SOURCE_PATTERN.search(tags))
    age_signal = hard_age or soft_age or age_source
    coercion = bool(COERCION_PATTERN.search(body))
    penetration = bool(PENETRATION_PATTERN.search(body))
    non_penetrative = bool(NON_PENETRATIVE_PATTERN.search(body))
    other_act = bool(OTHER_ADULT_ACT_PATTERN.search(body))
    minor_sexualization = age_signal and bool(MINOR_SEXUALIZATION_PATTERN.search(body))
    nudity = bool(NUDITY_PATTERN.search(body)) or minor_sexualization
    adult_source = bool(ADULT_SOURCE_PATTERN.search(tags))
    adult_signal = coercion or penetration or non_penetrative or other_act or nudity
    return {
        "hard_age": hard_age,
        "soft_age": soft_age,
        "age_source": age_source,
        "adult_source": adult_source,
        "coercion": coercion,
        "penetration": penetration,
        "non_penetrative": non_penetrative,
        "other_act": other_act,
        "nudity": nudity,
        "minor_sexualization": minor_sexualization,
        "age_signal": age_signal,
        "adult_signal": adult_signal,
    }


def style_target(prompt):
    body = _prompt_body(prompt)
    tags = _prompt_tags(prompt)
    combined = f"{body}\n{tags}"
    if NEGATIVE_STYLE_PATTERN.search(combined):
        return STYLE_TARGETS["negative"], "negative_or_exclusion_terms"
    if MEDIA_STYLE_PATTERN.search(combined):
        return STYLE_TARGETS["media_style"], "visual_media_or_rendering_style"
    if "各种风格" in tags or ARTIST_STYLE_PATTERN.search(combined):
        return STYLE_TARGETS["artist_style"], "artist_or_style_media"
    if "特殊画面" in tags or GRAPHIC_STYLE_PATTERN.search(combined):
        return STYLE_TARGETS["graphic"], "graphic_layout_or_effect"
    if "视角与打光" in tags or CAMERA_STYLE_PATTERN.search(combined):
        return STYLE_TARGETS["camera"], "camera_composition_or_lighting"
    if "质量词" in tags or QUALITY_STYLE_PATTERN.search(combined):
        return STYLE_TARGETS["quality"], "quality_or_positive_parameters"
    return STYLE_TARGETS["other"], "other_visual_control"


def _provenance_map(report):
    if not report:
        return {}
    return {
        str(item.get("prompt_id") or ""): str(item.get("provenance_category") or "")
        for item in report.get("decisions", [])
        if str(item.get("prompt_id") or "")
    }


def _provenance_from_tags(prompt):
    tags = [str(tag or "").strip() for tag in (prompt.get("tags") or [])]
    joined = "\n".join(tags)
    if "03_所长色色法典（下）" in joined or "色色法典（下）" in joined:
        source = "所长色色NovelAI个人法典(下)"
    elif "02_所长色色法典（上）" in joined or "色色法典（上）" in joined:
        source = "所长色色NovelAI个人法典(上)"
    elif "01_所长常规法典" in joined or "所长常规" in joined:
        source = "所长常规NovelAI个人法典"
    else:
        return ""
    sections = [
        tag for tag in tags
        if tag
        and "法典" not in tag
        and not re.fullmatch(r"20\d{2}[.年/-].*新增", tag)
    ]
    return f"{source}/{sections[-1]}" if sections else source


def _sanitized_release_prompt(prompt, signals):
    result = copy.deepcopy(prompt)
    if not signals.get("age_signal"):
        for field in ("alias", "prompt", "description"):
            result[field] = LOLITA_FASHION_PATTERN.sub(
                "frilled fashion outfit",
                str(result.get(field) or ""),
            )
    return result


def _adult_release_override(prompt, signals, target):
    if "/R18/" in target:
        return target, "existing_r18_target"
    sexual_signal = any(
        signals.get(name)
        for name in ("penetration", "non_penetrative", "other_act", "nudity")
    )
    if not sexual_signal:
        return target, ""

    body = normalize_text(_prompt_body(prompt))
    if signals.get("coercion"):
        if re.search(r"bondage|bound|shibari|拘束|捆绑|绳缚", body):
            return "Anima/姿势/R18/拘束/捆绑姿势/综合拘束姿态", "adult_semantic_override"
        return "Anima/姿势/R18/双人互动/胁迫与强制", "adult_semantic_override"
    if signals.get("penetration"):
        if re.search(r"dilat|close to (?:pussy|vagina)|spread (?:pussy|anal)|扩张", body):
            return "Anima/姿势/R18/身体构图/臀裆部", "adult_semantic_override"
        if re.search(r"doggy|from behind|rear entry|sex from behind|后入", body):
            return "Anima/姿势/R18/体位/后入与背后位/其他背后位", "adult_semantic_override"
        if re.search(r"cowgirl|riding|骑乘", body):
            return "Anima/姿势/R18/体位/骑乘位", "adult_semantic_override"
        if re.search(r"standing|站立", body):
            return "Anima/姿势/R18/体位/站立位", "adult_semantic_override"
        return "Anima/姿势/R18/体位/正身位", "adult_semantic_override"
    if signals.get("non_penetrative"):
        if re.search(r"fellatio|blowjob|deepthroat|cunnilingus|口交|深喉|舔阴", body):
            return "Anima/姿势/R18/非插入互动/口交与颜射/常规口交/综合口交", "adult_semantic_override"
        if re.search(r"handjob|手交", body):
            return "Anima/姿势/R18/非插入互动/手交", "adult_semantic_override"
        if re.search(r"footjob|足交", body):
            return "Anima/姿势/R18/非插入互动/足交", "adult_semantic_override"
        if re.search(r"paizuri|乳交", body):
            return "Anima/姿势/R18/非插入互动/乳交", "adult_semantic_override"
        if re.search(r"masturbat|自慰|fingering|指交", body):
            return "Anima/姿势/R18/单人表现/自慰/综合自慰", "adult_semantic_override"
        return "Anima/姿势/R18/非插入互动/身体摩擦", "adult_semantic_override"
    if re.search(r"lift(?:ing)? (?:own )?skirt|hands on hem|掀.*裙|lift.*dress", body):
        return "Anima/姿势/R18/单人表现/暴露/掀衣与敞开", "adult_semantic_override"
    if re.search(r"breasts?|nipples?|areola|乳房|乳头|挤奶", body):
        return "Anima/姿势/R18/身体构图/胸腹部", "adult_semantic_override"
    if re.search(r"pussy|vagina|clitoris|labia|anal|(?<![a-z])ass(?![a-z])|buttocks?|阴部|小穴|臀", body):
        return "Anima/姿势/R18/身体构图/臀裆部", "adult_semantic_override"
    return "Anima/姿势/R18/单人表现/暴露/裸体展示", "adult_semantic_override"


def _release_target(prompt, provenance, signals, contract, allowed_targets):
    sanitized = _sanitized_release_prompt(prompt, signals)
    manual_target = MANUAL_RELEASE_TARGETS.get(str(prompt.get("id") or ""))
    if manual_target:
        if manual_target not in allowed_targets:
            raise RuntimeError(f"人工审计目标不在分类契约中：{manual_target}")
        target, split_base = _capacity_target(manual_target, sanitized)
        reason = "manual_semantic_audit"
        if split_base:
            reason += "+capacity_split"
        return target, "manual_release_audit", reason, 0.99
    reference_source, reference_section = source_context_from_category(provenance)
    deterministic = classify_prompt(
        sanitized,
        current_category="",
        reference_source=reference_source,
        reference_section=reference_section,
        contract=contract,
    ).to_dict()
    semantic = {"deterministic": deterministic, "candidates": []}
    target, root_reason, reason, confidence = choose_managed_target(
        sanitized,
        provenance,
        semantic,
        {"deterministic": deterministic},
        allowed_targets,
        contract,
    )
    if target == contract["non_anima_contracts"]["excluded_category"]:
        target, style_reason = style_target(prompt)
        return target, "release_to_style_review", style_reason, 0.90
    if target not in allowed_targets:
        fallback_root = deterministic.get("root") or strong_title_root(prompt.get("alias"))
        if fallback_root in ROOT_DEFAULTS:
            target = _default_target(sanitized, fallback_root, provenance)
            reason = "deterministic_root_fallback"
            root_reason = deterministic.get("reasons") or root_reason
            confidence = max(0.74, float(deterministic.get("confidence") or 0))
        else:
            adult_target, adult_reason = _adult_release_override(sanitized, signals, "")
            if adult_reason:
                target = adult_target
                reason = adult_reason
                root_reason = "adult_semantic_fallback"
                confidence = 0.96
            else:
                return (
                    SAFETY_TARGETS["non_adult"],
                    "non_adult_age_boundary",
                    "no_stable_anima_root",
                    0.70,
                )
    target, adult_reason = _adult_release_override(sanitized, signals, target)
    if adult_reason:
        reason = adult_reason
        confidence = max(confidence, 0.96)
    if target not in allowed_targets:
        raise RuntimeError(f"成人语义定向目标不在分类契约中：{target}")
    target, split_base = _capacity_target(target, sanitized)
    if split_base:
        reason += "+capacity_split"
    return target, root_reason, reason, confidence


def classify_safety_prompt(prompt, provenance, contract, allowed_targets):
    signals = safety_signals(prompt)
    if signals["age_signal"] and (
        signals["adult_signal"] or signals["adult_source"]
    ):
        if signals["coercion"]:
            key = "coercion"
        elif signals["penetration"]:
            key = "penetration"
        elif signals["non_penetrative"]:
            key = "non_penetrative"
        elif signals["other_act"]:
            key = "other_act"
        elif signals["nudity"]:
            key = "nudity"
        else:
            key = "adult_relation"
        evidence = [name for name, matched in signals.items() if matched and name not in {"age_signal", "adult_signal"}]
        return SAFETY_TARGETS[key], "safety_quarantine_refined", key, 0.99, evidence

    target, root_reason, reason, confidence = _release_target(
        prompt,
        provenance,
        signals,
        contract,
        allowed_targets,
    )
    release_reason = "non_adult_age_content" if signals["age_signal"] else "false_positive_age_match"
    return target, root_reason, f"{release_reason}+{reason}", confidence, [
        name for name, matched in signals.items()
        if matched and name not in {"age_signal", "adult_signal"}
    ]


def _load_report(path):
    if not path:
        return {}, ""
    raw = path.read_bytes()
    return json.loads(raw), sha256_bytes(raw)


def build_audit(data, source_hash, provenance_report, provenance_hash, contract, args):
    allowed_targets = canonical_targets(contract)
    provenance_by_id = _provenance_map(provenance_report)
    categories = {
        str(category.get("name") or ""): category
        for category in data.get("categories", [])
    }
    missing_sources = [
        name for name in (SAFETY_SOURCE, STYLE_SOURCE)
        if name not in categories
    ]
    if missing_sources:
        raise SystemExit("缺少复核分类：" + ", ".join(missing_sources))

    decisions = []
    reason_counts = Counter()
    target_counts = Counter()
    current_counts = Counter({
        str(category.get("name") or ""): len(category.get("prompts", []))
        for category in data.get("categories", [])
    })
    safety_signal_counts = Counter()

    for source_name in (SAFETY_SOURCE, STYLE_SOURCE):
        for prompt in categories[source_name].get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            provenance = provenance_by_id.get(prompt_id) or _provenance_from_tags(prompt)
            if source_name == SAFETY_SOURCE:
                target, root_reason, reason, confidence, evidence = classify_safety_prompt(
                    prompt,
                    provenance,
                    contract,
                    allowed_targets,
                )
                for signal in evidence:
                    safety_signal_counts[signal] += 1
            else:
                target, reason = style_target(prompt)
                root_reason = "non_anima_visual_control"
                confidence = 0.96
                evidence = []
            decisions.append({
                "prompt_id": prompt_id,
                "alias": str(prompt.get("alias") or ""),
                "current_category": source_name,
                "provenance_category": provenance,
                "selected": target != source_name,
                "target": target,
                "root_reason": root_reason,
                "reason": reason,
                "confidence": round(float(confidence), 4),
                "safety_evidence": evidence,
                "image": str(prompt.get("image") or ""),
            })
            reason_counts[reason] += 1
            target_counts[target] += 1
            current_counts[source_name] -= 1
            current_counts[target] += 1

    source_prompt_count = sum(
        len(categories[name].get("prompts", []))
        for name in (SAFETY_SOURCE, STYLE_SOURCE)
    )
    if len(decisions) != source_prompt_count:
        raise SystemExit("复核条目覆盖不完整。")
    prompt_ids = [decision["prompt_id"] for decision in decisions]
    if len(set(prompt_ids)) != len(prompt_ids):
        raise SystemExit("复核条目存在重复 ID。")

    over_capacity = {
        name: count for name, count in current_counts.items()
        if count > args.capacity_limit and (
            name.startswith("Anima/")
            or name.startswith(f"{SAFETY_ROOT}/")
            or name.startswith(f"{STYLE_ROOT}/")
        )
    }
    if over_capacity:
        raise SystemExit(
            "细分后仍有分类超过容量："
            + json.dumps(over_capacity, ensure_ascii=False)
        )

    released_to_anima = sum(
        decision["target"].startswith("Anima/")
        for decision in decisions
    )
    retained_safety = sum(
        decision["target"].startswith(f"{SAFETY_ROOT}/")
        for decision in decisions
    )
    return {
        "schema_version": 1,
        "stage": "anima_review_refinement",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_data": {"path": str(args.data), "sha256": source_hash},
        "dependencies": {
            "provenance_report": {
                "path": str(args.provenance_report or ""),
                "sha256": provenance_hash,
            }
        },
        "policy": {
            "release_only_without_age_adult_conflict": True,
            "never_render_safety_quarantine": True,
            "capacity_limit": args.capacity_limit,
            "safety_source": SAFETY_SOURCE,
            "style_source": STYLE_SOURCE,
        },
        "summary": {
            "source_prompts": source_prompt_count,
            "safety_prompts": len(categories[SAFETY_SOURCE].get("prompts", [])),
            "style_prompts": len(categories[STYLE_SOURCE].get("prompts", [])),
            "released_to_anima": released_to_anima,
            "retained_safety_review": retained_safety,
            "refined_style_review": sum(
                decision["target"].startswith(f"{STYLE_ROOT}/")
                for decision in decisions
            ),
            "reason_counts": dict(reason_counts.most_common()),
            "target_counts": dict(target_counts.most_common()),
            "safety_signal_counts": dict(safety_signal_counts.most_common()),
            "projected_over_capacity": {},
        },
        "decisions": decisions,
    }


def atomic_write_json(path, value):
    serialized = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handle, temporary_name = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=path.parent,
    )
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
    return serialized


def apply_report(data_path, report_path, expected_sha256=""):
    source_bytes = data_path.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    if report.get("stage") != "anima_review_refinement":
        raise SystemExit("拒绝写入：报告类型不正确。")
    if str(report.get("source_data", {}).get("sha256") or "") != source_hash:
        raise SystemExit("拒绝写入：报告基于的数据已经变化。")
    if expected_sha256 and expected_sha256.lower() != source_hash:
        raise SystemExit("拒绝写入：当前数据与期望哈希不一致。")
    if report.get("summary", {}).get("projected_over_capacity"):
        raise SystemExit("拒绝写入：仍有分类超过容量。")

    data = json.loads(source_bytes)
    result = copy.deepcopy(data)
    decisions = {
        str(item.get("prompt_id") or ""): item
        for item in report.get("decisions", [])
    }
    source_names = {SAFETY_SOURCE, STYLE_SOURCE}
    prompt_by_id = {}
    source_prompt_ids = set()
    for category in result.get("categories", []):
        if str(category.get("name") or "") not in source_names:
            continue
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            if prompt_id in prompt_by_id:
                raise SystemExit(f"拒绝写入：重复 prompt ID {prompt_id}")
            prompt_by_id[prompt_id] = prompt
            source_prompt_ids.add(prompt_id)
        category["prompts"] = []

    if source_prompt_ids != set(decisions):
        missing = sorted(source_prompt_ids - set(decisions))
        extra = sorted(set(decisions) - source_prompt_ids)
        raise SystemExit(
            f"拒绝写入：报告覆盖不匹配 missing={missing[:5]} extra={extra[:5]}"
        )

    categories_by_name = {
        str(category.get("name") or ""): category
        for category in result.get("categories", [])
    }
    now = datetime.now(timezone.utc).astimezone().isoformat()
    for prompt_id, decision in decisions.items():
        target = str(decision.get("target") or "")
        if not target:
            raise SystemExit(f"拒绝写入：{prompt_id} 缺少目标分类。")
        target_category = categories_by_name.get(target)
        if target_category is None:
            target_category = {
                "id": deterministic_category_id(target),
                "name": target,
                "updated_at": now,
                "prompts": [],
            }
            result["categories"].append(target_category)
            categories_by_name[target] = target_category
        target_category.setdefault("prompts", []).append(prompt_by_id[prompt_id])
        target_category["updated_at"] = now

    result["categories"] = [
        category for category in result.get("categories", [])
        if str(category.get("name") or "") not in source_names
    ]
    result["last_modified"] = now

    all_prompt_ids = [
        str(prompt.get("id") or "")
        for category in result.get("categories", [])
        for prompt in category.get("prompts", [])
    ]
    if len(all_prompt_ids) != len(set(all_prompt_ids)):
        raise SystemExit("拒绝写入：迁移后 prompt ID 不唯一。")
    if len(all_prompt_ids) != sum(
        len(category.get("prompts", []))
        for category in data.get("categories", [])
    ):
        raise SystemExit("拒绝写入：迁移后预设数量变化。")

    report_dir = data_path.parent / "classification_reports"
    backup_dir = report_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"data-before-anima-review-{timestamp}-{source_hash[:12]}.json"
    backup_path.write_bytes(source_bytes)
    result_bytes = atomic_write_json(data_path, result)
    result_report = {
        "schema_version": 1,
        "stage": "anima_review_refinement_apply",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_hash,
        "result_sha256": sha256_bytes(result_bytes),
        "classification_report": str(report_path),
        "classification_report_sha256": sha256_bytes(report_bytes),
        "backup": str(backup_path),
        "moved": len(decisions),
        "removed_categories": sorted(source_names),
    }
    result_path = report_dir / f"anima-review-refinement-apply-{timestamp}.json"
    atomic_write_json(result_path, result_report)
    return result_report, result_path


def main():
    default_data = PLUGIN_DIR / "user_data" / "prompt_selector" / "data.json"
    default_report_dir = default_data.parent / "classification_reports"
    parser = argparse.ArgumentParser(
        description="Refine age-safety and visual-control review buckets without rendering risk prompts.",
    )
    parser.add_argument("--data", type=Path, default=default_data)
    parser.add_argument("--provenance-report", type=Path, default=None)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--capacity-limit", type=int, default=200)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--expected-sha256", default="")
    args = parser.parse_args()

    if args.apply:
        if not args.report:
            parser.error("--apply 需要 --report")
        result, result_path = apply_report(
            args.data,
            args.report,
            args.expected_sha256,
        )
        print(json.dumps({**result, "result_report": str(result_path)}, ensure_ascii=False, indent=2))
        return

    source_bytes = args.data.read_bytes()
    data = json.loads(source_bytes)
    provenance_report, provenance_hash = _load_report(args.provenance_report)
    contract = load_contract()
    audit = build_audit(
        data,
        sha256_bytes(source_bytes),
        provenance_report,
        provenance_hash,
        contract,
        args,
    )
    if not args.output:
        timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
        args.output = default_report_dir / f"anima-review-refinement-audit-{timestamp}.json"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(args.output, audit)
    print(json.dumps({
        "output": str(args.output),
        "source_sha256": audit["source_data"]["sha256"],
        "summary": audit["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
