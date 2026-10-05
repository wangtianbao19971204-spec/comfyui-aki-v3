"""Batch 30 rules: inherit batch 29 parent rules; round 116 fixes are refinement-node scope only."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('ears_tail_exposure',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_ears_tail_exposure/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

# No parent-level rule change is required for the round 116 reveal-verb
# decision; the inherited chain stays authoritative and re-exported verbatim.
SUPPORT=previous.SUPPORT
REMOVALS=previous.REMOVALS
candidates=previous.candidates
additions=previous.additions
