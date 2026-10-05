"""Batch 33 rules: work-title, exposure and body-fluid recall from round 119."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('animal_simile',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_animal_simile/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '作品角色':r"《[^》]{1,30}》|\b(?:original|series|game|anime|manga)\b",
    '裸露与遮盖':r"\b(?:nude|naked|topless|bottomless|exposed|exposing|bare skin|nsfw)\b",
    '射精与体液':r"\b(?:cum|semen|ejaculat\w*|love juices?|squirt\w*|saliva|drool\w*|sweat|fluid)\b",
}

WORK_TITLE=r"《[^》]{1,30}》"
EXPOSURE_CUE=r"\b(?:areolae?|nipples?)\b[^.;!?]{0,20}\b(?:exposed|visible|bare)\b|\b(?:exposed|visible|bared)\b[^.;!?]{0,20}\b(?:areolae?|nipples?)\b|\b(?:areolae?|nipples?)\s+(?:slightly\s+)?visible\b"
FLUID_CUE=r"\b(?:thick |sticky |creamy )?white fluid\b|\bthick white fluid\b"
FLUID_GUARD=r"\b(?:milk|latte|cream|custard|paint|glue|yogurt|yoghurt|drink|cup|glass of|bottle of)\b"


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
    want('作品角色',WORK_TITLE)
    want('裸露与遮盖',EXPOSURE_CUE)
    fluid_allowed=False
    for match in re.finditer(FLUID_CUE,positive,re.I):
        window=positive[max(0,match.start()-40):match.end()+40]
        if re.search(FLUID_GUARD,window,re.I):continue
        fluid_allowed=True;break
    want('射精与体液',FLUID_CUE,allowed=fluid_allowed)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
