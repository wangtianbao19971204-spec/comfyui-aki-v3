import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
PROMPT_SELECTOR_DIR = TOOLS_DIR.parent
PLUGIN_DIR = PROMPT_SELECTOR_DIR.parent
for module_path in (PROMPT_SELECTOR_DIR, TOOLS_DIR):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

from anima_second_pass import (  # noqa: E402
    EXCLUDED_CATEGORIES,
    canonical_targets,
    deterministic_category_id,
    has_adult_context,
    has_safety_risk,
    is_candidate_category,
    is_generic_alias,
    root_from_category,
    source_context_from_category,
    strong_title_leaf,
)
from anima_tag_classifier import (  # noqa: E402
    LEAF_RULES,
    LEGACY_TARGETS,
    SECTION_ROOT_HINTS,
    SECTION_TARGETS,
    _matched_terms,
    load_contract,
    normalize_text,
)
from anima_tag_semantic_pass import extract_tags, semantic_title_roots  # noqa: E402


@dataclass(frozen=True)
class ManagedRule:
    target: str
    terms: tuple
    min_hits: int = 1
    bonus: int = 0


@dataclass(frozen=True)
class CapacityRule:
    target: str
    terms: tuple


def managed_rule(target, terms, min_hits=1, bonus=0):
    return ManagedRule(target, tuple(terms), min_hits, bonus)


def capacity_rule(target, terms):
    return CapacityRule(target, tuple(terms))


ROOT_DEFAULTS = {
    "character": "Anima/角色/正常/人物模板/通用人物模板",
    "clothing": "Anima/服装/正常/日常与季节/完整穿搭",
    "pose": "Anima/姿势/正常/基础姿态/综合姿态",
    "background": "Anima/背景/正常/人物环境/综合人物环境",
}

ADULT_POSE_DEFAULTS = {
    "single": "Anima/姿势/R18/情境/成人日常/单人",
    "pair": "Anima/姿势/R18/情境/成人日常/双人",
    "group": "Anima/姿势/R18/情境/成人日常/多人",
}

MODEL_ROOT_MIN_MARGIN = 0.75
MODEL_LEAF_MIN_MARGIN = 0.75

TITLE_POSE_PATTERN = re.compile(
    r"小憩|休息|聚餐|就餐|进食|吃|喝|饮|抓|抱|搂|亲吻|舔|咬|摸|触|拍打|踩|踢|"
    r"挥|举|持|拿|坐姿|跪|蹲|躺|趴|弯腰|站立|行走|散步|奔跑|跑步|跳跃|空降|"
    r"起舞|跳舞|战斗|攻击|袭警|袭击|施法|练剑|拔剑|射击|逃脱|追逐|等待|仰望|"
    r"比心|画画|作画|佯装|自信一指|指向|竖中指|中指|生气|愤怒|厌恶|嫌弃|害羞|"
    r"慌张|惊讶|困惑|得意|开心|悲伤|倚栏|倒挂|"
    r"悬挂|穿(?:上|着|戴|鞋|袜|衣|胸罩)|给[^，,\s]{0,5}穿|"
    r"脱(?:下|光|掉|去)?[^，,\s]{0,6}(?:衣|裙|裤|袜|鞋|胸罩|内衣)|半脱|掀|拉下|"
    r"拉开|拉[^，,\s]{0,4}裙|扯开|调整|拧干|挤干|晾衣|收衣|擦窗|清洗|淋雨|"
    r"洗澡|洗浴|沐浴|泡水|潜水|游泳|做饭|烹饪|读书|"
    r"写字|睡觉|睡眠|做梦|搬运|拖拽|背负|被制服|柔道|摔跤|格斗|坠落|落下|而落|"
    r"起身|爬出|托起|抬起|胸压|拉弓|采摘|采蘑菇|采收|拾叶|买菜|回家|掌中|怀中|产卵|产下|"
    r"产台球|展示|露出|裙底|鞋底|"
    r"分穴|扩张|精液浴|塞袜|玩具|"
    r"诱惑|邀请|涩涩|挑衅|拒绝|哭|笑|颜艺|表情|自拍|直播|偷拍|合影|合照|喂食|送礼|"
    r"开门|接见|摆拍|侍奉|调教|侵犯|性交|性爱|做爱|爆炒|脑交|腿间交|自慰|口交|"
    r"足交|乳交|后入|骑身|骑乘|插入|指奸|塞满|塞入|玩具遥控|捆绑|拘束|绳缚|"
    r"手缚|吊[^，,\s]{0,4}缚|催眠|围攻|寡不敌众|侧像|背影|遛",
    re.IGNORECASE,
)
TITLE_CLOTHING_PATTERN = re.compile(
    r"服装|服饰|衣装|穿搭|套装|装束|制服|校服|军装|礼服|裙|裤|衫|外套|内衣|"
    r"泳装|泳衣|比基尼|睡衣|胶衣|旗袍|汉服|和服|浴衣|鞋|靴|袜|帽|眼镜|墨镜|"
    r"面纱|披风|围巾|手套|护甲|盔甲|铠甲|兔女郎|女仆装|护士服|cosplay",
    re.IGNORECASE,
)
TITLE_CHARACTER_PATTERN = re.compile(
    r"角色|人设|人物设定|人物形象|少女|女孩|女人|女性|男子|男孩|骑士|战士|法师|"
    r"术士|修女|护士|园丁|老师|教师|学生|偶像|歌手|长官|将军|护卫|弓手|射手|仙子|"
    r"魔女|女巫|机娘|机器人|人偶|手办|玩偶|fumo|q版|精灵|恶魔|天使|鬼影|幽灵|"
    r"僵尸|兽人|猫娘|狐娘|龙娘|魔物娘|人外|夜叉|女王|女神|御姐|妈妈|人妻|"
    r"灰皮|骨骼化|翅膀|耀翼|分离|分解|融化|逸散|散于空中|身材|体型|肤色|发型|"
    r"脸型|外貌|气质",
    re.IGNORECASE,
)
TITLE_BACKGROUND_PATTERN = re.compile(
    r"场景|背景|环境|房间|室内|室外|卧室|教室|浴室|厨房|客厅|餐厅|酒吧|咖啡厅|"
    r"地牢|监狱|牢房|森林|海边|海滩|沙滩|泳池|山谷|田野|花园|城市|街道|小巷|"
    r"车内|电车|站台|舞台|太空|天空|雨中|雪景|夜景|日落|黄昏|教堂|废墟|医院|"
    r"超市|公园|水下|轮船|码头|雪中|雪原|寺庙|灯泡|画框|窗口",
    re.IGNORECASE,
)
STYLE_ALIAS_PATTERN = re.compile(
    r"画师|质量词|负面词|风格串|滤镜|色调|线稿|草稿|厚涂|水彩|油画|贴纸|明信片|"
    r"分镜|排版|字效|禁止标志|logo|(?:原版?|附带|并收)[^，,]{0,6}画风[，,\s]*$|"
    r"减淡边框|喷漆色彩|悬赏公告|推特照片|故障剪影|数据删除|杂志封面|游戏界面|"
    r"通缉令|错误删除|错误数据|类似效果tag|随机时尚杂志封面|理论上是游戏界面|"
    r"人物痛车|电脑屏幕",
    re.IGNORECASE,
)
STYLE_TAG_TERMS = (
    "artist:", "style", "artstyle", "sketch", "lineart", "watercolor", "oil painting",
    "crayon line", "thick line", "sticker style", "postcard", "vintage postcard",
    "pixel art", "monochrome", "best quality", "masterpiece", "very aesthetic",
    "fake screenshot", "glitch", "glitch art", "pixel sorting", "datamosh", "distortion",
    "digital dissolve", "disintegration", "magazine cover", "wanted poster", "typography",
    "error message", "chromatic aberration", "multiple views", "through screen", "gameplay mechanics",
    "year 2022", "year 2023", "year 2024", "year 2025", "year 2026",
)
CONTENT_TAG_TERMS = (
    "girl", "boy", "woman", "man", "character", "dress", "shirt", "skirt", "uniform",
    "standing", "sitting", "lying", "kneeling", "eating", "drinking", "fighting",
    "indoors", "outdoors", "bedroom", "street", "forest", "beach", "ship", "wharf",
    "sex", "nude",
)
ROOT_GARMENT_TERMS = (
    "dress", "shirt", "skirt", "jacket", "coat", "pants", "shorts", "uniform", "bra",
    "panties", "stockings", "thighhighs", "boots", "shoes", "hat", "gloves", "outfit",
    "armor", "armour", "breastplate", "chainmail", "sleeves", "bodysuit", "clothes", "costume", "cape",
)
ROOT_BODY_TEMPLATE_TERMS = (
    "body", "figure", "petite", "mature", "muscular", "plump", "chubby", "skinny",
    "skin", "hair", "eyes", "face", "breasts", "hips", "thighs", "calves", "waist",
)
ROOT_BACKGROUND_TERMS = (
    "scenery", "landscape", "indoors", "outdoors", "bedroom", "bathroom", "classroom",
    "kitchen", "restaurant", "street", "city", "forest", "beach", "ocean", "mountain",
    "garden", "field", "river", "sky", "ship", "wharf", "stage", "dungeon", "castle",
)
ROOT_CHARACTER_TERMS = (
    "character", "monster girl", "android", "cyborg", "robot", "doll", "fumo", "nendoroid",
    "elf", "demon", "angel", "witch", "mermaid", "furry", "skin", "body type", "figure",
)
EXPLICIT_POSE_BODY_PATTERN = re.compile(
    r"\b(?:sex|vaginal|anal|penetration|blowjob|fellatio|handjob|footjob|paizuri|"
    r"masturbation|fingering|groping|doggystyle|cowgirl|missionary|rape|bondage|"
    r"spread pussy|pussy spread|dressing another|undressing|sex toy|vibrator)\b",
    re.IGNORECASE,
)

BROAD_PROVENANCE_ROOTS = {
    "Anima/角色/正常/人物形象": "character",
    "Anima/角色/R18/非原创人物": "character",
    "Anima/角色/正常/其他": "character",
    "Anima/服装/正常/其他": "clothing",
    "Anima/姿势/R18/另类日常": "pose",
    "Anima/背景/正常/人物环境": "background",
}

PROVENANCE_TARGETS = {
    "Anima/姿势/R18/诱惑": "Anima/姿势/R18/单人表现/诱惑",
    "Anima/姿势/R18/调戏猥亵": "Anima/姿势/R18/双人互动/调戏与猥亵",
    "Anima/姿势/R18/裙底小穴臀部": "Anima/姿势/R18/身体构图/臀裆部",
    "Anima/姿势/R18/足底展示": "Anima/姿势/R18/身体构图/腿足",
    "Anima/姿势/R18/胸腹部": "Anima/姿势/R18/身体构图/胸腹部",
    "Anima/姿势/R18/百合": "Anima/姿势/R18/多人互动/百合",
    "Anima/姿势/R18/口交（类口交颜射）": "Anima/姿势/R18/非插入互动/口交与颜射",
    "Anima/姿势/R18/协作侍奉": "Anima/姿势/R18/多人互动/协作侍奉",
    "Anima/姿势/R18/后入背后位": "Anima/姿势/R18/体位/后入与背后位",
    "Anima/姿势/R18/双飞多飞": "Anima/姿势/R18/多人互动/双飞与多人",
    "Anima/姿势/R18/素股摩擦腋下": "Anima/姿势/R18/非插入互动/身体摩擦",
    "Anima/姿势/R18/futa特辑": "Anima/角色/R18/成人身份/扶她",
    "Anima/姿势/R18/伪娘男娘特辑": "Anima/角色/R18/成人身份/伪娘与男娘",
    "Anima/背景/R18/色色场景": "Anima/背景/R18/成人场所",
    "Anima/背景/R18/触手": "Anima/姿势/R18/重口/异种互动/触手",
    "Anima/角色/R18/魔物娘": "Anima/角色/R18/成人种族/魔物娘与人外",
    "Anima/角色/R18/其他异种": "Anima/角色/R18/成人种族/魔物娘与人外",
    "Anima/角色/R18/人外": "Anima/角色/R18/成人种族/魔物娘与人外",
    "Anima/服装/R18/宠物调教": "Anima/姿势/R18/拘束/宠物调教",
    "Anima/服装/R18/节日献礼": "Anima/姿势/R18/情境/节庆献礼",
    "Anima/服装/兔女郎": "Anima/服装/正常/幻想与主题/兔女郎",
    "Anima/服装/舞娘": "Anima/服装/正常/幻想与主题/舞娘",
    "Anima/角色/魔法特辑": "Anima/角色/正常/身份与职业/魔法角色",
    "Anima/角色/运动人员": "Anima/角色/正常/身份与职业/运动人员",
    "Anima/角色/野族传说": "Anima/角色/正常/身份与职业/野族角色",
    "Anima/角色/非常规职业": "Anima/角色/正常/身份与职业/非常规职业",
    "Anima/姿势/正常/战斗华丽": "Anima/姿势/正常/战斗与动态",
    "Anima/姿势/正常/情感动作": "Anima/姿势/正常/表情与情绪",
    "Anima/背景/正常/室外": "Anima/背景/正常/室外与自然",
}

MANAGED_RULES = (
    managed_rule("Anima/姿势/正常/基础姿态/躺卧与趴伏", (
        "lying", "on back", "on stomach", "prone", "on side", "reclining", "all fours",
        "躺", "趴伏", "侧卧",
    ), bonus=7),
    managed_rule("Anima/姿势/正常/基础姿态/坐姿与跪姿", (
        "sitting", "kneeling", "squatting", "seiza", "wariza", "indian style", "knees up",
        "坐姿", "跪姿", "蹲姿",
    ), bonus=6),
    managed_rule("Anima/姿势/正常/基础姿态/站立与行走", (
        "standing", "walking", "contrapposto", "leaning", "tiptoe", "站立", "行走",
    ), bonus=5),
    managed_rule("Anima/姿势/正常/基础姿态/手势与持物", (
        "hand up", "hands up", "arm up", "arms up", "pointing", "waving", "holding object",
        "holding cup", "holding phone", "hand on own", "手势", "持物",
    ), min_hits=2, bonus=5),
    managed_rule("Anima/姿势/正常/单人动作", (
        "dressing", "undressing", "putting on", "taking off", "adjusting clothes", "穿衣", "脱衣", "整理服装",
    ), bonus=10),
    managed_rule("Anima/姿势/正常/单人动作", (
        "bathing", "showering", "washing", "swimming", "diving", "falling", "skydiving",
        "crawling out", "standing up", "getting up", "carrying", "holding books", "洗浴", "泡水", "潜水", "起身", "搬运",
    ), bonus=10),
    managed_rule("Anima/姿势/正常/表情与情绪", (
        "angry", "disgusted", "annoyed", "embarrassed", "shy", "panicked", "surprised",
        "confused", "happy", "sad", "生气", "愤怒", "厌恶", "嫌弃", "害羞", "慌张", "惊讶", "困惑",
    ), bonus=4),
    managed_rule("Anima/姿势/正常/战斗与动态", (
        "judo", "wrestling", "grappling", "martial arts", "fighting", "combat", "柔道", "摔跤", "格斗",
    ), bonus=11),
    managed_rule("Anima/姿势/R18/身体构图/臀裆部", (
        "spread pussy", "pussy spread", "spread labia", "spread ass", "genital focus", "pussy focus", "分穴",
    ), bonus=11),
    managed_rule("Anima/姿势/R18/身体构图/胸腹部", (
        "grabbing own breast", "breast hold", "breast lift", "breast focus", "chest focus", "胸部特写", "托胸",
    ), bonus=10),
    managed_rule("Anima/姿势/R18/双人互动/调戏与猥亵/腿足与腋下", (
        "foot licking", "licking foot", "feet on mouth", "mouth hold feet", "舔脚",
    ), bonus=11),
    managed_rule("Anima/姿势/R18/重口/暴力/暴虐与过激", (
        "fist in nipple", "nipple insertion", "fisting nipple", "乳孔", "拳交乳孔",
    ), bonus=12),
    managed_rule("Anima/服装/正常/制服与职业/职业制服", (
        "maid", "maid headdress", "apron", "nurse", "doctor", "police", "office lady",
        "chef", "waitress", "stewardess", "修女", "护士", "女仆",
    ), min_hits=2, bonus=8),
    managed_rule("Anima/服装/正常/日常与季节/冬装", (
        "coat", "winter", "scarf", "sweater", "turtleneck", "jacket", "gloves",
    ), min_hits=3, bonus=4),
    managed_rule("Anima/服装/正常/日常与季节/夏装", (
        "sundress", "tank top", "short shorts", "crop top", "sandals", "summer",
    ), min_hits=2, bonus=4),
    managed_rule("Anima/服装/正常/日常与季节/完整穿搭", (
        "shirt", "skirt", "dress", "jacket", "pants", "shorts", "shoes", "boots", "socks",
        "thighhighs", "pantyhose", "gloves", "hat", "服装", "穿搭",
    ), min_hits=4),
    managed_rule("Anima/服装/正常/组件与配饰", (
        "bandage", "bandages", "medical bandages", "wrappings", "绷带", "包扎",
    ), bonus=8),
    managed_rule("Anima/服装/R18/暴露与改造/综合成人穿搭", (
        "no bra", "no panties", "bottomless", "topless", "revealing clothes", "micro skirt",
        "sideboob", "underboob", "areola slip", "crotch cutout",
    ), min_hits=3, bonus=5),
    managed_rule("Anima/角色/正常/人物模板/可爱与Q版", (
        "chibi", "chibi only", "cute", "petite", "doll-like", "q版", "可爱",
    ), min_hits=2, bonus=7),
    managed_rule("Anima/角色/正常/人物模板/成熟与写实", (
        "mature female", "mature woman", "middle-aged", "realistic", "photorealistic", "成熟",
    ), bonus=6),
    managed_rule("Anima/角色/正常/人物模板/奇幻人物模板", (
        "fantasy", "elf", "demon", "angel", "fairy", "witch", "mage", "异色皮肤",
    ), min_hits=2, bonus=5),
    managed_rule("Anima/角色/正常/种族与形态/人工造物", (
        "fumo", "doll", "nendoroid", "figurine", "action figure", "android", "robot", "玩偶", "手办",
    ), bonus=9),
    managed_rule("Anima/角色/正常/身份与职业/魔法角色", (
        "mage", "witch", "sorcerer", "wizard", "magic user", "法师", "术士", "魔女", "女巫",
    ), bonus=7),
    managed_rule("Anima/角色/正常/身份与职业/常规职业", (
        "teacher", "nurse", "doctor", "gardener", "office lady", "chef", "waitress", "老师", "护士", "园丁",
    ), bonus=6),
    managed_rule("Anima/角色/正常/身份与职业/非常规职业", (
        "knight", "warrior", "guard", "general", "assassin", "pilot", "singer", "archer", "骑士", "战士", "护卫", "将军", "歌手", "弓手",
    ), bonus=6),
    managed_rule("Anima/角色/正常/外观与转化/人物转化", (
        "dissolving body", "disintegration", "body fall apart", "melting", "transformation", "分离", "分解", "融化", "逸散",
    ), bonus=8),
    managed_rule("Anima/角色/正常/外观与转化/人物外观", (
        "insect wings", "energy wings", "holographic cloth", "glowing wings", "mechanical wings", "翅膀", "耀翼",
    ), min_hits=2, bonus=8),
    managed_rule("Anima/角色/正常/作品角色/单机角色", (
        "sonic the hedgehog", "索尼克",
    ), bonus=10),
    managed_rule("Anima/背景/正常/人物环境/室内人物场景", (
        "indoors", "bedroom", "classroom", "bathroom", "kitchen", "living room", "hotel room",
    ), min_hits=2, bonus=4),
    managed_rule("Anima/背景/正常/人物环境/室外人物场景", (
        "outdoors", "forest", "beach", "garden", "field", "mountain", "river", "sky",
    ), min_hits=2, bonus=4),
)


CAPACITY_SPLITS = {
    "Anima/角色/正常/种族与形态/人工造物": (
        capacity_rule("Anima/角色/正常/种族与形态/人工造物/机器人与机甲", (
            "android", "cyborg", "robot", "mecha", "mechanical", "机器人", "机娘", "机甲",
        )),
        capacity_rule("Anima/角色/正常/种族与形态/人工造物/人偶与手办", (
            "doll", "fumo", "nendoroid", "figurine", "mannequin", "人偶", "玩偶", "手办",
        )),
        capacity_rule("Anima/角色/正常/种族与形态/人工造物/综合人工造物", ()),
    ),
    "Anima/姿势/正常/基础姿态/坐姿与跪姿": (
        capacity_rule("Anima/姿势/正常/基础姿态/坐姿与跪姿/跪姿与正坐", (
            "kneeling", "seiza", "wariza", "on knees", "跪姿", "正坐",
        )),
        capacity_rule("Anima/姿势/正常/基础姿态/坐姿与跪姿/蹲姿与屈膝", (
            "squatting", "crouching", "knees up", "hugging knees", "蹲姿", "屈膝",
        )),
        capacity_rule("Anima/姿势/正常/基础姿态/坐姿与跪姿/椅凳与座位", (
            "chair", "stool", "bench", "couch", "sofa", "seat", "椅子", "座位",
        )),
        capacity_rule("Anima/姿势/正常/基础姿态/坐姿与跪姿/地面坐姿", (
            "on floor", "sitting on ground", "crossed legs", "indian style", "地面", "席地",
        )),
        capacity_rule("Anima/姿势/正常/基础姿态/坐姿与跪姿/综合坐姿", ()),
    ),
    "Anima/服装/正常/日常与季节/完整穿搭": (
        capacity_rule("Anima/服装/正常/日常与季节/完整穿搭/外套与叠穿", (
            "jacket", "coat", "cardigan", "blazer", "hoodie", "sweater", "capelet", "披风", "外套",
        )),
        capacity_rule("Anima/服装/正常/日常与季节/完整穿搭/裙装与连衣裙", (
            "dress", "skirt", "gown", "sundress", "miniskirt", "long skirt", "连衣裙", "裙装",
        )),
        capacity_rule("Anima/服装/正常/日常与季节/完整穿搭/裤装与休闲", (
            "pants", "shorts", "jeans", "trousers", "slacks", "overalls", "裤装", "短裤",
        )),
        capacity_rule("Anima/服装/正常/日常与季节/完整穿搭/综合成套", ()),
    ),
    "Anima/姿势/R18/非插入互动/口交与颜射": (
        capacity_rule("Anima/姿势/R18/非插入互动/口交与颜射/舔阴与女性口交", ("cunnilingus", "pussy licking", "oral on female", "舔阴")),
        capacity_rule("Anima/姿势/R18/非插入互动/口交与颜射/深喉与强制口交", ("deepthroat", "irrumatio", "facefuck", "gagging", "throat", "深喉")),
        capacity_rule("Anima/姿势/R18/非插入互动/口交与颜射/颜射与口内", ("facial", "cum in mouth", "oral cum", "cum on face", "颜射", "口内")),
        capacity_rule("Anima/姿势/R18/非插入互动/口交与颜射/跪姿口交", ("kneeling", "on knees", "跪")),
        capacity_rule("Anima/姿势/R18/非插入互动/口交与颜射/常规口交", ()),
    ),
    "Anima/姿势/正常/战斗与动态": (
        capacity_rule("Anima/姿势/正常/战斗与动态/魔法与技能", ("magic", "spell", "casting", "energy", "aura", "魔法", "施法")),
        capacity_rule("Anima/姿势/正常/战斗与动态/枪械与远程", ("gun", "rifle", "pistol", "bow and arrow", "shooting", "firearm", "弓箭", "枪")),
        capacity_rule("Anima/姿势/正常/战斗与动态/武器近战", ("sword", "katana", "knife", "spear", "axe", "weapon", "挥剑", "近战")),
        capacity_rule("Anima/姿势/正常/战斗与动态/高速与冲击", ("motion blur", "speed lines", "impact", "explosion", "flying debris", "dynamic angle", "冲击", "爆炸")),
        capacity_rule("Anima/姿势/正常/战斗与动态/综合战斗姿态", ()),
    ),
    "Anima/姿势/R18/多人互动/百合": (
        capacity_rule("Anima/姿势/R18/多人互动/百合/口舌与亲吻", ("cunnilingus", "kissing", "tongue kiss", "oral", "亲吻", "舔阴")),
        capacity_rule("Anima/姿势/R18/多人互动/百合/摩擦与玩具", ("tribadism", "grinding", "sex toy", "dildo", "strap-on", "摩擦", "玩具")),
        capacity_rule("Anima/姿势/R18/多人互动/百合/胸臀爱抚", ("breast grab", "groping", "ass grab", "breast press", "揉胸")),
        capacity_rule("Anima/姿势/R18/多人互动/百合/多人百合", ("3girls", "4girls", "multiple girls", "group sex", "多人")),
        capacity_rule("Anima/姿势/R18/多人互动/百合/综合亲密互动", ()),
    ),
    "Anima/姿势/正常/表情与情绪": (
        capacity_rule("Anima/姿势/正常/表情与情绪/悲伤与哭泣", ("crying", "tears", "sad", "sobbing", "哭", "悲伤")),
        capacity_rule("Anima/姿势/正常/表情与情绪/愤怒与厌恶", ("angry", "disgust", "disgusted", "disdain", "annoyed", "frown", "生气", "厌恶", "嫌弃", "愤怒")),
        capacity_rule("Anima/姿势/正常/表情与情绪/害羞与慌张", ("embarrassed", "shy", "panicked", "nervous", "flustered", "害羞", "慌张")),
        capacity_rule("Anima/姿势/正常/表情与情绪/惊讶与困惑", ("surprised", "confused", "question mark", "shocked", "惊讶", "疑惑")),
        capacity_rule("Anima/姿势/正常/表情与情绪/开心与得意", ("laughing", "happy", "smug", "grin", "evil smile", "开心", "得意")),
        capacity_rule("Anima/姿势/正常/表情与情绪/夸张颜艺", ()),
    ),
    "Anima/姿势/R18/拘束/捆绑姿势": (
        capacity_rule("Anima/姿势/R18/拘束/捆绑姿势/悬吊与倒挂", ("suspension", "suspended", "hanging", "upside-down", "吊缚", "倒吊")),
        capacity_rule("Anima/姿势/R18/拘束/捆绑姿势/四肢固定", ("bound arms", "bound legs", "bound ankles", "hands tied", "feet tied", "hogtie", "四肢")),
        capacity_rule("Anima/姿势/R18/拘束/捆绑姿势/绳缚与龟甲缚", ("rope", "shibari", "kinbaku", "harness", "绳缚", "龟甲缚")),
        capacity_rule("Anima/姿势/R18/拘束/捆绑姿势/跪坐与躺卧拘束", ("kneeling", "sitting", "lying", "on bed", "跪", "躺")),
        capacity_rule("Anima/姿势/R18/拘束/捆绑姿势/综合拘束姿态", ()),
    ),
    "Anima/姿势/R18/双人互动/事后": (
        capacity_rule("Anima/姿势/R18/双人互动/事后/体内与流出", ("cumdrip", "cum in pussy", "cum in ass", "creampie", "流出", "中出")),
        capacity_rule("Anima/姿势/R18/双人互动/事后/颜面与口内痕迹", ("facial", "cum in mouth", "cum on face", "口内", "颜面")),
        capacity_rule("Anima/姿势/R18/双人互动/事后/体表痕迹", ("cum on body", "cum on breasts", "cum on stomach", "cum on ass", "体表")),
        capacity_rule("Anima/姿势/R18/双人互动/事后/疲惫与余韵", ()),
    ),
    "Anima/姿势/R18/体位/后入与背后位": (
        capacity_rule("Anima/姿势/R18/体位/后入与背后位/俯卧后入", ("prone bone", "on stomach", "lying prone", "俯卧")),
        capacity_rule("Anima/姿势/R18/体位/后入与背后位/站立后入", ("standing sex", "standing", "against wall", "站立")),
        capacity_rule("Anima/姿势/R18/体位/后入与背后位/侧卧与躺卧", ("on side", "lying", "spooning", "侧卧", "躺卧")),
        capacity_rule("Anima/姿势/R18/体位/后入与背后位/跪趴后入", ("all fours", "kneeling", "doggystyle", "跪趴")),
        capacity_rule("Anima/姿势/R18/体位/后入与背后位/其他背后位", ()),
    ),
    "Anima/姿势/R18/双人互动/调戏与猥亵": (
        capacity_rule("Anima/姿势/R18/双人互动/调戏与猥亵/胸部爱抚", ("breast grab", "groping breasts", "nipple", "揉胸", "摸胸")),
        capacity_rule("Anima/姿势/R18/双人互动/调戏与猥亵/臀裆触摸", ("ass grab", "crotch grab", "pussy", "groin", "摸臀", "扣穴")),
        capacity_rule("Anima/姿势/R18/双人互动/调戏与猥亵/腿足与腋下", ("thigh", "leg", "foot", "armpit", "摸腿", "腋下")),
        capacity_rule("Anima/姿势/R18/双人互动/调戏与猥亵/综合爱抚", ()),
    ),
    "Anima/姿势/R18/单人表现/诱惑": (
        capacity_rule("Anima/姿势/R18/单人表现/诱惑/表情与视线", ("seductive smile", "half-closed eyes", "bedroom eyes", "lip bite", "媚眼")),
        capacity_rule("Anima/姿势/R18/单人表现/诱惑/服装与半脱", ("clothes lift", "shirt lift", "skirt lift", "open clothes", "undressing", "半脱")),
        capacity_rule("Anima/姿势/R18/单人表现/诱惑/身体展示", ("spread legs", "arched back", "breast hold", "ass focus", "展示")),
        capacity_rule("Anima/姿势/R18/单人表现/诱惑/邀请姿态", ()),
    ),
    "Anima/姿势/正常/多人互动": (
        capacity_rule("Anima/姿势/正常/多人互动/亲吻与拥抱", ("kissing", "hug", "hugging", "亲吻", "拥抱")),
        capacity_rule("Anima/姿势/正常/多人互动/牵手与陪伴", ("holding hands", "handshake", "arm around", "牵手", "陪伴")),
        capacity_rule("Anima/姿势/正常/多人互动/抱起与背负", ("carrying another", "princess carry", "piggyback", "抱起", "背负")),
        capacity_rule("Anima/姿势/正常/多人互动/群体与合影", ()),
    ),
    "Anima/服装/正常/制服与职业/职业制服": (
        capacity_rule("Anima/服装/正常/制服与职业/职业制服/女仆与服务", ("maid", "waitress", "stewardess", "apron", "女仆", "服务员")),
        capacity_rule("Anima/服装/正常/制服与职业/职业制服/医疗", ("nurse", "doctor", "medical", "护士", "医生")),
        capacity_rule("Anima/服装/正常/制服与职业/职业制服/办公商务", ("office lady", "business suit", "secretary", "office", "职员", "商务")),
        capacity_rule("Anima/服装/正常/制服与职业/职业制服/治安与公共职业", ("police", "firefighter", "security", "delivery", "警察", "消防")),
        capacity_rule("Anima/服装/正常/制服与职业/职业制服/其他职业制服", ()),
    ),
    "Anima/服装/R18/暴露与改造/日常改造": (
        capacity_rule("Anima/服装/R18/暴露与改造/日常改造/掀衣展示", ("clothes lift", "shirt lift", "dress lift", "skirt lift", "掀衣")),
        capacity_rule("Anima/服装/R18/暴露与改造/日常改造/敞开与解扣", ("open clothes", "open shirt", "open jacket", "unbuttoned", "敞开", "解扣")),
        capacity_rule("Anima/服装/R18/暴露与改造/日常改造/下拉与半脱", ("clothes pull", "panties pull", "pants pull", "undressing", "half-dressed", "下拉", "半脱")),
        capacity_rule("Anima/服装/R18/暴露与改造/日常改造/破损与透视", ("torn clothes", "see-through", "wet clothes", "transparent", "破衣", "透视")),
        capacity_rule("Anima/服装/R18/暴露与改造/日常改造/综合日常改造", ()),
    ),
    "Anima/姿势/R18/单人表现/自慰": (
        capacity_rule("Anima/姿势/R18/单人表现/自慰/玩具自慰", ("dildo", "vibrator", "sex toy", "machine", "玩具")),
        capacity_rule("Anima/姿势/R18/单人表现/自慰/手指自慰", ("fingering self", "fingers in pussy", "hand in panties", "指交", "手指")),
        capacity_rule("Anima/姿势/R18/单人表现/自慰/摩擦与隔衣", ("rubbing", "grinding", "through clothes", "pillow humping", "摩擦", "隔衣")),
        capacity_rule("Anima/姿势/R18/单人表现/自慰/综合自慰", ()),
    ),
    "Anima/姿势/R18/重口/异种互动/触手": (
        capacity_rule("Anima/姿势/R18/重口/异种互动/触手/口部互动", ("tentacle in mouth", "oral", "mouth", "口部")),
        capacity_rule("Anima/姿势/R18/重口/异种互动/触手/插入与侵入", ("penetration", "tentacle sex", "vaginal", "anal", "插入")),
        capacity_rule("Anima/姿势/R18/重口/异种互动/触手/拘束与缠绕", ("bound", "restrained", "wrapped", "entangled", "拘束", "缠绕")),
        capacity_rule("Anima/姿势/R18/重口/异种互动/触手/覆盖与服装", ("tentacle clothes", "covered by tentacles", "tentacle suit", "覆盖", "触手服")),
        capacity_rule("Anima/姿势/R18/重口/异种互动/触手/综合触手互动", ()),
    ),
    "Anima/姿势/R18/单人表现/暴露": (
        capacity_rule("Anima/姿势/R18/单人表现/暴露/公共场所暴露", ("public nudity", "exhibitionism", "outdoors", "street", "public", "公共")),
        capacity_rule("Anima/姿势/R18/单人表现/暴露/掀衣与敞开", ("clothes lift", "shirt lift", "skirt lift", "open clothes", "掀衣", "敞开")),
        capacity_rule("Anima/姿势/R18/单人表现/暴露/意外走光", ("wardrobe malfunction", "accidental exposure", "slip", "走光", "意外")),
        capacity_rule("Anima/姿势/R18/单人表现/暴露/裸体展示", ()),
    ),
    "Anima/服装/正常/地域与时代/中国": (
        capacity_rule("Anima/服装/正常/地域与时代/中国/旗袍", ("qipao", "cheongsam", "china dress", "旗袍")),
        capacity_rule("Anima/服装/正常/地域与时代/中国/汉服", ("hanfu", "ruqun", "交领", "汉服")),
        capacity_rule("Anima/服装/正常/地域与时代/中国/仙侠与古风", ("xianxia", "wuxia", "cultivator", "仙侠", "武侠", "古风")),
        capacity_rule("Anima/服装/正常/地域与时代/中国/其他传统服饰", ()),
    ),
    "Anima/姿势/R18/身体构图/腿足": (
        capacity_rule("Anima/姿势/R18/身体构图/腿足/足底与脚趾", ("sole", "soles", "toes", "foot focus", "feet focus", "足底", "脚趾")),
        capacity_rule("Anima/姿势/R18/身体构图/腿足/腿部与大腿", ("leg focus", "thigh focus", "legs", "thighs", "腿部", "大腿")),
        capacity_rule("Anima/姿势/R18/身体构图/腿足/鞋袜与足部", ("shoes", "boots", "socks", "thighhighs", "pantyhose", "footwear", "鞋", "袜")),
        capacity_rule("Anima/姿势/R18/身体构图/腿足/综合腿足构图", ()),
    ),
    "Anima/姿势/R18/非插入互动/口交与颜射/常规口交": (
        capacity_rule("Anima/姿势/R18/非插入互动/口交与颜射/常规口交/躺卧与骑脸", ("lying", "on bed", "face sitting", "sitting on face", "躺卧", "骑脸")),
        capacity_rule("Anima/姿势/R18/非插入互动/口交与颜射/常规口交/站坐姿势", ("standing", "sitting", "seated", "against wall", "站立", "坐姿")),
        capacity_rule("Anima/姿势/R18/非插入互动/口交与颜射/常规口交/综合口交", ()),
    ),
    "Anima/姿势/R18/多人互动/百合/综合亲密互动": (
        capacity_rule("Anima/姿势/R18/多人互动/百合/综合亲密互动/拥抱与贴贴", ("hug", "embrace", "cuddling", "breast press", "拥抱", "贴贴")),
        capacity_rule("Anima/姿势/R18/多人互动/百合/综合亲密互动/双人姿态", ("sitting", "lying", "standing", "kneeling", "lap pillow", "双人")),
        capacity_rule("Anima/姿势/R18/多人互动/百合/综合亲密互动/综合百合", ()),
    ),
    "Anima/姿势/正常/表情与情绪/夸张颜艺": (
        capacity_rule("Anima/姿势/正常/表情与情绪/夸张颜艺/欲望与失神", ("ahegao", "rolling eyes", "empty eyes", "heart-shaped pupils", "tongue out", "drooling", "失神")),
        capacity_rule("Anima/姿势/正常/表情与情绪/夸张颜艺/冷淡与无语", ("expressionless", "jitome", "half-closed eyes", "blank stare", "shaded face", "无语", "冷淡")),
        capacity_rule("Anima/姿势/正常/表情与情绪/夸张颜艺/搞怪与漫画", ("comic", "chibi", "symbol", "wavy mouth", "sweatdrop", "搞怪", "颜艺")),
        capacity_rule("Anima/姿势/正常/表情与情绪/夸张颜艺/综合颜艺", ()),
    ),
    "Anima/姿势/正常/单人动作": (
        capacity_rule("Anima/姿势/正常/单人动作/生活动作", ("eating", "drinking", "cooking", "reading", "writing", "cleaning", "sleeping", "吃", "喝", "阅读")),
        capacity_rule("Anima/姿势/正常/单人动作/运动与舞蹈", ("running", "jumping", "dancing", "swimming", "climbing", "cycling", "运动", "舞蹈")),
        capacity_rule("Anima/姿势/正常/单人动作/整理与穿脱", ("dressing", "undressing", "brushing hair", "putting on", "taking off", "整理", "穿衣", "脱鞋")),
        capacity_rule("Anima/姿势/正常/单人动作/综合动作", ()),
    ),
    "Anima/服装/R18/内衣与泳装/内衣": (
        capacity_rule("Anima/服装/R18/内衣与泳装/内衣/情趣内衣", ("lingerie", "lace", "crotchless", "babydoll", "garter belt", "情趣内衣")),
        capacity_rule("Anima/服装/R18/内衣与泳装/内衣/连裤袜与吊带", ("pantyhose", "stockings", "thighhighs", "garter straps", "bodystocking", "连裤袜", "吊带")),
        capacity_rule("Anima/服装/R18/内衣与泳装/内衣/胸罩与内裤", ("bra", "panties", "underwear", "胸罩", "内裤")),
        capacity_rule("Anima/服装/R18/内衣与泳装/内衣/综合内衣", ()),
    ),
    "Anima/服装/R18/内衣与泳装/泳装": (
        capacity_rule("Anima/服装/R18/内衣与泳装/泳装/比基尼", ("bikini", "micro bikini", "string bikini", "比基尼")),
        capacity_rule("Anima/服装/R18/内衣与泳装/泳装/校泳与运动泳装", ("school swimsuit", "competition swimsuit", "sports swimsuit", "school swimwear", "校泳")),
        capacity_rule("Anima/服装/R18/内衣与泳装/泳装/连体与竞赛泳装", ("one-piece swimsuit", "highleg swimsuit", "swimsuit", "连体泳装")),
        capacity_rule("Anima/服装/R18/内衣与泳装/泳装/特殊泳装", ()),
    ),
    "Anima/背景/正常/室内": (
        capacity_rule("Anima/背景/正常/室内/卧室与酒店", ("bedroom", "hotel room", "bed", "pillow", "卧室", "酒店")),
        capacity_rule("Anima/背景/正常/室内/浴室与更衣", ("bathroom", "shower", "bathtub", "locker room", "dressing room", "浴室", "更衣室")),
        capacity_rule("Anima/背景/正常/室内/教室与办公", ("classroom", "school", "office", "library", "教室", "办公室")),
        capacity_rule("Anima/背景/正常/室内/厨房与居家", ("kitchen", "living room", "dining room", "sofa", "厨房", "客厅")),
        capacity_rule("Anima/背景/正常/室内/综合室内", ()),
    ),
    "Anima/背景/正常/室外与自然": (
        capacity_rule("Anima/背景/正常/室外与自然/海滩与水边", ("beach", "ocean", "sea", "river", "lake", "waterfall", "pool", "海滩", "水边")),
        capacity_rule("Anima/背景/正常/室外与自然/森林与山野", ("forest", "mountain", "jungle", "cave", "cliff", "森林", "山谷")),
        capacity_rule("Anima/背景/正常/室外与自然/花园与田野", ("garden", "field", "meadow", "flowers", "farm", "花园", "田野")),
        capacity_rule("Anima/背景/正常/室外与自然/天气与夜景", ("rain", "snow", "night", "sunset", "storm", "moon", "雨", "雪", "夜景")),
        capacity_rule("Anima/背景/正常/室外与自然/综合户外", ()),
    ),
    "Anima/背景/正常/恐怖扭曲": (
        capacity_rule("Anima/背景/正常/恐怖扭曲/血肉与身体恐怖", ("blood", "gore", "flesh", "body horror", "bones", "corpse", "血肉", "尸体")),
        capacity_rule("Anima/背景/正常/恐怖扭曲/废墟与灵异", ("haunted", "abandoned", "ruins", "ghost", "hospital", "graveyard", "废墟", "灵异")),
        capacity_rule("Anima/背景/正常/恐怖扭曲/怪物与追逐", ("monster", "creature", "chasing", "attack", "shadow figure", "怪物", "追逐")),
        capacity_rule("Anima/背景/正常/恐怖扭曲/诡异与超现实", ("surreal", "distorted", "liminal", "creepy", "uncanny", "诡异", "扭曲")),
        capacity_rule("Anima/背景/正常/恐怖扭曲/综合恐怖", ()),
    ),
    "Anima/角色/正常/人物模板/通用人物模板": (
        capacity_rule("Anima/角色/正常/人物模板/通用人物模板/体型与肤色", ("muscular", "plump", "chubby", "skinny", "dark skin", "pale skin", "colored skin", "体型", "肤色")),
        capacity_rule("Anima/角色/正常/人物模板/通用人物模板/外貌与发型", ("hair", "eyes", "freckles", "makeup", "face", "heterochromia", "发型", "外貌")),
        capacity_rule("Anima/角色/正常/人物模板/通用人物模板/身份气质", ("elegant", "cool", "gyaru", "tomboy", "lady", "girl", "woman", "气质", "身份")),
        capacity_rule("Anima/角色/正常/人物模板/通用人物模板/综合人物", ()),
    ),
    "Anima/姿势/正常/表情与情绪/夸张颜艺/综合颜艺": (
        capacity_rule("Anima/姿势/正常/表情与情绪/夸张颜艺/综合颜艺/眼神与视线", ("eyes", "pupils", "looking", "wink", "stare", "眼神", "视线")),
        capacity_rule("Anima/姿势/正常/表情与情绪/夸张颜艺/综合颜艺/口部与舌头", ("mouth", "tongue", "lips", "saliva", "smile", "口部", "舌头")),
        capacity_rule("Anima/姿势/正常/表情与情绪/夸张颜艺/综合颜艺/综合表情", ()),
    ),
}


NOISE_ALIAS_TAGS = {
    "1girl", "1boy", "solo", "looking at viewer", "best quality", "masterpiece",
    "amazing quality", "very aesthetic", "absurdres", "highres", "nsfw", "indoors",
    "outdoors", "simple background", "white background", "official art",
}


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _canonical_or_legacy_target(category, allowed_targets):
    category = str(category or "")
    if category in allowed_targets:
        return category
    target = PROVENANCE_TARGETS.get(category) or LEGACY_TARGETS.get(category)
    if target in allowed_targets:
        return target
    leaf = category.rsplit("/", 1)[-1]
    matches = [target for target in allowed_targets if target.rsplit("/", 1)[-1] == leaf]
    return matches[0] if len(matches) == 1 else ""


def _source_parts(provenance):
    source, section = source_context_from_category(provenance)
    return source, normalize_text(section).strip()


def _is_pure_style(prompt, provenance=""):
    alias = normalize_text(prompt.get("alias")).strip()
    clean_alias = re.sub(r"[（(][^）)]*[）)]", "", alias).strip()
    _source, section = _source_parts(provenance)
    if STYLE_ALIAS_PATTERN.search(clean_alias):
        return True
    if any(
        pattern.search(clean_alias)
        for pattern in (
            TITLE_POSE_PATTERN,
            TITLE_CLOTHING_PATTERN,
            TITLE_CHARACTER_PATTERN,
            TITLE_BACKGROUND_PATTERN,
        )
    ):
        return False
    if section.startswith("表情包") and clean_alias:
        return False
    tags = extract_tags(prompt.get("prompt"))
    style_hits = sum(
        1 for tag in tags
        if any(normalize_text(term) in tag for term in STYLE_TAG_TERMS)
    )
    content_hits = sum(
        1 for tag in tags
        if any(normalize_text(term) in tag for term in CONTENT_TAG_TERMS)
    )
    threshold = 3 if section == "特殊画面" else 5
    return style_hits >= threshold and content_hits <= 2


def _managed_title_root(prompt, provenance):
    alias = normalize_text(prompt.get("alias")).strip()
    _source, section = _source_parts(provenance)
    if TITLE_POSE_PATTERN.search(alias):
        return "pose", "managed_action_title"
    if TITLE_CLOTHING_PATTERN.search(alias):
        return "clothing", "managed_clothing_title"
    if TITLE_CHARACTER_PATTERN.search(alias):
        return "character", "managed_character_title"
    if section.startswith("表情包"):
        return "pose", "meme_source_default"
    if TITLE_BACKGROUND_PATTERN.search(alias):
        return "background", "managed_background_title"
    title_roots = semantic_title_roots(prompt.get("alias"))
    if len(title_roots) == 1:
        return next(iter(title_roots)), "single_title_root"
    return "", ""


def _source_default_root(prompt, provenance):
    source, section = _source_parts(provenance)
    if not source:
        return "", ""
    if section.startswith("表情包"):
        return "pose", "meme_source_default"
    if "美食" in section:
        return "background", "food_source_default"
    if "组件" in section:
        body = normalize_text(prompt.get("prompt"))
        garment_hits = _matched_terms(body, ROOT_GARMENT_TERMS, limit=6)
        body_hits = _matched_terms(body, ROOT_BODY_TEMPLATE_TERMS, limit=6)
        if len(garment_hits) > len(body_hits):
            return "clothing", "component_source_clothing"
        return "character", "component_source_character"
    if source.startswith("所长色色"):
        return "pose", "adult_source_default"
    return "", ""


def _composed_body_root(prompt):
    body = normalize_text(prompt.get("prompt"))
    garment_hits = len(_matched_terms(body, ROOT_GARMENT_TERMS, limit=12))
    background_hits = len(_matched_terms(body, ROOT_BACKGROUND_TERMS, limit=12))
    character_hits = len(_matched_terms(body, ROOT_CHARACTER_TERMS, limit=12))
    if garment_hits >= 4 and garment_hits > max(background_hits, character_hits):
        return "clothing", "garment_composition"
    if (
        background_hits >= 3
        and background_hits > garment_hits
        and ("no humans" in body or "scenery" in body or background_hits >= 5)
    ):
        return "background", "scene_composition"
    if character_hits >= 2 and character_hits > garment_hits:
        return "character", "character_composition"
    return "", ""


def _root_evidence(prompt, provenance, semantic, model, allowed_targets):
    managed_title_root, managed_title_reason = _managed_title_root(prompt, provenance)
    if managed_title_reason == "managed_action_title":
        return managed_title_root, managed_title_reason
    title_leaf = strong_title_leaf(prompt.get("alias"), allowed_targets)
    if title_leaf:
        return root_from_category(title_leaf), "explicit_title_leaf"
    if managed_title_root:
        return managed_title_root, managed_title_reason

    direct_target = _canonical_or_legacy_target(provenance, allowed_targets)
    if direct_target:
        return root_from_category(direct_target), "provenance_leaf"

    if EXPLICIT_POSE_BODY_PATTERN.search(normalize_text(prompt.get("prompt"))):
        return "pose", "explicit_action_tags"

    source, section = source_context_from_category(provenance)
    broad_root = BROAD_PROVENANCE_ROOTS.get(provenance) or SECTION_ROOT_HINTS.get((source, section))
    deterministic = semantic.get("deterministic") or model.get("deterministic") or {}
    deterministic_root = str(deterministic.get("root") or "")
    deterministic_confidence = float(deterministic.get("confidence") or 0)
    deterministic_margin = float(deterministic.get("margin") or 0)
    model_root = str((model.get("root_model") or {}).get("label") or "")
    model_margin = float((model.get("root_model") or {}).get("margin") or 0)
    if broad_root:
        if (
            deterministic_root
            and deterministic_root == model_root
            and deterministic_root != broad_root
            and deterministic_confidence >= 0.78
            and model_margin >= MODEL_ROOT_MIN_MARGIN
        ):
            return deterministic_root, "deterministic_model_override"
        return broad_root, "broad_provenance_root"

    section_target = SECTION_TARGETS.get((source, section))
    if section_target in allowed_targets:
        return root_from_category(section_target), "reference_section_leaf"

    semantic_candidates = semantic.get("candidates") or []
    if semantic_candidates:
        return str(semantic_candidates[0].get("root") or ""), "semantic_candidate_root"
    if deterministic_root and deterministic_root == model_root:
        return deterministic_root, "deterministic_model_agreement"
    if (
        deterministic_root
        and deterministic_confidence >= 0.70
        and deterministic_margin >= 0.30
    ):
        return deterministic_root, "deterministic_root"
    if model_root and model_margin >= MODEL_ROOT_MIN_MARGIN:
        return model_root, "model_root_high_margin"
    composed_root, composed_reason = _composed_body_root(prompt)
    if composed_root:
        return composed_root, composed_reason
    source_root, source_reason = _source_default_root(prompt, provenance)
    if source_root:
        return source_root, source_reason
    if model_root:
        return model_root, "model_root_low_margin_fallback"
    return "pose", "pose_last_resort"


def _managed_rule_target(prompt, root):
    alias = normalize_text(prompt.get("alias"))
    body = normalize_text(prompt.get("prompt"))
    scored = []
    for rule in MANAGED_RULES:
        if root_from_category(rule.target) != root:
            continue
        alias_hits = _matched_terms(alias, rule.terms, limit=12)
        body_hits = _matched_terms(body, rule.terms, limit=20)
        hits = len(set(alias_hits + body_hits))
        if hits < rule.min_hits:
            continue
        scored.append((rule.bonus + 8 * len(alias_hits) + 2 * len(body_hits), rule.target))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0] if scored else (0, "")


def _classifier_leaf_target(prompt, root, allowed_targets):
    alias = normalize_text(prompt.get("alias"))
    body = normalize_text(prompt.get("prompt"))
    scored = []
    for target, terms in LEAF_RULES:
        if target not in allowed_targets or root_from_category(target) != root:
            continue
        alias_hits = _matched_terms(alias, terms, limit=8)
        body_hits = _matched_terms(body, terms, limit=16)
        if not alias_hits and not body_hits:
            continue
        specificity = 10 if "/R18/" in target else 0
        scored.append((specificity + 9 * len(alias_hits) + 2 * len(body_hits), target))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return scored[0] if scored else (0, "")


def _participant_bucket(prompt):
    body = normalize_text(prompt.get("prompt"))
    if re.search(r"(?:\b[3-9](?:girls?|boys?|others?)\b|multiple (?:girls|boys)|group sex|gangbang|多人|群交)", body):
        return "group"
    if re.search(r"(?:\b2(?:girls?|boys?)\b|\b1girl\b.*\b1boy\b|\bcouple\b|hetero|yuri|lesbian|双人)", body):
        return "pair"
    return "single"


def _default_target(prompt, root, provenance):
    if root == "pose" and has_adult_context(prompt, provenance):
        return ADULT_POSE_DEFAULTS[_participant_bucket(prompt)]
    body = normalize_text(prompt.get("prompt"))
    _source, section = _source_parts(provenance)
    if root == "pose":
        if section.startswith("表情包"):
            return "Anima/姿势/正常/表情与情绪"
        if _participant_bucket(prompt) in {"pair", "group"}:
            return "Anima/姿势/正常/多人互动"
        if re.search(
            r"\b(?:eating|drinking|cooking|reading|writing|cleaning|sleeping|dancing|running|"
            r"jumping|swimming|climbing|cycling|dressing|undressing)\b",
            body,
        ):
            return "Anima/姿势/正常/单人动作"
        if re.search(
            r"\b(?:crying|tears|angry|disgusted|embarrassed|shy|panicked|surprised|confused|"
            r"laughing|happy|smug|grin|ahegao|expressionless)\b",
            body,
        ):
            return "Anima/姿势/正常/表情与情绪"
    if root == "background":
        if "美食" in section or re.search(r"\b(?:food|meal|fruit|meat|drink|dessert|ramen)\b", body):
            return "Anima/背景/正常/食物与静物"
        if re.search(r"\b(?:bedroom|bathroom|classroom|kitchen|living room|restaurant|indoors|interior)\b", body):
            return "Anima/背景/正常/室内"
        if re.search(r"\b(?:outdoors|forest|beach|ocean|mountain|garden|field|river|street|ship|wharf)\b", body):
            return "Anima/背景/正常/室外与自然"
    if root == "character":
        if any(term in body for term in ("chibi", "cute", "petite", "doll-like")):
            return "Anima/角色/正常/人物模板/可爱与Q版"
        if any(term in body for term in ("fantasy", "elf", "demon", "angel", "fairy", "witch")):
            return "Anima/角色/正常/人物模板/奇幻人物模板"
    return ROOT_DEFAULTS[root]


def choose_managed_target(prompt, provenance, semantic, model, allowed_targets, contract=None):
    contract = contract or load_contract()
    if has_safety_risk(prompt) and has_adult_context(prompt, provenance):
        return (
            contract["non_anima_contracts"]["safety_quarantine_category"],
            "safety_boundary",
            "safety_quarantine",
            0.99,
        )
    if _is_pure_style(prompt, provenance):
        return (
            contract["non_anima_contracts"]["excluded_category"],
            "pure_style_or_generation_parameters",
            "non_anima_style",
            0.96,
        )
    root, root_reason = _root_evidence(prompt, provenance, semantic, model, allowed_targets)
    title_leaf = strong_title_leaf(prompt.get("alias"), allowed_targets)
    if title_leaf and root_from_category(title_leaf) == root:
        return title_leaf, root_reason, "explicit_title_leaf", 0.97

    direct_target = _canonical_or_legacy_target(provenance, allowed_targets)
    if direct_target and root_from_category(direct_target) == root:
        return direct_target, root_reason, "provenance_leaf", 0.95

    semantic_candidates = [
        candidate for candidate in semantic.get("candidates") or []
        if candidate.get("target") in allowed_targets and candidate.get("root") == root
    ]
    if semantic_candidates:
        return semantic_candidates[0]["target"], root_reason, "semantic_candidate", 0.92

    managed_score, managed_target = _managed_rule_target(prompt, root)
    classifier_score, classifier_target = _classifier_leaf_target(prompt, root, allowed_targets)
    deterministic = semantic.get("deterministic") or model.get("deterministic") or {}
    deterministic_target = str(deterministic.get("target") or "")
    if deterministic_target not in allowed_targets or root_from_category(deterministic_target) != root:
        deterministic_target = ""
    model_leaf = str((model.get("leaf_model") or {}).get("label") or "")
    model_margin = float((model.get("leaf_model") or {}).get("margin") or 0)
    if model_leaf not in allowed_targets or root_from_category(model_leaf) != root:
        model_leaf = ""

    if managed_target and managed_score >= max(8, classifier_score):
        return managed_target, root_reason, "managed_tag_composition", min(0.94, 0.78 + managed_score / 100)
    if classifier_target and classifier_score >= 12:
        return classifier_target, root_reason, "classifier_tag_composition", min(0.93, 0.76 + classifier_score / 100)
    if deterministic_target:
        return deterministic_target, root_reason, "deterministic_leaf", float(deterministic.get("confidence") or 0.72)
    if managed_target:
        return managed_target, root_reason, "managed_tag_fallback", 0.76
    if classifier_target:
        return classifier_target, root_reason, "classifier_tag_fallback", 0.73
    if model_leaf and model_margin >= MODEL_LEAF_MIN_MARGIN:
        return model_leaf, root_reason, "model_leaf_fallback", min(0.88, 0.62 + model_margin / 6)
    return _default_target(prompt, root, provenance), root_reason, "readable_root_default", 0.70


def _capacity_target(base_target, prompt):
    combined = normalize_text(f"{prompt.get('alias', '')}\n{prompt.get('prompt', '')}")
    target = base_target
    visited = set()
    while target in CAPACITY_SPLITS and target not in visited:
        visited.add(target)
        rules = CAPACITY_SPLITS[target]
        for rule in rules:
            if not rule.terms or _matched_terms(combined, rule.terms, limit=1):
                target = rule.target
                break
        else:
            break
    return target, base_target if target != base_target else ""


def _semantic_alias(prompt, target):
    old_alias = str(prompt.get("alias") or "").strip()
    if not is_generic_alias(old_alias):
        return old_alias
    descriptors = [
        tag for tag in extract_tags(prompt.get("prompt"))
        if tag not in NOISE_ALIAS_TAGS and len(tag) > 1
    ][:2]
    leaf = target.rsplit("/", 1)[-1]
    return leaf + ("｜" + " + ".join(descriptors) if descriptors else "")


def _unique_alias(base, used):
    candidate = base or "已分类预设"
    index = 2
    while normalize_text(candidate).strip() in used:
        candidate = f"{base}__{index:03d}"
        index += 1
    used.add(normalize_text(candidate).strip())
    return candidate


def _load_dependency_report(path, source_hash, expected_stage):
    raw = path.read_bytes()
    report = json.loads(raw)
    if report.get("stage") != expected_stage:
        raise SystemExit(f"报告类型不正确：{path}")
    if str(report.get("source_data", {}).get("sha256") or "") != source_hash:
        raise SystemExit(f"报告数据哈希已过期：{path}")
    return report, sha256_bytes(raw)


def build_audit(data, source_hash, semantic_report, model_report, dependency_hashes, contract, args):
    allowed_targets = canonical_targets(contract)
    authorized_targets = allowed_targets | {
        contract["non_anima_contracts"]["excluded_category"],
        contract["non_anima_contracts"]["safety_quarantine_category"],
    }
    used_aliases = defaultdict(set)
    for category in data.get("categories", []):
        name = str(category.get("name") or "")
        for prompt in category.get("prompts", []):
            used_aliases[name].add(normalize_text(prompt.get("alias")).strip())

    semantic_by_id = {item["prompt_id"]: item for item in semantic_report.get("decisions", [])}
    model_by_id = {item["prompt_id"]: item for item in model_report.get("decisions", [])}
    decisions = []
    reason_counts = Counter()
    root_reason_counts = Counter()
    from_counts = Counter()
    to_counts = Counter()
    candidate_count = 0
    capacity_count = 0
    generic_renames = 0
    missing_dependencies = []

    for category in data.get("categories", []):
        current_category = str(category.get("name") or "")
        completion_candidate = (
            current_category not in EXCLUDED_CATEGORIES
            and is_candidate_category(current_category)
        )
        capacity_candidate = current_category in CAPACITY_SPLITS
        if not completion_candidate and not capacity_candidate:
            continue
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            if completion_candidate:
                candidate_count += 1
                semantic = semantic_by_id.get(prompt_id)
                model = model_by_id.get(prompt_id)
                if semantic is None or model is None:
                    missing_dependencies.append(prompt_id)
                    continue
                provenance = str(semantic.get("provenance_category") or current_category)
                base_target, root_reason, reason, confidence = choose_managed_target(
                    prompt,
                    provenance,
                    semantic,
                    model,
                    allowed_targets,
                    contract,
                )
            else:
                capacity_count += 1
                provenance = current_category
                base_target = current_category
                root_reason = "existing_canonical_category"
                reason = "capacity_split"
                confidence = 0.99

            target, split_base = (
                _capacity_target(base_target, prompt)
                if base_target in allowed_targets
                else (base_target, "")
            )
            if split_base and reason != "capacity_split":
                reason = reason + "+capacity_split"
            if target not in authorized_targets:
                raise SystemExit(f"分类契约缺少目标：{target}")
            new_alias = str(prompt.get("alias") or "").strip()
            if completion_candidate and target in allowed_targets:
                alias_base = _semantic_alias(prompt, target)
                if alias_base != new_alias:
                    new_alias = _unique_alias(alias_base, used_aliases[target])
                    generic_renames += 1
                else:
                    used_aliases[target].add(normalize_text(new_alias).strip())
            selected = target != current_category
            reason_counts[reason] += 1
            root_reason_counts[root_reason] += 1
            if selected:
                from_counts[current_category] += 1
                to_counts[target] += 1
            decisions.append({
                "prompt_id": prompt_id,
                "alias": str(prompt.get("alias") or ""),
                "new_alias": new_alias,
                "current_category": current_category,
                "provenance_category": provenance,
                "selected": selected,
                "target": target,
                "base_target": base_target,
                "split_base": split_base,
                "root_reason": root_reason,
                "reason": reason,
                "confidence": round(confidence, 4),
                "image": str(prompt.get("image") or ""),
            })

    if missing_dependencies:
        raise SystemExit("依赖报告缺少 prompt ID：" + ", ".join(missing_dependencies[:10]))
    selected = [decision for decision in decisions if decision["selected"]]
    projected_counts = Counter(
        str(category.get("name") or "")
        for category in data.get("categories", [])
        for _ in category.get("prompts", [])
    )
    for decision in selected:
        projected_counts[decision["current_category"]] -= 1
        projected_counts[decision["target"]] += 1
    projected_over_capacity = {
        name: count for name, count in projected_counts.items()
        if name.startswith("Anima/") and count > args.capacity_limit
    }
    low_confidence = [decision for decision in decisions if decision["confidence"] < 0.72]
    return {
        "schema_version": 1,
        "stage": "anima_managed_completion",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_data": {"path": str(args.data), "sha256": source_hash},
        "dependencies": {
            "semantic_report": {"path": str(args.semantic_report), "sha256": dependency_hashes[0]},
            "model_report": {"path": str(args.model_report), "sha256": dependency_hashes[1]},
        },
        "policy": {
            "single_primary_category": True,
            "complete_all_candidates": True,
            "preserve_excluded_and_safety_categories": sorted(EXCLUDED_CATEGORIES),
            "capacity_limit": args.capacity_limit,
            "capacity_split_bases": sorted(CAPACITY_SPLITS),
        },
        "summary": {
            "completion_candidates": candidate_count,
            "capacity_candidates": capacity_count,
            "selected_moves": len(selected),
            "generic_alias_renames": generic_renames,
            "unclassified_candidates": 0,
            "low_confidence_decisions": len(low_confidence),
            "reason_counts": dict(reason_counts.most_common()),
            "root_reason_counts": dict(root_reason_counts.most_common()),
            "from_counts": dict(from_counts.most_common()),
            "to_counts": dict(to_counts.most_common()),
            "projected_over_capacity": dict(sorted(projected_over_capacity.items())),
        },
        "decisions": decisions,
    }


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
    return serialized


def apply_report(data_path, report_path, expected_sha256=""):
    source_bytes = data_path.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    report_bytes = report_path.read_bytes()
    report = json.loads(report_bytes)
    if report.get("stage") != "anima_managed_completion":
        raise SystemExit("拒绝写入：报告类型不正确。")
    if str(report.get("source_data", {}).get("sha256") or "") != source_hash:
        raise SystemExit("拒绝写入：报告基于的数据已经变化。")
    if expected_sha256 and expected_sha256.lower() != source_hash:
        raise SystemExit("拒绝写入：当前数据与期望哈希不一致。")
    if report.get("summary", {}).get("unclassified_candidates") != 0:
        raise SystemExit("拒绝写入：报告仍有未归类条目。")

    contract = load_contract()
    allowed_targets = canonical_targets(contract)
    authorized_targets = allowed_targets | {
        contract["non_anima_contracts"]["excluded_category"],
        contract["non_anima_contracts"]["safety_quarantine_category"],
    }
    selected = {
        decision["prompt_id"]: decision
        for decision in report.get("decisions", [])
        if decision.get("selected")
    }
    invalid_targets = sorted({item["target"] for item in selected.values()} - authorized_targets)
    if invalid_targets:
        raise SystemExit("拒绝写入：存在未授权分类：" + ", ".join(invalid_targets))

    data = json.loads(source_bytes)
    result = copy.deepcopy(data)
    result["last_modified"] = datetime.now().astimezone().isoformat()
    categories = result.get("categories", [])
    by_name = {str(category.get("name") or ""): category for category in categories}
    moved = {}
    original_ids = []
    for category in categories:
        kept = []
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            original_ids.append(prompt_id)
            decision = selected.get(prompt_id)
            if not decision:
                kept.append(prompt)
                continue
            if decision["current_category"] != category.get("name"):
                raise SystemExit(f"拒绝写入：{prompt_id} 的当前分类不一致。")
            item = copy.deepcopy(prompt)
            item["alias"] = decision.get("new_alias") or item.get("alias") or ""
            moved[prompt_id] = item
        category["prompts"] = kept
    if len(moved) != len(selected):
        raise SystemExit("拒绝写入：报告中的部分条目不存在。")

    for decision in report.get("decisions", []):
        if not decision.get("selected"):
            continue
        target = decision["target"]
        category = by_name.get(target)
        if category is None:
            category = {"id": deterministic_category_id(target), "name": target, "prompts": []}
            categories.append(category)
            by_name[target] = category
        category.setdefault("prompts", []).append(moved[decision["prompt_id"]])

    preserved_empty = set(EXCLUDED_CATEGORIES)
    removed_categories = []
    kept_categories = []
    for category in categories:
        name = str(category.get("name") or "")
        removable = (
            not category.get("prompts")
            and name not in preserved_empty
            and (is_candidate_category(name) or name in CAPACITY_SPLITS or name.startswith("待归类/Anima清理"))
        )
        if removable:
            removed_categories.append(name)
        else:
            kept_categories.append(category)
    result["categories"] = kept_categories

    result_ids = [
        str(prompt.get("id") or "")
        for category in kept_categories
        for prompt in category.get("prompts", [])
    ]
    if Counter(original_ids) != Counter(result_ids):
        raise SystemExit("拒绝写入：应用后 prompt ID 集合发生变化。")
    category_names = [str(category.get("name") or "") for category in kept_categories]
    category_ids = [str(category.get("id") or "") for category in kept_categories]
    if len(category_names) != len(set(category_names)) or len(category_ids) != len(set(category_ids)):
        raise SystemExit("拒绝写入：应用后分类名称或 ID 重复。")

    report_dir = data_path.parent / "classification_reports"
    backup_dir = report_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"data-before-anima-managed-{timestamp}-{source_hash[:12]}.json"
    backup_path.write_bytes(source_bytes)
    result_bytes = atomic_write_json(data_path, result)
    apply_result = {
        "schema_version": 1,
        "stage": "anima_managed_completion_apply",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_hash,
        "result_sha256": sha256_bytes(result_bytes),
        "classification_report": str(report_path),
        "classification_report_sha256": sha256_bytes(report_bytes),
        "backup": str(backup_path),
        "moved": len(selected),
        "renamed": sum(item["alias"] != item["new_alias"] for item in selected.values()),
        "removed_empty_categories": removed_categories,
        "moves": [
            {
                "prompt_id": item["prompt_id"],
                "alias": item["alias"],
                "new_alias": item["new_alias"],
                "from": item["current_category"],
                "to": item["target"],
                "reason": item["reason"],
                "confidence": item["confidence"],
            }
            for item in report.get("decisions", []) if item.get("selected")
        ],
    }
    result_path = report_dir / f"anima-managed-completion-apply-{timestamp}.json"
    result_path.write_text(json.dumps(apply_result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result_path, apply_result


def main():
    parser = argparse.ArgumentParser(description="Complete managed Anima classification and split oversized leaves.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument("--data", type=Path, default=PLUGIN_DIR / "user_data" / "prompt_selector" / "data.json")
    audit.add_argument("--semantic-report", type=Path, required=True)
    audit.add_argument("--model-report", type=Path, required=True)
    audit.add_argument("--capacity-limit", type=int, default=200)
    audit.add_argument("--output", type=Path, default=None)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--data", type=Path, default=PLUGIN_DIR / "user_data" / "prompt_selector" / "data.json")
    apply_parser.add_argument("--report", type=Path, required=True)
    apply_parser.add_argument("--expected-sha256", default="")
    args = parser.parse_args()

    if args.command == "apply":
        result_path, result = apply_report(args.data, args.report, args.expected_sha256)
        print(json.dumps({
            "result": str(result_path),
            "moved": result["moved"],
            "renamed": result["renamed"],
            "source_sha256": result["source_sha256"],
            "result_sha256": result["result_sha256"],
            "backup": result["backup"],
        }, ensure_ascii=False, indent=2))
        return

    source_bytes = args.data.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    data = json.loads(source_bytes)
    semantic_report, semantic_hash = _load_dependency_report(
        args.semantic_report, source_hash, "anima_tag_semantic_pass"
    )
    model_report, model_hash = _load_dependency_report(
        args.model_report, source_hash, "anima_second_pass"
    )
    report = build_audit(
        data,
        source_hash,
        semantic_report,
        model_report,
        (semantic_hash, model_hash),
        load_contract(),
        args,
    )
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.output = args.data.parent / "classification_reports" / f"anima-managed-completion-audit-{timestamp}.json"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(args.output),
        "source_sha256": source_hash,
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
