"""Batch 36 rules: explicit `(weapon)` token recall from round 122."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('creature_on_body',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_creature_on_body/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '武器与装备':previous.SUPPORT['武器与装备']+r"|\(weapon\)",
}

WEAPON_TOKEN=r"\(weapon\)"


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))


def _raw_text(body,positive):
    # `(weapon)` 这类括注会被词元切分去掉，因此在去掉负权片段后的原文上匹配。
    cleaned=re.sub(r'-\s*\d+(?:\.\d+)?::.*?::',' ',body)
    return positive+' \n '+cleaned.lower()


def candidates(body,parents,refinements):
    return previous.candidates(body,parents,refinements)


def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    raw=_raw_text(body,positive)
    def want(parent,pattern,allowed=True):
        if parent in parents or parent in found or not allowed:return
        if re.search(pattern,raw,re.I):found.append(parent)
    want('武器与装备',WEAPON_TOKEN)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
