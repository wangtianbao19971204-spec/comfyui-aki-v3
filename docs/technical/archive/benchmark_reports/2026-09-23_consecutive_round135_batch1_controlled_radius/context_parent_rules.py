"""Batch 48 parent rules for the frozen round-135 batch-1 radius.

Only the rule-backed operations in ``operation_manifest.json`` belong here.
The two ID-bound accessory operations remain stage-only corrections.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re


_PREVIOUS_PATH = (
    Path(__file__).resolve().parent.parent
    / "2026-09-23_consecutive_backlog_wave1"
    / "context_parent_rules.py"
)
_SPEC = importlib.util.spec_from_file_location("round135_batch1_previous_rules", _PREVIOUS_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"cannot load previous parent rules: {_PREVIOUS_PATH}")
previous = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(previous)

SUPPORT = {**previous.SUPPORT}


# Contract-amendment v2 admits only this active, same-owner construction.
# In particular it excludes "one of her own hands holds ... pressed ...", all
# passive pressed constructions, and use/rub/hold predicates.
ACTIVE_SELF_DEVICE = re.compile(
    r"\b(?P<owner>her|his|their)\s+own hand pressing\s+"
    r"(?:a\s+)?(?:wand\s+)?(?:vibrator|dildo)\s+"
    r"(?:directly\s+)?against\s+(?P=owner)\s+"
    r"(?:clit(?:oris)?|pussy|vulva|genitals?|crotch|anus|penis)\b",
    re.I,
)

_MOVEMENT_FAMILY_PARTS = {
    "dynamic pose",
    "motion lines",
    "missionary pose",
    "sex",
    "lighting contour",
}
_INDEPENDENT_MOVEMENT = re.compile(
    r"\b(?:run(?:ning|s)?|walk(?:ing|s)?|fly(?:ing|s)?|dance|dancing|"
    r"fight(?:ing|s)?|boxing|punch(?:ing|es)?|slash(?:ing|es)?|"
    r"jump(?:ing|s)?|leap(?:ing|s)?|sprint(?:ing|s)?|charging|"
    r"swimming|skating|climbing|kicking|attack(?:ing|s)?)\b",
    re.I,
)
_DIAMOND_FLOWER_BUCKLE = re.compile(r"\bdiamond\s+flower\s+buckle\b", re.I)
_RECIPROCAL_CLINGING = re.compile(r"\bclinging\s+to\s+(?:each other|one another)\b", re.I)
_NONHUMAN_CLINGING_SUBJECT = re.compile(
    r"\b(?:clothes?|clothing|cloth|dress(?:es)?|fabric|pants|stockings?|tights|curtains?|"
    r"slime|mucus|leaves|vines?)\b[^,.;!?]{0,40}\bclinging\s+to\s+(?:each other|one another)\b",
    re.I,
)
_PLURAL_HUMAN = re.compile(
    r"\b(?:(?:multiple|several|many|two|three|four|five|six)\s+"
    r"(?:girls?|women|boys?|men|people|persons?|bodies)|"
    r"\d+\+?\s*(?:girls?|women|boys?|men|people|persons?|bodies)|everyone|everybody|clones|"
    r"multiple copies|body pile|stacked bodies|tangled limbs|arms reaching)\b",
    re.I,
)
_LAYOUT_FRAME = re.compile(r"\b(?:full|filling)\s+frame\b", re.I)
_LAYOUT_CROPPED_BODIES = re.compile(
    r"\b(?:bodies\s+(?:cut off|cropped)\s+at\s+(?:the\s+)?edges|"
    r"cropped\s+bodies\s+at\s+(?:the\s+)?edges)\b",
    re.I,
)


def _parts(body, refinements) -> list[str]:
    return [part.strip().lower() for part in refinements._positive_parts(body) if part.strip()]


def _positive(body, refinements) -> str:
    return ", ".join(_parts(body, refinements))


def _exact_movement_family(parts: list[str]) -> bool:
    values = set(parts)
    if not _MOVEMENT_FAMILY_PARTS <= values:
        return False
    independent = ", ".join(part for part in parts if part not in {"dynamic pose", "motion lines"})
    return not _INDEPENDENT_MOVEMENT.search(independent)


def _flower_buckle_only(body, refinements) -> bool:
    positive = _positive(body, refinements)
    if not _DIAMOND_FLOWER_BUCKLE.search(positive):
        return False
    remaining = _DIAMOND_FLOWER_BUCKLE.sub(" ", positive)
    return "plant.flowers" not in set(refinements.extract_refinements(remaining, ["植物与花园"]))


def _reciprocal_human_clinging(positive: str) -> bool:
    return bool(
        _RECIPROCAL_CLINGING.search(positive)
        and _PLURAL_HUMAN.search(positive)
        and not _NONHUMAN_CLINGING_SUBJECT.search(positive)
    )


def _layout_composite(positive: str) -> bool:
    return bool(_LAYOUT_FRAME.search(positive) and _LAYOUT_CROPPED_BODIES.search(positive))


def candidates(body, parents, refinements):
    """Return only contract-admitted parent removals."""
    result = previous.candidates(body, parents, refinements)
    parts = _parts(body, refinements)

    if "移动与运动" in parents and _exact_movement_family(parts):
        result["移动与运动"] = {
            "false_cues": ["dynamic pose", "motion lines"],
            "reason": "round135 batch1 exact duplicate family has no independent actor movement",
        }

    if "植物与花园" in parents and _flower_buckle_only(body, refinements):
        result["植物与花园"] = {
            "false_cues": ["diamond flower buckle"],
            "reason": "flower is an occurrence-level buckle decoration, not a plant",
        }
    return result


def additions(body, parents, refinements):
    """Return parent additions, then re-run all removal guards.

    The final candidates pass is intentional: it prevents an upstream generic
    addition from restoring a parent rejected by this batch.
    """
    found = list(previous.additions(body, parents, refinements))
    parts = _parts(body, refinements)
    positive = ", ".join(parts)

    def want(parent: str, allowed: bool) -> None:
        if allowed and parent not in parents and parent not in found:
            found.append(parent)

    want("种族与幻想生物", any(part == "elvaan" for part in parts))

    strict_device = any(ACTIVE_SELF_DEVICE.search(part) for part in parts)
    want("自慰", strict_device)
    want("持物与道具互动", strict_device)
    want("裸露与遮盖", strict_device)

    exact_family = _exact_movement_family(parts)
    want("光影效果", exact_family)
    want("拥抱与日常互动", _reciprocal_human_clinging(positive))
    want("布局与画面结构", _layout_composite(positive))

    rejected = candidates(body, list(parents) + found, refinements)
    return [parent for parent in found if parent not in rejected]


def planned_node_changes(body, parents, refinements):
    """Mirror the candidate semantic source for read-only scan accounting.

    Call with final parents to discover additions and with original parents to
    discover removals. Scan code compares these intentions with actual before
    and candidate-after extraction, so nonexistent operations are discarded.
    """
    parts = _parts(body, refinements)
    positive = ", ".join(parts)
    current = set(refinements.extract_refinements(body, parents))
    add: list[str] = []
    remove: list[str] = []

    strict_device = any(ACTIVE_SELF_DEVICE.search(part) for part in parts)
    for parent, node in (
        ("自慰", "self_touch.device"),
        ("持物与道具互动", "use_prop.holding"),
        ("裸露与遮盖", "cover.bottomless"),
    ):
        if strict_device and parent in parents and node not in current:
            add.append(node)

    if "拥抱与日常互动" in parents and _reciprocal_human_clinging(positive):
        if "interaction.hug" not in current:
            add.append("interaction.hug")

    if "植物与花园" in parents and _flower_buckle_only(body, refinements):
        if "plant.flowers" in current:
            remove.append("plant.flowers")

    return {"add": add, "remove": remove}
