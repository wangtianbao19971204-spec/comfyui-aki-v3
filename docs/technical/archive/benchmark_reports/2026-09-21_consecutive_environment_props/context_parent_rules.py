"""Batch 24 rules: costume, fantasy-environment, printed-text and sex-toy recall from round 110."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('tag_guards',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_tag_guards/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

# 兔女郎制服：playboy bunny / bunny suit / bunny girl（含中文写法）明确是制服。
COSTUME=r"\b(?:playboy bunn(?:y|ies)|bunn(?:y|ies) suits?|bunn(?:y|ies) girls?)\b|兔女郎"
# 幻想/科幻环境：地牢是节点级环境证据；“fantasy/magical + 环境名词”才是环境。
# 作品名（final fantasy、granblue fantasy）与 magical girl 不算，故不做裸词匹配。
ENVIRONMENT=r"\b(?:in|into|inside|within)\s+(?:a\s+|the\s+|an\s+)?(?:dark\s+|dark\s+stone\s+|stone\s+|ancient\s+|underground\s+|abandoned\s+)*dungeons?\b|\b(?:dark|dark stone|stone|ancient|underground|abandoned)\s+(?:stone\s+)?dungeons?\b|\bdungeons?\s+(?:background|interior|walls?|corridor|room|floor|setting|scene)s?\b|\b(?:fantasy|magical)\s+(?:environments?|worlds?|lands?|landscapes?|realms?|settings?|scenes?|forests?|kingdoms?|cities|city|backdrops?|natures?)\b"
# 物件上的可读文字：海报/标牌上的句子、贴标签、书写在物体上。
PRINTED_TEXT=r"\bposters?\b[^.;!?]{0,60}\b(?:reading|saying|text|words)\b|\bsigns?\b[^.;!?]{0,40}\b(?:reading|saying)\b|\bla?bel(?:led|ed|s)?\b|\bscreen print\b[^.;!?]{0,20}\b(?:text|lettering)\b|\bwriting on\b"
# 成人道具：vibrator 本身即明确性玩具；“magic wand / hitachi” 必须与性语境同句相邻
# （奇幻道具的魔法杖不算）。
SEX_TOY=r"\bvibrators?\b|\bhitachi magic wand\b|\bmagic wand\b"
SEX_TERM=r"\b(?:pussy|clit(?:oris)?|vagina|masturbat\w*|ejaculat\w*|orgasm\w*|cum|penis|anal|dildo|sex|nipples?|crotch)\b"
SEX_TOY_NEAR=re.compile(rf"(?:{SEX_TOY})[^.!?]{{0,80}}{SEX_TERM}|{SEX_TERM}[^.!?]{{0,80}}(?:{SEX_TOY})",re.I)

def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))

def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    def want(parent,pattern,allowed=True):
        if parent in parents or parent in found or not allowed:return
        if re.search(pattern,positive,re.I):found.append(parent)
    want('制服与职业装',COSTUME)
    want('幻想与科幻环境',ENVIRONMENT)
    want('文字与图形',PRINTED_TEXT)
    sex_toy=re.search(SEX_TOY,positive,re.I)
    want('成人道具',SEX_TOY,allowed=bool(sex_toy) and (sex_toy.group(0).lower().startswith('vibrator') or bool(SEX_TOY_NEAR.search(positive))))
    rejected=candidates(body,parents+found,refinements)
    return [p for p in found if p not in rejected]

def candidates(body,parents,refinements):
    # 第 110 轮 #6 的“服装材质与剪裁”是风格模板误挂（screen print texture / flat color palette），
    # 无可泛化触发词（“texture/print”在真实衣料记录里也会出现），只由轮次账本撤回。
    return previous.candidates(body,parents,refinements)
