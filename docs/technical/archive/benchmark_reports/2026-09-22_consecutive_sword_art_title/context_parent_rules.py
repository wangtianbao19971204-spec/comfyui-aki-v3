"""Batch 41 rules: `sword art online` title guard from round 127."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('camera_holding',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_camera_holding/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT}

TITLE_SWORD=r"\bsword art online\b"

REMOVALS=[
    ('武器与装备',[TITLE_SWORD],SUPPORT['武器与装备'],'Work title, not an in-image weapon.'),
]


def _positive(body,refinements):
    return '; '.join(refinements._positive_parts(body))


def candidates(body,parents,refinements):
    result=previous.candidates(body,parents,refinements)
    positive=_positive(body,refinements)
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
    # 作品名 `sword art online` 里的 sword 也会被上游 sword→武器与装备 规则命中，
    # 这里用本批的标题守卫把重新补挂的项过滤掉（真实刀剑写法不受影响）。
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
