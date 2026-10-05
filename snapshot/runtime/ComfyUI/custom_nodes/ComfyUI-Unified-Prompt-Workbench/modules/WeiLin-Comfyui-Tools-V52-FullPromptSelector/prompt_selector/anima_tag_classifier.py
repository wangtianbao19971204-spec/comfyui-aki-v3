import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path


ROOT_BY_PREFIX = {
    "Anima/角色/": "character",
    "Anima/服装/": "clothing",
    "Anima/姿势/": "pose",
    "Anima/背景/": "background",
}

SOURCE_REGULAR = "所长常规NovelAI个人法典"
SOURCE_ADULT_UPPER = "所长色色NovelAI个人法典(上)"
SOURCE_ADULT_LOWER = "所长色色NovelAI个人法典(下)"


SECTION_TARGETS = {
    (SOURCE_REGULAR, "单机角色"): "Anima/角色/正常/作品角色/单机角色",
    (SOURCE_REGULAR, "网络角色"): "Anima/角色/正常/作品角色/网络角色",
    (SOURCE_REGULAR, "端游角色"): "Anima/角色/正常/作品角色/端游角色",
    (SOURCE_REGULAR, "动漫角色"): "Anima/角色/正常/作品角色/动漫角色",
    (SOURCE_REGULAR, "明日方舟角色"): "Anima/角色/正常/作品角色/手游角色",
    (SOURCE_REGULAR, "其他手游角色"): "Anima/角色/正常/作品角色/手游角色",
    (SOURCE_REGULAR, "文化作品角色"): "Anima/角色/正常/作品角色/文化作品角色",
    (SOURCE_REGULAR, "类人种族"): "Anima/角色/正常/种族与形态/类人种族",
    (SOURCE_REGULAR, "动物娘化"): "Anima/角色/正常/种族与形态/动物娘化",
    (SOURCE_REGULAR, "西幻魔物"): "Anima/角色/正常/种族与形态/魔物与人外",
    (SOURCE_REGULAR, "中外经典"): "Anima/角色/正常/种族与形态/魔物与人外",
    (SOURCE_REGULAR, "人工造物"): "Anima/角色/正常/种族与形态/人工造物",
    (SOURCE_REGULAR, "furry特辑"): "Anima/角色/正常/种族与形态/动物娘化",
    (SOURCE_REGULAR, "人物转化"): "Anima/角色/正常/外观与转化/人物转化",
    (SOURCE_REGULAR, "服装组件"): "Anima/服装/正常/组件与配饰",
    (SOURCE_REGULAR, "日常服"): "Anima/服装/正常/日常与季节/日常服",
    (SOURCE_REGULAR, "夏装"): "Anima/服装/正常/日常与季节/夏装",
    (SOURCE_REGULAR, "冬装"): "Anima/服装/正常/日常与季节/冬装",
    (SOURCE_REGULAR, "室内服（运动服、睡衣、正常内衣等）"): "Anima/服装/正常/日常与季节/室内服",
    (SOURCE_REGULAR, "校服"): "Anima/服装/正常/制服与职业/校服",
    (SOURCE_REGULAR, "节日庆典礼服"): "Anima/服装/正常/制服与职业/节庆礼服",
    (SOURCE_REGULAR, "常规职业"): "Anima/服装/正常/制服与职业/职业制服",
    (SOURCE_REGULAR, "军装"): "Anima/服装/正常/制服与职业/军装",
    (SOURCE_REGULAR, "舞台曲艺"): "Anima/服装/正常/制服与职业/舞台服",
    (SOURCE_REGULAR, "运动人员"): "Anima/服装/正常/制服与职业/运动服",
    (SOURCE_REGULAR, "蓝白领"): "Anima/服装/正常/制服与职业/职业制服",
    (SOURCE_REGULAR, "街头人物"): "Anima/服装/正常/制服与职业/职业制服",
    (SOURCE_REGULAR, "非常规职业"): "Anima/服装/正常/制服与职业/职业制服",
    (SOURCE_REGULAR, "中国"): "Anima/服装/正常/地域与时代/中国",
    (SOURCE_REGULAR, "日本"): "Anima/服装/正常/地域与时代/日本",
    (SOURCE_REGULAR, "中东"): "Anima/服装/正常/地域与时代/中东",
    (SOURCE_REGULAR, "未来科幻"): "Anima/服装/正常/幻想与主题/未来科幻",
    (SOURCE_REGULAR, "游戏服装"): "Anima/服装/正常/幻想与主题/游戏服装",
    (SOURCE_REGULAR, "中近世纪"): "Anima/服装/正常/地域与时代/中近世纪",
    (SOURCE_REGULAR, "西幻奇幻"): "Anima/服装/正常/幻想与主题/西幻奇幻",
    (SOURCE_REGULAR, "魔法特辑"): "Anima/服装/正常/幻想与主题/魔法少女",
    (SOURCE_REGULAR, "野族传说"): "Anima/服装/正常/幻想与主题/野族服装",
    (SOURCE_REGULAR, "另类服装"): "Anima/服装/正常/幻想与主题/特殊服装",
    (SOURCE_REGULAR, "情感动作"): "Anima/姿势/正常/表情与情绪",
    (SOURCE_REGULAR, "战斗华丽"): "Anima/姿势/正常/战斗与动态",
    (SOURCE_REGULAR, "多人互动"): "Anima/姿势/正常/多人互动",
    (SOURCE_REGULAR, "室外"): "Anima/背景/正常/室外与自然",
    (SOURCE_REGULAR, "室内"): "Anima/背景/正常/室内",
    (SOURCE_REGULAR, "恐怖扭曲"): "Anima/背景/正常/恐怖扭曲",
    (SOURCE_REGULAR, "幻想童话"): "Anima/背景/正常/幻想童话",
    (SOURCE_REGULAR, "单纯场景"): "Anima/背景/正常/单纯场景",
    (SOURCE_REGULAR, "节日庆典"): "Anima/背景/正常/节庆与舞台",
    (SOURCE_ADULT_UPPER, "正身位"): "Anima/姿势/R18/体位/正身位",
    (SOURCE_ADULT_UPPER, "站立位"): "Anima/姿势/R18/体位/站立位",
    (SOURCE_ADULT_UPPER, "坐身位"): "Anima/姿势/R18/体位/坐身位",
    (SOURCE_ADULT_UPPER, "后入/背后位"): "Anima/姿势/R18/体位/后入与背后位",
    (SOURCE_ADULT_UPPER, "正/逆火车便当"): "Anima/姿势/R18/体位/火车便当",
    (SOURCE_ADULT_UPPER, "种付位"): "Anima/姿势/R18/体位/种付位",
    (SOURCE_ADULT_UPPER, "骑乘位"): "Anima/姿势/R18/体位/骑乘位",
    (SOURCE_ADULT_UPPER, "睡奸"): "Anima/姿势/R18/双人互动/睡眠侵犯",
    (SOURCE_ADULT_UPPER, "足交"): "Anima/姿势/R18/非插入互动/足交",
    (SOURCE_ADULT_UPPER, "口交（类口交/颜射）"): "Anima/姿势/R18/非插入互动/口交与颜射",
    (SOURCE_ADULT_UPPER, "素股"): "Anima/姿势/R18/非插入互动/身体摩擦",
    (SOURCE_ADULT_UPPER, "手交"): "Anima/姿势/R18/非插入互动/手交",
    (SOURCE_ADULT_UPPER, "乳交"): "Anima/姿势/R18/非插入互动/乳交",
    (SOURCE_ADULT_UPPER, "隐秘处展示/自拍/直播"): "Anima/姿势/R18/单人表现/隐秘展示与直播",
    (SOURCE_ADULT_UPPER, "自慰"): "Anima/姿势/R18/单人表现/自慰",
    (SOURCE_ADULT_UPPER, "诱惑"): "Anima/姿势/R18/单人表现/诱惑",
    (SOURCE_ADULT_UPPER, "暴露/露出"): "Anima/姿势/R18/单人表现/暴露",
    (SOURCE_ADULT_UPPER, "调戏猥亵"): "Anima/姿势/R18/双人互动/调戏与猥亵",
    (SOURCE_ADULT_UPPER, "胁迫强制"): "Anima/姿势/R18/双人互动/胁迫与强制",
    (SOURCE_ADULT_UPPER, "偷窥/直视"): "Anima/姿势/R18/双人互动/偷窥与直视",
    (SOURCE_ADULT_UPPER, "事后"): "Anima/姿势/R18/双人互动/事后",
    (SOURCE_ADULT_UPPER, "百合"): "Anima/姿势/R18/多人互动/百合",
    (SOURCE_ADULT_UPPER, "协作侍奉"): "Anima/姿势/R18/多人互动/协作侍奉",
    (SOURCE_ADULT_UPPER, "双飞/多飞"): "Anima/姿势/R18/多人互动/双飞与多人",
    (SOURCE_ADULT_UPPER, "攻守反转特辑（四爱/男m）"): "Anima/姿势/R18/双人互动/攻守反转",
    (SOURCE_ADULT_UPPER, "胸/腹部"): "Anima/姿势/R18/身体构图/胸腹部",
    (SOURCE_ADULT_UPPER, "裙底/小穴/臀部"): "Anima/姿势/R18/身体构图/臀裆部",
    (SOURCE_ADULT_UPPER, "脚/足底"): "Anima/姿势/R18/身体构图/腿足",
    (SOURCE_ADULT_UPPER, "腿/下半身"): "Anima/姿势/R18/身体构图/腿足",
    (SOURCE_ADULT_UPPER, "背部/背身"): "Anima/姿势/R18/身体构图/背身",
    (SOURCE_ADULT_UPPER, "NTR"): "Anima/姿势/R18/情境/NTR",
    (SOURCE_ADULT_UPPER, "催眠"): "Anima/姿势/R18/情境/催眠",
    (SOURCE_ADULT_UPPER, "场地"): "Anima/背景/R18/成人场所",
    (SOURCE_ADULT_LOWER, "泳装"): "Anima/服装/R18/内衣与泳装/泳装",
    (SOURCE_ADULT_LOWER, "内衣"): "Anima/服装/R18/内衣与泳装/内衣",
    (SOURCE_ADULT_LOWER, "睡衣"): "Anima/服装/R18/内衣与泳装/睡衣",
    (SOURCE_ADULT_LOWER, "日常改造"): "Anima/服装/R18/暴露与改造/日常改造",
    (SOURCE_ADULT_LOWER, "职业改造"): "Anima/服装/R18/暴露与改造/职业改造",
    (SOURCE_ADULT_LOWER, "裸体遮盖"): "Anima/服装/R18/暴露与改造/裸体遮盖",
    (SOURCE_ADULT_LOWER, "幻想改造"): "Anima/服装/R18/暴露与改造/幻想改造",
    (SOURCE_ADULT_LOWER, "兔女郎"): "Anima/服装/正常/幻想与主题/兔女郎",
    (SOURCE_ADULT_LOWER, "赛车女郎"): "Anima/服装/正常/制服与职业/运动服",
    (SOURCE_ADULT_LOWER, "连体胶衣/胶质服装"): "Anima/服装/R18/材质与紧身/连体胶衣",
    (SOURCE_ADULT_LOWER, "高腰紧身衣"): "Anima/服装/R18/材质与紧身/高腰紧身衣",
    (SOURCE_ADULT_LOWER, "舞娘"): "Anima/服装/正常/幻想与主题/舞娘",
    (SOURCE_ADULT_LOWER, "魔法少女"): "Anima/服装/正常/幻想与主题/魔法少女",
    (SOURCE_ADULT_LOWER, "恶堕之后"): "Anima/服装/R18/暴露与改造/恶堕服装",
    (SOURCE_ADULT_LOWER, "cosplay"): "Anima/服装/R18/Cosplay与角色服装",
    (SOURCE_ADULT_LOWER, "过激"): "Anima/姿势/R18/重口/暴力/暴虐与过激",
    (SOURCE_ADULT_LOWER, "多p/轮奸"): "Anima/姿势/R18/多人互动/多人强制",
    (SOURCE_ADULT_LOWER, "RBQ"): "Anima/姿势/R18/拘束/肉便器",
    (SOURCE_ADULT_LOWER, "兽交"): "Anima/姿势/R18/重口/异种互动/兽类",
    (SOURCE_ADULT_LOWER, "狗"): "Anima/姿势/R18/重口/异种互动/兽类",
    (SOURCE_ADULT_LOWER, "虫"): "Anima/姿势/R18/重口/异种互动/昆虫",
    (SOURCE_ADULT_LOWER, "马"): "Anima/姿势/R18/重口/异种互动/兽类",
    (SOURCE_ADULT_LOWER, "触手"): "Anima/姿势/R18/重口/异种互动/触手",
    (SOURCE_ADULT_LOWER, "史莱姆"): "Anima/姿势/R18/重口/异种互动/史莱姆",
    (SOURCE_ADULT_LOWER, "兽人"): "Anima/姿势/R18/重口/异种互动/人形魔物",
    (SOURCE_ADULT_LOWER, "哥布林"): "Anima/姿势/R18/重口/异种互动/人形魔物",
    (SOURCE_ADULT_LOWER, "小精灵/小人"): "Anima/姿势/R18/重口/异种互动/人形魔物",
    (SOURCE_ADULT_LOWER, "捆绑姿势"): "Anima/姿势/R18/拘束/捆绑姿势",
    (SOURCE_ADULT_LOWER, "捆绑用具"): "Anima/姿势/R18/拘束/捆绑用具",
    (SOURCE_ADULT_LOWER, "捆绑位置"): "Anima/姿势/R18/拘束/捆绑位置",
    (SOURCE_ADULT_LOWER, "监禁放置"): "Anima/姿势/R18/拘束/监禁放置",
    (SOURCE_ADULT_LOWER, "拘束凌辱"): "Anima/姿势/R18/拘束/拘束凌辱",
    (SOURCE_ADULT_LOWER, "另类捆绑"): "Anima/姿势/R18/拘束/捆绑姿势",
    (SOURCE_ADULT_LOWER, "节日献礼"): "Anima/姿势/R18/情境/节庆献礼",
    (SOURCE_ADULT_LOWER, "机械"): "Anima/姿势/R18/重口/机械",
    (SOURCE_ADULT_LOWER, "杀害"): "Anima/姿势/R18/重口/暴力/杀害",
    (SOURCE_ADULT_LOWER, "刑罚"): "Anima/姿势/R18/重口/暴力/暴虐与过激",
    (SOURCE_ADULT_LOWER, "暴虐"): "Anima/姿势/R18/重口/暴力/暴虐与过激",
    (SOURCE_ADULT_LOWER, "截肢/人棍"): "Anima/姿势/R18/重口/暴力/截肢与人棍",
    (SOURCE_ADULT_LOWER, "秀色"): "Anima/姿势/R18/重口/暴力/食人",
    (SOURCE_ADULT_LOWER, "血肉内脏"): "Anima/姿势/R18/重口/暴力/血肉内脏",
    (SOURCE_ADULT_LOWER, "排泄物"): "Anima/姿势/R18/重口/排泄物",
    (SOURCE_ADULT_LOWER, "扶她"): "Anima/角色/R18/成人身份/扶她",
    (SOURCE_ADULT_LOWER, "伪娘/男娘"): "Anima/角色/R18/成人身份/伪娘与男娘",
    (SOURCE_ADULT_LOWER, "人外"): "Anima/角色/R18/成人种族/魔物娘与人外",
}


SECTION_ROOT_HINTS = {
    (SOURCE_REGULAR, "人物形象"): "character",
    (SOURCE_REGULAR, "人物环境"): "background",
    (SOURCE_REGULAR, "表情包/搞怪"): "pose",
    (SOURCE_ADULT_UPPER, "性交场景"): "pose",
    (SOURCE_ADULT_UPPER, "场地"): "background",
    (SOURCE_ADULT_UPPER, "futa特辑"): "character",
    (SOURCE_ADULT_UPPER, "伪娘/男娘特辑"): "character",
    (SOURCE_ADULT_LOWER, "服饰"): "clothing",
    (SOURCE_ADULT_LOWER, "非原创人物"): "character",
    (SOURCE_ADULT_LOWER, "魔物娘"): "character",
    (SOURCE_ADULT_LOWER, "其他异种"): "character",
    (SOURCE_ADULT_LOWER, "触手"): "pose",
    (SOURCE_ADULT_LOWER, "史莱姆"): "pose",
    (SOURCE_ADULT_LOWER, "兽人"): "pose",
    (SOURCE_ADULT_LOWER, "哥布林"): "pose",
}


EXCLUDED_SECTIONS = {
    (SOURCE_REGULAR, "各种风格"),
    (SOURCE_REGULAR, "质量词"),
    (SOURCE_REGULAR, "视角与打光"),
}


SAFETY_REVIEW_SECTIONS = {
    (SOURCE_ADULT_UPPER, "大车小孩特辑"),
}


SAFETY_REVIEW_CATEGORIES = {
    "Anima/姿势/R18/大车小孩特辑",
}


LEGACY_TARGETS = {
    "Anima/角色/正常/单机角色": "Anima/角色/正常/作品角色/单机角色",
    "Anima/角色/正常/网络角色": "Anima/角色/正常/作品角色/网络角色",
    "Anima/角色/正常/端游角色": "Anima/角色/正常/作品角色/端游角色",
    "Anima/角色/正常/动漫角色": "Anima/角色/正常/作品角色/动漫角色",
    "Anima/角色/正常/明日方舟角色": "Anima/角色/正常/作品角色/手游角色",
    "Anima/角色/正常/其他手游角色": "Anima/角色/正常/作品角色/手游角色",
    "Anima/角色/正常/文化作品角色": "Anima/角色/正常/作品角色/文化作品角色",
    "Anima/角色/正常/类人种族": "Anima/角色/正常/种族与形态/类人种族",
    "Anima/角色/正常/动物娘化": "Anima/角色/正常/种族与形态/动物娘化",
    "Anima/角色/正常/人工造物": "Anima/角色/正常/种族与形态/人工造物",
    "Anima/角色/正常/人物转化": "Anima/角色/正常/外观与转化/人物转化",
    "Anima/服装/正常/服装组件": "Anima/服装/正常/组件与配饰",
    "Anima/服装/正常/日常服": "Anima/服装/正常/日常与季节/日常服",
    "Anima/服装/正常/夏装": "Anima/服装/正常/日常与季节/夏装",
    "Anima/服装/正常/冬装": "Anima/服装/正常/日常与季节/冬装",
    "Anima/服装/正常/校服": "Anima/服装/正常/制服与职业/校服",
    "Anima/服装/正常/军装": "Anima/服装/正常/制服与职业/军装",
    "Anima/服装/正常/中国": "Anima/服装/正常/地域与时代/中国",
    "Anima/服装/正常/日本": "Anima/服装/正常/地域与时代/日本",
    "Anima/服装/正常/中东": "Anima/服装/正常/地域与时代/中东",
    "Anima/服装/正常/中近世纪": "Anima/服装/正常/地域与时代/中近世纪",
    "Anima/服装/正常/游戏服装": "Anima/服装/正常/幻想与主题/游戏服装",
    "Anima/服装/正常/另类服装": "Anima/服装/正常/幻想与主题/特殊服装",
    "Anima/服装/R18/职业改造": "Anima/服装/R18/暴露与改造/职业改造",
    "Anima/服装/R18/幻想改造": "Anima/服装/R18/暴露与改造/幻想改造",
    "Anima/服装/R18/连体胶衣胶质服装": "Anima/服装/R18/材质与紧身/连体胶衣",
    "Anima/姿势/R18/露出": "Anima/姿势/R18/单人表现/暴露",
    "Anima/姿势/R18/暴露露出": "Anima/姿势/R18/单人表现/暴露",
    "Anima/姿势/R18/口交（类口交颜射）": "Anima/姿势/R18/非插入互动/口交与颜射",
    "Anima/姿势/R18/口交（类口交/颜射）": "Anima/姿势/R18/非插入互动/口交与颜射",
    "Anima/角色/R18/另类捆绑": "Anima/姿势/R18/拘束/捆绑姿势",
    "Anima/角色/R18/重口/刑罚": "Anima/姿势/R18/重口/暴力/暴虐与过激",
    "Anima/姿势/R18/睡奸": "Anima/姿势/R18/双人互动/睡眠侵犯",
    "Anima/姿势/R18/攻守反转特辑（四爱/男m）": "Anima/姿势/R18/双人互动/攻守反转",
    "Anima/姿势/R18/多p轮奸": "Anima/姿势/R18/多人互动/多人强制",
    "Anima/姿势/R18/RBQ": "Anima/姿势/R18/拘束/肉便器",
    "Anima/姿势/R18/重口/虫": "Anima/姿势/R18/重口/异种互动/昆虫",
    "Anima/姿势/R18/重口/狗": "Anima/姿势/R18/重口/异种互动/兽类",
    "Anima/姿势/R18/重口/马": "Anima/姿势/R18/重口/异种互动/兽类",
    "Anima/姿势/R18/重口/过激": "Anima/姿势/R18/重口/暴力/暴虐与过激",
    "Anima/姿势/R18/重口/暴虐": "Anima/姿势/R18/重口/暴力/暴虐与过激",
    "Anima/姿势/R18/重口/杀害": "Anima/姿势/R18/重口/暴力/杀害",
    "Anima/姿势/R18/重口/截肢人棍": "Anima/姿势/R18/重口/暴力/截肢与人棍",
    "Anima/姿势/R18/重口/秀色": "Anima/姿势/R18/重口/暴力/食人",
}


MINOR_TERMS = (
    "loli", "lolicon", "shota", "shotacon", "child", "children", "underage",
    "little girl", "little boy", "elementary school", "middle school student",
    "萝莉", "正太", "幼女", "幼童", "小孩", "小学生", "未成年", "儿童",
)
ADULT_TERMS = (
    "nsfw", "sex", "nude", "naked", "nipples", "pussy", "penis", "cum",
    "orgasm", "masturbation", "blowjob", "rape", "vaginal", "anal", "erotic",
    "性交", "自慰", "裸体", "强奸", "轮奸", "口交", "足交", "乳交",
)


ROOT_ALIAS_TERMS = {
    "character": (
        "角色", "人设", "种族", "精灵", "魔物", "兽人", "机器人", "人偶", "改造人",
        "娘化", "龙娘", "猫娘", "狐娘", "史莱姆娘", "人工生命", "cyborg", "android",
    ),
    "clothing": (
        "服装", "服饰", "穿搭", "套装", "制服", "校服", "军装", "泳装", "内衣", "睡衣",
        "裙", "衣", "衫", "裤", "袜", "鞋", "靴", "帽", "旗袍", "和服", "汉服", "胶衣",
        "兔女郎", "女仆装", "护士服", "cosplay", "outfit", "costume", "uniform",
    ),
    "pose": (
        "姿势", "动作", "表情", "互动", "战斗", "站立", "坐姿", "躺", "跪", "拥抱", "亲吻",
        "展示", "自拍", "直播", "体位", "骑乘", "后入", "背后位", "自慰", "诱惑", "捆绑", "拘束",
        "pose", "position", "interaction", "expression",
    ),
    "background": (
        "背景", "场景", "环境", "室内", "室外", "房间", "卧室", "教室", "街道", "城市", "森林",
        "海滩", "地牢", "舞台", "太空", "天空", "夜景", "background", "interior", "landscape",
    ),
}


ROOT_PROMPT_TERMS = {
    "character": (
        "character", "original character", "monster girl", "robot girl", "android", "cyborg",
        "doll joints", "robot joints", "mechanical body", "slime girl", "dragon girl", "cat girl",
        "fox girl", "dog girl", "bunny girl", "mermaid", "elf", "dark elf", "demon girl",
        "angel", "furry female", "centaur", "harpy", "goblin girl", "orc girl",
    ),
    "clothing": (
        "dress", "skirt", "shirt", "blouse", "jacket", "coat", "sweater", "hoodie", "pants",
        "shorts", "uniform", "kimono", "yukata", "hanfu", "cheongsam", "qipao", "swimsuit",
        "bikini", "lingerie", "panties", "bra", "thighhighs", "pantyhose", "gloves", "boots",
        "shoes", "hat", "veil", "cape", "armor", "apron", "leotard", "bodysuit", "latex",
        "school uniform", "military uniform", "maid outfit", "nurse uniform", "costume", "cosplay",
    ),
    "pose": (
        "standing", "sitting", "lying", "kneeling", "squatting", "all fours", "arms up",
        "arms behind back", "bent over", "leaning forward", "arched back", "leg up", "spread legs",
        "looking back", "looking at another", "holding hands", "hug", "kissing", "fighting",
        "dynamic pose", "running", "jumping", "sex", "vaginal", "anal", "oral", "blowjob",
        "masturbation", "handjob", "footjob", "paizuri", "bondage", "restrained", "bound",
        "sex from behind", "cowgirl position", "missionary", "gangbang", "group sex",
    ),
    "background": (
        "background", "indoors", "outdoors", "interior", "bedroom", "classroom", "bathroom",
        "kitchen", "restaurant", "street", "city", "forest", "mountain", "beach", "ocean",
        "river", "garden", "church", "castle", "dungeon", "spaceship", "space station", "sky",
        "night sky", "sunset", "rain", "snow", "stage", "festival", "landscape", "scenery",
    ),
}


STYLE_TERMS = (
    "artist:", "style", "artstyle", "masterpiece", "best quality", "very aesthetic",
    "score_9", "score 9", "anime coloring", "oil painting", "watercolor", "pixel art",
    "sketch", "lineart", "monochrome", "画风", "风格", "质量词", "负面词", "画师",
)


LEAF_RULES = (
    ("Anima/角色/正常/种族与形态/人工造物", ("机器人", "人偶", "机械少女", "android", "cyborg", "robot", "doll joints", "robot joints")),
    ("Anima/角色/正常/种族与形态/动物娘化", ("猫娘", "狐娘", "兔娘", "龙娘", "兽娘", "cat girl", "fox girl", "bunny girl", "dragon girl", "furry female")),
    ("Anima/角色/正常/种族与形态/魔物与人外", ("魔物", "人外", "史莱姆娘", "触手少女", "monster girl", "slime girl", "mermaid", "centaur", "harpy", "goblin girl", "orc girl")),
    ("Anima/角色/正常/种族与形态/类人种族", ("精灵", "天使", "恶魔", "elf", "dark elf", "angel", "demon girl")),
    ("Anima/角色/正常/外观与转化/人物转化", ("人物转化", "娘化", "性转", "变身", "transformation", "genderbend")),
    ("Anima/角色/R18/成人身份/扶她", ("扶她", "futa", "futanari")),
    ("Anima/角色/R18/成人身份/伪娘与男娘", ("伪娘", "男娘", "femboy", "otoko no ko")),
    ("Anima/服装/R18/Cosplay与角色服装", ("cosplay", "角色服装", "皮肤服装")),
    ("Anima/服装/R18/材质与紧身/连体胶衣", ("胶衣", "乳胶", "latex bodysuit", "rubber suit", "latex suit")),
    ("Anima/服装/R18/内衣与泳装/泳装", ("泳装", "泳衣", "swimsuit", "bikini")),
    ("Anima/服装/R18/内衣与泳装/内衣", ("内衣", "情趣内衣", "lingerie", "bra and panties", "underwear")),
    ("Anima/服装/R18/内衣与泳装/睡衣", ("睡衣", "睡裙", "pajamas", "nightgown")),
    ("Anima/服装/正常/制服与职业/校服", ("校服", "school uniform", "serafuku")),
    ("Anima/服装/正常/制服与职业/军装", ("军装", "military uniform", "military jacket")),
    ("Anima/服装/正常/制服与职业/职业制服", ("职业制服", "护士服", "护士制服", "女仆装", "厨师服", "警服", "nurse uniform", "maid outfit", "police uniform", "chef uniform")),
    ("Anima/服装/正常/地域与时代/中国", ("旗袍", "汉服", "china dress", "cheongsam", "hanfu")),
    ("Anima/服装/正常/地域与时代/日本", ("和服", "浴衣", "巫女服", "kimono", "yukata", "miko clothes")),
    ("Anima/服装/正常/幻想与主题/兔女郎", ("兔女郎", "playboy bunny", "bunnysuit")),
    ("Anima/服装/正常/组件与配饰", ("配饰", "服装组件", "accessories", "detached sleeves", "choker", "necklace")),
    ("Anima/姿势/正常/战斗与动态", ("战斗", "攻击", "挥剑", "fighting", "battle", "holding sword", "dynamic pose")),
    ("Anima/姿势/正常/多人互动", ("多人互动", "牵手", "拥抱", "holding hands", "hug", "multiple girls")),
    ("Anima/姿势/正常/表情与情绪", ("表情", "哭泣", "害羞", "愤怒", "smile", "crying", "embarrassed", "angry")),
    ("Anima/姿势/正常/单人动作", ("单人动作", "站立", "坐姿", "跪姿", "standing", "sitting", "kneeling", "squatting")),
    ("Anima/姿势/R18/体位/后入与背后位", ("后入", "背后位", "sex from behind", "doggystyle")),
    ("Anima/姿势/R18/体位/骑乘位", ("骑乘位", "cowgirl position", "reverse cowgirl")),
    ("Anima/姿势/R18/体位/正身位", ("正身位", "missionary", "mating press")),
    ("Anima/姿势/R18/体位/站立位", ("站立位", "standing sex")),
    ("Anima/姿势/R18/非插入互动/口交与颜射", ("口交", "颜射", "blowjob", "oral", "fellatio")),
    ("Anima/姿势/R18/非插入互动/手交", ("手交", "handjob")),
    ("Anima/姿势/R18/非插入互动/足交", ("足交", "footjob")),
    ("Anima/姿势/R18/非插入互动/乳交", ("乳交", "paizuri")),
    ("Anima/姿势/R18/单人表现/自慰", ("自慰", "masturbation", "fingering self")),
    ("Anima/姿势/R18/单人表现/诱惑", ("诱惑", "seductive pose", "seductive smile")),
    ("Anima/姿势/R18/拘束/捆绑姿势", ("捆绑", "bondage", "bound", "restrained")),
    ("Anima/姿势/R18/情境/NTR", ("ntr", "netorare")),
    ("Anima/姿势/R18/情境/催眠", ("催眠", "hypnosis", "mind control")),
    ("Anima/姿势/R18/多人互动/百合", ("百合", "yuri")),
    ("Anima/姿势/R18/多人互动/双飞与多人", ("双飞", "多人", "threesome", "gangbang", "group sex")),
    ("Anima/背景/正常/室内", ("室内", "卧室", "教室", "indoors", "bedroom", "classroom", "interior")),
    ("Anima/背景/正常/室外与自然", ("室外", "森林", "海滩", "outdoors", "forest", "beach", "mountain", "landscape")),
    ("Anima/背景/正常/城市与日常", ("城市街道", "街景", "都市", "city street", "cityscape", "urban street")),
    ("Anima/背景/正常/未来科幻", ("科幻场景", "太空站", "spaceship", "space station", "cyberpunk city")),
    ("Anima/背景/正常/恐怖扭曲", ("恐怖场景", "horror", "haunted", "blood-filled room")),
    ("Anima/背景/R18/拘束与监禁场所", ("监禁场所", "牢房", "prison cell", "dungeon room", "bondage room")),
)


@dataclass
class ClassificationResult:
    status: str
    root: str
    target: str
    confidence: float
    margin: float
    reasons: list
    root_scores: dict
    reference_source: str = ""
    reference_section: str = ""

    def to_dict(self):
        return asdict(self)


def load_contract(path=None):
    contract_path = Path(path) if path else (
        Path(__file__).resolve().parents[2]
        / "comfyui-anima-tools"
        / "data"
        / "weilin_anima_classification_contract.json"
    )
    return json.loads(contract_path.read_text(encoding="utf-8"))


def root_for_target(target):
    for prefix, root in ROOT_BY_PREFIX.items():
        if str(target or "").startswith(prefix):
            return root
    return ""


def normalize_text(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return text.replace("_", " ").replace("／", "/")


@lru_cache(maxsize=None)
def _compiled_term(term):
    normalized_term = normalize_text(term).strip()
    if not normalized_term:
        return "", None
    if re.fullmatch(r"[a-z0-9 +:/.-]+", normalized_term):
        pattern = r"(?<![a-z0-9])" + re.escape(normalized_term) + r"(?![a-z0-9])"
        return normalized_term, re.compile(pattern)
    return normalized_term, None


def _term_present(text, term):
    normalized_term, pattern = _compiled_term(term)
    if not normalized_term:
        return False
    if pattern is not None:
        return pattern.search(text) is not None
    return normalized_term in text


def _matched_terms(text, terms, limit=12):
    matches = []
    for term in terms:
        if _term_present(text, term):
            matches.append(term)
            if len(matches) >= limit:
                break
    return matches


def _root_score_target(scores, target, points):
    root = root_for_target(target)
    if root:
        scores[root] += points
    return root


def classify_prompt(
    prompt,
    current_category="",
    reference_source="",
    reference_section="",
    contract=None,
):
    contract = contract or load_contract()
    alias = normalize_text(prompt.get("alias"))
    prompt_text = normalize_text(prompt.get("prompt"))
    combined = f"{alias}\n{prompt_text}"
    reference_key = (str(reference_source or ""), str(reference_section or ""))

    minor_hits = _matched_terms(combined, MINOR_TERMS, limit=5)
    adult_hits = _matched_terms(combined, ADULT_TERMS, limit=5)
    forced_safety_review = (
        reference_key in SAFETY_REVIEW_SECTIONS
        or str(current_category or "") in SAFETY_REVIEW_CATEGORIES
    )
    if forced_safety_review or (minor_hits and adult_hits):
        target = contract["non_anima_contracts"]["safety_quarantine_category"]
        reasons = []
        if forced_safety_review:
            reasons.append("整章涉及年龄与成人内容边界，禁止自动进入 Anima")
        if minor_hits:
            reasons.append("年龄风险词: " + ", ".join(minor_hits))
        if adult_hits:
            reasons.append("成人内容词: " + ", ".join(adult_hits))
        return ClassificationResult(
            status="quarantine",
            root="",
            target=target,
            confidence=0.99,
            margin=1.0,
            reasons=reasons,
            root_scores={},
            reference_source=reference_source,
            reference_section=reference_section,
        )

    scores = defaultdict(float)
    leaf_scores = defaultdict(float)
    reasons = []

    section_target = SECTION_TARGETS.get(reference_key)
    if section_target:
        root = _root_score_target(scores, section_target, 5.5)
        leaf_scores[section_target] += 6.0
        reasons.append(f"参考章节支持 {root}: {reference_section}")
    section_root = SECTION_ROOT_HINTS.get(reference_key)
    if section_root:
        scores[section_root] += 1.8
        reasons.append(f"混合章节仅作弱提示: {reference_section}")

    legacy_target = LEGACY_TARGETS.get(str(current_category or ""))
    if legacy_target:
        root = _root_score_target(scores, legacy_target, 0.8)
        leaf_scores[legacy_target] += 0.8
        reasons.append(f"现分类仅作弱提示: {root}")
    else:
        current_root = root_for_target(str(current_category or "") + "/")
        if current_root:
            scores[current_root] += 0.35

    alias_root_hit_count = 0
    for root, terms in ROOT_ALIAS_TERMS.items():
        hits = _matched_terms(alias, terms, limit=8)
        if hits:
            alias_root_hit_count += len(hits)
            scores[root] += min(8.0, 3.0 + 1.25 * len(hits))
            reasons.append(f"标题命中 {root}: " + ", ".join(hits[:4]))

    for root, terms in ROOT_PROMPT_TERMS.items():
        hits = _matched_terms(prompt_text, terms, limit=16)
        if hits:
            scores[root] += min(8.0, 0.9 * len(hits))
            reasons.append(f"tags 命中 {root}: " + ", ".join(hits[:5]))

    for target, terms in LEAF_RULES:
        alias_hits = _matched_terms(alias, terms, limit=4)
        prompt_hits = _matched_terms(prompt_text, terms, limit=6)
        if not alias_hits and not prompt_hits:
            continue
        leaf_points = 3.6 * len(alias_hits) + 1.25 * len(prompt_hits)
        leaf_scores[target] += min(8.0, leaf_points)
        _root_score_target(scores, target, min(4.0, leaf_points * 0.45))

    style_hits = _matched_terms(combined, STYLE_TERMS, limit=8)
    style_alias_hits = _matched_terms(alias, STYLE_TERMS, limit=4)
    pure_excluded_section = reference_key in EXCLUDED_SECTIONS

    ordered_roots = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    top_root, top_score = ordered_roots[0] if ordered_roots else ("", 0.0)
    second_score = ordered_roots[1][1] if len(ordered_roots) > 1 else 0.0
    margin = (top_score - second_score) / max(top_score, 1.0)

    heuristic_style_only = (
        len(style_hits) >= 2
        and bool(style_alias_hits)
        and alias_root_hit_count == 0
        and not section_target
        and not section_root
        and top_score < 3.0
    )
    if pure_excluded_section or heuristic_style_only:
        target = contract["non_anima_contracts"]["excluded_category"]
        exclusion_reason = "参考章节不属于四类" if pure_excluded_section else "纯画风/质量/镜头特征"
        return ClassificationResult(
            status="excluded",
            root="",
            target=target,
            confidence=0.93 if pure_excluded_section else 0.82,
            margin=margin,
            reasons=[exclusion_reason] + (["命中: " + ", ".join(style_hits)] if style_hits else []),
            root_scores={key: round(value, 3) for key, value in ordered_roots},
            reference_source=reference_source,
            reference_section=reference_section,
        )

    candidate_leaves = [
        (target, score)
        for target, score in leaf_scores.items()
        if root_for_target(target) == top_root
    ]
    candidate_leaves.sort(key=lambda item: (-item[1], item[0]))
    target, leaf_score = candidate_leaves[0] if candidate_leaves else ("", 0.0)

    confidence = min(
        0.99,
        max(0.0, 0.46 + 0.035 * top_score + 0.24 * max(0.0, margin)),
    )
    thresholds = contract["decision_policy"]
    auto = (
        bool(target)
        and top_score >= 5.5
        and leaf_score >= 3.0
        and confidence >= float(thresholds["auto_apply_min_confidence"])
        and margin >= float(thresholds["auto_apply_min_margin"])
    )
    status = "auto" if auto else "review"
    if not target:
        target = contract["non_anima_contracts"]["review_categories"][2]
    if top_root in {"character", "clothing"} and len(ordered_roots) > 1:
        competitor = ordered_roots[1][0]
        if {top_root, competitor} == {"character", "clothing"} and margin < 0.28:
            status = "review"
            target = contract["non_anima_contracts"]["review_categories"][0]
            reasons.append("角色与服装证据接近，禁止自动决定")

    return ClassificationResult(
        status=status,
        root=top_root,
        target=target,
        confidence=round(confidence, 4),
        margin=round(margin, 4),
        reasons=reasons[:8],
        root_scores={key: round(value, 3) for key, value in ordered_roots},
        reference_source=reference_source,
        reference_section=reference_section,
    )
