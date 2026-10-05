"""Round-135 batch-2 parent additions layered on the live batch-48 rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re


_PREVIOUS_PATH = (
    Path(__file__).resolve().parent.parent
    / "2026-09-23_consecutive_round135_batch1_controlled_radius"
    / "context_parent_rules.py"
)
_SPEC = importlib.util.spec_from_file_location("round135_batch2_previous_rules", _PREVIOUS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load previous parent rules: {_PREVIOUS_PATH}")
previous = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(previous)

SUPPORT = {**previous.SUPPORT}

_WIDE_EYED = re.compile(r"\bwide[ -]eyed\b", re.I)
_WIDE_EYED_STYLE = re.compile(
    r"\bwide[ -]eyed\s+character[ -]design\s+(?:language|style|template|vocabulary|aesthetic)\b",
    re.I,
)
_SHOUTING = re.compile(r"\bshouting\b", re.I)
_SHOUTING_TEXT = re.compile(
    r"\b(?:the\s+)?word\s+shouting\b|\bshouting\b[^,.;!?]{0,45}\b(?:written|printed|lettering|caption|text)\b|"
    r"\b(?:written|printed|lettering|caption|text)\b[^,.;!?]{0,45}\bshouting\b",
    re.I,
)
_LOOKING_AHEAD = re.compile(r"\blooking ahead\b", re.I)
_LIMB_TO_FRONT = re.compile(r"\b(?:hand|arm|foot) to front\b", re.I)
_PARTED_MOUTH = re.compile(r"\bparted mouth\b", re.I)
_NO_HUMAN = re.compile(r"\bno humans?\b", re.I)
_VISIBLE_HUMAN_PART = re.compile(
    r"^(?:(?:\d+|one|two|three|four|five|six)\+?\s*)?(?:girls?|women|boys?|men|people|persons?)$|"
    r"\b(?:girls?|women|boys?|men|people|persons?)\b[^,.;!?]{0,80}\b(?:shouting|face|head|expression|angry|surprised|crying|looking)\b|"
    r"\b(?:shouting|face|head|expression|angry|surprised|crying|looking)\b[^,.;!?]{0,80}\b(?:girls?|women|boys?|men|people|persons?)\b",
    re.I,
)
_NONVISUAL_HUMAN_PART = re.compile(
    r"\b(?:voice|voices|sound|audio|off[- ]?screen|from indoors|portrait|painting|poster|photo|statue|written|printed|text)\b",
    re.I,
)
_DEPICTED_HEAD_OR_FACE = re.compile(
    r"\b(?:image|imagie) in (?:a )?speech ?bubble\b[^.;!?]{0,140}\b(?:head|face|girl|woman|boy|man)\b|"
    r"\b(?:head|face) only\b[^.;!?]{0,140}\b(?:image|imagie) in (?:a )?speech ?bubble\b|"
    r"\breflection on (?:a |the )?sword\b[^.;!?]{0,140}\b(?:head|face|girl|woman|boy|man)\b|"
    r"\b(?:head|face|girl|woman|boy|man)\b[^.;!?]{0,140}\breflection on (?:a |the )?sword\b",
    re.I,
)


def _parts(body, refinements) -> list[str]:
    return [part.strip().lower() for part in refinements._positive_parts(body) if part.strip()]


def _has_non_style_wide_eyed(parts: list[str]) -> bool:
    for part in parts:
        if not _WIDE_EYED.search(part):
            continue
        if _WIDE_EYED.search(_WIDE_EYED_STYLE.sub(" ", part)):
            return True
    return False


def _has_visible_shouting(parts: list[str]) -> bool:
    shouting_parts = [
        part for part in parts
        if _SHOUTING.search(part) and not _SHOUTING_TEXT.search(part)
    ]
    if not shouting_parts:
        return False
    positive = ", ".join(parts)
    if not _NO_HUMAN.search(positive):
        return True
    # An explicit no-human scene normally means the shout is off-screen audio.
    # A contradictory but explicit visible subject, or a depicted head/face in
    # a speech bubble or sword reflection, can independently restore evidence.
    for part in parts:
        if _VISIBLE_HUMAN_PART.search(part) and not _NONVISUAL_HUMAN_PART.search(part):
            return True
    for part in shouting_parts:
        if _VISIBLE_HUMAN_PART.search(part) and not _NONVISUAL_HUMAN_PART.search(part):
            return True
    return bool(_DEPICTED_HEAD_OR_FACE.search(positive))


def additions(body, parents, refinements):
    found = list(previous.additions(body, parents, refinements))
    parts = _parts(body, refinements)

    def want(parent: str, allowed: bool) -> None:
        if allowed and parent not in parents and parent not in found:
            found.append(parent)

    want("眼口表情", _has_non_style_wide_eyed(parts) or _has_visible_shouting(parts) or any(_PARTED_MOUTH.search(part) for part in parts))
    want("视线方向", any(_LOOKING_AHEAD.search(part) for part in parts))
    want("手势与肢体动作", any(_LIMB_TO_FRONT.search(part) for part in parts))

    rejected = previous.candidates(body, list(parents) + found, refinements)
    return [parent for parent in found if parent not in rejected]


def candidates(body, parents, refinements):
    return previous.candidates(body, parents, refinements)


def planned_node_changes(body, parents, refinements):
    # The candidate-source before/after extraction is authoritative.  This
    # batch introduces no imperative node branch: its only node delta comes
    # from the declarative parted-mouth synonym in semantic_refinements.py.
    return {"add": [], "remove": []}
