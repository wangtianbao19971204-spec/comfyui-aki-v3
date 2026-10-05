"""Batch 38 rules: reveal-through-fabric nipples and reviewed character-name cues from round 124."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('exposure_butterfly_fluid',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_exposure_butterfly_fluid/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '作品角色':r"《[^》]{1,30}》|\bbaccano!|\breverse ?: ?1999\b|\byoo joonghyuk\b|ichijou_ririka",
    '裸露与遮盖':r"\b(?:nude|naked|topless|bottomless|exposed|exposing|reveal\w*|bare skin|nsfw|see-through|transparent|sheer)\b",
}

# 隔衣可见的乳首/乳晕（含 reveal 动词式，带衣物跨接守卫）。
REVEAL_NIPPLES=r"\breveal(?:s|ed|ing)?\b([^.;!?]{0,25})\b(?:nipples?|areolae?)\b"
REVEAL_GUARD=r"\b(?:clothes|clothing|outfit|dress|lingerie|bra|pasties)\b"
# 第 124 轮全文审核确认的角色专名（无作品名或仅带来源括注的写法）。
NAME_CUE=r"\byoo joonghyuk\b|ichijou[ _]ririka"


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))


def candidates(body,parents,refinements):
    return previous.candidates(body,parents,refinements)


def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    def want(parent,pattern,allowed=True):
        if parent in parents or parent in found or not allowed:return
        if re.search(pattern,positive,re.I):found.append(parent)
    want('作品角色',NAME_CUE)
    reveal_allowed=False
    for match in re.finditer(REVEAL_NIPPLES,positive,re.I):
        if re.search(REVEAL_GUARD,match.group(1),re.I):continue
        reveal_allowed=True;break
    want('裸露与遮盖',REVEAL_NIPPLES,allowed=reveal_allowed)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
