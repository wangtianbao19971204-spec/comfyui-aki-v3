"""Batch 29 rules: inherit batch 28 parent rules; round 115 fixes are refinement-node scope only."""
import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location('exposure_guards',Path(__file__).resolve().parent.parent/'2026-09-22_consecutive_exposure_guards/context_parent_rules.py')
previous=importlib.util.module_from_spec(spec);spec.loader.exec_module(previous)

# No parent-level rule change is required for the round 115 ears/tail/exposure
# decisions; the inherited chain stays authoritative and re-exported verbatim.
SUPPORT=previous.SUPPORT
REMOVALS=previous.REMOVALS
candidates=previous.candidates
additions=previous.additions
