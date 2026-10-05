import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
PROMPT_SELECTOR_DIR = TOOLS_DIR.parent
PLUGIN_DIR = PROMPT_SELECTOR_DIR.parent
for module_path in (PROMPT_SELECTOR_DIR, TOOLS_DIR):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

from anima_tag_classifier import classify_prompt, load_contract, normalize_text, root_for_target  # noqa: E402
from anima_second_pass import (  # noqa: E402
    ALIAS_ROOT_TERMS,
    EXCLUDED_CATEGORIES,
    REFERENCE_PREFIXES,
    REVIEW_CATEGORIES,
    canonical_targets,
    deterministic_category_id,
    has_adult_context,
    has_safety_risk,
    is_candidate_category,
    source_context_from_category,
    strong_title_leaf,
    strong_title_root,
)


@dataclass(frozen=True)
class TagRule:
    target: str
    label: str
    priority: int
    patterns: tuple
    min_hits: int = 1
    requires: tuple = ()
    context: str = ""


def rule(target, label, priority, patterns, min_hits=1, requires=(), context=""):
    return TagRule(target, label, priority, tuple(patterns), min_hits, tuple(requires), context)


SEX_ACTION = (
    r"sex", r"vaginal", r"anal", r"penetration", r"rape", r"blowjob", r"fellatio",
    r"handjob", r"footjob", r"paizuri", r"masturbation", r"orgasm", r"cum",
    r".*(?:做爱|性交|侵犯|插入|爆炒|艹).*",
)

EXPOSURE_BODY = (
    r"nude", r"naked", r"completely nude", r"topless", r"bottomless", r"nipples",
    r"breasts", r"pussy", r"penis", r"groin", r"no panties", r"no bra", r"clothes lift",
    r"shirt lift", r"dress lift", r"public nudity", r"裸体", r"乳头", r"胸部", r"小穴", r"下体",
)

SEMANTIC_TITLE_ROOT_PATTERNS = {
    "pose": re.compile(
        r"吃|喝|烤|煮|打扫|散步|走路|跑|跳|舞|弹奏|演奏|摄影|拍照|抓|抱|摇头|拒绝|"
        r"送礼|站立|跪|躺|趴|弯腰|倒挂|伸懒腰|骑车|脱鞋|摘眼镜|拉扯|掀|扯开|挤干|"
        r"触摸|拍打|舔|吸奶|埋胸|插入|做爱|性爱|性交|射精|援交|展示|挑衅|踩|侍奉|"
        r"口爆|爆炒|捆|缚|后入|骑乘|自慰|足交|手交|乳交",
        re.IGNORECASE,
    ),
    "background": re.compile(
        r"水潭|水下|海边|海滨|沙滩|泳池|火车站|站台|楼道|练习室|墙角|窗边|雨中|"
        r"超市|教室|更衣室|电车|楼梯|桌下|课桌|小巷|车内|户外|室内|暗室|路边|"
        r"医院|酒吧|顶楼|舞台|森林|房间",
        re.IGNORECASE,
    ),
    "character": re.compile(
        r"学生|老师|教师|护士|修女|职员|社畜|女巫|魔女|法师|机娘|机兵|机甲|人偶|"
        r"辣妹|双子|舞娘",
        re.IGNORECASE,
    ),
}

EXPLICIT_SEXUAL_ACTION_ALIAS = re.compile(
    r"色情|涩涩|性爱|性欲|小穴|阴道|肛门|乳头|精液|吃精|榨精|飞机杯|几把|阴茎|"
    r"自慰|调教|性奴|母狗|裙底|爱抚|吃脚|吃奶|足穴|插入|做爱|性交|援交|颜射|口交|"
    r"露出|袒露|射身|托胸|摸.*胸|拉下.*裤|脱下.*裤",
    re.IGNORECASE,
)

SOURCE_CLOTHING_TERMS = (
    "服饰", "服装", "内衣", "泳装", "泳衣", "校服", "制服", "胶衣", "日常改造",
    "裸体遮盖", "组件／杂项", "组件/杂项",
)

TAG_RULES = (
    # Safety-sensitive and explicit actions outrank incidental clothes or scenery.
    rule("Anima/姿势/R18/重口/暴力/截肢与人棍", "截肢与人棍", 178,
         (r"amputee", r"amputation", r"dismemberment", r"limbless", r"stumpy", r"截肢", r"人棍")),
    rule("Anima/姿势/R18/重口/暴力/杀害", "杀害与处刑", 177,
         (r"decapitation", r"beheading", r"execution", r"dead body", r"corpse", r"杀害", r"处刑", r"斩首")),
    rule("Anima/姿势/R18/重口/暴力/食人", "食人", 176,
         (r"cannibalism", r"cannibal", r"eating human", r"食人")),
    rule("Anima/姿势/R18/重口/暴力/血肉内脏", "血肉与内脏", 175,
         (r"guro", r"guts", r"internal organs", r"intestines", r"disembowelment", r"exposed organs", r"内脏", r"血肉")),
    rule("Anima/姿势/R18/重口/暴力/暴虐与过激", "暴虐与过激", 168,
         (r"torture", r"brutal", r"body horror", r"mutilation", r"gorn", r"暴虐", r"酷刑")),
    rule("Anima/姿势/R18/重口/排泄物", "排泄物", 174,
         (r"scat", r"feces", r"defecation", r"urination", r"pissing", r"golden shower", r"urine", r"排泄", r"尿液", r"粪便")),
    rule("Anima/姿势/R18/重口/异种互动/触手", "触手互动", 172,
         (r"tentacle", r"tentacles", r"触手"), requires=(SEX_ACTION,)),
    rule("Anima/姿势/R18/重口/异种互动/史莱姆", "史莱姆互动", 171,
         (r"slime", r"slime creature", r"史莱姆"), requires=(SEX_ACTION,)),
    rule("Anima/姿势/R18/重口/异种互动/昆虫", "昆虫互动", 171,
         (r"insect", r"insectoid", r"facehugger", r"worm", r"昆虫", r"虫奸"), requires=(SEX_ACTION,)),
    rule("Anima/姿势/R18/重口/异种互动/兽类", "兽类互动", 171,
         (r"bestiality", r"zoophilia", r"dog sex", r"horse sex", r"animal sex", r"兽交", r"(?:海豚|企鹅|狗|马|动物).*(?:做爱|性交|侵犯)")),
    rule("Anima/姿势/R18/重口/机械", "机械互动", 171,
         (r"machine sex", r"robot sex", r"mechanical penetration", r"机械奸", r"机器侵犯", r"机械侵犯")),
    rule("Anima/姿势/R18/多人互动/多人强制", "多人强制", 170,
         (r"gang rape", r"rape train", r"多人强制", r"轮奸")),
    rule("Anima/姿势/R18/双人互动/胁迫与强制", "胁迫与强制", 169,
         (r"rape", r"forced sex", r"non-consensual", r"sexual assault", r"胁迫", r"强奸", r"侵犯")),
    rule("Anima/姿势/R18/拘束/肉便器", "肉便器", 169,
         (r"public use", r"human toilet", r"meat toilet", r"rbq", r"肉便器")),
    rule("Anima/姿势/R18/情境/NTR", "NTR", 166,
         (r"ntr", r"netorare", r"netori", r"cuckold", r"cuckoldry", r"牛头人")),
    rule("Anima/姿势/R18/情境/催眠", "催眠与精神控制", 166,
         (r"hypnosis", r"hypnotized", r"mind control", r"brainwashed", r"催眠", r"精神控制", r"洗脑")),
    rule("Anima/姿势/R18/双人互动/睡眠侵犯", "睡眠侵犯", 166,
         (r"sleep sex", r"sleeping sex", r"somnophilia", r"睡奸", r"醉奸")),
    rule("Anima/姿势/R18/双人互动/攻守反转", "攻守反转", 166,
         (r"pegging", r"reverse rape", r"role reversal", r"四爱", r"逆推")),
    rule("Anima/姿势/R18/多人互动/百合", "百合互动", 158,
         (r"yuri", r"lesbian", r"girl on girl", r"百合"), context="adult"),
    rule("Anima/姿势/R18/多人互动/双飞与多人", "多人互动", 164,
         (r"threesome", r"group sex", r"gangbang", r"double penetration", r"多人性爱", r"群交", r"乱交", r"双飞", r"[三四五六]飞")),
    rule("Anima/姿势/R18/多人互动/协作侍奉", "协作侍奉", 163,
         (r"double blowjob", r"multiple handjob", r"breast and handjob", r"协作侍奉")),
    rule("Anima/姿势/R18/体位/种付位", "种付位", 162,
         (r"mating press", r"breeding press", r"种付位")),
    rule("Anima/姿势/R18/体位/后入与背后位", "后入与背后位", 161,
         (r"doggystyle", r"sex from behind", r"prone bone", r"rear entry", r"后入", r"背后位")),
    rule("Anima/姿势/R18/体位/骑乘位", "骑乘位", 161,
         (r"cowgirl position", r"reverse cowgirl", r"riding penis", r"girl on top", r"骑乘位", r"女上位")),
    rule("Anima/姿势/R18/体位/正身位", "正身位", 160,
         (r"missionary", r"missionary position", r"face-to-face sex", r"正身位", r"正常位")),
    rule("Anima/姿势/R18/体位/站立位", "站立位", 160,
         (r"standing sex", r"upright sex", r"站立性爱", r"站立位")),
    rule("Anima/姿势/R18/体位/坐身位", "坐身位", 160,
         (r"seated sex", r"lap sex", r"sitting on penis", r"坐身位")),
    rule("Anima/姿势/R18/体位/火车便当", "火车便当", 162,
         (r"suspended congress", r"ekiben", r"火车便当")),
    rule("Anima/姿势/R18/非插入互动/口交与颜射", "口交与颜射", 159,
         (r"blowjob", r"fellatio", r"deepthroat", r"cunnilingus", r"irrumatio", r"facefuck", r"oral sex", r"penis in mouth", r"cum in mouth", r"facial", r"口交", r"颜射")),
    rule("Anima/姿势/R18/非插入互动/乳交", "乳交", 159,
         (r"paizuri", r"breast sex", r"titjob", r"乳交")),
    rule("Anima/姿势/R18/非插入互动/足交", "足交", 159,
         (r"footjob", r"foot sex", r"足交")),
    rule("Anima/姿势/R18/非插入互动/手交", "手交", 159,
         (r"handjob", r"penis grab", r"grabbing penis", r"手交")),
    rule("Anima/姿势/R18/非插入互动/身体摩擦", "身体摩擦", 158,
         (r"tribadism", r"frottage", r"thigh sex", r"intercrural sex", r"grinding", r"素股", r"腿交"), context="adult"),
    rule("Anima/姿势/R18/单人表现/自慰", "自慰", 157,
         (r"masturbation", r"female masturbation", r"male masturbation", r"fingering self", r"masturbating", r"自慰", r"手淫")),
    rule("Anima/姿势/R18/双人互动/调戏与猥亵", "调戏与猥亵", 155,
         (r"groping", r"breast grab", r"grabbing another's breast", r"grabbing another's breasts", r"ass grab", r"crotch grab", r"molestation", r"sexual harassment", r"猥亵", r"揉胸")),
    rule("Anima/姿势/R18/双人互动/事后", "事后", 151,
         (r"after sex", r"afterglow", r"post-sex", r"cum on body", r"excessive cum", r"cumdrip", r"事后"), min_hits=2),
    rule("Anima/姿势/R18/双人互动/偷窥与直视", "偷窥与直视", 150,
         (r"voyeurism", r"peeping", r"watching sex", r"caught in the act", r"偷窥")),
    rule("Anima/姿势/R18/拘束/监禁放置", "监禁放置", 154,
         (r"prisoner", r"imprisoned", r"confined", r"cage", r"pillory", r"crucifixion", r"bound on chair", r"绑在椅子", r"椅子拘束", r"监禁", r"囚禁")),
    rule("Anima/姿势/R18/拘束/捆绑用具", "捆绑用具", 153,
         (r"spreader bar", r"handcuffs", r"ankle cuffs", r"ball gag", r"nipple clamps", r"chastity belt", r"chastity cage", r"bondage equipment", r"拘束具")),
    rule("Anima/姿势/R18/拘束/捆绑位置", "捆绑位置", 153,
         (r"hogtie", r"suspension bondage", r"bound arms", r"bound ankles", r"hands tied", r"feet tied", r"吊缚", r"背手缚")),
    rule("Anima/姿势/R18/拘束/宠物调教", "宠物调教", 153,
         (r"petplay", r"pet play", r"human pet", r"dog leash", r"pet collar", r"宠物调教")),
    rule("Anima/姿势/R18/拘束/拘束凌辱", "拘束凌辱", 152,
         (r"bondage humiliation", r"restrained humiliation", r"slave training", r"拘束凌辱")),
    rule("Anima/姿势/R18/拘束/捆绑姿势", "捆绑姿势", 149,
         (r"bondage", r"shibari", r"bound", r"restrained", r"rope bondage", r"tied up", r"捆绑", r"束缚")),
    rule("Anima/姿势/R18/单人表现/暴露", "暴露展示", 148,
         (r"exhibitionism", r"public nudity", r"flashing", r"public exposure", r"露出", r"暴露", r"袒露", r"掀开衣服"), context="exposure"),
    rule("Anima/姿势/R18/单人表现/隐秘展示与直播", "隐秘展示与直播", 147,
         (r"nsfw selfie", r"mirror selfie", r"livestream", r"hidden camera", r"secret filming", r"成人视频直播", r"自拍", r"直播"), context="adult"),
    rule("Anima/姿势/R18/单人表现/诱惑", "诱惑姿态", 142,
         (r"seductive pose", r"inviting pose", r"inviting", r"seduction", r"诱惑", r"勾引", r"色诱"), min_hits=1),
    rule("Anima/姿势/R18/身体构图/腿足", "腿足构图", 145,
         (r"foot focus", r"feet focus", r"sole focus", r"soles focus", r"leg focus", r"足底特写", r"腿足特写")),
    rule("Anima/姿势/R18/身体构图/臀裆部", "臀裆构图", 145,
         (r"ass focus", r"crotch focus", r"pussy focus", r"groin focus", r"cameltoe focus", r"anus focus", r"臀部特写", r"裆部特写")),
    rule("Anima/姿势/R18/身体构图/胸腹部", "胸腹构图", 145,
         (r"breast focus", r"chest focus", r"nipple focus", r"stomach focus", r"torso focus", r"胸部特写", r"腹部特写")),
    rule("Anima/姿势/R18/身体构图/背身", "背身构图", 143,
         (r"back focus", r"bare back focus", r"back view focus", r"背身特写", r"背部特写")),

    # Normal actions are narrower than generic standing/sitting tags.
    rule("Anima/姿势/正常/战斗与动态", "战斗与动态", 137,
         (r"fighting", r"battle", r"attacking", r"incoming attack", r"sword swing", r"swinging sword", r"casting spell", r"spellcasting", r"magic attack", r"hitting ground", r"战斗", r"攻击", r"施法")),
    rule("Anima/姿势/正常/多人互动", "多人互动", 132,
         (r"hug", r"hugging", r"kissing", r"holding hands", r"handshake", r"headpat", r"carrying another", r"拥抱", r"相拥", r"牵手", r"亲吻", r"贴贴", r"合影", r"合照")),
    rule("Anima/姿势/正常/单人动作", "日常动作", 110,
         (r"eating", r"drinking", r"cooking", r"cleaning", r"reading", r"writing", r"walking", r"running", r"jumping", r"dancing", r"playing instrument", r"swimming", r"diving", r"climbing", r"stretching", r"waving", r"pointing at viewer", r"brushing .*hair", r"吃", r"喝", r"煮", r"烤", r"制作", r"打扫", r"散步", r"阅读", r"跑步", r"跳跃"), context="action"),
    rule("Anima/姿势/正常/表情与情绪", "表情与情绪", 102,
         (r"laughing", r"crying", r"angry", r"embarrassed", r"disgusted", r"panicked", r"surprised", r"smug", r"pouting", r"shouting", r"evil smile", r"teasing smile", r"嫌弃", r"害羞", r"愤怒", r"哭泣"), min_hits=2, context="expression"),

    # Clothing rules describe the outfit itself, not every incidental garment.
    rule("Anima/服装/R18/材质与紧身/连体胶衣", "连体胶衣", 130,
         (r"latex bodysuit", r"latex suit", r"rubber suit", r"latex clothes", r"latex clothing", r"胶衣", r"乳胶衣")),
    rule("Anima/服装/R18/材质与紧身/高腰紧身衣", "高腰紧身衣", 128,
         (r"highleg bodysuit", r"highleg leotard", r"high waist bodysuit", r"high-waisted bodysuit", r"高腰紧身衣")),
    rule("Anima/服装/R18/暴露与改造/裸体遮盖", "裸体遮盖", 128,
         (r"convenient censoring", r"body paint", r"body painting", r"painted clothes", r"naked bandage", r"tape censor", r"裸体遮盖", r"人体彩绘")),
    rule("Anima/服装/R18/暴露与改造/恶堕服装", "恶堕服装", 127,
         (r"corrupted outfit", r"corruption clothes", r"bimbo outfit", r"slutty corruption", r"恶堕服装")),
    rule("Anima/服装/R18/暴露与改造/职业改造", "职业服装改造", 126,
         (r"lewd .*uniform", r"revealing .*uniform", r"naked .*uniform", r"micro .*uniform", r"erotic .*uniform", r"职业改造")),
    rule("Anima/服装/R18/暴露与改造/幻想改造", "幻想服装改造", 125,
         (r"lewd .*armor", r"revealing .*armor", r"naked .*armor", r"erotic magical girl", r"fantasy micro bikini", r"幻想改造")),
    rule("Anima/服装/R18/暴露与改造/日常改造", "日常服装改造", 124,
         (r"torn clothes", r"clothes lift", r"shirt lift", r"dress lift", r"open clothes", r"see-through clothes", r"naked jacket", r"日常改造"), min_hits=1, context="clothing_mod"),
    rule("Anima/服装/R18/内衣与泳装/泳装", "泳装", 122,
         (r"swimsuit", r"bikini", r"school swimsuit", r"one-piece swimsuit", r"micro bikini", r"泳装", r"比基尼")),
    rule("Anima/服装/R18/内衣与泳装/睡衣", "睡衣", 121,
         (r"pajamas", r"pyjamas", r"nightgown", r"nightdress", r"sleepwear", r"babydoll", r"睡衣", r"睡裙")),
    rule("Anima/服装/R18/内衣与泳装/内衣", "内衣", 120,
         (r"lingerie", r"bra and panties", r"underwear only", r"lace panties", r"lace bra", r"crotchless panties", r"内衣", r"情趣内衣")),
    rule("Anima/服装/R18/Cosplay与角色服装", "Cosplay与角色服装", 119,
         (r"cosplay", r"character costume", r"game skin outfit", r"角色服装")),
    rule("Anima/服装/正常/制服与职业/校服", "校服", 118,
         (r"school uniform", r"serafuku", r"sailor uniform", r"schoolgirl outfit", r"校服", r"水手服")),
    rule("Anima/服装/正常/制服与职业/军装", "军装", 118,
         (r"military uniform", r"military dress", r"army uniform", r"naval uniform", r"军装")),
    rule("Anima/服装/正常/制服与职业/运动服", "运动服", 116,
         (r"sportswear", r"track suit", r"tracksuit", r"gym uniform", r"basketball uniform", r"tennis outfit", r"race queen", r"运动服")),
    rule("Anima/服装/正常/制服与职业/职业制服", "职业制服", 116,
         (r"nurse uniform", r"maid outfit", r"maid uniform", r"police uniform", r"office uniform", r"chef uniform", r"stewardess uniform", r"职业制服")),
    rule("Anima/服装/正常/制服与职业/舞台服", "舞台服", 115,
         (r"idol clothes", r"idol outfit", r"stage outfit", r"performance costume", r"concert outfit", r"舞台服")),
    rule("Anima/服装/正常/制服与职业/节庆礼服", "节庆礼服", 115,
         (r"wedding dress", r"bridal gown", r"evening gown", r"formal dress", r"party dress", r"christmas outfit", r"节庆礼服")),
    rule("Anima/服装/正常/地域与时代/中国", "中国服装", 117,
         (r"hanfu", r"china dress", r"cheongsam", r"qipao", r"chinese clothes", r"旗袍", r"汉服")),
    rule("Anima/服装/正常/地域与时代/日本", "日本服装", 117,
         (r"kimono", r"yukata", r"miko clothes", r"japanese clothes", r"wa maid", r"和服", r"浴衣", r"巫女服")),
    rule("Anima/服装/正常/地域与时代/中东", "中东服装", 116,
         (r"egyptian clothes", r"egyptian outfit", r"arabian clothes", r"arabian outfit", r"belly dancer outfit", r"埃及服装", r"阿拉伯服装")),
    rule("Anima/服装/正常/地域与时代/中近世纪", "中近世纪服装", 113,
         (r"medieval clothes", r"victorian clothes", r"renaissance clothes", r"gothic lolita", r"lolita fashion", r"中世纪服装")),
    rule("Anima/服装/正常/地域与时代/中外经典", "古典服装", 112,
         (r"greco-roman clothes", r"ancient greek clothes", r"roman clothes", r"toga", r"古典服装")),
    rule("Anima/服装/正常/幻想与主题/兔女郎", "兔女郎", 118,
         (r"bunnysuit", r"playboy bunny", r"bunny suit", r"兔女郎")),
    rule("Anima/服装/正常/幻想与主题/魔法少女", "魔法少女服装", 116,
         (r"magical girl outfit", r"magical girl costume", r"魔法少女服装")),
    rule("Anima/服装/正常/幻想与主题/舞娘", "舞娘服装", 114,
         (r"dancer attire", r"dancer outfit", r"belly dancer", r"舞娘服装")),
    rule("Anima/服装/正常/幻想与主题/野族服装", "野族服装", 114,
         (r"tribal clothes", r"native american clothes", r"loincloth", r"leaf clothes", r"野族服装")),
    rule("Anima/服装/正常/幻想与主题/未来科幻", "未来科幻服装", 113,
         (r"futuristic outfit", r"cyberpunk outfit", r"techwear", r"holographic clothing", r"sci-fi bodysuit", r"未来服装")),
    rule("Anima/服装/正常/幻想与主题/西幻奇幻", "西幻奇幻服装", 111,
         (r"fantasy armor", r"wizard robe", r"witch outfit", r"elf clothes", r"fantasy outfit", r"西幻服装")),
    rule("Anima/服装/正常/幻想与主题/游戏服装", "游戏服装", 111,
         (r"game outfit", r"rpg outfit", r"video game costume", r"游戏服装")),
    rule("Anima/服装/正常/日常与季节/冬装", "冬装", 109,
         (r"winter clothes", r"winter coat", r"puffer jacket", r"down jacket", r"thick scarf", r"冬装")),
    rule("Anima/服装/正常/日常与季节/夏装", "夏装", 108,
         (r"summer clothes", r"sundress", r"summer dress", r"tank top and shorts", r"夏装")),
    rule("Anima/服装/正常/日常与季节/室内服", "室内服", 108,
         (r"loungewear", r"housewear", r"homewear", r"room wear", r"室内服")),
    rule("Anima/服装/正常/日常与季节/日常服", "日常服", 106,
         (r"casual clothes", r"casual outfit", r"streetwear", r"daily outfit", r"日常服")),
    rule("Anima/服装/正常/组件与配饰", "服装组件与配饰", 95,
         (r"detached sleeves", r"choker", r"necklace", r"earrings", r"bracelet", r"hair ornament", r"hat", r"gloves", r"boots", r"thighhighs", r"pantyhose", r"组件", r"配饰"), min_hits=3, context="components"),

    # Character rules require identity or body-definition tags rather than clothes.
    rule("Anima/角色/R18/成人身份/扶她", "扶她", 136,
         (r"futanari", r"futa", r"newhalf", r"扶她")),
    rule("Anima/角色/R18/成人身份/伪娘与男娘", "伪娘与男娘", 135,
         (r"otoko no ko", r"femboy", r"crossdressing male", r"伪娘", r"男娘")),
    rule("Anima/角色/R18/成人种族/魔物娘与人外", "成人魔物娘与人外", 132,
         (r"monster girl", r"slime girl", r"demon girl", r"succubus", r"lamia", r"harpy", r"centaur"), requires=(SEX_ACTION,)),
    rule("Anima/角色/正常/种族与形态/人工造物", "人工造物", 128,
         (r"android", r"cyborg", r"robot girl", r"robot joints", r"doll joints", r"mechanical body", r"automaton", r"mecha musume", r"机器人", r"人偶", r"机娘", r"机兵", r"机甲")),
    rule("Anima/角色/正常/种族与形态/动物娘化", "动物娘化", 126,
         (r"cat girl", r"fox girl", r"dog girl", r"wolf girl", r"bunny girl", r"dragon girl", r"cow girl", r"animal girl", r"猫娘", r"狐娘", r"龙娘")),
    rule("Anima/角色/正常/种族与形态/魔物与人外", "魔物与人外", 126,
         (r"monster girl", r"slime girl", r"mermaid", r"lamia", r"harpy", r"centaur", r"goblin girl", r"orc girl", r"xenomorph", r"monster", r"1monster", r"魔物娘", r"人外")),
    rule("Anima/角色/正常/种族与形态/类人种族", "类人种族", 122,
         (r"elf", r"dark elf", r"angel", r"demon girl", r"oni", r"fairy", r"vampire", r"精灵", r"天使", r"恶魔")),
    rule("Anima/角色/正常/种族与形态/动物与生物", "动物与生物", 118,
         (r"no humans", r"bird", r"cat", r"dog", r"horse", r"deer", r"dragon", r"animal", r"creature"), min_hits=2, context="animal"),
    rule("Anima/角色/正常/外观与转化/身体装饰", "身体装饰", 121,
         (r"tattoo", r"body tattoo", r"body painting", r"body markings", r"nipple piercing", r"tongue piercing", r"navel piercing", r"body writing", r"纹身", r"穿环"), min_hits=2),
    rule("Anima/角色/正常/外观与转化/人物转化", "人物转化", 119,
         (r"transformation", r"genderbend", r"corruption", r"bimbofication", r"before and after", r"人物转化", r"性转")),
    rule("Anima/角色/正常/外观与转化/人物外观", "人物外观", 100,
         (r"muscular female", r"chubby female", r"plump", r"dark skin", r"colored skin", r"giantess", r"mini person", r"object head", r"headless", r"人物外观"), min_hits=2),
    rule("Anima/角色/正常/身份与职业/魔法角色", "魔法角色", 111,
         (r"witch", r"wizard", r"mage", r"sorceress", r"女巫", r"魔女", r"法师"), context="identity"),
    rule("Anima/角色/正常/身份与职业/运动人员", "运动人员", 109,
         (r"athlete", r"sportswoman", r"basketball player", r"tennis player", r"racing driver", r"运动员"), context="identity"),
    rule("Anima/角色/正常/身份与职业/常规职业", "常规职业角色", 103,
         (r"office lady", r"nurse", r"doctor", r"teacher", r"police officer", r"delivery person", r"chef", r"waitress", r"nun", r"(?<![a-z])ol(?![a-z])", r"护士", r"医生", r"教师", r"老师", r"警察", r"快递", r"厨师", r"服务员", r"修女", r"职员", r"社畜", r"常规职业"), context="identity"),
    rule("Anima/角色/正常/身份与职业/非常规职业", "非常规职业角色", 103,
         (r"assassin", r"mercenary", r"adventurer", r"fortune teller", r"priestess", r"courtesan", r"刺客", r"佣兵", r"冒险者", r"占卜师", r"祭司", r"花魁", r"非常规职业"), context="identity"),
    rule("Anima/角色/正常/身份与职业/野族角色", "野族角色", 106,
         (r"tribal girl", r"tribal warrior", r"native girl", r"wild woman", r"野族角色"), context="identity"),

    # Background requires explicit scene intent, no-human/scenery markers, or multiple scene tags.
    rule("Anima/背景/R18/拘束与监禁场所", "拘束与监禁场所", 116,
         (r"bondage room", r"prison cell", r"dungeon room", r"torture chamber", r"slave market", r"监禁场所"), context="scene"),
    rule("Anima/背景/R18/成人场所", "成人场所", 112,
         (r"brothel", r"love hotel", r"strip club", r"sex dungeon", r"adult shop", r"red-light district", r"成人场所"), context="scene"),
    rule("Anima/背景/正常/食物与静物", "食物与静物", 106,
         (r"food focus", r"drink focus", r"cake", r"dessert", r"cocktail", r"coffee", r"tea set", r"burger", r"ramen", r"noodles", r"cookies", r"food", r"饮品", r"美食"), context="scene"),
    rule("Anima/背景/正常/未来科幻", "未来科幻场景", 108,
         (r"spaceship", r"space station", r"sci-fi city", r"cyberpunk city", r"futuristic city", r"laboratory", r"science fiction", r"未来科幻"), min_hits=2, context="scene"),
    rule("Anima/背景/正常/恐怖扭曲", "恐怖扭曲场景", 108,
         (r"horror", r"haunted", r"abandoned hospital", r"creepy room", r"blood-filled room", r"body horror background", r"恐怖场景"), min_hits=2, context="scene"),
    rule("Anima/背景/正常/幻想童话", "幻想童话场景", 106,
         (r"fantasy scenery", r"enchanted forest", r"fairy tale", r"floating castle", r"magic forest", r"fantasy map", r"幻想场景"), min_hits=2, context="scene"),
    rule("Anima/背景/正常/节庆与舞台", "节庆与舞台", 105,
         (r"festival", r"stage", r"concert", r"fireworks", r"parade", r"celebration", r"节庆", r"舞台"), min_hits=2, context="scene"),
    rule("Anima/背景/正常/城市与日常", "城市与日常场景", 104,
         (r"city street", r"cityscape", r"urban street", r"alley", r"storefront", r"cafe", r"restaurant", r"train station", r"office", r"城市街道", r"街道", r"街景", r"小巷"), min_hits=2, context="scene"),
    rule("Anima/背景/正常/室外与自然", "室外与自然场景", 102,
         (r"outdoors", r"forest", r"mountain", r"beach", r"ocean", r"river", r"garden", r"field", r"desert", r"jungle", r"sky", r"室外", r"森林"), min_hits=3, context="scene"),
    rule("Anima/背景/正常/室内", "室内场景", 101,
         (r"indoors", r"bedroom", r"classroom", r"bathroom", r"kitchen", r"living room", r"hotel room", r"church", r"palace", r"library", r"室内"), min_hits=3, context="scene"),
    rule("Anima/背景/正常/单纯场景", "综合与概念场景", 96,
         (r"scenery", r"no humans", r"landscape", r"abstract background", r"surreal", r"concept art", r"double exposure", r"单纯场景"), min_hits=2, context="scene"),
)


TAG_DISPLAY = {
    "school uniform": "校服",
    "serafuku": "水手服",
    "bikini": "比基尼",
    "swimsuit": "泳装",
    "kimono": "和服",
    "yukata": "浴衣",
    "hanfu": "汉服",
    "cheongsam": "旗袍",
    "qipao": "旗袍",
    "latex bodysuit": "乳胶连体衣",
    "torn clothes": "破衣",
    "clothes lift": "掀衣",
    "shirt lift": "掀衫",
    "dress lift": "掀裙",
    "open clothes": "敞衣",
    "see-through clothes": "透视",
    "naked jacket": "裸外套",
    "futanari": "扶她",
    "monster girl": "魔物娘",
    "robot girl": "机娘",
    "android": "仿生人",
    "cat girl": "猫娘",
    "fox girl": "狐娘",
    "doggystyle": "后入",
    "cowgirl position": "骑乘",
    "missionary": "正身位",
    "blowjob": "口交",
    "fellatio": "口交",
    "deepthroat": "深喉",
    "cum in mouth": "口内精液",
    "facial": "颜射",
    "handjob": "手交",
    "footjob": "足交",
    "paizuri": "乳交",
    "bondage": "捆绑",
    "shibari": "绳缚",
    "bound arms": "缚手",
    "bound ankles": "缚足",
    "foot focus": "足部特写",
    "feet focus": "足部特写",
    "ass focus": "臀部特写",
    "crotch focus": "裆部特写",
    "pussy focus": "下体特写",
    "food": "食物",
    "cocktail": "鸡尾酒",
    "cake": "蛋糕",
    "burger": "汉堡",
}

GENERIC_ALIAS_RE = re.compile(
    r"^(?:(?:原版|原tag|其他版本|另一版本|版本|其[一二三四五六七八九十]+)"
    r"(?:服装|动作|背景|角色|人设|tag)?(?:\s*\d+)?)?"
    r"(?:[_\s-]*(?:\d+|dup\d+))*$",
    re.IGNORECASE,
)


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def is_generic_alias(alias):
    text = unicodedata.normalize("NFKC", str(alias or "")).strip()
    return not text or bool(GENERIC_ALIAS_RE.fullmatch(text))


def normalize_tag_token(value):
    token = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    token = token.replace("_", " ").replace("：", ":")
    token = re.sub(r"^(?:[+-]?\d+(?:\.\d+)?\s*::\s*)+", "", token)
    token = re.sub(r"^char\d+\s*:\s*", "", token)
    token = re.sub(r"\s*::\s*$", "", token)
    token = token.strip(" \t\r\n{}[]()<>!?:;.'\"")
    token = re.sub(r"\s+", " ", token)
    return token


def extract_tags(value):
    tags = []
    seen = set()
    for fragment in re.split(r"[,，\r\n]+", str(value or "")):
        alternatives = re.split(r"\|+", fragment) if "|" in fragment else (fragment,)
        for alternative in alternatives:
            token = normalize_tag_token(alternative)
            if not token or len(token) > 96 or token in seen:
                continue
            seen.add(token)
            tags.append(token)
    return tags


@lru_cache(maxsize=None)
def _compiled_pattern(pattern, search):
    expression = pattern if search else f"^(?:{pattern})$"
    return re.compile(expression, flags=re.IGNORECASE)


def _matches(pattern, value, search=False):
    return _compiled_pattern(pattern, search).search(value) is not None


def _matched_values(patterns, values):
    return [value for value in values if any(_matches(pattern, value) for pattern in patterns)]


def _required_groups_match(groups, values):
    return all(
        any(_matches(pattern, value) for pattern in group for value in values)
        for group in groups
    )


def _source_is_meme(category):
    normalized = str(category or "").replace("／", "/")
    return normalized.endswith("/表情包/搞怪")


def semantic_title_roots(alias):
    text = normalize_text(alias).strip()
    roots = {
        root
        for root, terms in ALIAS_ROOT_TERMS.items()
        if any(normalize_text(term) in text for term in terms)
    }
    roots.update(
        root
        for root, pattern in SEMANTIC_TITLE_ROOT_PATTERNS.items()
        if pattern.search(text)
    )
    return roots


def _alias_semantic_roots(alias):
    roots = set()
    for rule_item in TAG_RULES:
        if any(_matches(pattern, alias, search=True) for pattern in rule_item.patterns):
            root = root_for_target(rule_item.target + "/")
            if root:
                roots.add(root)
    return roots


def _rule_candidate(rule_item, alias, tags, context):
    tag_hits = _matched_values(rule_item.patterns, tags)
    alias_hits = [pattern for pattern in rule_item.patterns if _matches(pattern, alias, search=True)]
    if not tag_hits and not alias_hits:
        return None
    if len(tag_hits) < rule_item.min_hits and not alias_hits:
        return None
    combined_values = tags + ([alias] if alias else [])
    if rule_item.requires and not _required_groups_match(rule_item.requires, combined_values):
        return None

    rule_context = rule_item.context
    root = root_for_target(rule_item.target + "/")
    if rule_context == "adult" and not context["adult"]:
        return None
    if rule_context == "exposure" and not _required_groups_match((EXPOSURE_BODY,), combined_values):
        return None
    if rule_context == "scene":
        scene_intent = (
            context["no_humans"]
            or context["scenery"]
            or context["title_root"] == "background"
            or len(tag_hits) >= max(2, rule_item.min_hits)
        )
        if not scene_intent:
            return None
    if rule_context == "animal" and not context["no_humans"] and len(tag_hits) < 3:
        return None
    if rule_context == "action" and not (
        alias_hits or len(tag_hits) >= 2 or context["title_root"] == "pose"
    ):
        return None
    if rule_context == "action" and EXPLICIT_SEXUAL_ACTION_ALIAS.search(alias):
        return None
    if rule_context == "action" and "棒喝" in alias and not tag_hits:
        return None
    if rule_context == "expression" and not (
        alias_hits or context["meme_source"] or context["title_root"] == "pose"
    ):
        return None
    if rule_context == "components" and not alias_hits:
        return None
    if rule_context == "clothing_mod" and not (
        alias_hits or len(tag_hits) >= 2 or context["title_root"] == "clothing"
    ):
        return None
    if rule_context == "identity" and not (
        alias_hits or len(tag_hits) >= 2 or context["title_root"] == "character"
    ):
        return None
    if root == "clothing" and not (
        alias_hits
        or len(tag_hits) >= 2
        or context["title_root"] == "clothing"
        or context["source_clothing"]
    ):
        return None

    if (
        context["title_root"]
        and context["title_root"] != root
        and not alias_hits
        and len(tag_hits) < 3
    ):
        return None
    score = rule_item.priority + min(18, 3 * len(tag_hits)) + min(24, 16 * len(alias_hits))
    if alias_hits and rule_context == "action":
        score += 8
    if alias_hits and rule_context == "scene":
        score += 8
    if context["title_root"] == root:
        score += 24
    elif context["title_root"] and context["title_root"] != root:
        score -= 20
    return {
        "target": rule_item.target,
        "label": rule_item.label,
        "score": score,
        "reason": "tag_semantic_rule",
        "tag_hits": tag_hits,
        "alias_hits": alias_hits,
        "root": root,
    }


def choose_semantic_destination(prompt, current_category, provenance_category, contract):
    allowed_targets = canonical_targets(contract)
    source, section = source_context_from_category(provenance_category)
    deterministic = classify_prompt(
        prompt,
        current_category=current_category,
        reference_source=source,
        reference_section=section,
        contract=contract,
    )
    safety_target = contract["non_anima_contracts"]["safety_quarantine_category"]
    excluded_target = contract["non_anima_contracts"]["excluded_category"]
    if deterministic.status == "quarantine" or has_safety_risk(prompt):
        return {
            "target": safety_target,
            "reason": "safety_semantic_quarantine",
            "confidence": 0.99,
            "candidates": [],
            "deterministic": deterministic.to_dict(),
            "matched_tags": [],
            "label": "年龄与安全风险",
        }
    if deterministic.status == "excluded":
        return {
            "target": excluded_target,
            "reason": "excluded_semantic_content",
            "confidence": 0.96,
            "candidates": [],
            "deterministic": deterministic.to_dict(),
            "matched_tags": [],
            "label": "画风质量镜头",
        }

    alias = normalize_text(prompt.get("alias")).strip()
    tags = extract_tags(prompt.get("prompt"))
    title_root = strong_title_root(prompt.get("alias"))
    title_leaf = strong_title_leaf(prompt.get("alias"), allowed_targets)
    title_roots = semantic_title_roots(prompt.get("alias"))
    title_evidence_root = next(iter(title_roots)) if len(title_roots) == 1 else ""
    alias_semantic_roots = _alias_semantic_roots(alias) | title_roots
    adult = has_adult_context(prompt, provenance_category)
    if title_leaf == "Anima/姿势/R18/单人表现/隐秘展示与直播" and not adult:
        title_leaf = ""
    context = {
        "adult": adult,
        "title_root": title_root or title_evidence_root,
        "no_humans": any(tag in {"no human", "no humans"} for tag in tags),
        "scenery": any(tag in {"scenery", "landscape", "still life"} for tag in tags),
        "meme_source": _source_is_meme(provenance_category),
        "source_clothing": any(term in str(provenance_category or "") for term in SOURCE_CLOTHING_TERMS),
    }

    candidates = []
    title_leaf_root = root_for_target(title_leaf + "/") if title_leaf else ""
    explicit_pose_leaf = bool(
        title_leaf_root == "pose"
        and not (
            title_leaf == "Anima/姿势/正常/单人动作"
            and EXPLICIT_SEXUAL_ACTION_ALIAS.search(alias)
        )
        and (
            title_leaf != "Anima/姿势/R18/单人表现/暴露"
            or (
                adult
                and _required_groups_match((EXPOSURE_BODY,), tags + ([alias] if alias else []))
            )
        )
    )
    title_is_unambiguous = bool(
        title_leaf
        and title_leaf_root != "background"
        and (
            explicit_pose_leaf
            or (
                title_leaf_root != "pose"
                and
                title_leaf_root in {title_root, title_evidence_root}
                and not (alias_semantic_roots - {title_leaf_root})
            )
        )
    )
    if title_is_unambiguous:
        candidates.append({
            "target": title_leaf,
            "label": title_leaf.rsplit("/", 1)[-1],
            "score": 210,
            "reason": "alias_primary_intent",
            "tag_hits": [],
            "alias_hits": [str(prompt.get("alias") or "")],
            "root": root_for_target(title_leaf + "/"),
        })
    for rule_item in TAG_RULES:
        if rule_item.target not in allowed_targets:
            continue
        candidate = _rule_candidate(rule_item, alias, tags, context)
        if candidate:
            candidates.append(candidate)

    by_target = {}
    for candidate in candidates:
        previous = by_target.get(candidate["target"])
        if previous is None:
            by_target[candidate["target"]] = candidate
            continue
        if candidate["score"] > previous["score"]:
            candidate["tag_hits"] = list(dict.fromkeys(candidate["tag_hits"] + previous["tag_hits"]))
            candidate["alias_hits"] = list(dict.fromkeys(candidate["alias_hits"] + previous["alias_hits"]))
            by_target[candidate["target"]] = candidate
        else:
            previous["tag_hits"] = list(dict.fromkeys(previous["tag_hits"] + candidate["tag_hits"]))
            previous["alias_hits"] = list(dict.fromkeys(previous["alias_hits"] + candidate["alias_hits"]))
    ordered = sorted(by_target.values(), key=lambda item: (-item["score"], item["target"]))
    if not ordered:
        return {
            "target": "",
            "reason": "no_primary_semantic_intent",
            "confidence": 0.0,
            "candidates": [],
            "deterministic": deterministic.to_dict(),
            "matched_tags": [],
            "label": "",
        }

    top = ordered[0]
    second = ordered[1] if len(ordered) > 1 else None
    gap = top["score"] - (second["score"] if second else 0)
    other_root = next((item for item in ordered[1:] if item["root"] != top["root"]), None)
    same_root = next((item for item in ordered[1:] if item["root"] == top["root"]), None)
    other_root_gap = top["score"] - (other_root["score"] if other_root else 0)
    same_root_gap = top["score"] - (same_root["score"] if same_root else 0)
    cross_root_conflict = bool(
        other_root
        and (
            other_root_gap <= 12
            or ({top["root"], other_root["root"]} <= alias_semantic_roots)
        )
    )
    same_root_conflict = bool(same_root and same_root_gap <= 4)
    top_has_unique_alias_intent = bool(
        top["alias_hits"] and not any(item["alias_hits"] for item in ordered[1:])
    )
    if cross_root_conflict and top["reason"] != "alias_primary_intent" and not top_has_unique_alias_intent:
        return {
            "target": "",
            "reason": "cross_root_semantic_conflict",
            "confidence": 0.0,
            "candidates": ordered[:5],
            "deterministic": deterministic.to_dict(),
            "matched_tags": top["tag_hits"],
            "label": top["label"],
        }
    if same_root_conflict and top["reason"] != "alias_primary_intent" and not top_has_unique_alias_intent:
        return {
            "target": "",
            "reason": "same_root_semantic_conflict",
            "confidence": 0.0,
            "candidates": ordered[:5],
            "deterministic": deterministic.to_dict(),
            "matched_tags": top["tag_hits"],
            "label": top["label"],
        }
    if (
        len(title_roots) > 1
        and top["root"] in title_roots
        and top["reason"] != "alias_primary_intent"
        and not top["alias_hits"]
    ):
        return {
            "target": "",
            "reason": "cross_root_semantic_conflict",
            "confidence": 0.0,
            "candidates": ordered[:5],
            "deterministic": deterministic.to_dict(),
            "matched_tags": top["tag_hits"],
            "label": top["label"],
        }

    confidence = min(0.99, 0.84 + min(0.11, max(0, gap) / 100) + min(0.04, len(top["tag_hits"]) * 0.01))
    return {
        "target": top["target"],
        "reason": top["reason"],
        "confidence": round(confidence, 4),
        "candidates": ordered[:5],
        "deterministic": deterministic.to_dict(),
        "matched_tags": top["tag_hits"],
        "label": top["label"],
    }


def proposed_alias(prompt, decision):
    old_alias = str(prompt.get("alias") or "").strip()
    if (
        not is_generic_alias(old_alias)
        or not str(decision.get("target") or "").startswith("Anima/")
    ):
        return old_alias
    base = str(decision.get("label") or decision["target"].rsplit("/", 1)[-1]).strip()
    descriptors = []
    for tag in decision.get("matched_tags", []):
        display = TAG_DISPLAY.get(tag)
        if display and display not in base and display not in descriptors:
            descriptors.append(display)
    if descriptors:
        base += "｜" + " + ".join(descriptors[:2])
    return base or "已分类预设"


def _unique_alias(base, used):
    candidate = base
    index = 2
    while normalize_text(candidate).strip() in used:
        candidate = f"{base}__{index:03d}"
        index += 1
    used.add(normalize_text(candidate).strip())
    return candidate


def build_provenance_map(path):
    if not path:
        return {}, ""
    raw = path.read_bytes()
    data = json.loads(raw)
    result = {}
    for category in data.get("categories", []):
        name = str(category.get("name") or "")
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            if prompt_id and prompt_id not in result:
                result[prompt_id] = name
    return result, sha256_bytes(raw)


def default_provenance_path(data_path):
    backup_dir = data_path.parent / "classification_reports" / "backups"
    candidates = sorted(backup_dir.glob("data-before-anima-semantic-*.json"))
    return candidates[0] if candidates else None


def build_audit(data, source_hash, provenance_map, provenance_path, provenance_hash, contract, args):
    used_aliases = defaultdict(set)
    for category in data.get("categories", []):
        name = str(category.get("name") or "")
        for prompt in category.get("prompts", []):
            used_aliases[name].add(normalize_text(prompt.get("alias")).strip())

    decisions = []
    reason_counts = Counter()
    from_counts = Counter()
    to_counts = Counter()
    renamed = 0
    for category in data.get("categories", []):
        category_name = str(category.get("name") or "")
        if category_name in EXCLUDED_CATEGORIES or not is_candidate_category(category_name):
            continue
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            provenance_category = provenance_map.get(prompt_id, category_name)
            semantic = choose_semantic_destination(prompt, category_name, provenance_category, contract)
            target = semantic["target"]
            selected = bool(target and target != category_name)
            new_alias = str(prompt.get("alias") or "").strip()
            if selected:
                alias_base = proposed_alias(prompt, semantic)
                if alias_base != new_alias:
                    new_alias = _unique_alias(alias_base, used_aliases[target])
                    renamed += 1
                else:
                    used_aliases[target].add(normalize_text(new_alias).strip())
                from_counts[category_name] += 1
                to_counts[target] += 1
            reason_counts[semantic["reason"]] += 1
            decisions.append({
                "prompt_id": prompt_id,
                "alias": str(prompt.get("alias") or ""),
                "new_alias": new_alias,
                "current_category": category_name,
                "provenance_category": provenance_category,
                "selected": selected,
                "target": target if selected else category_name,
                "reason": semantic["reason"],
                "confidence": semantic["confidence"],
                "matched_tags": semantic["matched_tags"],
                "candidates": semantic["candidates"],
                "deterministic": semantic["deterministic"],
            })

    return {
        "schema_version": 1,
        "stage": "anima_tag_semantic_pass",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_data": {"path": str(args.data), "sha256": source_hash},
        "provenance_data": {
            "path": str(provenance_path) if provenance_path else "",
            "sha256": provenance_hash,
            "mapped_prompt_ids": len(provenance_map),
        },
        "policy": {
            "single_primary_category": True,
            "alias_priority": True,
            "generic_tags_never_decide_alone": ["1girl", "solo", "indoors", "quality/style/camera tags"],
            "generic_aliases_renamed_only_after_selection": True,
            "safety_quarantine_enabled": True,
            "semantic_rule_count": len(TAG_RULES),
        },
        "summary": {
            "candidate_prompts": len(decisions),
            "selected_moves": sum(decision["selected"] for decision in decisions),
            "renamed_prompts": renamed,
            "kept_for_review": sum(not decision["selected"] for decision in decisions),
            "reason_counts": dict(reason_counts.most_common()),
            "from_counts": dict(from_counts.most_common()),
            "to_counts": dict(to_counts.most_common()),
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
    report_hash = str(report.get("source_data", {}).get("sha256") or "").lower()
    if report.get("stage") != "anima_tag_semantic_pass":
        raise SystemExit("拒绝写入：报告类型不正确。")
    if report_hash != source_hash:
        raise SystemExit(f"拒绝写入：报告基于 {report_hash}，当前数据为 {source_hash}。")
    if expected_sha256 and expected_sha256.lower() != source_hash:
        raise SystemExit(f"拒绝写入：期望哈希 {expected_sha256.lower()}，当前数据为 {source_hash}。")

    data = json.loads(source_bytes)
    contract = load_contract()
    allowed_targets = canonical_targets(contract)
    allowed_targets.update(contract["non_anima_contracts"]["review_categories"])
    allowed_targets.add(contract["non_anima_contracts"]["excluded_category"])
    allowed_targets.add(contract["non_anima_contracts"]["safety_quarantine_category"])
    selected = {
        decision["prompt_id"]: decision
        for decision in report.get("decisions", [])
        if decision.get("selected")
    }
    if len(selected) != report.get("summary", {}).get("selected_moves"):
        raise SystemExit("拒绝写入：报告中的移动数量或 prompt ID 不一致。")
    invalid_targets = sorted({decision["target"] for decision in selected.values()} - allowed_targets)
    if invalid_targets:
        raise SystemExit("拒绝写入：报告包含未授权分类：" + ", ".join(invalid_targets))

    result = copy.deepcopy(data)
    result["last_modified"] = datetime.now().astimezone().isoformat()
    categories = result.get("categories", [])
    by_name = {str(category.get("name") or ""): category for category in categories}
    moved_prompts = {}
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
                raise SystemExit(f"拒绝写入：{prompt_id} 的当前分类与报告不一致。")
            moved = copy.deepcopy(prompt)
            moved["alias"] = decision.get("new_alias") or moved.get("alias") or ""
            moved_prompts[prompt_id] = moved
        category["prompts"] = kept

    if len(moved_prompts) != len(selected):
        missing = sorted(set(selected) - set(moved_prompts))
        raise SystemExit("拒绝写入：找不到报告中的 prompt ID：" + ", ".join(missing[:10]))

    for decision in report.get("decisions", []):
        if not decision.get("selected"):
            continue
        target = decision["target"]
        category = by_name.get(target)
        if category is None:
            category = {"id": deterministic_category_id(target), "name": target, "prompts": []}
            categories.append(category)
            by_name[target] = category
        category.setdefault("prompts", []).append(moved_prompts[decision["prompt_id"]])

    result_ids = [
        str(prompt.get("id") or "")
        for category in categories
        for prompt in category.get("prompts", [])
    ]
    if Counter(original_ids) != Counter(result_ids):
        raise SystemExit("拒绝写入：应用后 prompt ID 集合发生变化。")
    category_names = [str(category.get("name") or "") for category in categories]
    category_ids = [str(category.get("id") or "") for category in categories]
    if len(category_names) != len(set(category_names)) or len(category_ids) != len(set(category_ids)):
        raise SystemExit("拒绝写入：应用后分类名称或分类 ID 重复。")

    report_dir = data_path.parent / "classification_reports"
    backup_dir = report_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"data-before-anima-tag-semantic-{timestamp}-{source_hash[:12]}.json"
    backup_path.write_bytes(source_bytes)
    result_bytes = atomic_write_json(data_path, result)
    result_hash = sha256_bytes(result_bytes)
    moves = [{
        "prompt_id": decision["prompt_id"],
        "alias": decision["alias"],
        "new_alias": decision["new_alias"],
        "from": decision["current_category"],
        "to": decision["target"],
        "reason": decision["reason"],
        "matched_tags": decision["matched_tags"],
    } for decision in report.get("decisions", []) if decision.get("selected")]
    apply_result = {
        "schema_version": 1,
        "stage": "anima_tag_semantic_apply",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_hash,
        "result_sha256": result_hash,
        "result_bytes": len(result_bytes),
        "classification_report": str(report_path),
        "classification_report_sha256": sha256_bytes(report_bytes),
        "backup": str(backup_path),
        "moved": len(moves),
        "renamed": sum(move["alias"] != move["new_alias"] for move in moves),
        "moves": moves,
    }
    result_path = report_dir / f"anima-tag-semantic-apply-{timestamp}.json"
    result_path.write_text(json.dumps(apply_result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result_path, apply_result


def main():
    parser = argparse.ArgumentParser(description="Audit and apply a generic-tag semantic Anima classification pass.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    audit = subparsers.add_parser("audit")
    audit.add_argument(
        "--data",
        type=Path,
        default=PLUGIN_DIR / "user_data" / "prompt_selector" / "data.json",
    )
    audit.add_argument("--provenance-data", type=Path, default=None)
    audit.add_argument("--output", type=Path, default=None)
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
            "renamed": result["renamed"],
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
    contract = load_contract()
    report = build_audit(
        data,
        source_hash,
        provenance_map,
        provenance_path,
        provenance_hash,
        contract,
        args,
    )
    if args.output is None:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.output = args.data.parent / "classification_reports" / f"anima-tag-semantic-audit-{timestamp}.json"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(args.output),
        "source_sha256": source_hash,
        "summary": report["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
