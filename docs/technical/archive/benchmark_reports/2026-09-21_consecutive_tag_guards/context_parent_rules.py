"""Batch 23 rules: tag-level guards and self-touch recall from round 109."""
import importlib.util
from pathlib import Path
import re

spec=importlib.util.spec_from_file_location('prose_scene',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_prose_scene/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

# 手里/道具上的明确自写动作：手滑向自己下体、骑坐固定在地面的吸盘道具。
SELF_EXTRA=r"\b(?:hand|fingers?)\b[^.!?;]{0,40}\b(?:slid(?:e|es|ing)|moving|drift(?:s|ing)|trail(?:s|ing))\b[^.!?;]{0,40}\b(?:her|his|their)\b[^.!?;]{0,20}\b(?:wet |damp )?(?:crotch|groin|pussy|lap)\b|\b(?:rides?|riding|straddl(?:es|ing)|mounts?|mounting|grinds?|grinding)\b[^.!?;]{0,40}\b(?:suction[- ]base(?:d)?\s+dildo|dildo|sex toy|toy)\b[^.!?;]{0,40}\b(?:fixed|mounted|attached|suction|on the (?:floor|ground))\b|\bsuction[- ]base(?:d)?\s+dildo\b"
# 标签级手势与饰品：paw pose 是猫爪手势；bell 是铃铛饰品。
GESTURE_TAG=r"\bpaw pose\b"
# 铃铛只认“穿戴/配件”写法：项圈铃、发铃、尾铃、挤奶铃、乳铃等复合词，
# 或与服装/兽娘标记同现的独立 bell；排除角色名、寺庙铃、被套（bell sleeves）与场景铃铛。
ACCESSORY_TAG=r"\b(?:neck|hair|tail|jingle|cow|nipple|cat|pet)s?[ -]?bells?\b|\bbells? (?:pendant|collar|choker|necklace|earrings?|hair ornament)\b|\bbells?\s+on\s+(?:her|his|their)\s+(?:neck|collar|choker)\b"
ACCESSORY_CONTEXT=re.compile(r"\b(?:collar|choker|cow print|cow ears|cow horns|cat ears|cat girl|cow girl|fox girl|wolf girl|dog girl|pet play|cowbell|tail|paw pose)\b",re.I)
ACCESSORY_GUARD=re.compile(r"\bbell sleeves?\b|\b(?:tinker|trusty|shrine|temple|church|school|door|sleigh)\s*bell\b|\bbell (?:pepper|tower|curve|bottoms?|shaped|chain|chime)\b|\bbell cranel\b|\bbell[^.;]{0,24}\b(?:on the|on a)\s+(?:bar|table|ground|floor|shelf|counter)\b",re.I)
# 负向写法“no text / textless”本身不是文字证据：只否决新增，不做删除。
NEGATED_TEXT=re.compile(r"\bno (?:visible )?(?:text|words?|lettering|writing)\b|\btextless\b|\bwithout (?:any )?text\b|\bno text\b",re.I)
def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))

def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    def want(parent,pattern,allowed=True):
        if parent in parents or parent in found or not allowed:return
        if re.search(pattern,positive,re.I):found.append(parent)
    want('自慰',SELF_EXTRA)
    want('手势与肢体动作',GESTURE_TAG)
    bell_accessory=bool(re.search(ACCESSORY_TAG,positive,re.I)) or (bool(re.search(r"(?<![\w-])bells?(?![\w-])",positive,re.I)) and bool(ACCESSORY_CONTEXT.search(positive)))
    want('首饰与随身配饰',r"(?<![\w-])bells?(?![\w-])",allowed=bell_accessory and not ACCESSORY_GUARD.search(positive))
    if '文字与图形' in found:
        stripped=NEGATED_TEXT.sub(' ',positive)
        if stripped!=positive:
            probe=[p for p in parents if p!='文字与图形']
            if '文字与图形' not in previous.additions(stripped,probe,refinements):
                found=[p for p in found if p!='文字与图形']
    rejected=candidates(body,parents+found,refinements)
    return [p for p in found if p not in rejected]

def candidates(body,parents,refinements):
    # 第 109 轮 #10 的“文字与图形”误挂只由轮次账本撤回：历史已审正例中同类负向写法
    # （video website interface、screenshot、:d 等）保留文字父类，说明该父类的正例证据
    # 无法用关键词穷举，故不新增可泛化的删除规则。
    return previous.candidates(body,parents,refinements)
