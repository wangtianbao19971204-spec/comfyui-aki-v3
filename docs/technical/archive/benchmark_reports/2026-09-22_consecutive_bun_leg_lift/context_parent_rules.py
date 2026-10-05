"""Batch 27 rules: inherit batch 26 parent rules; round 113 fixes are refinement-node scope only."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('action_scope',Path(__file__).resolve().parent.parent/'2026-09-21_consecutive_action_scope/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

# No parent-level rule change is required for the round 113 bun/leg-lift
# misses; the inherited chain stays authoritative and re-exported verbatim.
SUPPORT=previous.SUPPORT
REMOVALS=previous.REMOVALS
candidates=previous.candidates
additions=previous.additions
