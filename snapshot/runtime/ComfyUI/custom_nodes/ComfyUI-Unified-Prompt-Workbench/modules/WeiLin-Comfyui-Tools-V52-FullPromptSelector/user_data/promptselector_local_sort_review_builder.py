#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Universal local PromptSelector builder for ComfyUI.

用途：
  从 WeiLin tags / Danbooru / history 数据库，以及本地 JSON / CSV / TXT / SQLite / 原 PromptSelector.py
  中抽取提示词，合并、近似去重、分类，然后生成一个新的 ComfyUI PromptSelector 节点脚本。

核心特性：
  - 仅使用 Python 标准库，无第三方依赖。
  - 支持 WeiLin userdatas_*_tags.db、userdatas_*_danbooru.db、userdatas_*_history.db。
  - 支持本地其它库：SQLite / JSON / CSV / TSV / TXT / Python PromptSelector 脚本。
  - 不做近似去重：只做精确归一去重；重复/相近项交给内置复核工具人工处理。
  - 生成运行时 override 文件，后续可在 ComfyUI 内用“排序复核编辑器”节点增删改/隐藏/排序/置顶。
  - 默认启用成人向安全过滤：会跳过未成年、非自愿、失去意识/操控、近亲、动物、尸体/血腥、公共非合意/偷拍等高风险项。

推荐用法：
  1. 把本文件放到 ComfyUI/custom_nodes/WeiLin-Comfyui-Tools/user_data/ 或任意总库目录。
  2. 运行：
       python promptselector_universal_local_builder.py
  3. 把生成的 NSFWPromptSelector_LocalMerged.py 放到任意 ComfyUI/custom_nodes 子目录。
  4. 重启 ComfyUI。

常用参数：
  python promptselector_universal_local_builder.py --scan-root . --output NSFWPromptSelector_LocalMerged.py
  python promptselector_universal_local_builder.py --source D:\\ComfyUI\\custom_nodes\\WeiLin-Comfyui-Tools\\user_data --base-py D:\\ComfyUI\\custom_nodes\\ComfyUI-NSFW-PromptSelector\\NSFWPromptSelector.py
  python promptselector_universal_local_builder.py --create-config
  python promptselector_universal_local_builder.py --config promptselector_builder_config.json --overwrite
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime as _dt
import difflib
import hashlib
import json
import os
import re
import sqlite3
import sys
import textwrap
from collections import Counter, defaultdict, OrderedDict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

BUILDER_VERSION = "2026.05.19-universal-local-v3-sort-review"
DEFAULT_OUTPUT = "NSFWPromptSelector_LocalMerged.py"
DEFAULT_CONFIG = "promptselector_builder_config.json"
DEFAULT_RUNTIME_OVERRIDES = "promptselector_user_overrides.json"
DEFAULT_REPORT = "promptselector_build_report.txt"
DEFAULT_DUPLICATES_CSV = "promptselector_duplicates_review.csv"
DEFAULT_EXCLUDED_CSV = "promptselector_excluded_tags.csv"

# 分类顺序。生成出来的 PromptSelector 会按这个顺序显示输入项。
CATEGORY_ORDER = [
    "主体关系",
    "角色身份",
    "服装外观",
    "身体特征",
    "表情反应",
    "姿态动作",
    "成人互动",
    "体液痕迹",
    "道具器具",
    "束缚BDSM",
    "场景地点",
    "镜头构图",
    "画面风格",
    "光线色调",
    "质量风格",
    "历史常用",
    "额外标签",
]

# 每类默认权重，生成节点里可以再调总权重与每类权重。
DEFAULT_CATEGORY_WEIGHTS = {
    "主体关系": 1.05,
    "角色身份": 0.95,
    "服装外观": 0.95,
    "身体特征": 1.00,
    "表情反应": 1.00,
    "姿态动作": 1.12,
    "成人互动": 1.18,
    "体液痕迹": 0.95,
    "道具器具": 0.90,
    "束缚BDSM": 0.90,
    "场景地点": 0.88,
    "镜头构图": 0.82,
    "画面风格": 0.82,
    "光线色调": 0.82,
    "质量风格": 0.80,
    "历史常用": 1.05,
    "额外标签": 1.00,
}

SOURCE_PRIORITY = {
    "manual_config": 100,
    "runtime_override": 95,
    "base_promptselector": 85,
    "weilin_history": 82,
    "weilin_collect_history": 81,
    "weilin_tags": 78,
    "local_json": 72,
    "local_csv": 71,
    "local_txt": 70,
    "generic_sqlite": 65,
    "danbooru": 55,
    "unknown": 20,
}

# 用于分类的关键词。越具体越靠前。
CATEGORY_RULES: List[Tuple[str, Sequence[str]]] = [
    ("体液痕迹", [
        "cum", "semen", "bukkake", "creampie", "facial", "ejaculat", "squirting", "saliva", "drool", "sweat", "tears", "wet", "dripping", "滴", "精液", "颜射", "顏射", "内射", "內射", "潮吹", "唾液", "流口水", "汗", "泪", "淚",
    ]),
    ("束缚BDSM", [
        "bdsm", "bondage", "bound", "rope", "shibari", "collar", "leash", "handcuff", "gag", "blindfold", "whip", "spank", "dominat", "submissive", "束缚", "束縛", "捆绑", "綑綁", "绳", "繩", "项圈", "項圈", "手铐", "手銬", "口塞", "眼罩", "鞭",
    ]),
    ("道具器具", [
        "toy", "dildo", "vibrator", "plug", "machine", "device", "clamp", "piercing", "prop", "道具", "玩具", "震动", "震動", "假阳", "假陽", "肛塞", "乳夹", "乳夾", "机器", "機器", "器具", "穿孔",
    ]),
    ("成人互动", [
        "sex", "intercourse", "penetrat", "oral", "blowjob", "handjob", "footjob", "titjob", "thighjob", "cunnilingus", "rimming", "deepthroat", "masturbat", "fingering", "kissing", "lick", "orgasm", "climax", "cowgirl", "missionary", "doggy", "threesome", "orgy", "group", "grinding", "69", "futanari", "tentacle", "性爱", "性交", "口交", "手交", "足交", "乳交", "腿交", "自慰", "手指", "舔", "接吻", "高潮", "女上", "传教士", "傳教士", "后入", "後入", "三人", "群体", "群體", "触手", "觸手", "扶他",
    ]),
    ("姿态动作", [
        "pose", "posing", "standing", "sitting", "lying", "kneeling", "squatting", "spread", "open", "crawling", "arched", "bent", "hands", "legs", "missionary", "cowgirl", "doggy", "action", "姿势", "姿勢", "体位", "體位", "站立", "坐", "躺", "跪", "蹲", "张开", "張開", "趴", "拱", "动作", "動作",
    ]),
    ("服装外观", [
        "clothes", "clothing", "dress", "skirt", "shirt", "uniform", "bikini", "lingerie", "underwear", "panties", "bra", "stockings", "thong", "g-string", "fishnet", "latex", "leather", "see through", "transparent", "wet clothes", "nude", "naked", "topless", "bottomless", "outfit", "costume", "服", "衣", "裙", "制服", "比基尼", "内衣", "內衣", "胸罩", "内裤", "內褲", "丝袜", "絲襪", "丁字", "渔网", "漁網", "乳胶", "乳膠", "皮革", "透明", "裸体", "裸體", "裸露",
    ]),
    ("身体特征", [
        "breast", "boob", "nipple", "areola", "ass", "butt", "hip", "thigh", "pussy", "vagina", "penis", "cock", "anus", "anal", "cameltoe", "cleavage", "sideboob", "underboob", "body", "skin", "hair", "piercing", "tattoo", "pregnant", "belly", "身体", "身體", "胸", "乳", "臀", "屁股", "大腿", "阴", "陰", "阳具", "陽具", "龟头", "龜頭", "肛", "乳沟", "乳溝", "纹身", "紋身", "怀孕", "懷孕", "腹",
    ]),
    ("表情反应", [
        "expression", "face", "eyes", "ahegao", "blush", "blushing", "embarrassed", "shy", "seductive", "lustful", "horny", "aroused", "panting", "moaning", "scream", "open mouth", "tongue", "heart eyes", "表情", "脸", "臉", "眼", "潮吹脸", "阿黑颜", "阿黑顏", "脸红", "臉紅", "害羞", "诱惑", "誘惑", "呻吟", "喘", "尖叫", "张嘴", "張嘴", "舌", "心形眼",
    ]),
    ("主体关系", [
        "1girl", "1boy", "2girls", "2boys", "multiple", "solo", "couple", "lesbian", "yaoi", "girl", "boy", "male", "female", "man", "woman", "subject", "relationship", "pair", "solo", "单人", "單人", "一人", "女孩", "男孩", "男女", "女性", "男性", "女同", "男同", "多人", "主体", "主體", "关系", "關係",
    ]),
    ("角色身份", [
        "maid", "nurse", "teacher", "office lady", "secretary", "police", "military", "idol", "princess", "queen", "goddess", "succubus", "catgirl", "bunny", "fox", "wolf", "dragon", "elf", "angel", "vampire", "witch", "role", "character", "职业", "職業", "角色", "女仆", "女僕", "护士", "護士", "教师", "教師", "秘书", "秘書", "警察", "军人", "軍人", "偶像", "公主", "女王", "女神", "魅魔", "猫女", "貓女", "兔女", "狐女", "精灵", "精靈", "天使", "吸血鬼", "女巫",
    ]),
    ("场景地点", [
        "bedroom", "bathroom", "shower", "bath", "beach", "rooftop", "hotel", "love hotel", "pool", "changing room", "sauna", "massage", "store", "forest", "car", "office", "room", "street", "alley", "nightclub", "onsen", "hot spring", "scene", "environment", "location", "背景", "场景", "場景", "环境", "環境", "卧室", "臥室", "浴室", "淋浴", "海滩", "海灘", "天台", "酒店", "泳池", "更衣", "桑拿", "按摩", "森林", "车内", "車內", "办公室", "辦公室", "夜店", "温泉", "房间", "房間",
    ]),
    ("镜头构图", [
        "camera", "angle", "view", "pov", "close-up", "closeup", "shot", "lens", "wide angle", "fisheye", "zoom", "focus", "composition", "x-ray", "internal view", "cross section", "镜头", "鏡頭", "视角", "視角", "机位", "機位", "构图", "構圖", "特写", "特寫", "焦距", "广角", "廣角", "鱼眼", "魚眼", "运镜", "運鏡", "透视", "透視",
    ]),
    ("光线色调", [
        "light", "lighting", "neon", "candle", "backlight", "rim light", "color tone", "tone", "red", "purple", "pink", "gold", "warm", "cool", "contrast", "glow", "光", "灯", "燈", "霓虹", "烛", "燭", "背光", "色调", "色調", "红色", "紅色", "紫色", "粉色", "金色", "暖色", "冷色", "对比", "對比", "光晕", "光暈",
    ]),
    ("画面风格", [
        "style", "film", "cinematic", "anime", "realistic", "photorealistic", "retro", "cyber", "surreal", "artistic", "magazine", "filter", "effect", "grain", "soft light", "bloom", "flare", "smoke", "water drop", "风格", "風格", "电影", "電影", "写实", "寫實", "复古", "復古", "赛博", "賽博", "超现实", "超現實", "艺术", "藝術", "杂志", "雜誌", "滤镜", "濾鏡", "特效", "颗粒", "顆粒", "烟雾", "煙霧",
    ]),
    ("质量风格", [
        "masterpiece", "best quality", "high quality", "ultra-detailed", "detailed", "8k", "4k", "resolution", "studio lighting", "professional", "质量", "品質", "画质", "畫質", "大师", "大師", "高清", "细节", "細節",
    ]),
]

# 默认跳过的高风险内容。这里是“生成器层”和“运行时 override 编辑器层”的双重过滤。
BLOCK_PATTERNS = [
    r"\b(loli|lolicon|shota|shotacon|child|children|minor|underage|toddler|infant|preteen|teenager|teen|little[-_\s]?girl|little[-_\s]?boy|age[-_\s]?gap|aged[-_\s]?up)\b",
    r"\b(school|classroom|schoolgirl|schoolboy|school\s*uniform|student|classmate|kindergarten|elementary\s*school|middle\s*school|high\s*school)\b",
    r"(萝莉|蘿莉|正太|未成年|未滿|未满|幼女|幼男|儿童|兒童|小学生|小學生|中学生|中學生|高中生|初中生|幼稚园|幼稚園|幼儿园|幼兒園|校服|学生|學生|同学|同學)",
    r"\b(young|younger|youth)\b",
    r"\b(rape|raped|raping|rapist|sexual[-_\s]?assault|assaulted|forced|forceful|non[-_\s]?consensual|nonconsensual|molestation|molest|coercion|coerced|blackmail)\b",
    r"\b(kidnap|kidnapped|abduction|hostage|unconscious|sleeping|sleep\s*sex|passed\s*out|chloroform)\b",
    r"\b(hypnosis|hypnotized|mind\s*control|brainwash|brainwashed|aphrodisiac|drug|drugs|drugged|drunk|intoxicated)\b",
    r"(强奸|強姦|強奸|强暴|強暴|性侵|强迫|強迫|强制|強制|非自愿|非自願|胁迫|脅迫|勒索|绑架|綁架|昏迷|睡眠|催眠|精神控制|洗脑|洗腦|下药|下藥|春药|春藥|醉酒|迷奸|风险|風險)",
    r"\b(incest|twincest|mother|father|sister|brother|daughter|son|aunt|uncle|cousin|family)\b",
    r"(近亲|近親|乱伦|亂倫|母亲|母親|父亲|父親|姐姐|妹妹|哥哥|弟弟|女儿|女兒|儿子|兒子|家庭)",
    r"\b(bestiality|zoophilia|animal\s*sex|dog\s*sex|horse\s*sex|pig\s*sex|beastiality)\b",
    r"(兽交|獸交|动物性交|動物性交)",
    r"\b(necrophilia|corpse|dead\s*body|guro|gore|snuff|torture|mutilation|dismemberment)\b",
    r"(尸体|屍體|恋尸|戀屍|虐杀|虐殺|肢解|血腥|猎奇|獵奇|酷刑)",
    r"\b(voyeur|voyeurism|voyeuristic|peeping|hidden\s*camera|spycam|upskirt|downblouse|public\s*sex|exhibitionism|flasher|accidental\s*exposure|wardrobe\s*malfunction)\b",
    r"(偷窥|偷窺|偷拍|走光|意外暴露|公共性爱|公共性愛|暴露狂|露出狂)",
    r"\b(ntr|cuckold|cuckolding|cheating|affair)\b",
]
BLOCK_RE = re.compile("|".join(f"(?:{p})" for p in BLOCK_PATTERNS), re.IGNORECASE)

# Danbooru / 泛本地库的保留规则。WeiLin tag 库、history、base py 会更宽松；普通库用它避免引入完全无关文本。
ALLOW_HINT_PATTERNS = [
    r"\b(1girl|1boy|solo|2girls|2boys|multiple|girl|boy|female|male|woman|man|couple|lesbian|yaoi|futanari)\b",
    r"\b(nude|naked|topless|bottomless|lingerie|bikini|panties|bra|stocking|thong|fishnet|latex|leather|see[-_\s]?through|transparent)\b",
    r"\b(breast|boob|nipple|ass|butt|hip|thigh|pussy|vagina|penis|cock|anus|anal|cleavage|cameltoe|sideboob|underboob)\b",
    r"\b(sex|intercourse|oral|blowjob|handjob|footjob|titjob|thighjob|cunnilingus|deepthroat|masturbat|fingering|kissing|licking|orgasm|climax|cowgirl|missionary|doggy|69|tentacle|grinding)\b",
    r"\b(cum|semen|bukkake|creampie|facial|ejaculat|squirting|saliva|drool|sweat|tears|wet|dripping)\b",
    r"\b(bdsm|bondage|rope|collar|leash|handcuff|gag|blindfold|whip|spank|dildo|vibrator|plug|sex\s*toy)\b",
    r"\b(bedroom|bathroom|shower|beach|hotel|love\s*hotel|pool|sauna|massage|onsen|car|office|nightclub)\b",
    r"\b(camera|angle|view|pov|close[-_\s]?up|lens|shot|x[-_\s]?ray|internal\s*view|cross\s*section)\b",
    r"(女孩|男孩|女性|男性|男女|多人|女同|男同|裸体|裸體|裸露|内衣|內衣|比基尼|乳|胸|臀|阴|陰|阳具|陽具|肛|性爱|性交|口交|自慰|舔|接吻|高潮|精液|潮吹|束缚|束縛|道具|玩具|场景|場景|镜头|鏡頭|视角|視角)",
]
ALLOW_HINT_RE = re.compile("|".join(f"(?:{p})" for p in ALLOW_HINT_PATTERNS), re.IGNORECASE)

# 合并归一化同义词，偏保守。可在 config 里继续加 alias_groups / replace。
DEFAULT_REPLACE_ALIASES = {}

SKIP_FILE_NAMES = {
    DEFAULT_OUTPUT,
    DEFAULT_CONFIG,
    DEFAULT_RUNTIME_OVERRIDES,
    DEFAULT_REPORT,
    DEFAULT_DUPLICATES_CSV,
    DEFAULT_EXCLUDED_CSV,
    "promptselector_universal_local_builder.py",
    "LocalPromptSelector_UniversalBuilder.py",
    "build_promptselector_universal.py",
    "build_promptselector_universal_local.py",
    "build_universal_promptselector.py",
    "local_promptselector_merge_builder.py",
    "universal_promptselector_builder.py",
}

TEXT_EXTENSIONS = {".txt", ".text", ".prompt", ".prompts"}
CSV_EXTENSIONS = {".csv", ".tsv"}
JSON_EXTENSIONS = {".json"}
SQLITE_EXTENSIONS = {".db", ".sqlite", ".sqlite3"}
PY_EXTENSIONS = {".py"}


def log(msg: str) -> None:
    print(f"[PromptSelectorBuilder] {msg}")


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    s = str(value)
    s = s.replace("\ufeff", "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def clean_prompt_token(value: Any) -> str:
    s = clean_text(value)
    if not s:
        return ""
    s = s.strip(" ,;，；")
    # 去掉常见权重壳：(tag:1.2)、[tag]、{tag}
    m = re.fullmatch(r"[\(\[\{]\s*(.+?)\s*:[0-9.]+\s*[\)\]\}]", s)
    if m:
        s = m.group(1).strip()
    while len(s) > 2 and s[0] in "([{" and s[-1] in ")]}" and s.count(s[0]) == 1:
        s = s[1:-1].strip()
    s = re.sub(r"\s*,\s*$", "", s)
    return s.strip()


def split_prompt_line(text: str) -> List[str]:
    """把 prompt 字符串拆成候选 tag。尽量保守，只按逗号/中文逗号/换行/分号拆。"""
    text = clean_text(text)
    if not text:
        return []
    # JSON 或 Python 列表字符串
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
        try:
            parsed = ast.literal_eval(text)
            return extract_strings_from_any(parsed)
        except Exception:
            pass
    parts = re.split(r"[,，;；\n]+", text)
    out = []
    for p in parts:
        token = clean_prompt_token(p)
        if not token or token in {"--", "——", "none", "None", "null"}:
            continue
        if len(token) > 160:
            # 长句作为完整 prompt 也可能有价值，但下拉菜单过长。留给 JSON/CSV 的 prompt 字段由上层处理。
            continue
        out.append(token)
    return out


def extract_strings_from_any(obj: Any) -> List[str]:
    out: List[str] = []
    if obj is None:
        return out
    if isinstance(obj, str):
        # 对列表/历史 prompt 字段再拆。
        if "," in obj or "，" in obj or "\n" in obj or ";" in obj or "；" in obj:
            out.extend(split_prompt_line(obj))
        else:
            token = clean_prompt_token(obj)
            if token:
                out.append(token)
        return out
    if isinstance(obj, (list, tuple, set)):
        for x in obj:
            out.extend(extract_strings_from_any(x))
        return out
    if isinstance(obj, dict):
        # 优先读取典型字段，避免把所有说明文字都当 tag。
        keys = [
            "tag", "tags", "text", "prompt", "positive", "positive_prompt", "alias", "aliases",
            "name", "display", "value", "keyword", "keywords", "tokens",
        ]
        used = False
        for k in keys:
            if k in obj:
                out.extend(extract_strings_from_any(obj.get(k)))
                used = True
        if not used:
            # 对 category -> [items] 这类结构递归。
            for v in obj.values():
                if isinstance(v, (list, tuple, dict)):
                    out.extend(extract_strings_from_any(v))
        return out
    return out


def normalize_for_key(text: str, replace_aliases: Optional[Dict[str, str]] = None) -> str:
    s = clean_prompt_token(text).lower()
    if not s:
        return ""
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\([^)]*\)", " ", s)  # 去掉 display 里的括号中文/英文残留
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    aliases = dict(DEFAULT_REPLACE_ALIASES)
    if replace_aliases:
        for k, v in replace_aliases.items():
            aliases[normalize_plain(k)] = normalize_plain(v)
    # 短语级别替换，先长后短。
    for k in sorted(aliases, key=len, reverse=True):
        kk = normalize_plain(k)
        vv = normalize_plain(aliases[k])
        if not kk or not vv:
            continue
        s = re.sub(rf"\b{re.escape(kk)}\b", vv, s)
    # 简单单复数归一化。避免把 1girl/2girls 改坏。
    words = []
    for w in s.split():
        if re.match(r"^[0-9]+girls?$", w) or re.match(r"^[0-9]+boys?$", w):
            words.append(w)
            continue
        if len(w) > 5 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 4 and w.endswith("ses"):
            w = w[:-2]
        elif len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        words.append(w)
    s = " ".join(words)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_plain(text: str) -> str:
    s = clean_prompt_token(text).lower().replace("_", " ").replace("-", " ")
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def is_blocked(prompt: str, display: str = "", extra: str = "") -> bool:
    joined = f"{prompt} {display} {extra}"
    joined_norm = joined.replace("_", " ").replace("-", " ")
    return bool(BLOCK_RE.search(joined) or BLOCK_RE.search(joined_norm))


def has_allow_hint(prompt: str, display: str = "", extra: str = "") -> bool:
    joined = f"{prompt} {display} {extra}"
    return bool(ALLOW_HINT_RE.search(joined))


def display_from_parts(prompt: str, zh: str = "") -> str:
    prompt = clean_prompt_token(prompt)
    zh = clean_text(zh)
    if not prompt:
        return ""
    if zh and zh.lower() != prompt.lower():
        zh = zh[:70]
        return f"{zh} ({prompt})"
    return prompt


def py_literal(obj: Any) -> str:
    return repr(obj)


def stable_id(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


@dataclass
class Item:
    prompt: str
    display: str = ""
    category: str = "额外标签"
    source_type: str = "unknown"
    source_path: str = ""
    group: str = ""
    subgroup: str = ""
    translate: str = ""
    hot: int = 0
    score: float = 0.0
    reason: str = ""

    def normalized(self, replace_aliases: Optional[Dict[str, str]] = None) -> str:
        return normalize_for_key(self.prompt, replace_aliases)

    def quality_score(self) -> float:
        base = SOURCE_PRIORITY.get(self.source_type, SOURCE_PRIORITY["unknown"])
        if self.hot:
            base += min(20.0, max(0.0, self.hot / 500000.0))
        if self.translate:
            base += 3
        if self.display and "(" in self.display and ")" in self.display:
            base += 1
        if len(self.prompt) <= 4:
            base -= 1
        return base + self.score

    def finalize_display(self) -> None:
        if not self.display:
            self.display = display_from_parts(self.prompt, self.translate)
        self.display = clean_text(self.display)[:160]
        self.prompt = clean_prompt_token(self.prompt)
        if self.category not in CATEGORY_ORDER:
            self.category = "额外标签"


@dataclass
class Excluded:
    prompt: str
    display: str
    category: str
    source_type: str
    source_path: str
    reason: str


@dataclass
class DuplicateRecord:
    kept_prompt: str
    kept_display: str
    dropped_prompt: str
    dropped_display: str
    category: str
    reason: str
    similarity: float
    kept_source: str
    dropped_source: str


DEFAULT_CONFIG_TEMPLATE: Dict[str, Any] = {
    "version": BUILDER_VERSION,
    "说明": "这个文件可选。你可以用它指定扫描目录、排序模式、手动添加、隐藏、合并、移动分类。保存后重新运行生成器。",
    "sources": {
        "scan_roots": ["."],
        "explicit_files": [],
        "base_promptselector_py": "",
        "recursive": True,
        "max_depth": 5,
        "include_file_types": ["sqlite", "json", "csv", "txt", "py"],
        "exclude_globs": [
            "**/__pycache__/**", "**/*.pyc", "**/*-wal", "**/*-shm", "**/node_modules/**",
            "**/NSFWPromptSelector_LocalMerged*.py", "**/promptselector_*_review.csv",
            "**/promptselector_duplicates_review.csv", "**/promptselector_excluded_tags.csv",
        ],
    },
    "filters": {
        "max_per_category": 500,
        "fuzzy_threshold": 1.0,
        "enable_fuzzy_dedupe": False,
        "sort_mode": "quality",
        "danbooru_min_hot": 0,
        "danbooru_limit": 6000,
        "include_general_danbooru": False,
        "include_general_weilin_tags": False,
        "include_generic_sqlite_without_allow_hint": False,
        "min_prompt_length": 1,
        "max_prompt_length": 120,
    },
    "manual_merge": {
        "replace": {},
        "alias_groups": [],
        "hide": [],
        "category_overrides": {
            "示例：某个英文tag": "姿态动作"
        },
        "display_renames": {
            "示例：某个英文tag": "新的中文显示名 (english tag)"
        },
        "add": {
            "额外标签": [
                {"display": "示例标签 (example tag)", "prompt": "example tag"}
            ]
        }
    },
    "output": {
        "file": DEFAULT_OUTPUT,
        "overwrite": False,
        "legacy_node_key": False,
        "runtime_override_file": DEFAULT_RUNTIME_OVERRIDES,
        "node_display_name": "NSFW 提示词选择器 · 本地合并版"
    }
}


def load_json_file(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def save_json_file(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def deep_update(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    for k, v in src.items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            deep_update(dst[k], v)
        else:
            dst[k] = v
    return dst


def load_config(path: Optional[Path]) -> Dict[str, Any]:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG_TEMPLATE, ensure_ascii=False))
    if path and path.exists():
        user_cfg = load_json_file(path)
        if isinstance(user_cfg, dict):
            deep_update(cfg, user_cfg)
    return cfg


def write_config_template(path: Path, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        log(f"配置文件已存在，不覆盖：{path}")
        return
    save_json_file(path, DEFAULT_CONFIG_TEMPLATE)
    log(f"已写入配置模板：{path}")


def merge_alias_config(cfg: Dict[str, Any]) -> Dict[str, str]:
    replace: Dict[str, str] = {}
    mm = cfg.get("manual_merge", {}) or {}
    for k, v in (mm.get("replace", {}) or {}).items():
        nk, nv = normalize_plain(k), normalize_plain(v)
        if nk and nv:
            replace[nk] = nv
    for group in (mm.get("alias_groups", []) or []):
        if isinstance(group, (list, tuple)) and group:
            canonical = normalize_plain(str(group[0]))
            for x in group[1:]:
                nx = normalize_plain(str(x))
                if nx and canonical:
                    replace[nx] = canonical
    return replace


def hidden_keys_from_config(cfg: Dict[str, Any], aliases: Dict[str, str]) -> set[str]:
    hidden = set()
    for x in ((cfg.get("manual_merge", {}) or {}).get("hide", []) or []):
        key = normalize_for_key(str(x), aliases)
        if key:
            hidden.add(key)
    return hidden


def path_is_excluded(path: Path, exclude_globs: Sequence[str], root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except Exception:
        rel = path
    rel_s = rel.as_posix()
    name = path.name
    if name in SKIP_FILE_NAMES:
        return True
    if name.endswith(("-wal", "-shm", ".pyc")):
        return True
    for pat in exclude_globs:
        try:
            if path.match(pat) or rel.match(pat):
                return True
        except Exception:
            if pat.strip("*") and pat.strip("*") in rel_s:
                return True
    return False


def discover_files(cfg: Dict[str, Any], cwd: Path) -> List[Path]:
    src_cfg = cfg.get("sources", {}) or {}
    explicit = [Path(p).expanduser() for p in (src_cfg.get("explicit_files", []) or []) if str(p).strip()]
    base_py = src_cfg.get("base_promptselector_py") or ""
    if base_py:
        explicit.append(Path(base_py).expanduser())
    roots = [Path(p).expanduser() for p in (src_cfg.get("scan_roots", ["."]) or ["."])]
    recursive = bool(src_cfg.get("recursive", True))
    max_depth = int(src_cfg.get("max_depth", 5) or 5)
    types = set((src_cfg.get("include_file_types", []) or []))
    exclude_globs = src_cfg.get("exclude_globs", []) or []

    allowed_exts = set()
    if "sqlite" in types:
        allowed_exts |= SQLITE_EXTENSIONS
    if "json" in types:
        allowed_exts |= JSON_EXTENSIONS
    if "csv" in types:
        allowed_exts |= CSV_EXTENSIONS
    if "txt" in types:
        allowed_exts |= TEXT_EXTENSIONS
    if "py" in types:
        allowed_exts |= PY_EXTENSIONS

    files: List[Path] = []
    seen = set()

    def add_file(p: Path) -> None:
        p = (cwd / p).resolve() if not p.is_absolute() else p.resolve()
        if not p.exists():
            return
        if p.is_dir():
            return
        if p.suffix.lower() not in allowed_exts:
            return
        if p.name in SKIP_FILE_NAMES:
            return
        key = str(p)
        if key not in seen:
            files.append(p)
            seen.add(key)

    for p in explicit:
        p = (cwd / p).resolve() if not p.is_absolute() else p.resolve()
        if p.is_dir():
            for child in p.rglob("*") if recursive else p.glob("*"):
                if child.is_file() and child.suffix.lower() in allowed_exts and not path_is_excluded(child, exclude_globs, p):
                    # max_depth 限制
                    if recursive:
                        try:
                            depth = len(child.relative_to(p).parts) - 1
                            if depth > max_depth:
                                continue
                        except Exception:
                            pass
                    add_file(child)
        else:
            add_file(p)

    for root in roots:
        root = (cwd / root).resolve() if not root.is_absolute() else root.resolve()
        if not root.exists():
            continue
        iterator = root.rglob("*") if recursive else root.glob("*")
        for child in iterator:
            if not child.is_file():
                continue
            if child.suffix.lower() not in allowed_exts:
                continue
            if path_is_excluded(child, exclude_globs, root):
                continue
            if recursive:
                try:
                    depth = len(child.relative_to(root).parts) - 1
                    if depth > max_depth:
                        continue
                except Exception:
                    pass
            add_file(child)

    # 优先处理 base py / history / tags / danbooru，再处理泛本地库。
    def sort_key(p: Path) -> Tuple[int, str]:
        n = p.name.lower()
        if p.suffix.lower() == ".py" and "promptselector" in n:
            return (0, str(p))
        if "history" in n:
            return (1, str(p))
        if "tags" in n:
            return (2, str(p))
        if "danbooru" in n:
            return (3, str(p))
        if p.suffix.lower() in SQLITE_EXTENSIONS:
            return (4, str(p))
        return (5, str(p))

    files.sort(key=sort_key)
    return files


def sqlite_table_names(path: Path) -> set[str]:
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    except Exception:
        return set()


def sqlite_columns(con: sqlite3.Connection, table: str) -> List[str]:
    try:
        return [r[1] for r in con.execute(f'PRAGMA table_info("{table.replace(chr(34), chr(34)*2)}")').fetchall()]
    except Exception:
        return []


def qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def detect_sqlite_kind(path: Path) -> str:
    tables = sqlite_table_names(path)
    if {"tag_groups", "tag_subgroups", "tag_tags"}.issubset(tables):
        return "weilin_tags"
    if "danbooru_tag" in tables:
        return "danbooru"
    if "history" in tables or "collect_history" in tables:
        return "weilin_history"
    return "generic_sqlite"


def extract_weilin_tags(path: Path, include_general: bool = False) -> List[Item]:
    items: List[Item] = []
    query = """
    SELECT DISTINCT
        g.name AS group_name,
        sg.name AS subgroup_name,
        t.text AS tag,
        t.desc AS desc,
        t.id_index AS tag_id
    FROM tag_groups AS g
    JOIN tag_subgroups AS sg
      ON (sg.group_id = g.id_index OR sg.p_uuid = g.p_uuid)
    JOIN tag_tags AS t
      ON (t.subgroup_id = sg.id_index OR t.g_uuid = sg.g_uuid)
    ORDER BY g.id_index, sg.id_index, t.id_index
    """
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            rows = con.execute(query).fetchall()
    except Exception as e:
        log(f"读取 WeiLin tags 失败：{path} -> {e}")
        return items
    for r in rows:
        prompt = clean_prompt_token(r["tag"])
        desc = clean_text(r["desc"])
        group = clean_text(r["group_name"])
        subgroup = clean_text(r["subgroup_name"])
        if not prompt:
            continue
        ctx = f"{group} {subgroup}"
        is_r18_context = bool(re.search(r"r18|nsfw|成人|情色|性|体液|体位|束缚|R18", ctx, re.IGNORECASE))
        if not include_general and not is_r18_context and not has_allow_hint(prompt, desc, ctx):
            continue
        cat = category_from_context(prompt, desc, group, subgroup, prefer_weilin=True)
        items.append(Item(
            prompt=prompt,
            display=display_from_parts(prompt, desc),
            translate=desc,
            category=cat,
            source_type="weilin_tags",
            source_path=str(path),
            group=group,
            subgroup=subgroup,
        ))
    return items


def extract_danbooru(path: Path, min_hot: int = 0, limit: int = 6000, include_general: bool = False) -> List[Item]:
    items: List[Item] = []
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            where = "WHERE hot >= ?" if min_hot > 0 else ""
            params: Tuple[Any, ...] = (min_hot,) if min_hot > 0 else tuple()
            query = f"SELECT tag, translate, hot, color_id, aliases FROM danbooru_tag {where} ORDER BY hot DESC, id_index ASC"
            if limit and limit > 0:
                query += f" LIMIT {int(limit)}"
            rows = con.execute(query, params).fetchall()
    except Exception as e:
        log(f"读取 Danbooru 失败：{path} -> {e}")
        return items
    for r in rows:
        prompt = clean_prompt_token(r["tag"])
        trans = clean_text(r["translate"])
        if not prompt:
            continue
        if not include_general and not has_allow_hint(prompt, trans):
            continue
        cat = category_from_context(prompt, trans, "danbooru", "", prefer_weilin=False)
        items.append(Item(
            prompt=prompt,
            display=display_from_parts(prompt, trans),
            translate=trans,
            category=cat,
            source_type="danbooru",
            source_path=str(path),
            hot=int(r["hot"] or 0),
        ))
    return items


def parse_history_tag_payload(payload: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    payload = clean_text(payload)
    if not payload:
        return out
    try:
        data = json.loads(payload)
    except Exception:
        data = None
    if isinstance(data, dict):
        for token in data.get("temp_prompt", []) or []:
            if isinstance(token, dict):
                text = clean_prompt_token(token.get("text"))
                translate = clean_text(token.get("translate"))
                if text and not token.get("isPunctuation"):
                    out.append((text, translate))
        for token in split_prompt_line(data.get("prompt", "")):
            out.append((token, ""))
    else:
        for token in split_prompt_line(payload):
            out.append((token, ""))
    # 去重保序
    seen = set()
    final = []
    for p, zh in out:
        k = normalize_plain(p)
        if k and k not in seen:
            seen.add(k)
            final.append((p, zh))
    return final


def extract_history(path: Path) -> List[Item]:
    items: List[Item] = []
    tables = sqlite_table_names(path)
    for table, stype in [("history", "weilin_history"), ("collect_history", "weilin_collect_history")]:
        if table not in tables:
            continue
        try:
            with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
                con.row_factory = sqlite3.Row
                cols = sqlite_columns(con, table)
                if "tag" not in cols:
                    continue
                rows = con.execute(f"SELECT tag, name, create_time, is_deleted FROM {qident(table)} ORDER BY create_time DESC").fetchall()
        except Exception as e:
            log(f"读取历史库失败：{path}:{table} -> {e}")
            continue
        for r in rows:
            try:
                if int(r["is_deleted"] or 0):
                    continue
            except Exception:
                pass
            for prompt, trans in parse_history_tag_payload(r["tag"]):
                cat = category_from_context(prompt, trans, "history", "", prefer_weilin=True)
                # 历史常用：不强制全部放历史类；有明确分类就归到具体类，兜底才历史常用。
                if cat == "额外标签":
                    cat = "历史常用"
                items.append(Item(
                    prompt=prompt,
                    display=display_from_parts(prompt, trans),
                    translate=trans,
                    category=cat,
                    source_type=stype,
                    source_path=str(path),
                ))
    return items


def extract_generic_sqlite(path: Path, cfg: Dict[str, Any]) -> List[Item]:
    items: List[Item] = []
    include_without_hint = bool((cfg.get("filters", {}) or {}).get("include_generic_sqlite_without_allow_hint", False))
    try:
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()]
            for table in tables:
                cols = sqlite_columns(con, table)
                lower_cols = {c.lower(): c for c in cols}
                candidate_cols = [c for c in cols if c.lower() in {
                    "tag", "tags", "text", "prompt", "positive", "positive_prompt", "name", "alias", "aliases", "keyword", "keywords", "content", "value"
                }]
                if not candidate_cols:
                    continue
                translate_col = next((lower_cols.get(k) for k in ["translate", "translation", "desc", "description", "cn", "zh", "chinese"] if lower_cols.get(k)), None)
                cat_col = next((lower_cols.get(k) for k in ["category", "group", "subgroup", "type"] if lower_cols.get(k)), None)
                select_cols = list(dict.fromkeys(candidate_cols + ([translate_col] if translate_col else []) + ([cat_col] if cat_col else [])))
                query = f"SELECT {', '.join(qident(c) for c in select_cols)} FROM {qident(table)} LIMIT 20000"
                try:
                    rows = con.execute(query).fetchall()
                except Exception:
                    continue
                for r in rows:
                    trans = clean_text(r[translate_col]) if translate_col else ""
                    ctx = clean_text(r[cat_col]) if cat_col else table
                    for c in candidate_cols:
                        raw = r[c]
                        if raw is None:
                            continue
                        # tag/name 单字段通常是一个标签；prompt/content 可能是逗号串。
                        tokens = split_prompt_line(str(raw)) if c.lower() in {"tags", "prompt", "positive", "positive_prompt", "content", "keywords"} else [clean_prompt_token(raw)]
                        for prompt in tokens:
                            if not prompt:
                                continue
                            if not include_without_hint and not has_allow_hint(prompt, trans, ctx):
                                continue
                            cat = category_from_context(prompt, trans, ctx, "", prefer_weilin=False)
                            items.append(Item(
                                prompt=prompt,
                                display=display_from_parts(prompt, trans),
                                translate=trans,
                                category=cat,
                                source_type="generic_sqlite",
                                source_path=f"{path}:{table}",
                                group=ctx,
                            ))
    except Exception as e:
        log(f"读取泛 SQLite 失败：{path} -> {e}")
    return items


def extract_json(path: Path) -> List[Item]:
    items: List[Item] = []
    try:
        data = load_json_file(path)
    except Exception as e:
        log(f"读取 JSON 失败：{path} -> {e}")
        return items

    def walk(obj: Any, category_hint: str = "") -> None:
        if obj is None:
            return
        if isinstance(obj, str):
            for prompt in extract_strings_from_any(obj):
                if not prompt:
                    continue
                if not has_allow_hint(prompt, "", category_hint):
                    continue
                cat = category_from_context(prompt, "", category_hint, "", prefer_weilin=False)
                items.append(Item(prompt=prompt, display=prompt, category=cat, source_type="local_json", source_path=str(path), group=category_hint))
            return
        if isinstance(obj, list):
            for x in obj:
                walk(x, category_hint)
            return
        if isinstance(obj, dict):
            # 典型 tag 对象
            tag = obj.get("prompt", obj.get("tag", obj.get("text", obj.get("alias", obj.get("value", "")))))
            trans = obj.get("translate", obj.get("translation", obj.get("desc", obj.get("description", obj.get("zh", obj.get("cn", ""))))))
            display = obj.get("display", obj.get("name", ""))
            cat_raw = obj.get("category", obj.get("group", obj.get("subgroup", category_hint)))
            if tag:
                tokens = extract_strings_from_any(tag)
                for prompt in tokens:
                    if not prompt:
                        continue
                    if not has_allow_hint(prompt, str(trans), str(cat_raw)) and not category_hint:
                        continue
                    cat = category_from_context(prompt, str(trans), str(cat_raw), "", prefer_weilin=True)
                    items.append(Item(
                        prompt=prompt,
                        display=clean_text(display) or display_from_parts(prompt, str(trans)),
                        translate=clean_text(trans),
                        category=cat,
                        source_type="local_json",
                        source_path=str(path),
                        group=clean_text(cat_raw),
                    ))
                return
            # category -> children
            for k, v in obj.items():
                if k in {"说明", "description", "version"}:
                    continue
                new_hint = clean_text(k) or category_hint
                walk(v, new_hint)

    walk(data)
    return items


def extract_csv(path: Path) -> List[Item]:
    items: List[Item] = []
    try:
        sample = path.read_text(encoding="utf-8-sig", errors="ignore")[:4096]
        delimiter = "\t" if path.suffix.lower() == ".tsv" else None
        if delimiter is None:
            try:
                delimiter = csv.Sniffer().sniff(sample).delimiter
            except Exception:
                delimiter = ","
        with path.open("r", encoding="utf-8-sig", errors="ignore", newline="") as f:
            reader = csv.DictReader(f, delimiter=delimiter)
            if not reader.fieldnames:
                return items
            for row in reader:
                lower = {str(k).lower(): k for k in row.keys()}
                tag_col = next((lower.get(k) for k in ["prompt", "tag", "text", "alias", "value", "tags", "positive", "positive_prompt", "keyword", "keywords"] if lower.get(k)), None)
                if not tag_col:
                    # 无表头或不规范时，读第一个非空值
                    vals = [v for v in row.values() if clean_text(v)]
                    if not vals:
                        continue
                    tag_val = vals[0]
                else:
                    tag_val = row.get(tag_col, "")
                trans_col = next((lower.get(k) for k in ["translate", "translation", "desc", "description", "zh", "cn"] if lower.get(k)), None)
                disp_col = next((lower.get(k) for k in ["display", "name", "label"] if lower.get(k)), None)
                cat_col = next((lower.get(k) for k in ["category", "group", "subgroup", "type"] if lower.get(k)), None)
                trans = clean_text(row.get(trans_col, "")) if trans_col else ""
                disp = clean_text(row.get(disp_col, "")) if disp_col else ""
                ctx = clean_text(row.get(cat_col, "")) if cat_col else ""
                for prompt in extract_strings_from_any(tag_val):
                    if not prompt:
                        continue
                    if not has_allow_hint(prompt, trans, ctx):
                        continue
                    cat = category_from_context(prompt, trans, ctx, "", prefer_weilin=False)
                    items.append(Item(
                        prompt=prompt,
                        display=disp or display_from_parts(prompt, trans),
                        translate=trans,
                        category=cat,
                        source_type="local_csv",
                        source_path=str(path),
                        group=ctx,
                    ))
    except Exception as e:
        log(f"读取 CSV/TSV 失败：{path} -> {e}")
    return items


def extract_txt(path: Path) -> List[Item]:
    items: List[Item] = []
    try:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception as e:
        log(f"读取 TXT 失败：{path} -> {e}")
        return items
    for line in text.splitlines():
        line = clean_text(line)
        if not line or line.startswith("#") or line.startswith("//"):
            continue
        for prompt in split_prompt_line(line):
            if not prompt:
                continue
            if not has_allow_hint(prompt, "", path.stem):
                continue
            cat = category_from_context(prompt, "", path.stem, "", prefer_weilin=False)
            items.append(Item(prompt=prompt, display=prompt, category=cat, source_type="local_txt", source_path=str(path), group=path.stem))
    return items


PROMPTSELECTOR_METHOD_CATEGORY = {
    "_get_scene_mapping": "场景地点",
    "_get_action_mapping": "姿态动作",
    "_get_clothing_mapping": "服装外观",
    "_get_mood_mapping": "表情反应",
    "_get_camera_movement_mapping": "镜头构图",
    "_get_camera_angle_mapping": "镜头构图",
    "_get_light_source_mapping": "光线色调",
    "_get_light_type_mapping": "光线色调",
    "_get_lens_type_mapping": "镜头构图",
    "_get_focal_length_mapping": "镜头构图",
    "_get_color_tone_mapping": "光线色调",
    "_get_visual_style_mapping": "画面风格",
    "_get_effect_mapping": "画面风格",
    "_get_filter_mapping": "画面风格",
}

PROMPTSELECTOR_LIST_CATEGORY = {
    "触发词选项": "主体关系",
    "场景类型选项": "场景地点",
    "动作姿态选项": "姿态动作",
    "服饰选项": "服装外观",
    "情绪氛围选项": "表情反应",
    "运镜方式选项": "镜头构图",
    "机位角度选项": "镜头构图",
    "光源类型选项": "光线色调",
    "光线类型选项": "光线色调",
    "镜头类型选项": "镜头构图",
    "焦距选项": "镜头构图",
    "色调选项": "光线色调",
    "视觉风格选项": "画面风格",
    "特效镜头选项": "画面风格",
    "镜头滤镜选项": "画面风格",
}

PROMPTSELECTOR_MAPPING_CATEGORY = {
    "触发词映射": "主体关系",
}


def literal_eval_node(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def extract_return_dict_from_function(fn: ast.FunctionDef) -> Optional[Dict[Any, Any]]:
    for node in ast.walk(fn):
        if isinstance(node, ast.Return):
            value = literal_eval_node(node.value)
            if isinstance(value, dict):
                return value
    return None


def extract_base_promptselector_py(path: Path) -> List[Item]:
    """从原 PromptSelector.py 中抽取列表/映射。不会执行该文件。"""
    items: List[Item] = []
    try:
        text = path.read_text(encoding="utf-8-sig", errors="ignore")
        tree = ast.parse(text)
    except Exception as e:
        log(f"解析 Python PromptSelector 失败：{path} -> {e}")
        return items

    # class-level mappings / lists
    list_values: Dict[str, List[str]] = {}
    dict_values: Dict[str, Dict[str, str]] = {}
    method_maps: Dict[str, Dict[str, str]] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.Assign):
                    for target in stmt.targets:
                        if isinstance(target, ast.Name):
                            value = literal_eval_node(stmt.value)
                            if isinstance(value, list) and target.id.endswith("选项"):
                                list_values[target.id] = [clean_text(x) for x in value if clean_text(x) and clean_text(x) != "——"]
                            elif isinstance(value, dict) and (target.id.endswith("映射") or target.id in PROMPTSELECTOR_MAPPING_CATEGORY):
                                dict_values[target.id] = {clean_text(k): clean_text(v) for k, v in value.items() if clean_text(k) and clean_text(v)}
                elif isinstance(stmt, ast.FunctionDef) and stmt.name in PROMPTSELECTOR_METHOD_CATEGORY:
                    d = extract_return_dict_from_function(stmt)
                    if isinstance(d, dict):
                        method_maps[stmt.name] = {clean_text(k): clean_text(v) for k, v in d.items() if clean_text(k) and clean_text(v)}

    # 先读 dict mapping，最可靠。
    for name, mapping in dict_values.items():
        cat = PROMPTSELECTOR_MAPPING_CATEGORY.get(name, category_from_context(name, "", "", "", prefer_weilin=True))
        for display, prompt in mapping.items():
            if display == "——" or not prompt:
                continue
            items.append(Item(
                prompt=prompt,
                display=display,
                category=cat,
                source_type="base_promptselector",
                source_path=str(path),
                group=name,
            ))

    for name, mapping in method_maps.items():
        cat = PROMPTSELECTOR_METHOD_CATEGORY.get(name, "额外标签")
        for display, prompt in mapping.items():
            if display == "——" or not prompt:
                continue
            items.append(Item(
                prompt=prompt,
                display=display,
                category=cat,
                source_type="base_promptselector",
                source_path=str(path),
                group=name,
            ))

    # 再读没有 mapping 的 list 值。
    mapped_displays = {i.display for i in items}
    for name, values in list_values.items():
        if name in {"随机选择选项", "预设选项", "质量等级选项", "负面提示词预设选项"}:
            continue
        cat = PROMPTSELECTOR_LIST_CATEGORY.get(name, "额外标签")
        for display in values:
            if display in mapped_displays or display == "——":
                continue
            # 如果 display 形如 中文 (english)，取括号英文。
            m = re.search(r"\(([^()]+)\)\s*$", display)
            prompt = clean_prompt_token(m.group(1) if m else display)
            if not prompt:
                continue
            items.append(Item(
                prompt=prompt,
                display=display,
                category=cat,
                source_type="base_promptselector",
                source_path=str(path),
                group=name,
            ))
    return items


def category_from_context(prompt: str, translate: str = "", group: str = "", subgroup: str = "", prefer_weilin: bool = False) -> str:
    ctx = " ".join(clean_text(x) for x in [prompt, translate, group, subgroup] if clean_text(x))
    low = ctx.lower().replace("_", " ").replace("-", " ")

    # WeiLin 分组直映射。
    direct_map = {
        "人物关系": "主体关系",
        "对象": "主体关系",
        "身份": "角色身份",
        "角色": "角色身份",
        "二次元角色": "角色身份",
        "服饰": "服装外观",
        "服装状态": "服装外观",
        "身体部位": "身体特征",
        "身体特征": "身体特征",
        "表情反应": "表情反应",
        "表情动作": "表情反应",
        "行为互动": "成人互动",
        "体位姿态": "姿态动作",
        "体液痕迹": "体液痕迹",
        "道具器具": "道具器具",
        "束缚控制": "束缚BDSM",
        "场景处境": "场景地点",
        "环境": "场景地点",
        "镜头构图": "镜头构图",
        "画面": "画面风格",
        "画风": "画面风格",
        "光照": "光线色调",
        "色调": "光线色调",
        "R18词": "额外标签",
        "质量": "质量风格",
    }
    for key, cat in direct_map.items():
        if key.lower() in low:
            return cat

    for cat, keywords in CATEGORY_RULES:
        for kw in keywords:
            if kw.lower() in low:
                return cat
    return "额外标签"


def apply_manual_config_items(cfg: Dict[str, Any]) -> List[Item]:
    items: List[Item] = []
    add = ((cfg.get("manual_merge", {}) or {}).get("add", {}) or {})
    if isinstance(add, dict):
        for cat, rows in add.items():
            if not isinstance(rows, list):
                continue
            cat = cat if cat in CATEGORY_ORDER else "额外标签"
            for row in rows:
                if isinstance(row, str):
                    prompt = clean_prompt_token(row)
                    display = prompt
                    trans = ""
                elif isinstance(row, dict):
                    prompt = clean_prompt_token(row.get("prompt") or row.get("tag") or row.get("text") or "")
                    display = clean_text(row.get("display") or row.get("name") or "")
                    trans = clean_text(row.get("translate") or row.get("desc") or "")
                else:
                    continue
                if not prompt or prompt == "example tag":
                    continue
                items.append(Item(prompt=prompt, display=display or display_from_parts(prompt, trans), translate=trans, category=cat, source_type="manual_config", source_path="config.manual_merge.add"))
    return items


def extract_items_from_file(path: Path, cfg: Dict[str, Any]) -> List[Item]:
    ext = path.suffix.lower()
    if ext in SQLITE_EXTENSIONS:
        kind = detect_sqlite_kind(path)
        if kind == "weilin_tags":
            f = cfg.get("filters", {}) or {}
            return extract_weilin_tags(path, include_general=bool(f.get("include_general_weilin_tags", False)))
        if kind == "danbooru":
            f = cfg.get("filters", {}) or {}
            return extract_danbooru(path, int(f.get("danbooru_min_hot", 0) or 0), int(f.get("danbooru_limit", 6000) or 6000), bool(f.get("include_general_danbooru", False)))
        if kind == "weilin_history":
            return extract_history(path)
        return extract_generic_sqlite(path, cfg)
    if ext in JSON_EXTENSIONS:
        # 不要把 override/config/report JSON 自己吃进去。
        if path.name in {DEFAULT_CONFIG, DEFAULT_RUNTIME_OVERRIDES}:
            return []
        return extract_json(path)
    if ext in CSV_EXTENSIONS:
        if path.name in {DEFAULT_DUPLICATES_CSV, DEFAULT_EXCLUDED_CSV}:
            return []
        return extract_csv(path)
    if ext in TEXT_EXTENSIONS:
        if path.name == DEFAULT_REPORT:
            return []
        return extract_txt(path)
    if ext in PY_EXTENSIONS:
        # 只解析疑似 PromptSelector 的 py，避免把生成器自己的文本拆进去。
        name = path.name.lower()
        if "promptselector" in name or "prompt_selector" in name or "nsfw" in name:
            return extract_base_promptselector_py(path)
    return []




def sort_key_for_item(item: Item, mode: str) -> tuple:
    """Build-time category sorting. This is deterministic and does not merge near-duplicates."""
    mode = (mode or "quality").strip().lower()
    display_key = normalize_plain(item.display or item.prompt)
    prompt_key = normalize_plain(item.prompt)
    source_key = SOURCE_PRIORITY.get(item.source_type, SOURCE_PRIORITY["unknown"])
    if mode in {"display", "display_az", "name", "az"}:
        return (display_key, prompt_key, -item.hot, -item.quality_score())
    if mode in {"prompt", "prompt_az"}:
        return (prompt_key, display_key, -item.hot, -item.quality_score())
    if mode in {"hot", "danbooru_hot", "frequency"}:
        return (-item.hot, display_key, prompt_key)
    if mode in {"source", "source_then_name"}:
        return (-source_key, display_key, prompt_key, -item.hot)
    if mode in {"length", "short_first"}:
        return (len(item.prompt), display_key, prompt_key)
    if mode in {"long_first"}:
        return (-len(item.prompt), display_key, prompt_key)
    # quality: WeiLin tags / base script / high-hot entries first, then stable A-Z.
    return (-item.quality_score(), -item.hot, display_key, prompt_key)

def filter_and_dedupe_items(items: List[Item], cfg: Dict[str, Any]) -> Tuple[Dict[str, List[Item]], List[Excluded], List[DuplicateRecord], Dict[str, Any]]:
    filters = cfg.get("filters", {}) or {}
    max_len = int(filters.get("max_prompt_length", 120) or 120)
    min_len = int(filters.get("min_prompt_length", 1) or 1)
    enable_fuzzy = False  # v3：按用户要求禁用近似去重，只保留精确/别名合并。
    threshold = float(filters.get("fuzzy_threshold", 0.92) or 0.92)
    max_per_cat = int(filters.get("max_per_category", 500) or 0)
    sort_mode = str(filters.get("sort_mode", "quality") or "quality")
    aliases = merge_alias_config(cfg)
    hidden = hidden_keys_from_config(cfg, aliases)
    cat_overrides_raw = ((cfg.get("manual_merge", {}) or {}).get("category_overrides", {}) or {})
    cat_overrides = {normalize_for_key(k, aliases): v for k, v in cat_overrides_raw.items() if v in CATEGORY_ORDER}
    display_renames_raw = ((cfg.get("manual_merge", {}) or {}).get("display_renames", {}) or {})
    display_renames = {normalize_for_key(k, aliases): clean_text(v) for k, v in display_renames_raw.items() if clean_text(v)}

    excluded: List[Excluded] = []
    duplicates: List[DuplicateRecord] = []
    by_key: OrderedDict[str, Item] = OrderedDict()
    key_to_bucket: Dict[str, str] = {}
    fuzzy_buckets: Dict[Tuple[str, int], List[str]] = defaultdict(list)
    source_counts = Counter()

    def exclude(item: Item, reason: str) -> None:
        excluded.append(Excluded(item.prompt, item.display, item.category, item.source_type, item.source_path, reason))

    def find_fuzzy_key(item_key: str, category: str) -> Optional[Tuple[str, float]]:
        if not enable_fuzzy or not item_key:
            return None
        toks = item_key.split()
        if not toks:
            return None
        prefix = toks[0][:3]
        length = len(toks)
        candidates: List[str] = []
        for d in (-2, -1, 0, 1, 2):
            candidates.extend(fuzzy_buckets.get((prefix, length + d), []))
        # 同时比较同类别所有短 key，避免 one-word 同义词漏掉。
        if len(toks) <= 2:
            candidates.extend(fuzzy_buckets.get((prefix, 1), []))
            candidates.extend(fuzzy_buckets.get((prefix, 2), []))
        seen_cands = set()
        best_key, best_ratio = None, 0.0
        for old_key in candidates:
            if old_key in seen_cands:
                continue
            seen_cands.add(old_key)
            old_item = by_key.get(old_key)
            if not old_item:
                continue
            if old_item.category != category:
                # 跨分类只做严格 key 合并，不做 fuzzy，以免误折叠。
                continue
            ratio = difflib.SequenceMatcher(None, item_key, old_key).ratio()
            if ratio > best_ratio:
                best_key, best_ratio = old_key, ratio
        if best_key and best_ratio >= threshold:
            return best_key, best_ratio
        return None

    for item in items:
        item.finalize_display()
        if not item.prompt:
            exclude(item, "empty_prompt")
            continue
        if len(item.prompt) < min_len or len(item.prompt) > max_len:
            exclude(item, "length_filter")
            continue
        # 默认安全过滤。
        if is_blocked(item.prompt, item.display, f"{item.group} {item.subgroup}"):
            exclude(item, "safety_blocklist")
            continue
        key = item.normalized(aliases)
        if not key:
            exclude(item, "empty_normalized_key")
            continue
        if key in hidden:
            exclude(item, "manual_hide")
            continue
        if key in cat_overrides:
            item.category = cat_overrides[key]
        if key in display_renames:
            item.display = display_renames[key]
        source_counts[item.source_type] += 1

        if key in by_key:
            old = by_key[key]
            if item.quality_score() > old.quality_score():
                by_key[key] = item
                duplicates.append(DuplicateRecord(item.prompt, item.display, old.prompt, old.display, item.category, "exact_or_alias_key_replaced", 1.0, item.source_type, old.source_type))
            else:
                duplicates.append(DuplicateRecord(old.prompt, old.display, item.prompt, item.display, old.category, "exact_or_alias_key", 1.0, old.source_type, item.source_type))
            continue
        fuzzy = find_fuzzy_key(key, item.category)
        if fuzzy:
            old_key, ratio = fuzzy
            old = by_key[old_key]
            if item.quality_score() > old.quality_score() + 5:
                by_key[old_key] = item
                duplicates.append(DuplicateRecord(item.prompt, item.display, old.prompt, old.display, item.category, "fuzzy_replaced", ratio, item.source_type, old.source_type))
            else:
                duplicates.append(DuplicateRecord(old.prompt, old.display, item.prompt, item.display, old.category, "fuzzy", ratio, old.source_type, item.source_type))
            continue

        by_key[key] = item
        toks = key.split()
        prefix = toks[0][:3] if toks else ""
        fuzzy_buckets[(prefix, len(toks))].append(key)

    # 分类聚合、排序、截断。
    categorized: Dict[str, List[Item]] = {cat: [] for cat in CATEGORY_ORDER}
    for item in by_key.values():
        cat = item.category if item.category in CATEGORY_ORDER else "额外标签"
        categorized[cat].append(item)

    for cat in CATEGORY_ORDER:
        categorized[cat].sort(key=lambda i: sort_key_for_item(i, sort_mode))
        if max_per_cat and max_per_cat > 0 and len(categorized[cat]) > max_per_cat:
            for item in categorized[cat][max_per_cat:]:
                exclude(item, f"max_per_category>{max_per_cat}")
            categorized[cat] = categorized[cat][:max_per_cat]

    stats = {
        "accepted_total": sum(len(v) for v in categorized.values()),
        "excluded_total": len(excluded),
        "duplicate_total": len(duplicates),
        "source_counts_after_basic_filters": dict(source_counts),
        "category_counts": {cat: len(categorized.get(cat, [])) for cat in CATEGORY_ORDER},
    }
    return categorized, excluded, duplicates, stats


def category_data_for_output(categorized: Dict[str, List[Item]]) -> Dict[str, Dict[str, str]]:
    data: Dict[str, Dict[str, str]] = OrderedDict()
    for cat in CATEGORY_ORDER:
        mapping: OrderedDict[str, str] = OrderedDict()
        for item in categorized.get(cat, []):
            display = item.display or display_from_parts(item.prompt, item.translate)
            prompt = item.prompt
            # 确保 display 唯一。
            if display in mapping and mapping[display] != prompt:
                display = f"{display} #{stable_id(prompt)}"
            mapping[display] = prompt
        if mapping:
            data[cat] = mapping
    return data


def negative_presets() -> Dict[str, str]:
    return {
        "标准负面提示词": "low quality, worst quality, normal quality, lowres, pixelated, blurry, bad anatomy, bad hands, bad feet, missing fingers, extra fingers, mutated hands, poorly drawn hands, poorly drawn face, mutation, deformed, ugly, bad proportions, extra limbs, malformed limbs, fused fingers, too many fingers, long neck, cross-eyed, duplicate, out of frame, disfigured, missing arms, missing legs, extra arms, extra legs, watermark, signature, text",
        "WAN视频负面提示词": "色调艳丽，过曝，静态，细节模糊不清，字幕，风格，作品，画作，画面，静止，整体发灰，最差质量，低质量，JPEG压缩残留，丑陋的，残缺的，多余的手指，画得不好的手部，画得不好的脸部，畸形的，毁容的，形态畸形的肢体，手指融合，静止不动的画面，杂乱的背景，三条腿，背景人很多，倒着走",
        "文生图负面提示词": "(low quality:1.5), (worst quality:1.5), (normal quality:1.5), (lowres:1.5), (pixelated:1.5), (blurry:1.5), (bad anatomy:1.5), (bad hands:1.5), (bad feet:1.5), (missing fingers:1.5), (extra fingers:1.5), (mutated hands:1.5), (poorly drawn hands:1.5), (poorly drawn face:1.5), (mutation:1.5), (deformed:1.5), (ugly:1.5), (bad proportions:1.5), (extra limbs:1.5), (malformed limbs:1.5), (fused fingers:1.5), (too many fingers:1.5), (long neck:1.5), (cross-eyed:1.5), (duplicate:1.5), (out of frame:1.5), (disfigured:1.5), (missing arms:1.5), (missing legs:1.5), (extra arms:1.5), (extra legs:1.5), (username:1.5), (watermark:1.5), (signature:1.5), (text:1.5)",
        "高质量负面提示词": "(worst quality:2.0), (low quality:2.0), (normal quality:1.8), (lowres:1.8), (bad anatomy:1.8), (bad hands:1.8), (text:1.8), (error:1.8), (missing fingers:1.8), (extra digit:1.8), (fewer digits:1.8), (cropped:1.8), (jpeg artifacts:1.8), (signature:1.8), (watermark:1.8), (username:1.8), (blurry:1.8), (artist name:1.8), (out of focus:1.8), (ugly:1.8), (duplicate:1.8), (extra fingers:1.8), (mutated hands:1.8), (poorly drawn hands:1.8), (poorly drawn face:1.8), (mutation:1.8), (deformed:1.8), (bad proportions:1.8), (extra limbs:1.8), (cloned face:1.8), (disfigured:1.8), (malformed limbs:1.8), (missing arms:1.8), (missing legs:1.8), (extra arms:1.8), (extra legs:1.8), (fused fingers:1.8), (too many fingers:1.8), (long neck:1.8), (cross-eyed:1.8)",
        "自定义负面提示词": "",
    }


def generate_node_script(category_data: Dict[str, Dict[str, str]], cfg: Dict[str, Any], stats: Dict[str, Any]) -> str:
    output_cfg = cfg.get("output", {}) or {}
    legacy = bool(output_cfg.get("legacy_node_key", False))
    runtime_file = clean_text(output_cfg.get("runtime_override_file") or DEFAULT_RUNTIME_OVERRIDES)
    display_name = clean_text(output_cfg.get("node_display_name") or "NSFW 提示词选择器 · 本地合并版")
    category_weights = {cat: DEFAULT_CATEGORY_WEIGHTS.get(cat, 1.0) for cat in category_data.keys()}
    generated_at = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    node_key = "NSFWPromptSelector_LocalMerged"
    legacy_line = f'    "NSFWPromptSelector": NSFWPromptSelector_LocalMerged,\n' if legacy else ""
    legacy_display_line = f'    "NSFWPromptSelector": "NSFW 提示词选择器",\n' if legacy else ""

    # 运行时脚本内也放同一套安全过滤。注意用 repr，避免转义错误。
    block_patterns_literal = py_literal(BLOCK_PATTERNS)
    category_order_literal = py_literal(list(category_data.keys()))
    category_data_literal = py_literal(category_data)
    category_weights_literal = py_literal(category_weights)
    negative_presets_literal = py_literal(negative_presets())
    stats_literal = py_literal(stats)

    script = fr'''# -*- coding: utf-8 -*-
"""
Auto-generated ComfyUI PromptSelector.

生成时间：{generated_at}
生成器版本：{BUILDER_VERSION}

本文件可以直接放入 ComfyUI/custom_nodes 的任意子目录。
同目录下可放 {runtime_file} 进行运行时增删改/隐藏/排序/置顶。
也可以在 ComfyUI 里使用“PromptSelector 本地排序复核编辑器”节点写入该 override 文件。
"""

from __future__ import annotations

import ast
import json
import os
import random
import re
from collections import OrderedDict

CATEGORY = "prompt/nsfw_generator"
RUNTIME_OVERRIDE_FILE = {runtime_file!r}
CATEGORY_ORDER = {category_order_literal}
CATEGORY_DATA = {category_data_literal}
CATEGORY_WEIGHTS = {category_weights_literal}
NEGATIVE_PRESETS = {negative_presets_literal}
BUILD_STATS = {stats_literal}
BLOCK_PATTERNS = {block_patterns_literal}
BLOCK_RE = re.compile("|".join(f"(?:{{p}})" for p in BLOCK_PATTERNS), re.IGNORECASE)

QUALITY_LEVELS = ["标准", "高质量", "超高质量", "大师级"]
RANDOM_MODES = ["关闭", "每类随机1个", "随机3个", "随机5个", "随机10个"]
NEGATIVE_TYPES = list(NEGATIVE_PRESETS.keys())
DEDUP_MODES = ["不去重", "严格去重"]
SORT_MODES = ["保持当前顺序", "显示名升序", "显示名降序", "Prompt升序", "Prompt降序", "短词优先", "长词优先", "中文显示名优先", "英文显示名优先"]
OVERRIDE_SWITCH = ["开启", "关闭"]
NL = chr(10)
_CATEGORY_DATA_CACHE = {{"mtime": None, "data": None}}


def _clean_text(value):
    if value is None:
        return ""
    s = str(value).replace(chr(0xfeff), "").replace(chr(13), " ").replace(chr(10), " ").replace(chr(9), " ")
    return re.sub(r"\s+", " ", s).strip()


def _clean_prompt(value):
    s = _clean_text(value).strip(" ,;，；")
    m = re.fullmatch(r"[\(\[\{{]\s*(.+?)\s*:[0-9.]+\s*[\)\]\}}]", s)
    if m:
        s = m.group(1).strip()
    return s


def _normalize_key(text):
    s = _clean_prompt(text).lower().replace("_", " ").replace("-", " ")
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # v3: 不做自动语义/近似合并；只做大小写、空格、符号、简单单复数归一。
    replacements = {{}}
    for k in sorted(replacements, key=len, reverse=True):
        pattern = "(?<![A-Za-z0-9])" + re.escape(k) + "(?![A-Za-z0-9])"
        s = re.sub(pattern, replacements[k], s)
    words = []
    for w in s.split():
        if re.match(r"^[0-9]+girls?$", w) or re.match(r"^[0-9]+boys?$", w):
            words.append(w)
        elif len(w) > 5 and w.endswith("ies"):
            words.append(w[:-3] + "y")
        elif len(w) > 4 and w.endswith("ses"):
            words.append(w[:-2])
        elif len(w) > 4 and w.endswith("s") and not w.endswith("ss"):
            words.append(w[:-1])
        else:
            words.append(w)
    return " ".join(words).strip()


def _is_blocked(prompt, display=""):
    joined = f"{{prompt}} {{display}}"
    joined_norm = joined.replace("_", " ").replace("-", " ")
    return bool(BLOCK_RE.search(joined) or BLOCK_RE.search(joined_norm))


def _script_dir():
    return os.path.dirname(os.path.abspath(__file__)) if "__file__" in globals() else os.getcwd()


def _override_path():
    return os.path.join(_script_dir(), RUNTIME_OVERRIDE_FILE)


def _default_override_data():
    return {{
        "说明": "PromptSelector 运行时覆盖文件。改完后重启 ComfyUI 或刷新节点定义。可用本文件内置的排序复核编辑器节点写入。",
        "add": {{}},
        "hide": [],
        "replace": {{}},
        "move": {{}},
        "rename_display": {{}},
        "alias_groups": [],
        "sort": {{"global_mode": "保持当前顺序", "category_modes": {{}}, "pins": {{}}, "ranks": {{}}}},
        "pin": {{}}
    }}


def _load_override():
    path = _override_path()
    if not os.path.exists(path):
        return _default_override_data()
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        if isinstance(data, dict):
            base = _default_override_data()
            for k, v in data.items():
                base[k] = v
            return base
    except Exception as e:
        print(f"[PromptSelector] 读取 override 失败: {{path}} -> {{e}}")
    return _default_override_data()


def _save_override(data):
    path = _override_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def _normalize_override_replace(data):
    replace = {{}}
    raw = data.get("replace", {{}}) or {{}}
    if isinstance(raw, dict):
        for k, v in raw.items():
            nk, nv = _normalize_key(k), _normalize_key(v)
            if nk and nv:
                replace[nk] = nv
    for group in data.get("alias_groups", []) or []:
        if isinstance(group, list) and group:
            canonical = _normalize_key(group[0])
            for x in group[1:]:
                nx = _normalize_key(x)
                if canonical and nx:
                    replace[nx] = canonical
    return replace


def _apply_replacements(prompt, replace):
    key = _normalize_key(prompt)
    if key in replace:
        return replace[key]
    return prompt


def _contains_chinese(text):
    return bool(re.search(r"[\u4e00-\u9fff]", _clean_text(text)))


def _sort_mapping_for_category(cat, mapping, override_data):
    items = list(mapping.items())
    if not items:
        return OrderedDict()
    sort_rules = override_data.get("sort", {{}}) or {{}}
    mode = sort_rules.get(cat, "保持当前顺序")
    if isinstance(mode, dict):
        mode = mode.get("mode", "保持当前顺序")
    if mode not in SORT_MODES:
        mode = "保持当前顺序"

    pin_rules = override_data.get("pin", {{}}) or {{}}
    raw_pins = pin_rules.get(cat, [])
    if isinstance(raw_pins, str):
        raw_pins = [raw_pins]
    if not isinstance(raw_pins, list):
        raw_pins = []
    pin_keys = [_normalize_key(x) for x in raw_pins if _normalize_key(x)]

    pinned = []
    unpinned = []
    for idx, (display, prompt) in enumerate(items):
        key_p = _normalize_key(prompt)
        key_d = _normalize_key(display)
        rank = None
        for i, pk in enumerate(pin_keys):
            if pk == key_p or pk == key_d:
                rank = i
                break
        if rank is None:
            unpinned.append((idx, display, prompt))
        else:
            pinned.append((rank, idx, display, prompt))

    pinned.sort(key=lambda x: (x[0], x[1]))

    def key_display(row):
        _, display, prompt = row
        return (_normalize_key(display), _normalize_key(prompt))

    def key_prompt(row):
        _, display, prompt = row
        return (_normalize_key(prompt), _normalize_key(display))

    def key_len(row):
        _, display, prompt = row
        return (len(_clean_prompt(prompt)), _normalize_key(display))

    def key_zh_first(row):
        _, display, prompt = row
        return (0 if _contains_chinese(display) else 1, _normalize_key(display), _normalize_key(prompt))

    def key_en_first(row):
        _, display, prompt = row
        return (0 if not _contains_chinese(display) else 1, _normalize_key(display), _normalize_key(prompt))

    if mode == "显示名升序":
        unpinned = sorted(unpinned, key=key_display)
    elif mode == "显示名降序":
        unpinned = sorted(unpinned, key=key_display, reverse=True)
    elif mode == "Prompt升序":
        unpinned = sorted(unpinned, key=key_prompt)
    elif mode == "Prompt降序":
        unpinned = sorted(unpinned, key=key_prompt, reverse=True)
    elif mode == "短词优先":
        unpinned = sorted(unpinned, key=key_len)
    elif mode == "长词优先":
        unpinned = sorted(unpinned, key=key_len, reverse=True)
    elif mode == "中文显示名优先":
        unpinned = sorted(unpinned, key=key_zh_first)
    elif mode == "英文显示名优先":
        unpinned = sorted(unpinned, key=key_en_first)
    else:
        unpinned = sorted(unpinned, key=lambda x: x[0])

    out = OrderedDict()
    for _, _, display, prompt in pinned:
        out[display] = prompt
    for _, display, prompt in unpinned:
        out[display] = prompt
    return out




def _sort_data(data):
    sort = data.get("sort", {{}}) if isinstance(data, dict) else {{}}
    if not isinstance(sort, dict):
        sort = {{}}
    sort.setdefault("global_mode", "保持当前顺序")
    sort.setdefault("category_modes", {{}})
    sort.setdefault("pins", {{}})
    sort.setdefault("ranks", {{}})
    return sort


def _rank_value(ranks, prompt):
    if not isinstance(ranks, dict):
        return None
    candidates = [prompt, _normalize_key(prompt)]
    for c in candidates:
        if c in ranks:
            try:
                return int(ranks[c])
            except Exception:
                return None
    return None


def _sort_category_mapping(cat, mapping, override_data):
    sort = _sort_data(override_data)
    mode = sort.get("category_modes", {{}}).get(cat, sort.get("global_mode", "默认顺序"))
    pins = sort.get("pins", {{}}).get(cat, []) if isinstance(sort.get("pins", {{}}), dict) else []
    pin_keys = []
    for x in pins or []:
        k = _normalize_key(x)
        if k and k not in pin_keys:
            pin_keys.append(k)
    ranks = sort.get("ranks", {{}}) if isinstance(sort.get("ranks", {{}}), dict) else {{}}
    items = list(mapping.items())

    def keyfunc(idx_pair):
        idx, pair = idx_pair
        display, prompt = pair
        k = _normalize_key(prompt)
        pin_i = pin_keys.index(k) if k in pin_keys else 10**9
        rv = _rank_value(ranks, prompt)
        rank_bucket = 0 if rv is not None else 1
        rank_val = rv if rv is not None else 10**9
        dkey = _normalize_key(display)
        pkey = _normalize_key(prompt)
        if mode in ("显示名A-Z", "显示名升序"):
            mode_key = (dkey, pkey)
        elif mode in ("显示名Z-A", "显示名降序"):
            mode_key = tuple(-ord(ch) for ch in dkey[:120])
        elif mode in ("提示词A-Z", "Prompt升序"):
            mode_key = (pkey, dkey)
        elif mode in ("提示词Z-A", "Prompt降序"):
            mode_key = tuple(-ord(ch) for ch in pkey[:120])
        elif mode == "短词优先":
            mode_key = (len(prompt), pkey, dkey)
        elif mode == "长词优先":
            mode_key = (-len(prompt), pkey, dkey)
        elif mode == "中文显示名优先":
            mode_key = (0 if re.search(r"[\u4e00-\u9fff]", display) else 1, dkey, pkey)
        elif mode == "英文显示名优先":
            mode_key = (0 if not re.search(r"[\u4e00-\u9fff]", display) else 1, dkey, pkey)
        else:
            # 保持当前顺序/手动排序优先：保留生成时顺序，但置顶和手动序号仍生效。
            mode_key = (idx,)
        return (pin_i, rank_bucket, rank_val, mode_key, idx)

    sorted_items = sorted(enumerate(items), key=keyfunc)
    return OrderedDict(pair for _, pair in sorted_items)


def _apply_runtime_sort(final, override_data):
    out = OrderedDict()
    for cat, mapping in final.items():
        out[cat] = _sort_category_mapping(cat, mapping, override_data)
    return out

def _merged_category_data(enable_override=True):
    merged = OrderedDict((cat, OrderedDict(items)) for cat, items in CATEGORY_DATA.items())
    if not enable_override:
        return merged
    path = _override_path()
    try:
        mtime = os.path.getmtime(path) if os.path.exists(path) else -1
    except Exception:
        mtime = -1
    if _CATEGORY_DATA_CACHE.get("mtime") == mtime and _CATEGORY_DATA_CACHE.get("data") is not None:
        return _CATEGORY_DATA_CACHE["data"]
    data = _load_override()
    replace = _normalize_override_replace(data)
    hide = {{_normalize_key(x) for x in data.get("hide", []) or [] if _normalize_key(x)}}
    move = data.get("move", {{}}) or {{}}
    rename = data.get("rename_display", {{}}) or {{}}

    # 添加自定义项。
    add = data.get("add", {{}}) or {{}}
    if isinstance(add, dict):
        for cat, rows in add.items():
            if cat not in CATEGORY_ORDER:
                cat = "额外标签" if "额外标签" in merged else (CATEGORY_ORDER[-1] if CATEGORY_ORDER else cat)
            merged.setdefault(cat, OrderedDict())
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, str):
                        prompt = _clean_prompt(row)
                        display = prompt
                    elif isinstance(row, dict):
                        prompt = _clean_prompt(row.get("prompt") or row.get("tag") or row.get("text") or "")
                        display = _clean_text(row.get("display") or row.get("name") or prompt)
                    else:
                        continue
                    if not prompt or _is_blocked(prompt, display):
                        continue
                    merged[cat][display or prompt] = prompt

    # 处理隐藏、替换、改名、移动。按 prompt key 识别。
    final = OrderedDict((cat, OrderedDict()) for cat in merged.keys())
    final_keys = {{cat: set() for cat in final.keys()}}
    for cat, mapping in merged.items():
        for display, prompt in mapping.items():
            prompt = _clean_prompt(prompt)
            if not prompt:
                continue
            key = _normalize_key(prompt)
            if key in hide:
                continue
            # replace 合并：把重复项的 prompt 改成 canonical key。display 也可在 rename_display 里改。
            new_prompt = replace.get(key, prompt)
            new_key = _normalize_key(new_prompt)
            new_cat = move.get(prompt) or move.get(key) or move.get(new_key) or cat
            if new_cat not in final:
                new_cat = cat if cat in final else next(iter(final.keys()))
            new_display = rename.get(prompt) or rename.get(key) or rename.get(new_key) or display
            # 同 key 去重：保留先出现的显示名。
            existing_keys = final_keys.setdefault(new_cat, set())
            if new_key in existing_keys:
                continue
            final[new_cat][new_display] = new_prompt
            existing_keys.add(new_key)

    # 应用运行时排序和置顶规则。排序不删除任何项目，只改变菜单顺序。
    for _cat in list(final.keys()):
        final[_cat] = _sort_mapping_for_category(_cat, final[_cat], data)

    final = _apply_runtime_sort(final, data)
    _CATEGORY_DATA_CACHE["mtime"] = mtime
    _CATEGORY_DATA_CACHE["data"] = final
    return final


def _options_for_category(cat, enable_override=True):
    data = _merged_category_data(enable_override=enable_override)
    opts = ["——"] + list(data.get(cat, {{}}).keys())
    return opts


def _parse_multi(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [_clean_text(x) for x in value if _clean_text(x) and _clean_text(x) != "——"]
    if isinstance(value, tuple):
        return [_clean_text(x) for x in value if _clean_text(x) and _clean_text(x) != "——"]
    if isinstance(value, str):
        s = value.strip()
        if not s or s == "——":
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, list):
                    return [_clean_text(x) for x in parsed if _clean_text(x) and _clean_text(x) != "——"]
            except Exception:
                pass
        return [s]
    s = _clean_text(value)
    return [s] if s and s != "——" else []


def _quality_tags(level):
    mapping = {{
        "标准": ["detailed", "high quality"],
        "高质量": ["masterpiece", "best quality", "ultra-detailed", "high resolution"],
        "超高质量": ["masterpiece", "best quality", "ultra-detailed", "extremely detailed", "8k", "photorealistic"],
        "大师级": ["masterpiece", "best quality", "ultra-detailed", "extremely detailed", "8k", "4k", "photorealistic", "professional photography", "studio lighting", "perfect anatomy"],
    }}
    return mapping.get(level, [])


def _dedupe_prompt_parts(parts, mode="严格去重"):
    cleaned = []
    for p in parts:
        p = _clean_prompt(p)
        if p:
            cleaned.append(p)
    if mode == "不去重":
        return cleaned
    out = []
    keys = set()
    for p in cleaned:
        k = _normalize_key(p)
        if not k or k in keys:
            continue
        keys.add(k)
        out.append(p)
    return out


class NSFWPromptSelector_LocalMerged:
    CATEGORY = CATEGORY
    FUNCTION = "generate_nsfw_prompt"
    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("正面提示词", "负面提示词", "完整提示词")

    @classmethod
    def VALIDATE_INPUTS(cls, **kwargs):
        # 动态覆盖文件会改变选项，放宽验证，避免旧 workflow 因选项变化报错。
        return True

    @classmethod
    def INPUT_TYPES(cls):
        required = OrderedDict()
        # 每个分类都是多选，方便从大库里组合。
        data = _merged_category_data(enable_override=True)
        for cat in CATEGORY_ORDER:
            opts = ["——"] + list(data.get(cat, {{}}).keys())
            if len(opts) > 1:
                required[cat] = (opts, {{"default": ["——"], "multi_select": True}})
        optional = OrderedDict()
        optional["随机模式"] = (RANDOM_MODES, {{"default": "关闭"}})
        optional["质量等级"] = (QUALITY_LEVELS, {{"default": "高质量"}})
        optional["分类权重倍率"] = ("FLOAT", {{"default": 1.0, "min": 0.0, "max": 2.0, "step": 0.05}})
        optional["输出去重"] = (DEDUP_MODES, {{"default": "严格去重"}})
        optional["启用运行时覆盖"] = (OVERRIDE_SWITCH, {{"default": "开启"}})
        optional["自定义前缀"] = ("STRING", {{"default": "", "multiline": False}})
        optional["自定义后缀"] = ("STRING", {{"default": "", "multiline": False}})
        optional["负面提示词类型"] = (NEGATIVE_TYPES, {{"default": "标准负面提示词"}})
        optional["自定义负面提示词"] = ("STRING", {{"default": "", "multiline": True}})
        optional["调试信息"] = (["关闭", "开启"], {{"default": "关闭"}})
        return {{"required": required, "optional": optional}}

    def generate_nsfw_prompt(self, **kwargs):
        enable_override = kwargs.get("启用运行时覆盖", "开启") == "开启"
        data = _merged_category_data(enable_override=enable_override)
        random_mode = kwargs.get("随机模式", "关闭")
        quality = kwargs.get("质量等级", "高质量")
        weight_scale = float(kwargs.get("分类权重倍率", 1.0) or 1.0)
        dedupe_mode = kwargs.get("输出去重", "严格去重")
        debug_info = kwargs.get("调试信息", "关闭") == "开启"

        parts = []
        prefix = _clean_text(kwargs.get("自定义前缀", ""))
        suffix = _clean_text(kwargs.get("自定义后缀", ""))
        if prefix:
            parts.append(prefix)
        parts.extend(_quality_tags(quality))

        selected_count = 0
        per_category_selected = OrderedDict()

        for cat in CATEGORY_ORDER:
            mapping = data.get(cat, {{}})
            if not mapping:
                continue
            selected = _parse_multi(kwargs.get(cat))
            if random_mode == "每类随机1个":
                selected = [random.choice(list(mapping.keys()))]
            elif random_mode in ["随机3个", "随机5个", "随机10个"]:
                n = int(re.sub(r"\D", "", random_mode) or "3")
                all_opts = []
                for _cat in CATEGORY_ORDER:
                    all_opts.extend([( _cat, k) for k in data.get(_cat, {{}}).keys()])
                chosen = random.sample(all_opts, min(n, len(all_opts))) if all_opts else []
                # 统一在后面一次性处理，避免每类循环重复抽样。
                if cat == CATEGORY_ORDER[0]:
                    for c2, display in chosen:
                        prompt = data.get(c2, {{}}).get(display, "")
                        if prompt:
                            w = CATEGORY_WEIGHTS.get(c2, 1.0) * weight_scale
                            parts.append(f"({{prompt}}:{{w:.2f}})" if w and abs(w - 1.0) > 0.01 else prompt)
                            per_category_selected[c2] = per_category_selected.get(c2, 0) + 1
                            selected_count += 1
                continue
            for display in selected:
                if display == "——":
                    continue
                prompt = mapping.get(display)
                if not prompt:
                    # 兼容旧 workflow：如果值已经是 prompt 本身，也允许。
                    for d, p in mapping.items():
                        if _normalize_key(d) == _normalize_key(display) or _normalize_key(p) == _normalize_key(display):
                            prompt = p
                            break
                if not prompt or _is_blocked(prompt, display):
                    continue
                w = CATEGORY_WEIGHTS.get(cat, 1.0) * weight_scale
                parts.append(f"({{prompt}}:{{w:.2f}})" if w and abs(w - 1.0) > 0.01 else prompt)
                selected_count += 1
                per_category_selected[cat] = per_category_selected.get(cat, 0) + 1

        if suffix:
            parts.append(suffix)
        parts = _dedupe_prompt_parts(parts, mode=dedupe_mode)
        positive_prompt = ", ".join(parts) if parts else "masterpiece, best quality"

        neg_type = kwargs.get("负面提示词类型", "标准负面提示词")
        custom_neg = kwargs.get("自定义负面提示词", "") or ""
        negative_prompt = custom_neg if neg_type == "自定义负面提示词" and custom_neg.strip() else NEGATIVE_PRESETS.get(neg_type, NEGATIVE_PRESETS["标准负面提示词"])

        settings = f"Quality={{quality}}, Selected={{selected_count}}, Override={{'on' if enable_override else 'off'}}, Dedup={{dedupe_mode}}"
        if debug_info:
            settings += f"{{NL}}Categories={{dict(per_category_selected)}}{{NL}}BuildStats={{BUILD_STATS}}{{NL}}OverridePath={{_override_path()}}"
        full_prompt = f"POSITIVE: {{positive_prompt}}{{NL}}{{NL}}NEGATIVE: {{negative_prompt}}{{NL}}{{NL}}SETTINGS: {{settings}}"
        return (positive_prompt, negative_prompt, full_prompt)


class PromptSelectorLocalSortReviewEditor:
    CATEGORY = CATEGORY
    FUNCTION = "edit_override"
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("状态",)

    @classmethod
    def INPUT_TYPES(cls):
        cats = list(CATEGORY_ORDER) + ["额外标签"]
        return {{
            "required": {{
                "操作": ([
                    "查看配置路径", "查看分类清单", "搜索标签",
                    "添加或更新标签", "隐藏标签", "取消隐藏",
                    "替换合并标签", "移动分类", "重命名显示名",
                    "设置分类排序", "设为置顶", "取消置顶", "设置排序序号", "清除排序设置"
                ], {{"default": "查看配置路径"}}),
                "分类": (cats, {{"default": cats[0] if cats else "额外标签"}}),
                "排序方式": (SORT_MODES, {{"default": "保持当前顺序"}}),
                "显示名": ("STRING", {{"default": "", "multiline": False}}),
                "提示词": ("STRING", {{"default": "", "multiline": False}}),
                "目标提示词": ("STRING", {{"default": "", "multiline": False}}),
            }},
            "optional": {{
                "排序序号": ("INT", {{"default": 100, "min": -999999, "max": 999999, "step": 1}}),
                "筛选关键词": ("STRING", {{"default": "", "multiline": False}}),
                "起始序号": ("INT", {{"default": 0, "min": 0, "max": 999999, "step": 1}}),
                "显示数量": ("INT", {{"default": 60, "min": 1, "max": 300, "step": 1}}),
                "备注": ("STRING", {{"default": "", "multiline": True}}),
            }}
        }}

    def _resolve_prompt(self, cat, display, prompt):
        prompt = _clean_prompt(prompt)
        if prompt:
            return prompt
        display = _clean_text(display)
        if not display:
            return ""
        data = _merged_category_data(enable_override=True)
        cats = [cat] if cat in data else list(data.keys())
        for c in cats:
            for d, p in data.get(c, {{}}).items():
                if d == display or _normalize_key(d) == _normalize_key(display) or _normalize_key(p) == _normalize_key(display):
                    return p
        return display

    def _list_category(self, cat, keyword="", start=0, limit=60):
        data = _merged_category_data(enable_override=True)
        rows = list(data.get(cat, {{}}).items())
        kw = _normalize_key(keyword)
        if kw:
            rows = [(d, p) for d, p in rows if kw in _normalize_key(d) or kw in _normalize_key(p)]
        start = max(0, int(start or 0))
        limit = max(1, min(300, int(limit or 60)))
        shown = rows[start:start + limit]
        lines = [f"分类：{{cat}} | 总数：{{len(rows)}} | 显示：{{start}} - {{start + len(shown) - 1 if shown else start}}"]
        for i, (d, p) in enumerate(shown, start=start):
            lines.append(f"{{i:04d}}. {{d}} -> {{p}}")
        return NL.join(lines)

    def _search_all(self, keyword="", start=0, limit=80):
        data = _merged_category_data(enable_override=True)
        kw = _normalize_key(keyword)
        rows = []
        for cat, mapping in data.items():
            for d, p in mapping.items():
                if not kw or kw in _normalize_key(d) or kw in _normalize_key(p):
                    rows.append((cat, d, p))
        start = max(0, int(start or 0))
        limit = max(1, min(300, int(limit or 80)))
        shown = rows[start:start + limit]
        lines = [f"搜索：{{keyword or '全部'}} | 命中：{{len(rows)}} | 显示：{{start}} - {{start + len(shown) - 1 if shown else start}}"]
        for i, (cat, d, p) in enumerate(shown, start=start):
            lines.append(f"{{i:04d}}. [{{cat}}] {{d}} -> {{p}}")
        return NL.join(lines)

    def edit_override(self, 操作, 分类, 排序方式, 显示名, 提示词, 目标提示词, 排序序号=100, 筛选关键词="", 起始序号=0, 显示数量=60, 备注=""):
        data = _load_override()
        path = _override_path()
        prompt = self._resolve_prompt(分类, 显示名, 提示词)
        target = _clean_prompt(目标提示词)
        display = _clean_text(显示名)
        sort = _sort_data(data)
        data["sort"] = sort

        if 操作 == "查看配置路径":
            _save_override(data)
            return (f"override 文件路径：{{path}}{{NL}}当前分类数：{{len(CATEGORY_ORDER)}}{{NL}}排序配置：{{json.dumps(sort, ensure_ascii=False)}}{{NL}}提示：改完后重启 ComfyUI 或刷新节点定义。",)
        if 操作 == "查看分类清单":
            return (self._list_category(分类, 筛选关键词, 起始序号, 显示数量),)
        if 操作 == "搜索标签":
            return (self._search_all(筛选关键词 or 显示名 or 提示词, 起始序号, 显示数量),)
        if 操作 == "添加或更新标签":
            if not prompt:
                return ("失败：提示词不能为空。",)
            if _is_blocked(prompt, display):
                return ("失败：该提示词命中安全过滤规则，未写入。",)
            cat = 分类 if 分类 in CATEGORY_ORDER else "额外标签"
            data.setdefault("add", {{}}).setdefault(cat, [])
            rows = data["add"][cat]
            found = False
            for row in rows:
                if isinstance(row, dict) and _normalize_key(row.get("prompt", "")) == _normalize_key(prompt):
                    row["display"] = display or prompt
                    row["prompt"] = prompt
                    row["note"] = _clean_text(备注)
                    found = True
                    break
            if not found:
                rows.append({{"display": display or prompt, "prompt": prompt, "note": _clean_text(备注)}})
            _save_override(data)
            return (f"已添加/更新：{{display or prompt}} -> {{prompt}}{{NL}}文件：{{path}}",)
        if 操作 == "隐藏标签":
            if not prompt:
                return ("失败：提示词不能为空。",)
            data.setdefault("hide", [])
            if prompt not in data["hide"]:
                data["hide"].append(prompt)
            _save_override(data)
            return (f"已隐藏：{{prompt}}{{NL}}文件：{{path}}",)
        if 操作 == "取消隐藏":
            if not prompt:
                return ("失败：提示词不能为空。",)
            key = _normalize_key(prompt)
            old = data.get("hide", []) or []
            data["hide"] = [x for x in old if _normalize_key(x) != key]
            _save_override(data)
            return (f"已取消隐藏：{{prompt}}{{NL}}文件：{{path}}",)
        if 操作 == "替换合并标签":
            if not prompt or not target:
                return ("失败：提示词和目标提示词都不能为空。",)
            if _is_blocked(prompt) or _is_blocked(target):
                return ("失败：输入命中安全过滤规则，未写入。",)
            data.setdefault("replace", {{}})[prompt] = target
            _save_override(data)
            return (f"已设置人工合并：{{prompt}} -> {{target}}{{NL}}文件：{{path}}",)
        if 操作 == "移动分类":
            if not prompt:
                return ("失败：提示词不能为空。",)
            cat = 分类 if 分类 in CATEGORY_ORDER else "额外标签"
            data.setdefault("move", {{}})[prompt] = cat
            _save_override(data)
            return (f"已移动：{{prompt}} -> {{cat}}{{NL}}文件：{{path}}",)
        if 操作 == "重命名显示名":
            if not prompt or not display:
                return ("失败：提示词和显示名都不能为空。",)
            data.setdefault("rename_display", {{}})[prompt] = display
            _save_override(data)
            return (f"已重命名：{{prompt}} -> {{display}}{{NL}}文件：{{path}}",)
        if 操作 == "设置分类排序":
            cat = 分类 if 分类 in CATEGORY_ORDER else "额外标签"
            sort.setdefault("category_modes", {{}})[cat] = 排序方式 if 排序方式 in SORT_MODES else "保持当前顺序"
            _save_override(data)
            return (f"已设置分类排序：{{cat}} -> {{sort['category_modes'][cat]}}{{NL}}文件：{{path}}",)
        if 操作 == "设为置顶":
            if not prompt:
                return ("失败：提示词不能为空。",)
            cat = 分类 if 分类 in CATEGORY_ORDER else "额外标签"
            pins = sort.setdefault("pins", {{}}).setdefault(cat, [])
            key = _normalize_key(prompt)
            if not any(_normalize_key(x) == key for x in pins):
                pins.append(prompt)
            _save_override(data)
            return (f"已置顶：{{prompt}} -> {{cat}}{{NL}}文件：{{path}}",)
        if 操作 == "取消置顶":
            if not prompt:
                return ("失败：提示词不能为空。",)
            cat = 分类 if 分类 in CATEGORY_ORDER else "额外标签"
            key = _normalize_key(prompt)
            pins = sort.setdefault("pins", {{}}).get(cat, []) or []
            sort["pins"][cat] = [x for x in pins if _normalize_key(x) != key]
            _save_override(data)
            return (f"已取消置顶：{{prompt}}{{NL}}文件：{{path}}",)
        if 操作 == "设置排序序号":
            if not prompt:
                return ("失败：提示词不能为空。",)
            sort.setdefault("ranks", {{}})[prompt] = int(排序序号)
            _save_override(data)
            return (f"已设置排序序号：{{prompt}} -> {{int(排序序号)}}{{NL}}文件：{{path}}",)
        if 操作 == "清除排序设置":
            cat = 分类 if 分类 in CATEGORY_ORDER else "额外标签"
            if prompt:
                key = _normalize_key(prompt)
                ranks = sort.setdefault("ranks", {{}})
                for k in list(ranks.keys()):
                    if _normalize_key(k) == key:
                        ranks.pop(k, None)
                pins = sort.setdefault("pins", {{}}).get(cat, []) or []
                sort["pins"][cat] = [x for x in pins if _normalize_key(x) != key]
                msg = f"已清除该标签排序：{{prompt}}"
            else:
                sort.setdefault("category_modes", {{}}).pop(cat, None)
                sort.setdefault("pins", {{}}).pop(cat, None)
                msg = f"已清除分类排序：{{cat}}"
            _save_override(data)
            return (f"{{msg}}{{NL}}文件：{{path}}",)
        return ("未知操作。",)

NODE_CLASS_MAPPINGS = {{
    "{node_key}": NSFWPromptSelector_LocalMerged,
    "PromptSelectorLocalSortReviewEditor": PromptSelectorLocalSortReviewEditor,
{legacy_line}}}

NODE_DISPLAY_NAME_MAPPINGS = {{
    "{node_key}": {display_name!r},
    "PromptSelectorLocalSortReviewEditor": "PromptSelector 本地排序复核编辑器",
{legacy_display_line}}}
'''
    return script


def write_runtime_override_template(path: Path, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        return
    data = {
        "说明": "运行时覆盖文件。生成的 PromptSelector.py 会读取它。改完后重启 ComfyUI 或刷新节点定义。",
        "add": {
            "额外标签": [
                {"display": "示例自定义标签 (example custom tag)", "prompt": "example custom tag", "note": "删除这一项或改成你自己的。"}
            ]
        },
        "hide": [],
        "replace": {
            "示例重复旧词": "示例保留新词"
        },
        "move": {
            "示例要移动的词": "姿态动作"
        },
        "rename_display": {
            "示例英文词": "新的中文显示名 (example english tag)"
        },
        "alias_groups": [],
        "sort": {
            "global_mode": "保持当前顺序",
            "category_modes": {"示例分类名": "显示名升序"},
            "pins": {"示例分类名": ["示例要置顶的 prompt"]},
            "ranks": {}
        },
        "pin": {
            "示例分类名": ["示例要置顶的 prompt"]
        }
    }
    save_json_file(path, data)


def write_reports(out_dir: Path, files: List[Path], all_items: List[Item], categorized: Dict[str, List[Item]], excluded: List[Excluded], duplicates: List[DuplicateRecord], stats: Dict[str, Any]) -> Tuple[Path, Path, Path]:
    report_path = out_dir / DEFAULT_REPORT
    dup_path = out_dir / DEFAULT_DUPLICATES_CSV
    excl_path = out_dir / DEFAULT_EXCLUDED_CSV

    source_counter = Counter(i.source_type for i in all_items)
    accepted_source_counter = Counter(i.source_type for rows in categorized.values() for i in rows)
    lines = []
    lines.append("PromptSelector 本地合并生成报告")
    lines.append("=" * 40)
    lines.append(f"生成时间: {_dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"生成器版本: {BUILDER_VERSION}")
    lines.append("")
    lines.append("扫描文件:")
    for p in files:
        lines.append(f"  - {p}")
    lines.append("")
    lines.append(f"原始候选项: {len(all_items)}")
    lines.append(f"最终导入项: {stats.get('accepted_total', 0)}")
    lines.append(f"过滤/截断项: {len(excluded)}")
    lines.append(f"精确/别名合并项: {len(duplicates)}")
    lines.append("")
    lines.append("原始来源统计:")
    for k, v in source_counter.most_common():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("最终来源统计:")
    for k, v in accepted_source_counter.most_common():
        lines.append(f"  {k}: {v}")
    lines.append("")
    lines.append("分类统计:")
    for cat in CATEGORY_ORDER:
        lines.append(f"  {cat}: {len(categorized.get(cat, []))}")
    lines.append("")
    lines.append("说明:")
    lines.append("  - promptselector_duplicates_review.csv 记录 exact/alias 被折叠的项；本版默认不做近似去重。")
    lines.append("  - promptselector_excluded_tags.csv 记录安全过滤、长度过滤、分类上限截断等项。")
    lines.append("  - 需要手动解决的重复，可在 ComfyUI 里用“排序复核编辑器”查看、置顶、隐藏、移动、重命名或手动合并。")
    report_path.write_text("\n".join(lines), encoding="utf-8")

    with dup_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["category", "reason", "similarity", "kept_prompt", "kept_display", "kept_source", "dropped_prompt", "dropped_display", "dropped_source"])
        w.writeheader()
        for d in duplicates:
            w.writerow(asdict(d))

    with excl_path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["reason", "category", "prompt", "display", "source_type", "source_path"])
        w.writeheader()
        for e in excluded:
            w.writerow(asdict(e))
    return report_path, dup_path, excl_path


def build(cfg: Dict[str, Any], cwd: Path, overwrite_cli: bool = False, output_cli: Optional[str] = None) -> Dict[str, Any]:
    files = discover_files(cfg, cwd)
    if not files:
        raise RuntimeError("没有发现可读取的本地库文件。请用 --source 或 --scan-root 指定目录。")
    log(f"发现 {len(files)} 个候选文件。")

    all_items: List[Item] = []
    per_file_counts = []
    base_py_value = (cfg.get("sources", {}) or {}).get("base_promptselector_py") or ""
    base_py_abs = None
    if base_py_value:
        bp = Path(base_py_value).expanduser()
        base_py_abs = (cwd / bp).resolve() if not bp.is_absolute() else bp.resolve()
    for path in files:
        if base_py_abs is not None and path.resolve() == base_py_abs and path.suffix.lower() in PY_EXTENSIONS:
            items = extract_base_promptselector_py(path)
        else:
            items = extract_items_from_file(path, cfg)
        if items:
            all_items.extend(items)
            per_file_counts.append((path, len(items)))
            log(f"读取 {len(items):5d} 项 <- {path.name}")

    manual_items = apply_manual_config_items(cfg)
    if manual_items:
        all_items.extend(manual_items)
        log(f"读取 {len(manual_items)} 项 <- config.manual_merge.add")

    if not all_items:
        raise RuntimeError("候选文件存在，但没有抽取到可用提示词。请检查过滤设置或库格式。")

    categorized, excluded, duplicates, stats = filter_and_dedupe_items(all_items, cfg)
    category_data = category_data_for_output(categorized)

    out_cfg = cfg.get("output", {}) or {}
    output_name = output_cli or out_cfg.get("file") or DEFAULT_OUTPUT
    output_path = Path(output_name).expanduser()
    if not output_path.is_absolute():
        output_path = cwd / output_path
    out_dir = output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    overwrite = overwrite_cli or bool(out_cfg.get("overwrite", False))
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"输出文件已存在：{output_path}。使用 --overwrite 或改 output.file。")

    script = generate_node_script(category_data, cfg, stats)
    output_path.write_text(script, encoding="utf-8")
    log(f"已生成节点脚本：{output_path}")

    runtime_name = clean_text(out_cfg.get("runtime_override_file") or DEFAULT_RUNTIME_OVERRIDES)
    runtime_path = out_dir / runtime_name
    write_runtime_override_template(runtime_path, overwrite=False)
    log(f"已准备运行时覆盖模板：{runtime_path}")

    report_path, dup_path, excl_path = write_reports(out_dir, files, all_items, categorized, excluded, duplicates, stats)
    log(f"已生成报告：{report_path}")
    log(f"已生成重复审查 CSV：{dup_path}")
    log(f"已生成过滤审查 CSV：{excl_path}")

    return {
        "output": str(output_path),
        "runtime_override": str(runtime_path),
        "report": str(report_path),
        "duplicates_csv": str(dup_path),
        "excluded_csv": str(excl_path),
        "stats": stats,
        "files": [str(p) for p in files],
        "per_file_counts": [(str(p), n) for p, n in per_file_counts],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="本地多库合并生成 ComfyUI PromptSelector 节点脚本")
    ap.add_argument("--config", default="", help=f"配置 JSON 路径，默认尝试读取 ./{DEFAULT_CONFIG}")
    ap.add_argument("--create-config", action="store_true", help="只创建配置模板，不生成节点脚本")
    ap.add_argument("--source", action="append", default=[], help="显式指定文件或目录，可重复。支持 db/json/csv/txt/py")
    ap.add_argument("--scan-root", action="append", default=[], help="扫描目录，可重复。默认当前目录。")
    ap.add_argument("--base-py", default="", help="原 PromptSelector.py 路径；会抽取其中已有选项并合并。")
    ap.add_argument("--output", default="", help=f"输出节点脚本名，默认 {DEFAULT_OUTPUT}")
    ap.add_argument("--overwrite", action="store_true", help="允许覆盖输出脚本")
    ap.add_argument("--max-per-category", type=int, default=None, help="每个分类最多保留多少项，0 为不限制")
    ap.add_argument("--fuzzy-threshold", type=float, default=None, help="兼容旧参数；v3 不执行近似去重。")
    ap.add_argument("--sort-mode", default=None, choices=["quality", "display", "prompt", "hot", "source", "length", "long_first"], help="生成时排序方式。默认 quality。")
    ap.add_argument("--danbooru-limit", type=int, default=None, help="Danbooru 最多读取多少条，默认 6000")
    ap.add_argument("--danbooru-min-hot", type=int, default=None, help="Danbooru 最低 hot，默认 0")
    ap.add_argument("--include-general-danbooru", action="store_true", help="导入更多 Danbooru 泛用标签；会让节点菜单更大")
    ap.add_argument("--legacy-node-key", action="store_true", help="同时注册旧节点键 NSFWPromptSelector；只有替换原脚本时才建议开启")
    return ap.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    cwd = Path.cwd().resolve()
    config_path = Path(args.config).expanduser() if args.config else cwd / DEFAULT_CONFIG
    if args.create_config:
        write_config_template(config_path, overwrite=args.overwrite)
        return 0

    cfg = load_config(config_path if config_path.exists() else None)
    # CLI 覆盖配置。
    if args.source:
        cfg.setdefault("sources", {})["explicit_files"] = args.source
    if args.scan_root:
        cfg.setdefault("sources", {})["scan_roots"] = args.scan_root
    elif not cfg.get("sources", {}).get("scan_roots"):
        cfg.setdefault("sources", {})["scan_roots"] = ["."]
    if args.base_py:
        cfg.setdefault("sources", {})["base_promptselector_py"] = args.base_py
    if args.max_per_category is not None:
        cfg.setdefault("filters", {})["max_per_category"] = args.max_per_category
    if args.fuzzy_threshold is not None:
        cfg.setdefault("filters", {})["fuzzy_threshold"] = 1.0
        cfg.setdefault("filters", {})["enable_fuzzy_dedupe"] = False
    if args.sort_mode is not None:
        cfg.setdefault("filters", {})["sort_mode"] = args.sort_mode
    if args.danbooru_limit is not None:
        cfg.setdefault("filters", {})["danbooru_limit"] = args.danbooru_limit
    if args.danbooru_min_hot is not None:
        cfg.setdefault("filters", {})["danbooru_min_hot"] = args.danbooru_min_hot
    if args.include_general_danbooru:
        cfg.setdefault("filters", {})["include_general_danbooru"] = True
    if args.legacy_node_key:
        cfg.setdefault("output", {})["legacy_node_key"] = True
    if args.output:
        cfg.setdefault("output", {})["file"] = args.output
    if args.overwrite:
        cfg.setdefault("output", {})["overwrite"] = True

    # 如果配置不存在，顺手写一份，便于后续用户改合并规则。
    if not config_path.exists():
        write_config_template(config_path, overwrite=False)

    result = build(cfg, cwd, overwrite_cli=args.overwrite, output_cli=args.output or None)
    log("完成。")
    log(f"最终导入：{result['stats'].get('accepted_total', 0)} 项；精确/别名合并：{result['stats'].get('duplicate_total', 0)} 项；过滤：{result['stats'].get('excluded_total', 0)} 项。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
