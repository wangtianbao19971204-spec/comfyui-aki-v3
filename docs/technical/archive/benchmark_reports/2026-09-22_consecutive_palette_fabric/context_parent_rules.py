"""Batch 42 rules: explicit palette and fabric/cut recall from round 128."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('sword_art_title',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_sword_art_title/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '色彩与调色':r"\b(?:tones?|palette|colou?r scheme|contrast|saturation|monochrome|grayscale|gradient)\b",
    '服装材质与剪裁':r"\b(?:fabric|cloth|texture|cuts?|hem|folds?|lace|silk|denim|leather|frills?|sleeves?)\b",
}

PALETTE_CUE=r"\btones? (?:are|were) dominated by\b|\bpalette (?:is|was) (?:dominated by|composed of)\b|\bcolou?r (?:palette|scheme)\b[^.;!?]{0,25}\b(?:dominated|composed|consists?|based)\b"
FABRIC_CUE=r"\bfabric\b[^.;!?]{0,40}\b(?:soft texture|subtle lust(?:er|re)|light and flowing)\b"
# 场景里的布料（地板/前景/背景/家具等）不是服装材质。
FABRIC_GUARD=r"\b(?:floor|foreground|background|wall|couch|sofa|bed|mattress|carpet|rug|curtains?|sheets?|pillow|table)\b"


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
    want('色彩与调色',PALETTE_CUE)
    fabric_allowed=False
    for match in re.finditer(FABRIC_CUE,positive,re.I):
        window=positive[max(0,match.start()-40):match.end()+40]
        if re.search(FABRIC_GUARD,window,re.I):continue
        fabric_allowed=True;break
    want('服装材质与剪裁',FABRIC_CUE,allowed=fabric_allowed)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
