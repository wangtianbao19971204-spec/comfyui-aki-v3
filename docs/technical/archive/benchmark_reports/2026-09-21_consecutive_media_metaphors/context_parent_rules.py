"""Batch 25 rules: explicit fantasy/sci-fi scenes, work-character titles and metaphor guards from round 111."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('envprops',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_environment_props/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)


def _merged_support():
    chain=[];node=previous
    while node is not None:
        chain.append(node);node=getattr(node,'previous',None)
    merged={}
    for module in reversed(chain):
        merged.update(getattr(module,'SUPPORT',None) or {})
    # 服装材质与剪裁此前没有独立支持词表；本批按“衣料/裁剪”正例判断，
    # 手套、饰品与蚕茧材质不计入该父类。
    merged['服装材质与剪裁']=r"\b(?:lace|leather|latex|rubber clothes?|silk|satin|denim|see-through|transparent clothes?|frills|ruffles|sleeves?|tight clothes|skin-tight|patchwork|fabric|garments?|dress|gown|shirt|blouse|skirt|corset|bodysuit|robe|jacket|coat|kimono|hanfu|qipao|vest)\b|布料|面料|裁剪|剪裁"
    return merged


SUPPORT=_merged_support()
# 幻想/科幻环境：明确的宇宙锻造与未来科幻场景，必须带环境名词，
# 以免把 futuristic sci-fi rifle 这类器械也当成场景（影响审核第 2 条）。
SCENE=r"\bcosmic forge\b|(?:futuristic |the )?(?:sci-?fi|science fiction) (?:space|environment|setting|scene|world|interior|city|cityscape|landscape|realm|architecture|structure|corridor|room)s?\b"
# 作品角色：明确的作品与角色专名（同库 fate/grand order 记录绝大多数已挂作品角色）。
CHARACTER=r"\bmash kyrielight\b|\bfate(?:/| )grand order\b"
# 随身配饰：ear rings / nipple rings 是明确的耳饰与乳环，空格写法需归一化。
ACCESSORY=r"\bear ?rings?\b|\bnipple rings?\b"
# 建筑与设施：实际木地板与木墙是建筑构件；家具门板、道具木料不算
# （“木门”在既有词表里同时靠近生活用品，本批只收地板与墙面证据）。
STRUCTURE=r"\b(?:wood(?:en)?|hard ?wood|parquet)\s+(?:floors?|flooring|walls?)\b"
# 色彩与调色：整体色调描述，必须带颜色词或调色词，避免 overall skin/muscle tone 误挂。
PALETTE=r"\b(?:overall|predominantly|mostly)\b[^.;!?]{0,40}\b(?:colou?rs?|palette)\b|\b(?:overall|predominantly|mostly)\b[^.;!?]{0,40}\b(?:warm|cool|cold|neutral|muted|vivid|vibrant|pastel|monochrome|sepia)\b[^.;!?]{0,25}\btones?\b"
BAD={
    # 第 111 轮 #12：the painting 是泛称画面；第 111 轮 #13：墙上画是画中画，不证明整幅媒介。
    '绘画与插画':[r'\b(?:side|part|half|portion|edge|corner|middle) of the painting\b',r'\bpainting in (?:a |the )?(?:[a-z-]+ ){0,3}frame\b'],
    # 第 111 轮 #13：modern city woman 是人物描写，不是城市街道景物。
    '城市与街道':[r'\bcity (?:woman|man|girl|boy|dwellers?|people)\b'],
    # 第 111 轮 #16：mirror-like puddles 与 mirror water 是水面比喻，不是实体镜子。
    '家具与生活用品':[r'\bmirror-like\b',r'\bmirror water\b'],
    # 第 111 轮 #11：penis juice 是体液；第 111 轮 #16：hanging like dead fruits 是比喻。
    '食物与饮料':[r'\bpenis juice\b',r'\blike dead fruits?\b'],
    # 第 111 轮 #16：silk cocoons 是蚕茧材质，不是衣料。
    '服装材质与剪裁':[r'\bsilk cocoons?\b'],
}


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))


def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive=_positive(body,refinements)
    for parent,patterns in BAD.items():
        if parent not in parents:continue
        remaining=positive;cues=[]
        for pattern in patterns:
            cues.extend(match.group() for match in re.finditer(pattern,remaining,re.I))
            remaining=re.sub(pattern,' ',remaining,flags=re.I)
        if cues and not re.search(SUPPORT[parent],remaining,re.I):
            result[parent]={'false_cues':cues,'reason':'Title, simile or depicted-object phrase; no independent parent evidence.'}
    return result


def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    def want(parent,pattern):
        if parent in parents or parent in found:return
        if re.search(pattern,positive,re.I):found.append(parent)
    want('幻想与科幻环境',SCENE)
    want('作品角色',CHARACTER)
    want('首饰与随身配饰',ACCESSORY)
    want('建筑与设施',STRUCTURE)
    want('色彩与调色',PALETTE)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
