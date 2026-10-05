"""Batch 46 rules: backlog wave 1 (manual self-touch, sign text, stitched mouth, through-fabric nipples)."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('phrase_object_guard',Path(__file__).resolve().parent.parent/'2026-09-23_consecutive_phrase_object_guard/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT}

# 手伸进自身生殖部位，或伸进衣物后同句继续明确刺激，才补自慰。
# 多人/伴侣施事语境按精度优先排除，避免把他人 fingering 当成 self-touch。
SELF_TOUCH=(r"\b(?:hand|fingers?)\b[^.;!?]{0,40}\b(?:deep(?:ly)? |buried |pushed |plunged )?inside\b"
    r"[^.;!?]{0,35}\b(?:pussy|vagina)\b"
    r"|\b(?:hand|fingers?)\b[^.;!?]{0,40}\b(?:deep(?:ly)? )?inside\b[^.;!?]{0,30}"
    r"\b(?:waistband|panties|shorts|leggings)\b[^.;!?]{0,90}"
    r"\b(?:slick with lube|working (?:her|his|their) (?:pussy|vagina|clit)|"
    r"rubb?\w* (?:her|his|their) (?:pussy|vagina|clit)|fingering (?:herself|himself|themself))\b")
PARTNER=(r"\b(?:1boy|\d+boys?|male|man|another|penis|hetero|partner|group sex|another's)\b"
    r"|\b(?:multiple|several)\s+(?:nude |naked )?(?:boys?|girls?|men|women|people|partners?)\b"
    r"|\b(?:boys?|men|partners?)\b[^.;!?]{0,45}\b(?:groping|fingering|penetrating)\b")

# 引号里的实体招牌/霓虹文字。
SIGN_TEXT=(r"\b(?:neon )?signs?\b[^.;!?]{0,25}[\"“][^\"”]{1,30}[\"”]"
    r"|[\"“][^\"”]{1,30}[\"”][^.;!?]{0,15}\b(?:neon )?signs?\b"
    r"|[\"“][^\"”]{1,30}[\"”][^.;!?]{0,10}\b(?:lettering|graffiti|neon)\b")
GESTURE_SIGN=(r"\b(?:hands?|fingers?)\b[^.;!?]{0,65}[\"“]v[\"”]\s+sign\b"
    r"|\b(?:cute|playful|peace|victory|two[- ]finger)\b[^.;!?]{0,20}[\"“]?v?[\"”]?\s+sign\b")

# 缝合嘴/唇属面部特征写法。
STITCHED=r"\bstitched (?:mouth|lips)\b"
STITCHED_NONFACE=(r"\b(?:mask|print|pattern|motif|logo|doll|plush|toy|sculpture|tattoo|body writing)\b"
    r"[^.;!?]{0,25}\bstitched (?:mouth|lips)\b"
    r"|\bstitched (?:mouth|lips)\b[^.;!?]{0,20}\b(?:mask|print|pattern|motif|logo)\b")

# 隔衣可见的乳头/乳晕支持裸露与遮盖父类（细分 cover.topless 仍按隔衣守卫不命中）。
THROUGH_FABRIC=(r"\b(?:nipples?|areolae?)\b[^.;!?]{0,20}"
    r"\b(?:visible|showing|outlined?|pressing|poking|hard|erect|hinted?|glimpsed?|peeking)\b"
    r"[^.;!?]{0,20}\b(?:through|under|beneath|against)\b[^.;!?]{0,18}"
    r"\b(?:fabric|cloth|clothing|shirt|top|bra|dress|lingerie|bikini|swimsuit|lace|mesh)\b"
    r"|\b(?:nipples?|areolae?)\b[^.;!?]{0,18}\b(?:through|under|beneath|against)\b"
    r"[^.;!?]{0,12}\b(?:thin|sheer|transparent|translucent|wet|clinging|lace|mesh)\b[^.;!?]{0,10}"
    r"\b(?:fabric|cloth|clothing|shirt|top|bra|dress|lingerie|bikini|swimsuit)\b")
COVERED=(r"\b(?:covered|hidden|concealed|obscured|invisible|not visible)\b[^.;!?]{0,20}\b(?:nipples?|areolae?)\b"
    r"|\b(?:nipples?|areolae?)\b[^.;!?]{0,20}\b(?:fully covered|hidden|concealed|obscured|not visible|opaque)\b")

# x_(作品名) 形式的角色专名：只认已知作品名白名单，不做整类扩召回。
WORKS=(r"arknights|genshin impact|blue archive|kancolle|kantai collection|pokemon|azur lane|fate/grand order|hololive|idolmaster|touhou|vocaloid|love live|uma musume|girls' frontline|nikke|splatoon|persona|final fantasy|fire emblem|honkai|zenless zone zero")
NAME_WORK=r"\b[a-z][a-z0-9' -]{1,40}\("+WORKS+r"\)"


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body)).replace('; ', ', ')


# 屏幕/显示器等设备按库内既有口径算家具与生活用品，不得因眼镜守卫误删（第 134 轮修正单）。
DEVICE_NONPHYSICAL=r"\b(?:screen ?print|screenprint|screenshots?|screen capture|off[- ]screen|status bar|screening)\b"
DEVICE_SUPPORT=(r"\b(?:led|display|projection|computer|television|tv)\s+screens?\b"
    r"|\b(?:screens?|monitors?|tvs?|televisions?|laptops?|computers?|tablets?|projectors?)\b"
    r"[^.;!?]{0,35}\b(?:behind|mounted|hanging|on (?:the )?(?:wall|desk|table)|displays?|displaying|shows?|showing|glowing|powered)\b"
    r"|\b(?:mounted|hanging|displaying|shows?|glowing)\b[^.;!?]{0,35}"
    r"\b(?:screens?|monitors?|tvs?|televisions?|projectors?)\b")
REMOVALS=[]


def _raw_text(body):
    # 引号内的实体文字在 positive 分词里会被当作引用材料剥掉，因此招牌文字在去负权原文上匹配。
    cleaned=re.sub(r'-\s*\d+(?:\.\d+)?::.*?::',' ',str(body or ''))
    return cleaned.lower().replace('\\','')


def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive=_positive(body,refinements)
    physical_device=re.search(DEVICE_SUPPORT,re.sub(DEVICE_NONPHYSICAL,' ',positive,flags=re.I),re.I)
    if '家具与生活用品' in result and physical_device:
        del result['家具与生活用品']
    node_parents={node['parent'] for node in refinements.REFINEMENT_NODES.values()}
    for parent,patterns,support,reason in REMOVALS:
        if parent not in parents:continue
        remaining=positive;cues=[]
        for pattern in patterns:
            cues.extend(match.group() for match in re.finditer(pattern,remaining,re.I))
            remaining=re.sub(pattern,' ',remaining,flags=re.I)
        if not cues:continue
        if re.search(support,remaining,re.I):continue
        if parent in node_parents and refinements.extract_refinements(remaining,[parent]):continue
        result[parent]={'false_cues':cues,'reason':reason}
    return result


def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    raw=_raw_text(body)
    def want(parent,pattern,allowed=True):
        if parent in parents or parent in found or not allowed:return
        if re.search(pattern,positive,re.I):found.append(parent)
    def want_raw(parent,pattern,allowed=True):
        if parent in parents or parent in found or not allowed:return
        if re.search(pattern,raw,re.I):found.append(parent)
    want('自慰',SELF_TOUCH,allowed=not re.search(PARTNER,positive,re.I))
    sign_raw=re.sub(GESTURE_SIGN,' ',raw,flags=re.I)
    want_raw('文字与图形',SIGN_TEXT,allowed=bool(re.search(SIGN_TEXT,sign_raw,re.I)))
    want('面部特征',STITCHED,allowed=not re.search(STITCHED_NONFACE,positive,re.I))
    want('裸露与遮盖',THROUGH_FABRIC,allowed=not re.search(COVERED,positive,re.I))
    # `x_(作品名)` 专名写法（890 条候选）另建独立批次处理，本批不动，避免与其它写法混审。
    rejected=candidates(body,list(parents)+list(found),refinements)
    return [parent for parent in found if parent not in rejected]
