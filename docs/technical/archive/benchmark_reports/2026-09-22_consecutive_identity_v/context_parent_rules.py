"""Batch 39 rules: explicit `identity v` work-title recall from round 125."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('reveal_nipples_names',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_reveal_nipples_names/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '作品角色':previous.SUPPORT['作品角色']+r"|\bidentity v\b",
}

WORK_CUE=r"\bidentity v\b"


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
    want('作品角色',WORK_CUE)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
