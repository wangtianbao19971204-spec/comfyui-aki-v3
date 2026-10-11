"""Central Anima block-architecture mapping tables.

This module has NO dependency on ComfyUI, torch, or any other runtime -- it is
pure data + pure functions, so it can be imported and unit-tested on its own
(including outside a ComfyUI environment).

Anima ships in (currently) three known transformer-block-count variants, each
a depth-expansion of the previous one -- new blocks are spliced into specific
positions of an otherwise byte-identical, relocated copy of every block from
the smaller variant:

    28 blocks (Anima base / anima-preview)
      -> insert 12 new blocks -> 40 blocks (Anima 2.9B)
        -> insert 12 more new blocks -> 52 blocks (Anima 3.8B)

The 28->40 insertion indices were established by sparklingcoffee777's
ComfyUI-Anima-2.9B-loraPatch, via direct tensor comparison between
anima-base-v1.0 and Anima-2.9B-preview-v1. This project independently
re-verified that same 28->40 table (see ComfyUI-Anima-2.9B-controlnetPatch,
Task 2 of this line of work) using torch.equal() weight comparisons of its
own, and separately, independently derived the 40->52 table below from
scratch via a brute-force, all-pairs torch.equal() search across every real
block in Anima-2.9B-preview-v1.safetensors and Anima-3.8B.safetensors (all 40
blocks matched exactly one 3.8B block each, across four different weight
tensor types per block, with zero collisions and zero misses) -- this result
happens to exactly match the insertion tuple used (without in-repo weight
verification of its own) by Lakeside529's ComfyUI-Anima-3.8B-LoRA-Bridge,
which is independent cross-confirmation, not the source of this table.

The 28->52 mapping is deliberately NOT a third hard-coded table: it is always
derived by composing 28->40 and 40->52, so there is exactly one place
(this module) that can disagree with itself.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

# ----------------------------------------------------------------------------
# Known architectures
# ----------------------------------------------------------------------------

# Supported block counts, smallest to largest. Part 1 scope: exactly these
# three. Anything else is an "unknown architecture" -- see get_mapping().
ANIMA_BLOCK_COUNTS: Tuple[int, ...] = (28, 40, 52)

# Indices of the 12 blocks inserted when expanding 28 blocks -> 40 blocks.
# Verified via direct torch.equal() weight comparison (see module docstring).
INSERTED_28_40: Tuple[int, ...] = (2, 5, 8, 11, 14, 17, 21, 24, 27, 30, 33, 36)

# Indices (in the 40-block numbering after the first expansion has already
# happened) of the 12 blocks inserted when expanding 40 blocks -> 52 blocks.
# Verified via direct torch.equal() weight comparison (see module docstring).
INSERTED_40_52: Tuple[int, ...] = (3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 43, 47)


def _inherited_destinations(old_count: int, insertion_positions: Tuple[int, ...]) -> list:
    """Given the smaller block count and the set of newly-inserted indices in
    the larger layout, return the larger-layout indices that are NOT newly
    inserted, in ascending order -- i.e. the destination slot for source
    index 0, 1, 2, ... in order."""
    inserted = set(insertion_positions)
    new_count = old_count + len(inserted)
    return [i for i in range(new_count) if i not in inserted]


def _build_expansion_map(old_count: int, insertion_positions: Tuple[int, ...]) -> Dict[int, int]:
    """source block index (0..old_count-1) -> destination block index in the
    expanded layout."""
    kept = _inherited_destinations(old_count, insertion_positions)
    assert len(kept) == old_count, (
        f"expansion map is inconsistent: expected {old_count} kept slots, got {len(kept)}"
    )
    return {source: dest for source, dest in enumerate(kept)}


# The two directly-verified expansion steps.
MAP_28_40: Dict[int, int] = _build_expansion_map(28, INSERTED_28_40)
MAP_40_52: Dict[int, int] = _build_expansion_map(40, INSERTED_40_52)

# 28->52 is DERIVED by composition, never hand-written, so it can't drift
# from the two verified steps above.
MAP_28_52: Dict[int, int] = {source: MAP_40_52[dest] for source, dest in MAP_28_40.items()}

assert len(MAP_28_40) == 28 and len(set(MAP_28_40.values())) == 28
assert len(MAP_40_52) == 40 and len(set(MAP_40_52.values())) == 40
assert len(MAP_28_52) == 28 and len(set(MAP_28_52.values())) == 28

# All known forward maps (source_count, target_count) -> {source_idx: target_idx}.
# Identity pairs (28,28)/(40,40)/(52,52) are intentionally absent: callers must
# treat "source == target" as "no mapping object needed" themselves (see
# get_mapping's docstring) rather than materializing a trivial identity dict.
_FORWARD_MAPS: Dict[Tuple[int, int], Dict[int, int]] = {
    (28, 40): MAP_28_40,
    (28, 52): MAP_28_52,
    (40, 52): MAP_40_52,
}


def get_mapping(source_count: int, target_count: int) -> Optional[Dict[int, int]]:
    """Return the forward block-index mapping (source_idx -> target_idx) for
    remapping something trained on a `source_count`-block Anima architecture
    onto a `target_count`-block host, or None if:

      - source_count == target_count (nothing to remap -- caller should treat
        this as "pass through unchanged", not as an error), or
      - the (source_count, target_count) pair is not a known, verified
        expansion step (Part 1 only knows about strictly-increasing
        28->40, 28->52, 40->52 -- anything else, including any downgrade
        where source_count > target_count, or either count not in
        ANIMA_BLOCK_COUNTS, returns None so the caller does not guess).

    Callers are expected to distinguish "identity, nothing to do" from
    "unrecognized pair, nothing to do" themselves (e.g. for logging/
    diagnostics) using bucket_block_count()/ANIMA_BLOCK_COUNTS if they care;
    both cases mean "leave the object untouched" either way.
    """
    if source_count == target_count:
        return None
    return _FORWARD_MAPS.get((source_count, target_count))


def get_inverse_mapping(source_count: int, target_count: int) -> Optional[Dict[int, int]]:
    """Return the inverse of get_mapping(): target_idx -> source_idx. This is
    what a ControlNet/LLLite-style consumer needs, since it is handed a raw
    *host* block_index at call time and must find which *source* (checkpoint)
    block index that corresponds to -- the opposite direction from LoRA's
    load-time key rewrite, which walks source keys and rewrites them to
    target keys.

    Returns None under the same conditions as get_mapping(). Note the inverse
    is not necessarily total: block indices inserted by the expansion have no
    source counterpart, so `target_idx not in inverse_map` for those -- the
    caller (AnimaLLLite.apply's wrapper) must treat a missing key as "this
    host block has no trained correction available", not as an error.
    """
    forward = get_mapping(source_count, target_count)
    if forward is None:
        return None
    return {target: source for source, target in forward.items()}


def get_reduction_mapping(source_count: int, target_count: int) -> Optional[Dict[int, int]]:
    """The downward counterpart of get_mapping(): remap an adapter trained
    for a LARGER architecture (source_count) onto a SMALLER host
    (target_count < source_count) -- e.g. a genuinely 40-block LoRA applied
    to the 28-block base model.

    Returns target_idx (host, the smaller architecture) -> source_idx
    (adapter, the larger architecture): for every host block, which adapter
    block holds the physically identical weights that host block
    corresponds to. This requires NO new mapping data -- every host position
    in the smaller architecture has a real ancestor in the larger one (that
    is exactly the fact get_mapping(target_count, source_count) already
    encodes, just consumed in the direction the expansion tables were
    always capable of), so this is simply:

        get_reduction_mapping(K, M) == get_mapping(M, K)   for M < K

    Unlike get_inverse_mapping() (used for the *host-is-larger* case, where
    12 host positions per expansion step have no source counterpart and are
    legitimately absent from the map), this mapping is TOTAL over
    range(target_count): every smaller-architecture position has exactly one
    larger-architecture ancestor, by construction of the expansion tables.

    Returns None if source_count <= target_count (that is an expansion --
    use get_mapping() instead) or the pair isn't a known architecture pair.
    """
    if source_count <= target_count:
        return None
    return get_mapping(target_count, source_count)


def bucket_block_count(observed_max_index_plus_one: int) -> Optional[int]:
    """Given the number of distinct blocks actually referenced by something
    (typically `max(observed_block_indices) + 1`), return the smallest known
    Anima architecture that could structurally contain that many blocks, or
    None if it exceeds every known architecture.

    This is deliberately permissive about *partial* coverage: a LoRA or
    ControlNet-LLLite checkpoint need not reference every block of its source
    architecture (e.g. it may only target a subset of layers) -- what matters
    is that the *highest* index it references is physically impossible for a
    smaller architecture to have. E.g. observing index 35 is impossible for
    the 28-block architecture (max index 27) and impossible for full coverage
    but not for partial coverage of the 40-block one (max index 39), so it is
    bucketed as 40 -- the smallest architecture that could actually contain
    that index.
    """
    for count in ANIMA_BLOCK_COUNTS:
        if observed_max_index_plus_one <= count:
            return count
    return None
