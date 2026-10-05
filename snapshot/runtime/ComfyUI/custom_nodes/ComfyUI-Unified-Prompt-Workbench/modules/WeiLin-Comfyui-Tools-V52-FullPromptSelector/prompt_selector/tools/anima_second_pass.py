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
if str(PROMPT_SELECTOR_DIR) not in sys.path:
    sys.path.insert(0, str(PROMPT_SELECTOR_DIR))

from anima_tag_classifier import (  # noqa: E402
    SECTION_TARGETS,
    classify_prompt,
    load_contract,
    normalize_text,
    root_for_target,
)


REVIEW_CATEGORIES = {
    "待归类/Anima复核/角色服装冲突",
    "待归类/Anima复核/混合全套",
    "待归类/Anima复核/低置信",
}
EXCLUDED_CATEGORIES = {
    "待归类/Anima复核/画风质量镜头",
    "待归类/Anima复核/年龄与安全风险",
}
REFERENCE_PREFIXES = (
    "所长常规NovelAI个人法典/",
    "所长色色NovelAI个人法典(上)/",
    "所长色色NovelAI个人法典(下)/",
)
ROOT_PREFIXES = {
    "character": "Anima/角色/",
    "clothing": "Anima/服装/",
    "pose": "Anima/姿势/",
    "background": "Anima/背景/",
}


STRONG_TITLE_ROOT_PATTERNS = {
    "clothing": (
        r"(?:原版|原tag|搭配|一套|完整|默认|初始|char\d*)[^\n]{0,10}(?:服装|服饰|衣装|穿搭|套装|装束)",
        r"^(?:服装|服饰|衣装|穿搭|套装|装束)(?:版|原版)?(?:__\d+)?$",
    ),
    "pose": (
        r"(?:原版|原tag|搭配|默认|初始)[^\n]{0,10}(?:动作|姿势|表情|体位)",
        r"^(?:动作|姿势|表情|体位)(?:版|原版|前置)?(?:__\d+)?$",
    ),
    "background": (
        r"(?:原版|原tag|搭配|默认|初始)[^\n]{0,10}(?:背景|场景|环境|房间)",
        r"^(?:背景|场景|环境|房间)(?:版|原版)?(?:__\d+)?$",
    ),
    "character": (
        r"(?:原版|原tag|搭配|默认|初始)[^\n]{0,10}(?:角色|人设|人物|种族|形象)",
        r"^(?:角色|人设|人物|种族|形象)(?:版|原版|设定)?(?:__\d+)?$",
    ),
}


ALIAS_ROOT_TERMS = {
    "character": (
        "角色", "人设", "人物形象", "种族", "机娘", "机器人", "人偶", "魔物娘",
        "兽娘", "猫娘", "狐娘", "龙娘", "精灵", "恶魔", "天使", "扶她", "伪娘", "男娘",
    ),
    "clothing": (
        "服装", "服饰", "衣装", "穿搭", "套装", "装束", "裙", "制服", "校服", "军装",
        "水手服", "衬衫", "裤袜", "泳装", "泳衣", "比基尼", "内衣", "睡衣", "胶衣", "旗袍", "汉服", "和服",
        "兔女郎", "女仆装", "护士服", "半脱", "爆衣", "破衣", "cosplay",
    ),
    "pose": (
        "姿势", "动作", "表情", "体位", "站立", "坐姿", "跪", "躺", "趴", "拥抱",
        "亲吻", "贴贴", "战斗", "施法", "跳舞", "哭", "笑", "诱惑", "展示", "直播",
        "偷窥", "事后", "侵犯", "做爱", "性交", "口交", "乳交", "足交", "手交", "自慰",
        "骑乘", "后入", "捆绑", "绳缚", "拘束", "催眠", "ntr", "乱交", "群交",
    ),
    "background": (
        "背景", "场景", "环境", "房间", "室内", "室外", "街道", "街景", "城市", "森林",
        "海滩", "山谷", "草原", "天空", "夜景", "教室", "卧室", "浴室", "暗室", "仓库",
        "监狱", "地牢", "舞台", "车内",
    ),
}


STRONG_TITLE_LEAF_RULES = (
    ("Anima/姿势/R18/情境/NTR", (r"\bntr\b", r"牛头人")),
    ("Anima/姿势/R18/情境/催眠", (r"催眠", r"洗脑", r"精神控制", r"mind control")),
    ("Anima/姿势/R18/非插入互动/足交", (r"足交", r"脚交", r"footjob")),
    ("Anima/姿势/R18/非插入互动/手交", (r"手交", r"handjob")),
    ("Anima/姿势/R18/非插入互动/乳交", (r"乳交", r"奶交", r"paizuri")),
    ("Anima/姿势/R18/非插入互动/身体摩擦", (r"素股", r"腿交", r"股交", r"thigh sex")),
    ("Anima/姿势/R18/非插入互动/口交与颜射", (r"口交", r"颜射", r"吹箫", r"blowjob", r"fellatio")),
    ("Anima/姿势/R18/体位/后入与背后位", (r"后入", r"背后位", r"狗爬", r"doggy")),
    ("Anima/姿势/R18/体位/骑乘位", (r"骑乘", r"女上位", r"cowgirl")),
    ("Anima/姿势/R18/体位/正身位", (r"传教士", r"正身位", r"正常位", r"missionary")),
    ("Anima/姿势/R18/体位/站立位", (r"站立位", r"站立做爱", r"standing sex")),
    ("Anima/姿势/R18/体位/种付位", (r"种付", r"mating press")),
    ("Anima/姿势/R18/单人表现/自慰", (r"自慰", r"手淫", r"masturbat")),
    ("Anima/姿势/R18/单人表现/隐秘展示与直播", (r"自拍", r"直播", r"偷拍视频", r"对镜", r"selfie", r"livestream")),
    ("Anima/姿势/R18/单人表现/诱惑", (r"诱惑", r"勾引", r"媚眼", r"暗示", r"seduc")),
    ("Anima/姿势/R18/单人表现/暴露", (r"露出", r"暴露", r"public nudity")),
    ("Anima/姿势/R18/双人互动/事后", (r"事后", r"after sex")),
    ("Anima/姿势/R18/双人互动/睡眠侵犯", (r"睡奸", r"sleep sex")),
    ("Anima/姿势/R18/双人互动/攻守反转", (r"四爱", r"逆推", r"攻守反转", r"pegging")),
    ("Anima/姿势/R18/多人互动/百合", (r"百合", r"\byuri\b")),
    ("Anima/姿势/R18/多人互动/多人强制", (r"轮奸", r"多人强制", r"gang rape")),
    ("Anima/姿势/R18/多人互动/双飞与多人", (r"双飞", r"群交", r"乱交", r"\d+p", r"gangbang", r"group sex")),
    ("Anima/姿势/R18/拘束/肉便器", (r"肉便器", r"\brbq\b")),
    ("Anima/姿势/R18/拘束/监禁放置", (r"监禁", r"囚禁", r"关押", r"拘束放置", r"玩具放置")),
    ("Anima/姿势/R18/拘束/捆绑姿势", (r"捆绑", r"绳缚", r"绑缚", r"吊缚", r"悬吊", r"倒吊", r"束缚", r"拘束", r"bondage", r"shibari")),
    ("Anima/姿势/R18/重口/异种互动/触手", (r"触手", r"章鱼.*(?:交|侵犯|捕获)", r"tentacle")),
    ("Anima/姿势/R18/重口/异种互动/史莱姆", (r"史莱姆", r"slime")),
    ("Anima/姿势/R18/重口/异种互动/昆虫", (r"虫奸", r"昆虫", r"抱脸虫", r"蠕虫.*(?:交|侵犯)", r"insect")),
    ("Anima/姿势/R18/重口/异种互动/兽类", (r"兽交", r"狗交", r"蛇.*(?:交|侵犯)", r"巨兽.*(?:交|侵犯)", r"zooph", r"bestiality")),
    ("Anima/姿势/R18/重口/机械", (r"机械奸", r"机器侵犯", r"machine sex")),
    ("Anima/姿势/R18/重口/排泄物", (r"排泄", r"尿液", r"粪便", r"scat")),
    ("Anima/姿势/R18/重口/暴力/截肢与人棍", (r"截肢", r"人棍", r"amput")),
    ("Anima/姿势/R18/重口/暴力/杀害", (r"杀害", r"处刑", r"斩首", r"decapitat")),
    ("Anima/姿势/R18/重口/暴力/食人", (r"食人", r"烹饪人体", r"cannibal")),
    ("Anima/姿势/R18/重口/排泄物", (r"撒尿", r"尿尿", r"排尿", r"urination")),
    ("Anima/姿势/R18/体位/坐身位", (r"坐身位", r"坐位", r"seated sex")),
    ("Anima/姿势/R18/身体构图/腿足", (r"足底", r"脚底", r"腿足特写", r"sole focus")),
    ("Anima/姿势/R18/身体构图/臀裆部", (r"屁股特写", r"臀部特写", r"骆驼趾特写", r"小穴.*(?:特写|展示)", r"裆部特写")),
    ("Anima/姿势/R18/身体构图/胸腹部", (r"胸部特写", r"乳房特写", r"腹部特写", r"躯体特写")),
    ("Anima/姿势/R18/双人互动/调戏与猥亵", (r"调戏", r"猥亵", r"揉胸", r"扣穴", r"摸大腿")),
    ("Anima/姿势/R18/双人互动/胁迫与强制", (r"胁迫", r"强制", r"强奸", r"侵犯", r"rape")),
    ("Anima/服装/R18/内衣与泳装/泳装", (r"泳装", r"泳衣", r"比基尼", r"bikini", r"swimsuit")),
    ("Anima/服装/R18/内衣与泳装/内衣", (r"内衣", r"胸罩", r"内裤", r"lingerie", r"underwear")),
    ("Anima/服装/R18/内衣与泳装/睡衣", (r"睡衣", r"睡裙", r"pajama", r"nightgown")),
    ("Anima/服装/R18/材质与紧身/连体胶衣", (r"胶衣", r"乳胶", r"latex", r"rubber suit")),
    ("Anima/服装/R18/Cosplay与角色服装", (r"cosplay", r"角色服装", r"皮肤服装")),
    ("Anima/服装/正常/制服与职业/校服", (r"校服", r"school uniform", r"serafuku")),
    ("Anima/服装/正常/制服与职业/军装", (r"军装", r"military uniform")),
    ("Anima/服装/正常/制服与职业/运动服", (r"赛车女郎", r"篮球服", r"运动服", r"sportswear")),
    ("Anima/服装/正常/日常与季节/日常服", (r"日常服", r"日常穿搭", r"casual wear")),
    ("Anima/服装/正常/地域与时代/中国", (r"旗袍", r"汉服", r"china dress", r"hanfu")),
    ("Anima/服装/正常/地域与时代/中东", (r"埃及服装", r"阿拉伯服装", r"egyptian outfit")),
    ("Anima/服装/正常/地域与时代/日本", (r"和服", r"浴衣", r"巫女服", r"kimono", r"yukata")),
    ("Anima/服装/正常/幻想与主题/兔女郎", (r"兔女郎", r"bunnysuit", r"playboy bunny")),
    ("Anima/角色/R18/成人身份/扶她", (r"扶她", r"futa", r"futanari")),
    ("Anima/角色/R18/成人身份/伪娘与男娘", (r"伪娘", r"男娘", r"femboy")),
    ("Anima/角色/正常/种族与形态/人工造物", (r"机娘", r"机器人", r"机械少女", r"android", r"cyborg")),
    ("Anima/角色/正常/种族与形态/魔物与人外", (r"魔物娘", r"人外娘", r"monster girl")),
    ("Anima/角色/正常/种族与形态/动物娘化", (r"猫娘", r"狐娘", r"龙娘", r"兽娘", r"cat girl", r"fox girl")),
    ("Anima/角色/正常/外观与转化/身体装饰", (r"纹身", r"刺青", r"龙纹", r"身体彩绘", r"body painting", r"tattoo")),
    ("Anima/姿势/正常/战斗与动态", (r"战斗", r"攻击", r"施法", r"挥剑", r"对决", r"猛击", r"亮剑", r"躲避爆炸", r"天降魔法", r"battle", r"fighting")),
    ("Anima/姿势/正常/多人互动", (r"拥抱", r"牵手", r"贴贴", r"亲吻", r"合照", r"hug", r"holding hands")),
    ("Anima/姿势/正常/表情与情绪", (r"表情", r"哭泣", r"害羞", r"愤怒", r"嫌弃", r"颜艺", r"邪笑", r"恼怒", r"得意", r"羞红", r"打招呼")),
    ("Anima/姿势/正常/单人动作", (r"伸懒腰", r"跑步", r"跳跃", r"单人动作")),
    ("Anima/背景/正常/室内", (r"室内", r"房间", r"卧室", r"教室", r"浴室", r"interior")),
    ("Anima/背景/正常/室外与自然", (r"室外", r"森林", r"海滩", r"山谷", r"草原", r"outdoors", r"forest")),
    ("Anima/背景/正常/城市与日常", (r"城市", r"街道", r"街景", r"都市", r"小镇", r"咖啡店", r"city")),
    ("Anima/背景/正常/未来科幻", (r"科幻场景", r"太空站", r"赛博城市", r"space station")),
    ("Anima/背景/正常/恐怖扭曲", (r"恐怖场景", r"鬼屋", r"haunted", r"horror")),
)


GENERIC_ALIAS_PATTERNS = (
    r"^(?:原版|原tag|其他版本|另一版本|版本\d*|\d+版|其[一二三四五六七八九十]+|测试|未命名)(?:__\d+)?$",
    r"^(?:原版|其他版本|另一版本)?[_\s-]*\d+(?:__\d+)?$",
)


ADULT_CONTEXT_TERMS = (
    "nsfw", "explicit", "sex", "nude", "naked", "nipples", "pussy", "penis", "cum",
    "orgasm", "masturb", "blowjob", "rape", "vaginal", "anal", "erotic", "uncensored",
    "性交", "性爱", "自慰", "裸体", "强奸", "轮奸", "口交", "足交", "乳交", "几把",
    "小穴", "精液", "中出", "乳头", "露出", "无码", "避孕套", "援交",
)

SAFETY_RISK_TERMS = (
    "幼女", "幼童", "未成年", "小女孩", "小男孩", "正太", "萝莉", "loli", "shota",
    "child", "children", "underage", "minor", "little girl", "little boy",
)


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def source_context_from_category(category_name):
    raw_name = str(category_name or "")
    for prefix in REFERENCE_PREFIXES:
        if raw_name.startswith(prefix):
            source = prefix[:-1]
            # Full-width slashes are part of a source section's display name,
            # not hierarchy separators (for example, 表情包／搞怪).
            section = raw_name[len(prefix):].split("/", 1)[0].replace("／", "/")
            return source, section
    return "", ""


def is_candidate_category(category_name):
    normalized = str(category_name or "").replace("／", "/")
    return category_name in REVIEW_CATEGORIES or normalized.startswith(REFERENCE_PREFIXES)


def canonical_targets(contract):
    return {
        name
        for names in contract.get("canonical_categories", {}).values()
        for name in names
    }


def root_from_category(category_name):
    return root_for_target(str(category_name or "") + "/")


def prompt_text(prompt):
    alias = normalize_text(prompt.get("alias")).strip()
    tags = normalize_text(prompt.get("prompt")).strip()
    description = normalize_text(prompt.get("description")).strip()
    # Repeating the title makes the learned classifier honor user-facing intent.
    return f"标题 {alias} 标题 {alias} 标题 {alias}\n标签 {tags}\n描述 {description}"


def strong_title_root(alias):
    text = normalize_text(alias).strip()
    matches = []
    for root, patterns in STRONG_TITLE_ROOT_PATTERNS.items():
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            matches.append(root)
    return matches[0] if len(matches) == 1 else ""


def alias_root_evidence(alias):
    text = normalize_text(alias).strip()
    matched_roots = []
    for root, terms in ALIAS_ROOT_TERMS.items():
        if any(normalize_text(term) in text for term in terms):
            matched_roots.append(root)
    return matched_roots[0] if len(matched_roots) == 1 else ""


def strong_title_leaf(alias, allowed_targets):
    text = normalize_text(alias).strip()
    matches = []
    for target, patterns in STRONG_TITLE_LEAF_RULES:
        if target not in allowed_targets:
            continue
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            matches.append(target)
    # Rules are ordered from specific actions to incidental identity/clothing.
    # The root model still has to agree before this result can be applied.
    return matches[0] if matches else ""


def is_generic_alias(alias):
    text = normalize_text(alias).strip()
    if not text:
        return True
    return any(re.fullmatch(pattern, text, flags=re.IGNORECASE) for pattern in GENERIC_ALIAS_PATTERNS)


def has_adult_context(prompt, provenance_category):
    if str(provenance_category or "").startswith("所长色色NovelAI个人法典"):
        return True
    combined = f"{normalize_text(prompt.get('alias'))}\n{normalize_text(prompt.get('prompt'))}"
    return any(normalize_text(term) in combined for term in ADULT_CONTEXT_TERMS)


def has_safety_risk(prompt):
    combined = "\n".join(
        normalize_text(prompt.get(field))
        for field in ("alias", "prompt", "description")
    )
    return any(normalize_text(term) in combined for term in SAFETY_RISK_TERMS)


def build_provenance_map(path):
    if not path:
        return {}, ""
    raw = path.read_bytes()
    data = json.loads(raw)
    result = {}
    for category in data.get("categories", []):
        category_name = str(category.get("name") or "")
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            if prompt_id and prompt_id not in result:
                result[prompt_id] = category_name
    return result, sha256_bytes(raw)


def load_prior_applied_moves(report_dir):
    moved_prompt_ids = set()
    reports = []
    if not report_dir.exists():
        return moved_prompt_ids, reports
    for path in sorted(report_dir.glob("anima-second-pass-apply-*.json")):
        try:
            raw = path.read_bytes()
            report = json.loads(raw)
        except (OSError, ValueError):
            continue
        if report.get("stage") != "anima_second_pass_apply":
            continue
        report_ids = {
            str(move.get("prompt_id") or "")
            for move in report.get("moves", [])
            if str(move.get("prompt_id") or "")
        }
        moved_prompt_ids.update(report_ids)
        reports.append({
            "path": str(path),
            "sha256": sha256_bytes(raw),
            "moved_prompt_ids": len(report_ids),
        })
    return moved_prompt_ids, reports


def unique_exact_targets(data, allowed_targets, excluded_prompt_ids=None):
    excluded_prompt_ids = excluded_prompt_ids or set()
    by_prompt = defaultdict(set)
    by_alias_prompt = defaultdict(set)
    for category in data.get("categories", []):
        name = str(category.get("name") or "")
        if name not in allowed_targets:
            continue
        for prompt in category.get("prompts", []):
            if str(prompt.get("id") or "") in excluded_prompt_ids:
                continue
            body = normalize_text(prompt.get("prompt")).strip()
            alias = normalize_text(prompt.get("alias")).strip()
            if body:
                by_prompt[body].add(name)
                by_alias_prompt[(alias, body)].add(name)
    return (
        {key: next(iter(values)) for key, values in by_prompt.items() if len(values) == 1},
        {key: next(iter(values)) for key, values in by_alias_prompt.items() if len(values) == 1},
    )


def fit_model(texts, labels):
    from sklearn.pipeline import make_pipeline
    from sklearn.svm import LinearSVC
    from sklearn.feature_extraction.text import TfidfVectorizer

    return make_pipeline(
        TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 5),
            min_df=2,
            max_df=0.997,
            max_features=140000,
            sublinear_tf=True,
        ),
        LinearSVC(C=1.1, class_weight="balanced", random_state=23),
    ).fit(texts, labels)


def predict_with_margin(model, texts):
    labels = model.predict(texts)
    scores = model.decision_function(texts)
    classes = list(model.classes_)
    if len(classes) == 2:
        scores = [[-float(value), float(value)] for value in scores]
    results = []
    for label, row in zip(labels, scores):
        ordered = sorted((float(value), classes[index]) for index, value in enumerate(row))
        top_score, top_label = ordered[-1]
        second_score = ordered[-2][0] if len(ordered) > 1 else top_score
        results.append({
            "label": str(label),
            "score": round(top_score, 5),
            "margin": round(top_score - second_score, 5),
            "runner_up": ordered[-2][1] if len(ordered) > 1 else "",
        })
    return results


def validate_model(texts, labels, model_name):
    from sklearn.metrics import accuracy_score
    from sklearn.model_selection import train_test_split

    counts = Counter(labels)
    eligible = [index for index, label in enumerate(labels) if counts[label] >= 5]
    if len(set(labels[index] for index in eligible)) < 2 or len(eligible) < 40:
        return {"name": model_name, "evaluated": 0}
    usable_texts = [texts[index] for index in eligible]
    usable_labels = [labels[index] for index in eligible]
    train_texts, test_texts, train_labels, test_labels = train_test_split(
        usable_texts,
        usable_labels,
        test_size=0.2,
        random_state=23,
        stratify=usable_labels,
    )
    model = fit_model(train_texts, train_labels)
    predictions = predict_with_margin(model, test_texts)
    predicted_labels = [prediction["label"] for prediction in predictions]
    result = {
        "name": model_name,
        "evaluated": len(test_labels),
        "accuracy": round(float(accuracy_score(test_labels, predicted_labels)), 4),
        "thresholds": {},
    }
    for threshold in (0.2, 0.35, 0.5, 0.75, 1.0):
        selected = [
            index for index, prediction in enumerate(predictions)
            if prediction["margin"] >= threshold
        ]
        if not selected:
            continue
        correct = sum(predicted_labels[index] == test_labels[index] for index in selected)
        result["thresholds"][str(threshold)] = {
            "coverage": round(len(selected) / len(test_labels), 4),
            "precision": round(correct / len(selected), 4),
            "count": len(selected),
        }
    return result


def build_models(data, allowed_targets, excluded_prompt_ids=None):
    excluded_prompt_ids = excluded_prompt_ids or set()
    training = []
    for category in data.get("categories", []):
        category_name = str(category.get("name") or "")
        if category_name not in allowed_targets:
            continue
        root = root_from_category(category_name)
        if not root:
            continue
        for prompt in category.get("prompts", []):
            if str(prompt.get("id") or "") in excluded_prompt_ids:
                continue
            training.append((prompt_text(prompt), root, category_name))

    texts = [item[0] for item in training]
    roots = [item[1] for item in training]
    root_validation = validate_model(texts, roots, "root")
    root_model = fit_model(texts, roots)

    leaf_models = {}
    leaf_validation = {}
    for root in ROOT_PREFIXES:
        rows = [item for item in training if item[1] == root]
        labels = [item[2] for item in rows]
        if len(set(labels)) < 2:
            continue
        root_texts = [item[0] for item in rows]
        leaf_validation[root] = validate_model(root_texts, labels, f"leaf:{root}")
        leaf_models[root] = fit_model(root_texts, labels)
    return root_model, leaf_models, {
        "training_prompts": len(training),
        "training_categories": len(set(item[2] for item in training)),
        "root": root_validation,
        "leaves": leaf_validation,
    }


def choose_destination(
    prompt,
    current_category,
    provenance_category,
    deterministic,
    root_prediction,
    leaf_predictions,
    exact_prompt_targets,
    exact_alias_prompt_targets,
    allowed_targets,
    min_root_margin,
    min_leaf_margin,
):
    if deterministic.status in {"quarantine", "excluded"}:
        return "", f"deterministic_{deterministic.status}_preserved"
    if has_safety_risk(prompt):
        return "", "explicit_safety_risk_preserved"
    alias = str(prompt.get("alias") or "")
    body = normalize_text(prompt.get("prompt")).strip()
    normalized_alias = normalize_text(alias).strip()
    exact_alias_prompt = exact_alias_prompt_targets.get((normalized_alias, body))
    if exact_alias_prompt:
        return exact_alias_prompt, "exact_canonical_alias_prompt_match"

    title_root = strong_title_root(alias)
    title_leaf = strong_title_leaf(alias, allowed_targets)
    if (
        title_leaf == "Anima/姿势/R18/单人表现/隐秘展示与直播"
        and not has_adult_context(prompt, provenance_category)
    ):
        title_leaf = ""
    if title_leaf:
        title_leaf_root = root_from_category(title_leaf)
        if (
            root_prediction["label"] == title_leaf_root
            and root_prediction["margin"] >= min_root_margin
        ):
            return title_leaf, "strong_title_leaf"

    predicted_root = root_prediction["label"]
    leaf_prediction = leaf_predictions.get(predicted_root)
    if not leaf_prediction:
        return "", "no_leaf_model"
    predicted_leaf = leaf_prediction["label"]
    deterministic_target = deterministic.target if deterministic.target in allowed_targets else ""
    deterministic_root = deterministic.root

    if title_root:
        title_root_leaf = leaf_predictions.get(title_root)
        if not title_root_leaf:
            return "", "title_root_without_leaf_model"
        if deterministic_target and root_from_category(deterministic_target) == title_root:
            if (
                title_root_leaf["label"] == deterministic_target
                and title_root_leaf["margin"] >= max(0.35, min_leaf_margin)
            ):
                return deterministic_target, "strong_title_root_deterministic_leaf"
        if (
            predicted_root == title_root
            and title_root_leaf["margin"] >= max(0.75, min_leaf_margin)
        ):
            return title_root_leaf["label"], "strong_title_root_model_leaf"

    source, section = source_context_from_category(provenance_category)
    section_target = SECTION_TARGETS.get((source, section))
    if (
        section_target
        and section_target in allowed_targets
        and root_from_category(section_target) == predicted_root
        and root_prediction["margin"] >= min_root_margin
        and leaf_prediction["margin"] >= min_leaf_margin
        and not is_generic_alias(alias)
    ):
        return section_target, "source_model_root_agreement"

    return "", "kept_for_review"


def build_audit(
    data,
    source_hash,
    provenance_map,
    provenance_path,
    provenance_hash,
    contract,
    args,
    prior_moved_ids=None,
    prior_apply_reports=None,
):
    prior_moved_ids = prior_moved_ids or set()
    prior_apply_reports = prior_apply_reports or []
    allowed_targets = canonical_targets(contract)
    root_model, leaf_models, validation = build_models(data, allowed_targets, prior_moved_ids)
    exact_prompt_targets, exact_alias_prompt_targets = unique_exact_targets(
        data,
        allowed_targets,
        prior_moved_ids,
    )

    rows = []
    prompts = []
    for category in data.get("categories", []):
        category_name = str(category.get("name") or "")
        if category_name in EXCLUDED_CATEGORIES or not is_candidate_category(category_name):
            continue
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            provenance_category = provenance_map.get(prompt_id, category_name)
            source, section = source_context_from_category(provenance_category)
            deterministic = classify_prompt(
                prompt,
                current_category=category_name,
                reference_source=source,
                reference_section=section,
                contract=contract,
            )
            rows.append((category_name, provenance_category, prompt, deterministic))
            prompts.append(prompt_text(prompt))

    root_predictions = predict_with_margin(root_model, prompts) if prompts else []
    leaf_predictions_by_root = {}
    for root, model in leaf_models.items():
        leaf_predictions_by_root[root] = predict_with_margin(model, prompts) if prompts else []

    decisions = []
    reason_counts = Counter()
    from_counts = Counter()
    to_counts = Counter()
    for index, (current_category, provenance_category, prompt, deterministic) in enumerate(rows):
        root_prediction = root_predictions[index]
        leaf_predictions = {
            root: predictions[index]
            for root, predictions in leaf_predictions_by_root.items()
        }
        target, reason = choose_destination(
            prompt,
            current_category,
            provenance_category,
            deterministic,
            root_prediction,
            leaf_predictions,
            exact_prompt_targets,
            exact_alias_prompt_targets,
            allowed_targets,
            args.min_root_margin,
            args.min_leaf_margin,
        )
        selected = bool(target and target != current_category)
        reason_counts[reason] += 1
        if selected:
            from_counts[current_category] += 1
            to_counts[target] += 1
        decisions.append({
            "prompt_id": str(prompt.get("id") or ""),
            "alias": str(prompt.get("alias") or ""),
            "current_category": current_category,
            "provenance_category": provenance_category,
            "selected": selected,
            "target": target if selected else current_category,
            "reason": reason,
            "title_root": strong_title_root(prompt.get("alias")),
            "title_leaf": strong_title_leaf(prompt.get("alias"), allowed_targets),
            "alias_root_evidence": alias_root_evidence(prompt.get("alias")),
            "deterministic": deterministic.to_dict(),
            "root_model": root_prediction,
            "leaf_model": leaf_predictions.get(root_prediction["label"], {}),
        })

    return {
        "schema_version": 1,
        "stage": "anima_second_pass",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_data": {
            "path": str(args.data),
            "sha256": source_hash,
        },
        "provenance_data": {
            "path": str(provenance_path) if provenance_path else "",
            "sha256": provenance_hash,
            "mapped_prompt_ids": len(provenance_map),
        },
        "policy": {
            "candidate_categories": sorted(REVIEW_CATEGORIES),
            "reference_prefixes": list(REFERENCE_PREFIXES),
            "excluded_categories": sorted(EXCLUDED_CATEGORIES),
            "min_root_margin": args.min_root_margin,
            "min_leaf_margin": args.min_leaf_margin,
            "training_excluded_applied_prompt_ids": len(prior_moved_ids),
            "prior_apply_reports": prior_apply_reports,
        },
        "validation": validation,
        "summary": {
            "candidate_prompts": len(decisions),
            "selected_moves": sum(decision["selected"] for decision in decisions),
            "kept_for_review": sum(not decision["selected"] for decision in decisions),
            "reason_counts": dict(reason_counts.most_common()),
            "from_counts": dict(from_counts.most_common()),
            "to_counts": dict(to_counts.most_common()),
        },
        "decisions": decisions,
    }


def deterministic_category_id(name):
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:16]
    return f"cat-anima-{digest}"


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


def apply_report(data_path, report_path, expected_sha256=""):
    source_bytes = data_path.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    report_hash = str(report.get("source_data", {}).get("sha256") or "").lower()
    if report.get("stage") != "anima_second_pass":
        raise SystemExit("拒绝写入：不是第二轮分类报告。")
    if report_hash != source_hash:
        raise SystemExit(f"拒绝写入：报告基于 {report_hash}，当前数据为 {source_hash}。")
    if expected_sha256 and expected_sha256.lower() != source_hash:
        raise SystemExit(f"拒绝写入：命令要求 {expected_sha256.lower()}，当前数据为 {source_hash}。")

    data = json.loads(source_bytes)
    contract = load_contract()
    allowed_targets = canonical_targets(contract)
    selected = {
        str(decision.get("prompt_id") or ""): decision
        for decision in report.get("decisions", [])
        if decision.get("selected")
    }
    if "" in selected:
        raise SystemExit("拒绝写入：报告中存在空 prompt_id。")

    category_by_name = {}
    original_ids = []
    original_fingerprints = {}
    for category in data.get("categories", []):
        name = str(category.get("name") or "")
        category_by_name[name] = category
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            if not prompt_id or prompt_id in original_fingerprints:
                raise SystemExit(f"拒绝写入：数据中存在空或重复 prompt_id: {prompt_id!r}")
            original_ids.append(prompt_id)
            original_fingerprints[prompt_id] = sha256_bytes(
                json.dumps(prompt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            )

    missing = sorted(set(selected) - set(original_ids))
    if missing:
        raise SystemExit(f"拒绝写入：报告含当前数据不存在的 prompt_id: {missing[:5]}")

    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="microseconds")
    moved_prompts = defaultdict(list)
    applied = []
    new_categories = []
    for category in data.get("categories", []):
        category_copy = copy.copy(category)
        category_name = str(category.get("name") or "")
        kept = []
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            decision = selected.get(prompt_id)
            if not decision:
                kept.append(prompt)
                continue
            if str(decision.get("current_category") or "") != category_name:
                raise SystemExit(
                    f"拒绝写入：{prompt_id} 报告目录 {decision.get('current_category')!r} 与当前 {category_name!r} 不符。"
                )
            target = str(decision.get("target") or "")
            if target not in allowed_targets:
                raise SystemExit(f"拒绝写入：目标不在分类契约中: {target!r}")
            moved_prompts[target].append(prompt)
            applied.append({
                "prompt_id": prompt_id,
                "alias": str(prompt.get("alias") or ""),
                "from": category_name,
                "to": target,
                "reason": decision.get("reason"),
            })
        category_copy["prompts"] = kept
        if len(kept) != len(category.get("prompts", [])):
            category_copy["updated_at"] = now
        normalized_category = category_name.replace("／", "/")
        if kept or not normalized_category.startswith(REFERENCE_PREFIXES):
            new_categories.append(category_copy)

    emitted_targets = set()
    for category in new_categories:
        name = str(category.get("name") or "")
        additions = moved_prompts.get(name)
        if additions:
            category["prompts"] = list(category.get("prompts", [])) + additions
            category["updated_at"] = now
            emitted_targets.add(name)
    for target, prompts in moved_prompts.items():
        if target in emitted_targets:
            continue
        new_categories.append({
            "id": deterministic_category_id(target),
            "name": target,
            "updated_at": now,
            "prompts": prompts,
        })

    migrated = copy.copy(data)
    migrated["categories"] = new_categories
    migrated["last_modified"] = now
    written_ids = [
        str(prompt.get("id") or "")
        for category in new_categories
        for prompt in category.get("prompts", [])
    ]
    written_fingerprints = {
        str(prompt.get("id") or ""): sha256_bytes(
            json.dumps(prompt, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        for category in new_categories
        for prompt in category.get("prompts", [])
    }
    if Counter(written_ids) != Counter(original_ids):
        raise RuntimeError("迁移后 prompt_id 集合发生变化。")
    if written_fingerprints != original_fingerprints:
        raise RuntimeError("迁移后预设内容发生变化；第二轮只允许移动分类。")

    live_hash = sha256_bytes(data_path.read_bytes())
    if live_hash != source_hash:
        raise SystemExit(f"拒绝写入：计算期间数据已从 {source_hash} 变为 {live_hash}。")
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    report_dir = data_path.parent / "classification_reports"
    backup_dir = report_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"data-before-anima-second-pass-{timestamp}-{source_hash[:12]}.json"
    backup_path.write_bytes(source_bytes)
    result_hash, result_size = atomic_write_json(data_path, migrated)
    result = {
        "schema_version": 1,
        "stage": "anima_second_pass_apply",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_hash,
        "result_sha256": result_hash,
        "result_bytes": result_size,
        "classification_report": str(report_path),
        "classification_report_sha256": sha256_bytes(report_bytes),
        "backup": str(backup_path),
        "moved": len(applied),
        "moves": applied,
    }
    result_path = report_dir / f"anima-second-pass-apply-{timestamp}.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result_path, result


def default_provenance_path(data_path):
    backup_dir = data_path.parent / "classification_reports" / "backups"
    candidates = sorted(backup_dir.glob("data-before-anima-semantic-*.json"))
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser(description="Audit and apply a conservative second-pass Anima classification.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit")
    audit.add_argument(
        "--data",
        type=Path,
        default=PLUGIN_DIR / "user_data" / "prompt_selector" / "data.json",
    )
    audit.add_argument("--provenance-data", type=Path, default=None)
    audit.add_argument("--output", type=Path, default=None)
    audit.add_argument("--min-root-margin", type=float, default=0.42)
    audit.add_argument("--min-leaf-margin", type=float, default=0.3)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument(
        "--data",
        type=Path,
        default=PLUGIN_DIR / "user_data" / "prompt_selector" / "data.json",
    )
    apply_parser.add_argument("--report", type=Path, required=True)
    apply_parser.add_argument("--expected-sha256", default="")

    args = parser.parse_args()
    if args.command == "apply":
        result_path, result = apply_report(args.data, args.report, args.expected_sha256)
        print(json.dumps({
            "result": str(result_path),
            "moved": result["moved"],
            "source_sha256": result["source_sha256"],
            "result_sha256": result["result_sha256"],
            "backup": result["backup"],
        }, ensure_ascii=False, indent=2))
        return

    source_bytes = args.data.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    data = json.loads(source_bytes)
    provenance_path = args.provenance_data or default_provenance_path(args.data)
    provenance_map, provenance_hash = build_provenance_map(provenance_path)
    prior_moved_ids, prior_apply_reports = load_prior_applied_moves(
        args.data.parent / "classification_reports"
    )
    contract = load_contract()
    report = build_audit(
        data,
        source_hash,
        provenance_map,
        provenance_path,
        provenance_hash,
        contract,
        args,
        prior_moved_ids,
        prior_apply_reports,
    )
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.output = args.data.parent / "classification_reports" / f"anima-second-pass-audit-{timestamp}.json"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(args.output),
        "source_sha256": source_hash,
        "validation": report["validation"],
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
