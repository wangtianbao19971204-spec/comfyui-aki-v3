"""Batch 40 rules: in-scene camera holding recall from round 126."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('identity_v',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_identity_v/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '持物与道具互动':r"\b(?:holding|holds?|carrying|carries|grip(?:ping|s)?|grabb?\w*|lift(?:ing|s)?|rais(?:e|es|ing))\b[^.;!?]{0,30}\b(?:camera|film camera|dslr|polaroid|camcorder|microphone|book|cup|sword|gun|bag|bottle|flower|umbrella)\b",
}

# 画面内人物持相机（非“用相机拍摄”）才补持物与道具互动。
CAMERA_HOLD=r"\b(?:holding|holds?|raising|raises?|lift(?:ing|s)?|carrying|carries|grip(?:ping|s)?)\b[^.;!?]{0,25}\b(?:vintage film camera|film camera|camera|dslr|polaroid|camcorder)\b"
CAMERA_GUARD=(r"\b(?:shot (?:with|on)|captured (?:with|by)|photographed (?:with|by)|taken (?:with|on))\b"
    r"|\b(?:toward|towards|to|at|into)\s+(?:the\s+)?camera\b"
    r"|\b(?:shelf|table|frame|wall|stand|tripod|rack|hook|cabinet|box|bag)\s+(?:holds?|holding|carries?|carrying)\b")


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
    camera_allowed=False
    for match in re.finditer(CAMERA_HOLD,positive,re.I):
        window=positive[max(0,match.start()-40):match.end()+40]
        if re.search(CAMERA_GUARD,window,re.I):continue
        camera_allowed=True;break
    want('持物与道具互动',CAMERA_HOLD,allowed=camera_allowed)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
