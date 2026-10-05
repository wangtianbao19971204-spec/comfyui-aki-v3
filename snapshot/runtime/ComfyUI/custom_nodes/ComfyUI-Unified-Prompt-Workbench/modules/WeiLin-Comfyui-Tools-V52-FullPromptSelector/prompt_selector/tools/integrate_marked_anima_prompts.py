import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent
PROMPT_SELECTOR_DIR = TOOLS_DIR.parent
PLUGIN_DIR = PROMPT_SELECTOR_DIR.parent
for module_path in (PROMPT_SELECTOR_DIR, TOOLS_DIR):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

from anima_managed_completion import (  # noqa: E402
    _capacity_target,
    _classifier_leaf_target,
    _default_target,
    _managed_rule_target,
)
from anima_second_pass import canonical_targets, is_generic_alias  # noqa: E402
from anima_tag_classifier import load_contract, normalize_text  # noqa: E402


SOURCE_ROOTS = (
    "Anima/正太萝莉",
    "待归类/Anima复核/正太萝莉",
)
ALIAS_PREFIX = "正太萝莉-"

POSE = "Anima/姿势"
CHARACTER = "Anima/角色"
CLOTHING = "Anima/服装"

TARGET = {
    "normal_pair": f"{POSE}/正常/多人互动/亲吻与拥抱",
    "normal_companion": f"{POSE}/正常/多人互动/牵手与陪伴",
    "normal_emotion": f"{POSE}/正常/表情与情绪",
    "adult_single": f"{POSE}/R18/情境/成人日常/单人",
    "adult_pair": f"{POSE}/R18/情境/成人日常/双人",
    "ntr": f"{POSE}/R18/情境/NTR",
    "hypnosis": f"{POSE}/R18/情境/催眠",
    "coercion": f"{POSE}/R18/双人互动/胁迫与强制",
    "sleep_assault": f"{POSE}/R18/双人互动/睡眠侵犯",
    "groping": f"{POSE}/R18/双人互动/调戏与猥亵",
    "aftercare": f"{POSE}/R18/双人互动/事后",
    "group_service": f"{POSE}/R18/多人互动/协作侍奉",
    "group_sex": f"{POSE}/R18/多人互动/双飞与多人",
    "group_force": f"{POSE}/R18/多人互动/多人强制",
    "yuri": f"{POSE}/R18/多人互动/百合",
    "restraint": f"{POSE}/R18/拘束/捆绑姿势",
    "captivity": f"{POSE}/R18/拘束/监禁放置",
    "pet_training": f"{POSE}/R18/拘束/宠物调教",
    "restraint_humiliation": f"{POSE}/R18/拘束/拘束凌辱",
    "oral": f"{POSE}/R18/非插入互动/口交与颜射",
    "handjob": f"{POSE}/R18/非插入互动/手交",
    "footjob": f"{POSE}/R18/非插入互动/足交",
    "paizuri": f"{POSE}/R18/非插入互动/乳交",
    "friction": f"{POSE}/R18/非插入互动/身体摩擦",
    "masturbation": f"{POSE}/R18/单人表现/自慰",
    "seduction": f"{POSE}/R18/单人表现/诱惑",
    "exposure": f"{POSE}/R18/单人表现/暴露",
    "chest": f"{POSE}/R18/身体构图/胸腹部",
    "crotch": f"{POSE}/R18/身体构图/臀裆部",
    "legs": f"{POSE}/R18/身体构图/腿足",
    "missionary": f"{POSE}/R18/体位/正身位",
    "standing": f"{POSE}/R18/体位/站立位",
    "seated": f"{POSE}/R18/体位/坐身位",
    "fireman": f"{POSE}/R18/体位/火车便当",
    "mating_press": f"{POSE}/R18/体位/种付位",
    "riding": f"{POSE}/R18/体位/骑乘位",
    "rear": f"{POSE}/R18/体位/后入与背后位",
    "violence": f"{POSE}/R18/重口/暴力/暴虐与过激",
    "killing": f"{POSE}/R18/重口/暴力/杀害",
    "amputation": f"{POSE}/R18/重口/暴力/截肢与人棍",
    "flesh": f"{POSE}/R18/重口/暴力/血肉内脏",
    "slime": f"{POSE}/R18/重口/异种互动/史莱姆",
    "humanoid_monster": f"{POSE}/R18/重口/异种互动/人形魔物",
    "beast": f"{POSE}/R18/重口/异种互动/兽类",
    "tentacle": f"{POSE}/R18/重口/异种互动/触手",
    "excretion": f"{POSE}/R18/重口/排泄物",
    "futanari": f"{CHARACTER}/R18/成人身份/扶她",
    "femboy": f"{CHARACTER}/R18/成人身份/伪娘与男娘",
    "monster_character": f"{CHARACTER}/R18/成人种族/魔物娘与人外",
    "cute_character": f"{CHARACTER}/正常/人物模板/可爱与Q版",
}

# These entries have generic or misleading titles, so their dominant use was
# reviewed against the complete prompt instead of relying on keyword fallback.
MANUAL_TARGETS = {
    "6f6293ad-b988-5d69-b9ba-93c648126c5f": f"{POSE}/R18/情境/成人日常/双人",
    "34dea58d-efd3-510b-ab59-f6d5e43da44c": f"{POSE}/R18/多人互动/协作侍奉",
    "ab69cff3-9201-5eee-9162-7f04152fee39": f"{POSE}/R18/情境/成人日常/双人",
    "10bb2cbc-d451-53ed-bb07-aa57bae5e092": f"{POSE}/R18/非插入互动/手交",
    "e5b2648a-d0c1-5106-8a7a-81f411b4f15c": f"{POSE}/R18/情境/成人日常/双人",
    "773ca538-5a91-5359-9472-250be10c53cc": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "926fdfa1-00f2-5bf1-b326-13bedce4c6a0": f"{POSE}/正常/多人互动/牵手与陪伴",
    "4dd592ab-af76-5dff-86e5-a71fa8d1aa7c": f"{POSE}/R18/多人互动/协作侍奉",
    "ad72d351-0c4c-512d-86df-8f1c6daf1227": f"{POSE}/R18/多人互动/双飞与多人",
    "cdfa2355-9eb7-5ca5-8646-82203e84d111": f"{POSE}/正常/单人动作/综合动作",
    "957c31b0-6c20-5f51-885c-bb22ebf3a53f": f"{POSE}/R18/单人表现/诱惑/身体展示",
    "382dd9c0-452b-540d-9085-93371ed0c3fb": f"{POSE}/R18/情境/成人日常/双人",
    "24399476-2429-5268-b028-af98e49cd897": f"{POSE}/R18/单人表现/诱惑/邀请姿态",
    "a06dec82-1f78-5001-8308-05b952f3ec73": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "662beadb-5954-525a-a1e5-658eb6ce76ba": f"{CHARACTER}/正常/人物模板/奇幻人物模板",
    "f294e752-de46-5fce-8dff-de22169d0b07": f"{POSE}/正常/单人动作/运动与舞蹈",
    "7aecaed0-4953-5731-9bc8-55a5fe9a09c6": f"{POSE}/R18/身体构图/胸腹部",
    "a6c7473f-0455-5b64-91ce-c0f6eb5006b2": f"{CLOTHING}/正常/地域与时代/中国/汉服",
    "36137bc7-65b3-5722-b777-511996510c41": f"{POSE}/正常/多人互动/牵手与陪伴",
    "58cef071-7451-5a2f-a4a5-dd2e64c7ba1c": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "af72c0d6-5841-52df-86ac-1d576f6b030b": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "30bceb63-dcb5-5c9a-8384-91111bd27fcc": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "6275e29f-a085-5ee8-a12c-64f448471147": f"{POSE}/正常/多人互动/牵手与陪伴",
    "23641a38-1f45-553e-a19a-13a1f25d75d5": f"{POSE}/R18/身体构图/胸腹部",
    "b8ff0aab-3cab-504a-b96c-a94f5d4ff43e": f"{CHARACTER}/正常/作品角色/手游角色",
    "a4e75137-ea8d-51b1-b993-bc4e8fd12c56": f"{CLOTHING}/R18/暴露与改造/裸体遮盖",
    "0655cecd-786b-5aac-ab86-4cb0eadc7af8": f"{POSE}/R18/双人互动/调戏与猥亵/腿足与腋下",
    "eab258d9-18ac-5bc9-9c2a-0b4953d71c1a": f"{POSE}/R18/多人互动/百合/多人百合",
    "5028648c-5c56-5b78-b457-15b4087f5b38": f"{CLOTHING}/正常/制服与职业/节庆礼服",
    "a29e463e-442f-5ddd-a27b-55582e0e261b": f"{CHARACTER}/正常/作品角色/单机角色",
    "ad495df7-05d4-5944-8132-df87cf5cee93": f"{CLOTHING}/正常/日常与季节/完整穿搭/裙装与连衣裙",
    "7ca64492-298c-5fac-8446-64deebef413f": f"{POSE}/R18/身体构图/胸腹部",
    "1cdb40ba-34a9-578f-b815-d0876669bd56": f"{CLOTHING}/R18/内衣与泳装/泳装/比基尼",
    "52ef701b-2b18-5e43-b515-7aff15b19086": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "f66a00b2-5325-5a55-8cf2-c5552c257933": f"{CLOTHING}/R18/暴露与改造/日常改造/破损与透视",
    "1cdc0051-34e7-53e4-8644-ee75157578ac": f"{CLOTHING}/正常/制服与职业/节庆礼服",
    "c43ea8dd-1404-58b8-b4ef-2c0c8b1718ff": f"{CLOTHING}/正常/地域与时代/日本",
    "bc003432-420d-50ba-b9e9-97a10cb9fb7f": f"{POSE}/R18/体位/正身位",
    "80bdd8c1-95f4-57a1-9ea0-4b624bf27f47": f"{POSE}/R18/多人互动/双飞与多人",
    "540d710b-5f69-5a31-ae64-76d40c763452": f"{POSE}/R18/单人表现/自慰/玩具自慰",
    "333e6626-66fb-5ea8-af1f-649c95f3048c": f"{POSE}/R18/情境/成人日常/单人",
    "2d3c1054-19e7-5237-92cf-51ad3b4f05b4": f"{POSE}/正常/多人互动/亲吻与拥抱",
    "0ca218c2-045a-571f-a355-ce5d5a7fa8bf": f"{CLOTHING}/R18/暴露与改造/日常改造/下拉与半脱",
    "cc5b73c3-e5cb-51ec-9285-40884b27246c": f"{POSE}/正常/基础姿态/综合姿态",
    "bf1768c5-8284-5216-80dc-015f94e2c626": f"{POSE}/正常/多人互动/亲吻与拥抱",
    "de2ba204-279d-5a70-a5b9-cdbdb1f2f6a3": f"{POSE}/R18/多人互动/协作侍奉",
    "8527dceb-f38d-5ef3-93d0-fd57c20e6baf": f"{POSE}/正常/表情与情绪/夸张颜艺/冷淡与无语",
    "9a36f330-938e-5c0d-ae19-118cac6306b9": f"{POSE}/正常/表情与情绪/害羞与慌张",
    "53585dc8-f01a-5a0f-8ff2-caf3fe41b902": f"{POSE}/正常/多人互动/牵手与陪伴",
    "ef3330d9-e645-57da-a335-fc5144f1f631": f"{POSE}/正常/表情与情绪/夸张颜艺/冷淡与无语",
    "23f22983-9906-54ab-8acb-9e60d75a1f4d": f"{POSE}/正常/表情与情绪/害羞与慌张",
    "9f15bb0c-5bc7-56af-b434-f4a3c99bb148": f"{POSE}/正常/表情与情绪/害羞与慌张",
    "a7bb4af0-3715-54a8-ad5b-f7d7ca8e2b47": f"{POSE}/正常/表情与情绪/惊讶与困惑",
    "8d85284e-5051-54c4-9037-dda240de6eff": f"{POSE}/正常/表情与情绪/害羞与慌张",
    "afe74c69-8f29-5d64-980e-43038ae04998": f"{POSE}/正常/表情与情绪/开心与得意",
    "836041f5-1824-5da1-bfbb-78612fc0d0a2": f"{POSE}/R18/多人互动/协作侍奉",
    "0ed076ca-efcd-5b14-97b0-d8df11ae4288": f"{POSE}/R18/非插入互动/手交",
    "a18ba501-550d-5b21-a29d-917e56cfc3b0": f"{POSE}/R18/单人表现/自慰/综合自慰",
    "ecaaf6b5-3e11-50a2-bc6e-7f8fc0f5456e": f"{POSE}/R18/情境/成人日常/双人",
    "a7037926-4af2-5605-be15-2a1da3e4c630": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "339e7890-619e-55b1-8c5d-78a5493e9212": f"{POSE}/R18/体位/正身位",
    "d63b32e6-9f5a-5f70-88d8-27af9ce0e3b9": f"{POSE}/R18/体位/正身位",
    "ce376c0b-0d50-5d51-b172-b5f133fc72bd": f"{POSE}/R18/双人互动/调戏与猥亵/腿足与腋下",
    "92d8cec5-f5b7-59b9-bcc3-231409ea491f": f"{POSE}/R18/多人互动/双飞与多人",
    "cd53ca00-1d2d-5c5a-a4e6-b24a32e91d21": f"{POSE}/R18/双人互动/调戏与猥亵/臀裆触摸",
    "8fb2fee2-d303-5034-9b10-92691f6ff919": f"{POSE}/R18/情境/成人日常/双人",
    "30c70cd6-6ee2-54f8-bc76-9ed9bece31fc": f"{POSE}/R18/多人互动/双飞与多人",
    "01c83b9b-7fb5-5faf-9ec9-a496d8993497": f"{POSE}/R18/情境/成人日常/双人",
    "c335bfb5-e98d-5407-b301-e2fdc6c3877f": f"{CLOTHING}/R18/Cosplay与角色服装",
    "ad676367-d1a8-5972-a07c-8300a40e8503": f"{POSE}/R18/情境/成人日常/双人",
    "52bc9291-cef9-5b08-bb28-0f60dac8a37a": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "b86d5ea2-4313-5527-bd98-c05ea368ee5c": f"{CHARACTER}/正常/人物模板/奇幻人物模板",
    "c847eee2-aa80-5b89-ac77-1969e2901d8e": f"{CHARACTER}/正常/人物模板/通用人物模板/体型与肤色",
    "cc398ed1-c169-53e1-a41f-775b8b01a953": f"{CLOTHING}/R18/Cosplay与角色服装",
    "bf25dc8c-efa5-5809-bd45-de3e6edcd026": f"{POSE}/R18/单人表现/自慰/玩具自慰",
    "4befbdf5-375d-562b-8a70-f446a9b184ea": f"{POSE}/R18/双人互动/事后/体内与流出",
    "0b18f59c-65c5-57ea-a1cd-968e556e0f18": f"{POSE}/R18/体位/正身位",
    "d42a4683-ea36-5a8f-9fb2-e7f78a80b9d8": f"{POSE}/R18/情境/成人日常/双人",
    "d825a31b-4ea3-5b80-ad8e-e7fe6247032f": f"{POSE}/R18/非插入互动/手交",
    "c0f3e4ca-4f12-5039-8be0-4d1f89550403": f"{POSE}/R18/体位/坐身位",
    "ac4911c3-efe0-5643-9d88-789a8668b172": f"{POSE}/R18/体位/坐身位",
    "bd7a7eb4-9158-5074-ba6f-07c6f0ed66f2": f"{POSE}/R18/非插入互动/口交与颜射/深喉与强制口交",
    "1a882441-92aa-5c8c-95a1-1f71bf8cb267": f"{POSE}/正常/表情与情绪/开心与得意",
    "457baf91-dcce-5ab5-8018-05f13cd6bc68": f"{CHARACTER}/正常/作品角色/手游角色",
    "6f6bcde5-96a2-5817-9dfc-9f13d906476a": f"{POSE}/R18/情境/成人日常/单人",
    "7fe43af0-8daf-5cb3-8fde-05f06b91b53c": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "2745c6a0-d97c-543c-a07e-1fe55aa15e60": f"{POSE}/R18/双人互动/调戏与猥亵/胸部爱抚",
    "b6b4328e-8b64-591d-b562-8e66fc535c09": f"{POSE}/R18/情境/成人日常/双人",
    "0eb5ba9e-552c-5b74-8407-dde7bc119da8": f"{POSE}/R18/非插入互动/身体摩擦",
    "e7c1447f-54ee-5f02-b09c-1dcebbc1dd62": f"{POSE}/R18/情境/成人日常/双人",
    "9b1e364f-0b30-580e-8077-a22980372bf2": f"{POSE}/R18/重口/异种互动/人形魔物",
    "a1824ac0-f91f-55bf-b61b-cb3301dab569": f"{POSE}/R18/拘束/捆绑姿势/综合拘束姿态",
    "cbcc1c72-ac2b-5af3-9a1c-cdf3a7b315a8": f"{POSE}/R18/单人表现/暴露/掀衣与敞开",
    "4e246486-c549-5306-8c46-2daa8f4f8520": f"{CLOTHING}/R18/暴露与改造/恶堕服装",
    "27fc53e1-ba32-514f-91f7-efac15aec990": f"{POSE}/正常/多人互动/亲吻与拥抱",
    "a2936572-e19f-526e-a037-5a8ecef6d72f": f"{CHARACTER}/正常/人物模板/奇幻人物模板",
    "86a05c1d-a505-5b07-97aa-245e1b78ec24": f"{POSE}/R18/重口/异种互动/人形魔物",
    "091e8f97-b6a8-54e2-b89a-d2276e6beb79": f"{POSE}/正常/多人互动/亲吻与拥抱",
    "c2f9bf5d-f5f2-5662-b8d7-7b25e487bc74": f"{POSE}/R18/情境/成人日常/双人",
    "9b493da8-b090-53d8-8636-834408d46530": f"{CHARACTER}/正常/作品角色/动漫角色",
}


def sha256_bytes(value):
    return hashlib.sha256(value).hexdigest()


def atomic_write_json(path, value):
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
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
    finally:
        if os.path.exists(temporary_name):
            os.remove(temporary_name)
    return serialized


def under_root(name, root):
    return name == root or name.startswith(root + "/")


def is_source_category(name):
    return any(under_root(name, root) for root in SOURCE_ROOTS)


def matches(text, pattern):
    return bool(re.search(pattern, text, re.IGNORECASE))


def marked_alias(alias):
    value = str(alias or "").strip()
    return value if value.startswith(ALIAS_PREFIX) else ALIAS_PREFIX + value


def managed_target(prompt, root, provenance, allowed_targets):
    _score, target = _managed_rule_target(prompt, root)
    if not target:
        _score, target = _classifier_leaf_target(prompt, root, allowed_targets)
    if not target:
        target = _default_target(prompt, root, provenance)
    target, _split_base = _capacity_target(target, prompt)
    return target


def capacity_target(target, prompt):
    return _capacity_target(target, prompt)[0]


def route_text(prompt, source, text, allowed_targets, scope):
    if matches(text, r"截肢|人棍|断首|斩首|肢体切除|三肢|四肢切除|amput|decapitat|severed (?:head|limb)"):
        return TARGET["amputation"], "explicit_amputation", 0.99
    if matches(text, r"奸尸|尸体|待宰|杀害|奸杀|necroph|corpse sex|killed after"):
        return TARGET["killing"], "explicit_killing_or_corpse", 0.99
    if matches(text, r"血肉|内脏|gore|guts|viscera|flesh interior"):
        return TARGET["flesh"], "explicit_flesh_or_gore", 0.99
    if matches(text, r"暴虐|酷刑|虐待|打烂|膝击蛋蛋|torture|brutal|guro"):
        return TARGET["violence"], "explicit_extreme_violence", 0.98

    if matches(text, r"触手|tentacle"):
        return capacity_target(TARGET["tentacle"], prompt), "explicit_tentacle", 0.99
    if matches(text, r"史莱姆|slime"):
        return TARGET["slime"], "explicit_slime", 0.99
    if matches(text, r"兽交|公狗|bestial|zooph|animal sex"):
        return TARGET["beast"], "explicit_beast_interaction", 0.99
    if matches(text, r"哥布林|丧尸|鬼魂|鬼娃|异形|orc|goblin|zombie|ghost sex|alien sex"):
        return TARGET["humanoid_monster"], "explicit_humanoid_monster", 0.97
    if matches(text, r"排尿|尿液|尿在|喝尿|放尿|urine|piss|urination"):
        return TARGET["excretion"], "explicit_excretion", 0.99

    if matches(text, r"催眠|洗脑|精神控制|hypno|mind control|brainwash"):
        return TARGET["hypnosis"], "explicit_hypnosis", 0.99
    if matches(text, r"\bntr\b|苦主|当着(?:女儿|丈夫|男友|苦主).*面"):
        return TARGET["ntr"], "explicit_ntr", 0.99

    is_group = matches(
        text,
        r"(?:^|\D)[34]p(?:\D|$)|双飞|三飞|多人|轮奸|群交|乱交|gangbang|group sex|"
        r"三个小正太|三位|两男|二男二女|前后夹击|左右夹住|两女夹住|二女前后",
    )
    is_forced = matches(
        text,
        r"强制|侵犯|强暴|轮奸|胁迫|绑架|袭击|捕获|被抓|rape|forced|molest|assault",
    )
    if is_group and is_forced:
        return TARGET["group_force"], "forced_group_interaction", 0.98
    if matches(text, r"百合|\byuri\b|lesbian|母女相拥|母女盖饭|双扶她百合|扶她百合"):
        return capacity_target(TARGET["yuri"], prompt), "explicit_yuri", 0.97
    if is_group:
        if matches(text, r"侍奉|协作|手交|口交|夹住|围攻|左右|前后"):
            return TARGET["group_service"], "group_service", 0.96
        return TARGET["group_sex"], "group_interaction", 0.95

    if matches(text, r"睡奸|睡眠侵犯|趁.*睡|sleep sex|sleeping assault"):
        return TARGET["sleep_assault"], "explicit_sleep_assault", 0.99
    if matches(text, r"强制.*(?:深喉|口交)|(?:深喉|口交).*强制|facefuck|irrumatio"):
        return capacity_target(TARGET["oral"], prompt), "forced_oral", 0.99
    if matches(text, r"项圈|牵绳|母狗|男奴|性奴|宠物调教|leash|pet play|sex slave"):
        return TARGET["pet_training"], "pet_or_slave_training", 0.97
    if matches(text, r"绑架|监禁|囚禁|拘束放置|玩具放置|关押|牢房|captiv|imprison"):
        return TARGET["captivity"], "captivity_or_placement", 0.98
    if matches(text, r"吊缚|倒吊|捆绑|绳缚|手铐|束缚|拘束|绑住|bound|bondage|shibari|hogtie"):
        return capacity_target(TARGET["restraint"], prompt), "explicit_restraint", 0.98
    if is_forced:
        return TARGET["coercion"], "coercion_semantics", 0.94

    if matches(text, r"舔阴|舔穴|吃穴|cunnilingus|pussy lick"):
        return f"{TARGET['oral']}/舔阴与女性口交", "female_oral", 0.99
    if matches(text, r"深喉|deepthroat|gagging|throat sex"):
        return f"{TARGET['oral']}/深喉与强制口交", "deepthroat", 0.99
    if matches(text, r"颜射|口内|cum in mouth|cum on face|facial"):
        return f"{TARGET['oral']}/颜射与口内", "oral_finish", 0.97
    if matches(text, r"口交|嗦|吃.*几把|吹箫|舔.*几把|blowjob|fellatio|oral sex|骑脸"):
        return capacity_target(TARGET["oral"], prompt), "oral_interaction", 0.98
    if matches(text, r"手交|手冲|手淫|handjob"):
        return TARGET["handjob"], "handjob", 0.99
    if matches(text, r"足交|脚.*几把|踩.*几把|footjob"):
        return TARGET["footjob"], "footjob", 0.99
    if matches(text, r"乳交|奶夹|乳夹|paizuri"):
        return TARGET["paizuri"], "paizuri", 0.99
    if matches(text, r"素股|腿交|股交|thigh sex|grinding between thighs"):
        return TARGET["friction"], "body_friction", 0.99
    if matches(text, r"自慰|手指自慰|玩具自慰|masturbat|fingering self|dildo|vibrator"):
        return capacity_target(TARGET["masturbation"], prompt), "masturbation", 0.99

    if matches(text, r"事后|余韵|射在身上|流精|抽离|被榨干|after sex|cumdrip|creampie"):
        return capacity_target(TARGET["aftercare"], prompt), "aftercare_or_finish", 0.96

    if matches(text, r"后入|背后位|狗爬|背身骑乘|从背后|rear entry|doggy|from behind|prone bone"):
        return capacity_target(TARGET["rear"], prompt), "rear_position", 0.99
    if matches(text, r"火车便当|standing carry sex"):
        return TARGET["fireman"], "carried_position", 0.99
    if matches(text, r"骑乘位|女上位|骑身|骑背|cowgirl|reverse cowgirl"):
        return TARGET["riding"], "riding_position", 0.99
    if matches(text, r"站立位|挂身性爱|面对面站立|standing sex"):
        return TARGET["standing"], "standing_position", 0.99
    if matches(text, r"坐身位|面对坐位|背身坐位|坐位性爱|seated sex"):
        return TARGET["seated"], "seated_position", 0.99
    if matches(text, r"种付位|种付|mating press|压身性爱"):
        return TARGET["mating_press"], "mating_press", 0.98
    if matches(text, r"侧入|侧躺.*(?:性爱|插入)|side sex"):
        return f"{TARGET['rear']}/侧卧与躺卧", "side_lying_position", 0.95
    if matches(text, r"正身位|传教士|正常位|做爱|性爱|性交|插入|爆炒|被炒|被艹|被草|missionary|penetrat"):
        return TARGET["missionary"], "general_penetrative_position", 0.90

    if matches(text, r"揉胸|抓胸|摸胸|揉屁股|扣穴|摸大腿|膝顶|壁咚|breast grab|grop|ass grab|crotch grab"):
        return capacity_target(TARGET["groping"], prompt), "groping_or_teasing", 0.96
    if matches(text, r"吸奶|吃奶|哺乳|授乳|喂奶|breastfeed|suckling"):
        return f"{TARGET['groping']}/胸部爱抚", "breastfeeding_or_chest_contact", 0.92
    if matches(text, r"公共.*露|电车露出|裸大衣|露出|public nudity|exhibition"):
        return f"{TARGET['exposure']}/公共场所暴露", "public_exposure", 0.98
    if matches(text, r"掀.*衣|掀.*裙|拉下胸罩|撩起衣服|敞开|clothes lift|skirt lift|open clothes"):
        return f"{TARGET['exposure']}/掀衣与敞开", "clothes_lift_or_opening", 0.98
    if matches(text, r"走光|裙底|accidental exposure|wardrobe malfunction"):
        return f"{TARGET['exposure']}/意外走光", "accidental_exposure", 0.97
    if (
        matches(text, r"全裸|裸体|裸体展示|nude|naked|topless|bottomless")
        and (scope == "alias" or source.endswith("/裸露与性化展示"))
    ):
        return f"{TARGET['exposure']}/裸体展示", "nudity_display", 0.95
    if matches(text, r"诱惑|勾引|邀请|挑衅|调戏|seduc|teasing pose|inviting"):
        return capacity_target(TARGET["seduction"], prompt), "seduction", 0.94
    if matches(text, r"胸部特写|乳房特写|抓住乳头|拉扯乳头|挤.*奶|breast focus|nipple focus"):
        return TARGET["chest"], "chest_composition", 0.95
    if matches(text, r"小穴特写|屁股特写|下半身特写|臀裆|genital focus|pussy focus|ass focus"):
        return TARGET["crotch"], "crotch_composition", 0.96
    if matches(text, r"足底|腿间视角|大腿特写|sole focus|feet focus|leg focus"):
        return capacity_target(TARGET["legs"], prompt), "leg_or_foot_composition", 0.95

    if matches(text, r"扶她|futanari") and not matches(text, r"(?:做爱|后入|骑乘|口交|手交|肛交|插入|爆炒)"):
        return TARGET["futanari"], "futanari_identity", 0.93
    if matches(text, r"伪娘|男娘|女装少年|femboy|otokonoko") and not matches(text, r"(?:做爱|后入|骑乘|口交|手交|肛交|插入|爆炒)"):
        return TARGET["femboy"], "femboy_identity", 0.93
    if matches(text, r"原版服装|服装版|角色服装|衣装"):
        return managed_target(prompt, "clothing", source, allowed_targets), "explicit_clothing_title", 0.90
    if matches(text, r"原版角色|去除角色tag|角色版"):
        return managed_target(prompt, "character", source, allowed_targets), "explicit_character_title", 0.90

    if matches(text, r"亲脸|亲吻|激吻|深吻|湿吻|索吻|强吻|kiss"):
        return TARGET["normal_pair"], "kiss_or_intimacy", 0.92
    if matches(text, r"拥抱|相拥|牵手|共枕|贴身|抱住|hug|cuddl|holding hands"):
        return TARGET["normal_pair"], "hug_or_intimacy", 0.90
    if matches(text, r"耳边说|悄悄话|坐在一起|合影|陪伴"):
        return TARGET["normal_companion"], "companionship", 0.90
    if matches(text, r"害羞|惊慌|害怕|生气|不满意|呆滞|回味|哭泣|得逞|慌张|shy|angry|scared|crying"):
        return capacity_target(TARGET["normal_emotion"], prompt), "emotion_or_reaction", 0.88
    return "", "", 0.0


def classify_prompt(prompt, source, allowed_targets):
    manual_target = MANUAL_TARGETS.get(str(prompt.get("id") or ""))
    if manual_target:
        return manual_target, "manual_semantic_audit", 0.99

    alias = normalize_text(prompt.get("alias")).strip()
    body = normalize_text(
        f"{prompt.get('alias', '')}\n{prompt.get('prompt', '')}\n{prompt.get('description', '')}"
    )

    title_target, reason, confidence = route_text(
        prompt,
        source,
        alias,
        allowed_targets,
        "alias",
    )
    if title_target:
        return title_target, "alias_" + reason, confidence

    body_target, reason, confidence = route_text(
        prompt,
        source,
        body,
        allowed_targets,
        "body",
    )
    if body_target:
        confidence_cap = 0.92 if (
            is_generic_alias(alias)
            or matches(
                alias,
                r"^(?:原版|另一版本|其他版本|自然语言|简化版本|附带原tag|原版杂项|原版未整理)",
            )
        ) else 0.90
        return body_target, "body_" + reason, min(confidence, confidence_cap)

    if source.endswith("/口部与非插入行为"):
        return TARGET["friction"], "source_nonpenetrative_fallback", 0.74
    if source.endswith("/插入与体位"):
        return TARGET["missionary"], "source_penetration_fallback", 0.74
    if source.endswith("/强制拘束与暴力"):
        return TARGET["coercion"], "source_coercion_fallback", 0.74
    if source.endswith("/裸露与性化展示"):
        return f"{TARGET['exposure']}/裸体展示", "source_nudity_fallback", 0.72
    if source.endswith("/其他性行为"):
        return TARGET["adult_pair"], "source_adult_pair_fallback", 0.72
    if source.endswith("/成人语境与年龄关系"):
        return TARGET["normal_companion"], "source_relationship_fallback", 0.70
    raise RuntimeError(f"没有可用路由：{source} / {prompt.get('id', '')}")


def build_audit(data, source_hash, capacity_limit):
    contract = load_contract()
    allowed_targets = canonical_targets(contract)
    categories = data.get("categories", [])
    existing = {
        str(category.get("name") or ""): category
        for category in categories
    }
    source_categories = [
        category for category in categories
        if is_source_category(str(category.get("name") or ""))
    ]
    if not source_categories:
        raise SystemExit("没有找到待分散的正太萝莉分类。")

    decisions = []
    target_counts = Counter()
    reason_counts = Counter()
    seen_prompt_ids = set()
    for category in source_categories:
        source = str(category.get("name") or "")
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            if not prompt_id or prompt_id in seen_prompt_ids:
                raise SystemExit(f"待分散条目 ID 缺失或重复：{prompt_id}")
            seen_prompt_ids.add(prompt_id)
            target, reason, confidence = classify_prompt(
                prompt,
                source,
                allowed_targets,
            )
            if target not in allowed_targets or target not in existing:
                raise SystemExit(f"目标不是现有 Anima 叶子：{target}")
            decisions.append({
                "prompt_id": prompt_id,
                "alias": str(prompt.get("alias") or ""),
                "new_alias": marked_alias(prompt.get("alias")),
                "source": source,
                "target": target,
                "reason": reason,
                "confidence": round(confidence, 4),
                "image": str(prompt.get("image") or ""),
            })
            target_counts[target] += 1
            reason_counts[reason] += 1

    projected = Counter({
        name: len(category.get("prompts", []))
        for name, category in existing.items()
    })
    for decision in decisions:
        projected[decision["source"]] -= 1
        projected[decision["target"]] += 1
    over_capacity = {
        name: count for name, count in sorted(projected.items())
        if name.startswith("Anima/")
        and not is_source_category(name)
        and count > capacity_limit
    }
    return {
        "schema_version": 1,
        "stage": "integrate_marked_anima_prompts",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_sha256": source_hash,
        "source_roots": list(SOURCE_ROOTS),
        "alias_prefix": ALIAS_PREFIX,
        "category_count": len(source_categories),
        "prompt_count": len(decisions),
        "target_count": len(target_counts),
        "target_counts": dict(target_counts.most_common()),
        "reason_counts": dict(reason_counts.most_common()),
        "low_confidence_count": sum(
            decision["confidence"] < 0.80 for decision in decisions
        ),
        "projected_over_capacity": over_capacity,
        "decisions": decisions,
    }


def integrated_data(data, audit):
    result = copy.deepcopy(data)
    decisions = {
        decision["prompt_id"]: decision
        for decision in audit["decisions"]
    }
    categories = result.get("categories", [])
    by_name = {
        str(category.get("name") or ""): category
        for category in categories
    }
    now = datetime.now(timezone.utc).astimezone().isoformat()

    for category in categories:
        source = str(category.get("name") or "")
        if not is_source_category(source):
            continue
        for prompt in category.get("prompts", []):
            prompt_id = str(prompt.get("id") or "")
            decision = decisions[prompt_id]
            moved_prompt = copy.deepcopy(prompt)
            moved_prompt["alias"] = decision["new_alias"]
            moved_prompt["updated_at"] = now
            target_category = by_name[decision["target"]]
            target_category.setdefault("prompts", []).append(moved_prompt)
            target_category["updated_at"] = now

    result["categories"] = [
        category for category in categories
        if not is_source_category(str(category.get("name") or ""))
    ]
    result["last_modified"] = now
    return result


def validate_result(source, result, audit):
    source_categories = source.get("categories", [])
    result_categories = result.get("categories", [])
    source_prompts = {
        str(prompt.get("id") or ""): prompt
        for category in source_categories
        for prompt in category.get("prompts", [])
    }
    result_prompts = {
        str(prompt.get("id") or ""): prompt
        for category in result_categories
        for prompt in category.get("prompts", [])
    }
    moved_ids = {decision["prompt_id"] for decision in audit["decisions"]}
    if set(source_prompts) != set(result_prompts):
        raise SystemExit("分散后预设 ID 集合发生变化，拒绝写入。")
    if any(is_source_category(str(category.get("name") or "")) for category in result_categories):
        raise SystemExit("分散后仍存在正太萝莉专属目录，拒绝写入。")
    result_category_ids = [str(category.get("id") or "") for category in result_categories]
    expected_category_ids = [
        str(category.get("id") or "") for category in source_categories
        if not is_source_category(str(category.get("name") or ""))
    ]
    if result_category_ids != expected_category_ids:
        raise SystemExit("分散改变了保留分类的 ID 或顺序，拒绝写入。")

    for prompt_id, before in source_prompts.items():
        after = result_prompts[prompt_id]
        if prompt_id in moved_ids:
            before_copy = copy.deepcopy(before)
            after_copy = copy.deepcopy(after)
            before_copy.pop("alias", None)
            before_copy.pop("updated_at", None)
            after_copy.pop("alias", None)
            after_copy.pop("updated_at", None)
            if before_copy != after_copy:
                raise SystemExit(f"分散改变了预设内容：{prompt_id}")
            if not str(after.get("alias") or "").startswith(ALIAS_PREFIX):
                raise SystemExit(f"分散条目缺少标题前缀：{prompt_id}")
        elif before != after:
            raise SystemExit(f"非目标预设发生变化：{prompt_id}")


def main():
    default_data = PLUGIN_DIR / "user_data" / "prompt_selector" / "data.json"
    parser = argparse.ArgumentParser(
        description="Disperse marked prompts into existing Anima leaves.",
    )
    parser.add_argument("--data", type=Path, default=default_data)
    parser.add_argument("--expected-sha256", default="")
    parser.add_argument("--capacity-limit", type=int, default=200)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    source_bytes = args.data.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    if args.expected_sha256 and source_hash != args.expected_sha256:
        raise SystemExit(
            f"源数据哈希变化：expected={args.expected_sha256} actual={source_hash}"
        )
    source = json.loads(source_bytes)
    audit = build_audit(source, source_hash, args.capacity_limit)
    if audit["projected_over_capacity"]:
        raise SystemExit(
            "分散后存在超过容量上限的分类："
            + json.dumps(audit["projected_over_capacity"], ensure_ascii=False)
        )
    result = integrated_data(source, audit)
    validate_result(source, result, audit)

    report_dir = args.data.parent / "classification_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    audit["applied"] = bool(args.apply)

    if args.apply:
        backup_dir = report_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = (
            backup_dir
            / f"data-before-marked-anima-integration-{timestamp}-{source_hash[:12]}.json"
        )
        backup_path.write_bytes(source_bytes)
        result_bytes = atomic_write_json(args.data, result)
        audit["result_sha256"] = sha256_bytes(result_bytes)
        audit["backup"] = str(backup_path)

    output = args.output or (
        report_dir / f"marked-anima-integration-{timestamp}.json"
    )
    atomic_write_json(output, audit)
    print(json.dumps({
        "source_sha256": source_hash,
        "category_count": audit["category_count"],
        "prompt_count": audit["prompt_count"],
        "target_count": audit["target_count"],
        "target_counts": audit["target_counts"],
        "low_confidence_count": audit["low_confidence_count"],
        "projected_over_capacity": audit["projected_over_capacity"],
        "applied": audit["applied"],
        "result_sha256": audit.get("result_sha256", ""),
        "backup": audit.get("backup", ""),
        "report": str(output),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
