"""Batch 28 rules: inherit batch 27 parent rules; round 114 fixes are refinement-node scope only."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('bun_leg_lift',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_bun_leg_lift/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

# No parent-level rule change is required for the round 114 exposure/glasses
# decisions; the inherited chain stays authoritative and re-exported verbatim.
SUPPORT=previous.SUPPORT
REMOVALS=previous.REMOVALS
candidates=previous.candidates
additions=previous.additions
