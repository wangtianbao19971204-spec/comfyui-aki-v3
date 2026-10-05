"""Batch 35 rules: real-creature-on-body recall from round 121."""
import importlib.util
import re
from pathlib import Path

spec=importlib.util.spec_from_file_location('work_title_recall',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_work_title_recall/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

SUPPORT={**previous.SUPPORT,
    '动物主体':r"\b(?:caterpillars?|butterfl(?:y|ies)|moths?|beetles?|worms?|snails?|spiders?|ants?|bees?|snakes?|lizards?|frogs?|tadpoles?|insects?|bugs?|cats?|dogs?|birds?|mice|mouse|hamsters?)\b",
}

# 生物需紧贴 `on <部位>`，避免「mouse visible…glow on face」「lizard tail…goggles on head」
# 这类同句跨成分误触；`mouse` 与电脑鼠标同形，只由批量 32 的 `(animal)` 限定写法覆盖。
CREATURE_ON_BODY=r"\b(?:caterpillars?|butterfl(?:y|ies)|moths?|beetles?|worms?|snails?|spiders?|ants?|bees?|snakes?|lizards?|frogs?|tadpoles?|insects?|bugs?|hamsters?)\b[\s,]{0,3}\bon (?:the )?(?:belly|body|back|chest|arm|hand|leg|thigh|shoulder|head|lap|face)\b"
CREATURE_FAKE=r"\b(?:plush|stuffed|toy|fake|drawn|print|pattern|motif|costume|cushion|pillow|keychain|charm|statue|figure|logo|symbol)\b"


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
    creature_allowed=False
    for match in re.finditer(CREATURE_ON_BODY,positive,re.I):
        window=positive[max(0,match.start()-40):match.end()+40]
        if re.search(CREATURE_FAKE,window,re.I):continue
        creature_allowed=True;break
    want('动物主体',CREATURE_ON_BODY,allowed=creature_allowed)
    rejected=candidates(body,parents+found,refinements)
    return [parent for parent in found if parent not in rejected]
