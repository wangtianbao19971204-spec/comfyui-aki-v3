"""Batch 34 rules: explicit work-title recall (baccano!, reverse:1999) from round 120."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('work_exposure_fluid',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_work_exposure_fluid/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '作品角色':r"《[^》]{1,30}》|\bbaccano!|\breverse ?: ?1999\b",
}

# 第 120 轮全文审核确认的显式作品专名写法（与库内既有精确作品名清单同一做法）。
WORK_TITLE=r"《[^》]{1,30}》|\bbaccano!|\breverse ?: ?1999\b"


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))


def _title_text(body,positive):
    # `reverse:1999` 这类带冒号的作品名会被词元切分拆开，因此作品专名同时
    # 在原文（去掉负权片段后）上匹配；负权排除写法仍不触发。
    cleaned=re.sub(r'-\s*\d+(?:\.\d+)?::.*?::',' ',body)
    return positive+' \\n '+cleaned.lower()


def candidates(body,parents,refinements):
    return previous.candidates(body,parents,refinements)


def additions(body,parents,refinements):
    found=previous.additions(body,parents,refinements)
    positive=_positive(body,refinements)
    title_text=_title_text(body,positive)
    def want(parent,pattern,allowed=True):
        if parent in parents or parent in found or not allowed:return
        if re.search(pattern,title_text,re.I):found.append(parent)
    want('作品角色',WORK_TITLE)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
