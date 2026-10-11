"""LoRA compatibility: monkeypatches comfy.lora.load_lora.

Generalizes ComfyUI-Anima-2.9B-loraPatch's approach (same target function,
same overall shape: wrap load_lora, rewrite the to_load key_map's diffusion
block indices before calling the original) to the full 28/40/52 chain,
driven entirely by the central tables in anima_arch.py -- in BOTH
directions: a smaller-architecture LoRA applied to a larger model
("expand", e.g. 28-block LoRA on a 40-block model), and a larger-
architecture LoRA applied to a smaller model ("reduce", e.g. a genuinely
40-block LoRA -- native or physically expanded by expand.py -- applied to
the 28-block base model). Without the "reduce" direction, ComfyUI's default
key-matching applies a 40-block LoRA's own "block 5" tensor to the 28-block
model's ACTUAL, differently-identified block 5, producing exactly the kind
of incoherent output a real block-identity mismatch causes -- the same
failure mode Task 2/3 already demonstrated for the "expand" direction with
no patch at all.

Detection, unlike a hand-rolled per-pair check, is generic:
  - the LORA's source architecture is bucketed from the highest DiT block
    index its own keys reference (anima_arch.bucket_block_count) -- so a
    partial-coverage LoRA is still correctly attributed to its real source
    architecture, not just an exact 0..27 / 0..39 / 0..51 match.
  - the MODEL's target architecture requires an exact, contiguous 0..N-1
    block set for one of the known counts -- a real loaded model always has
    a complete set of blocks for whatever architecture it is, so there is no
    partial-coverage case to worry about on this side; anything else is
    treated as an unknown layout and left untouched.
  - source == target => nothing to do (already native).
  - source < target => "expand": rewrite to_load's VALUES (the model-side
    target key) from the naive/uncorrected block number to
    anima_arch.get_mapping(source, target)[naive_number] -- unchanged from
    the original single-direction implementation.
  - source > target => "reduce": rewrite to_load's KEYS (the LoRA-side
    lookup template) from the naive/uncorrected block number to
    anima_arch.get_reduction_mapping(source, target)[naive_number], leaving
    the VALUE (the real, already-correct host model parameter) untouched.
    This is the mirror image of "expand": there, the LoRA's own numbering is
    correct and the model-side target needs correcting; here, the model-side
    target is already correct (it's the real host model) and the LoRA's own
    (larger-architecture) numbering needs to be substituted in so
    comfy.lora.load_lora's `lora[f"{x}.diff"]` lookup finds the adapter's
    real tensor for the block that host position physically corresponds to,
    instead of coincidentally matching by naive number.
  - no known mapping for the (source, target) pair (an architecture Part 1
    doesn't know about) => leave untouched + log why.

"Already remapped, don't double-remap": detection is re-derived from scratch
on every call purely from the keys actually present, not from any stored
state. A LoRA that has already been converted to target 40 blocks (by this
patch, by a from-file converter, or by having been trained natively on 40
blocks) is, by definition, indistinguishable from a native 40-block LoRA --
its own keys now reference blocks 0..39 directly -- so it buckets as
source_count=40, and applying it to a 40-block model correctly resolves to
"native match, nothing to do". No extra state/flag is needed for this.
"""

from __future__ import annotations

import logging
import os
import re

import comfy.lora

from . import anima_arch

LOG_PREFIX = "[Anima LoRA/ControlNet Patch]"
_PATCH_MARKER = "_anima_compat_lora_patch"
# Marker used by the older, single-purpose ComfyUI-Anima-2.9B-loraPatch. If
# that patch is already installed underneath us, installing on top of it
# risks double-remapping (see README "Coexistence with the older patches").
_SIBLING_MARKER = "_anima29b_lora_patch"

# Matches a model-side (key_map value) diffusion block key. Anchored so that
# diffusion_model.llm_adapter.blocks.N.* is NOT matched.
_MODEL_BLOCK_RE = re.compile(r"^(diffusion_model\.blocks\.)(\d+)(\..*)$")

# Matches a LoRA-side key belonging to a diffusion block, in the formats seen
# in the wild for Anima (kohya / peft-style / bare).
_LORA_BLOCK_RES = (
    re.compile(r"^lora_unet_blocks_(\d+)_"),
    re.compile(r"^diffusion_model\.blocks\.(\d+)\."),
    re.compile(r"^blocks\.(\d+)\."),
)

# Same patterns as _LORA_BLOCK_RES, but capturing prefix/suffix too -- needed
# to rewrite the LoRA-side KEY itself (the "reduce" direction), not just
# detect an index. Kept as separate compiled objects (some ambiguity is
# unavoidable without a single shared table across two different capture
# shapes) but textually aligned -- update both together if a new naming
# convention needs to be recognized.
_LORA_BLOCK_RES_FULL = (
    re.compile(r"^(lora_unet_blocks_)(\d+)(_.*)$"),
    re.compile(r"^(diffusion_model\.blocks\.)(\d+)(\..*)$"),
    re.compile(r"^(blocks\.)(\d+)(\..*)$"),
)

_orig_load_lora = None


def _enabled() -> bool:
    return os.environ.get("ANIMA_COMPAT_LORA_REMAP", "1").strip().lower() not in ("0", "off", "false", "no")


def _model_block_indices(to_load) -> set:
    out = set()
    for value in to_load.values():
        if not isinstance(value, str):
            continue
        m = _MODEL_BLOCK_RE.match(value)
        if m is not None:
            out.add(int(m.group(2)))
    return out


def _lora_block_indices(lora) -> set:
    out = set()
    for key in lora.keys():
        if not isinstance(key, str):
            continue
        for rex in _LORA_BLOCK_RES:
            m = rex.match(key)
            if m is not None:
                out.add(int(m.group(1)))
                break
    return out


def _is_anima(to_load) -> bool:
    for value in to_load.values():
        if isinstance(value, str) and value.startswith("diffusion_model.llm_adapter."):
            return True
    return False


def _match_lora_key_block(key):
    """Like _lora_block_indices' matching, but returns (prefix, index,
    suffix) so the key can be rewritten, not just detected."""
    if not isinstance(key, str):
        return None, None, None
    for rex in _LORA_BLOCK_RES_FULL:
        m = rex.match(key)
        if m is not None:
            return m.group(1), int(m.group(2)), m.group(3)
    return None, None, None


def _remap_key_map(to_load, forward_map):
    """"Expand" direction (source < target): rewrite to_load's VALUES (the
    model-side target key) from the naive/uncorrected block number to
    forward_map[naive_number]. Return (new_to_load, remapped_count,
    dropped_count)."""
    out = {}
    remapped = 0
    dropped = 0
    for key, value in to_load.items():
        m = _MODEL_BLOCK_RE.match(value) if isinstance(value, str) else None
        if m is None:
            out[key] = value
            continue
        src = int(m.group(2))
        dst = forward_map.get(src)
        if dst is None:
            # This source block has no destination in the target architecture
            # (shouldn't happen for a forward/expansion map, since every
            # source index has a destination by construction -- defensive
            # only). Drop rather than guess.
            dropped += 1
            continue
        out[key] = "{}{}{}".format(m.group(1), dst, m.group(3))
        if dst != src:
            remapped += 1
    return out, remapped, dropped


def _remap_key_map_for_reduction(to_load, reduction_map):
    """"Reduce" direction (source > target): rewrite to_load's KEYS (the
    LoRA-side lookup template ComfyUI generated from the host model's own,
    smaller-architecture numbering) to reduction_map[naive_number] (the
    LARGER-architecture number the adapter's own file actually uses),
    leaving the VALUE (the real host model parameter -- already correct)
    untouched. Return (new_to_load, remapped_count, dropped_count)."""
    out = {}
    remapped = 0
    dropped = 0
    for key, value in to_load.items():
        prefix, idx, suffix = _match_lora_key_block(key)
        if idx is None:
            out[key] = value
            continue
        new_idx = reduction_map.get(idx)
        if new_idx is None:
            # Shouldn't happen: get_reduction_mapping is total over the
            # smaller architecture's full index range. Drop rather than
            # guess if it ever does.
            dropped += 1
            continue
        out["{}{}{}".format(prefix, new_idx, suffix)] = value
        if new_idx != idx:
            remapped += 1
    return out, remapped, dropped


def _decide(lora, to_load):
    """Return (direction, source_count, target_count, mapping), where
    direction is "expand" (source < target, mapping is source_idx ->
    target_idx, applied to to_load's VALUES) or "reduce" (source > target,
    mapping is target_idx -> source_idx, applied to to_load's KEYS); or None
    meaning "leave to_load exactly as-is" (already logged why, if
    relevant)."""
    if not _is_anima(to_load):
        return None

    model_blocks = _model_block_indices(to_load)
    if not model_blocks:
        return None

    target_count = None
    highest = max(model_blocks)
    if model_blocks == set(range(highest + 1)) and (highest + 1) in anima_arch.ANIMA_BLOCK_COUNTS:
        target_count = highest + 1
    if target_count is None:
        logging.info(
            "{} unknown Anima block layout on the model side ({} blocks); leaving LoRA untouched.".format(
                LOG_PREFIX, len(model_blocks)
            )
        )
        return None

    lora_blocks = _lora_block_indices(lora)
    if not lora_blocks:
        return None  # this LoRA doesn't reference any DiT block -- nothing to remap

    source_count = anima_arch.bucket_block_count(max(lora_blocks) + 1)
    if source_count is None:
        logging.info(
            "{} LoRA references block index {}, beyond every known Anima architecture; "
            "leaving it untouched.".format(LOG_PREFIX, max(lora_blocks))
        )
        return None

    if source_count == target_count:
        return None  # already native for this target -- nothing to do

    if source_count < target_count:
        forward_map = anima_arch.get_mapping(source_count, target_count)
        if forward_map is None:
            logging.info(
                "{} no known mapping from a {}-block LoRA to a {}-block model; "
                "leaving it untouched.".format(LOG_PREFIX, source_count, target_count)
            )
            return None
        return "expand", source_count, target_count, forward_map

    reduction_map = anima_arch.get_reduction_mapping(source_count, target_count)
    if reduction_map is None:
        logging.info(
            "{} no known mapping from a {}-block LoRA down to a {}-block model; "
            "leaving it untouched.".format(LOG_PREFIX, source_count, target_count)
        )
        return None
    return "reduce", source_count, target_count, reduction_map


def _patched_load_lora(lora, to_load, *args, **kwargs):
    try:
        if _enabled():
            decision = _decide(lora, to_load)
            if decision is not None:
                direction, source_count, target_count, mapping = decision
                if direction == "expand":
                    new_to_load, remapped, dropped = _remap_key_map(to_load, mapping)
                else:
                    new_to_load, remapped, dropped = _remap_key_map_for_reduction(to_load, mapping)
                extra = " ({} keys dropped, no destination block)".format(dropped) if dropped else ""
                verb = "up" if direction == "expand" else "down"
                logging.info(
                    "{} {}-block LoRA on {}-block Anima host: remapped {} target keys{} ({}).".format(
                        LOG_PREFIX, source_count, target_count, remapped, extra, verb
                    )
                )
                to_load = new_to_load
    except Exception as err:
        # Never let this patch break normal LoRA loading.
        logging.warning("{} LoRA remap skipped due to error: {}".format(LOG_PREFIX, err))
    return _orig_load_lora(lora, to_load, *args, **kwargs)


setattr(_patched_load_lora, _PATCH_MARKER, True)


def install():
    global _orig_load_lora
    current = getattr(comfy.lora, "load_lora", None)
    if current is None:
        logging.warning(
            "{} comfy.lora.load_lora not found; this ComfyUI version is not supported "
            "by the LoRA half of this patch.".format(LOG_PREFIX)
        )
        return False
    if getattr(current, _PATCH_MARKER, False):
        logging.info("{} LoRA hook already installed; skipping.".format(LOG_PREFIX))
        return True
    if getattr(current, _SIBLING_MARKER, False):
        logging.warning(
            "{} ComfyUI-Anima-2.9B-loraPatch is already active on comfy.lora.load_lora. "
            "Installing this unified patch on top of it would risk double-remapping "
            "28-block LoRAs. Skipping the LoRA half of this patch -- please remove or "
            "disable ComfyUI-Anima-2.9B-loraPatch (this package supersedes it: 28->40, "
            "28->52, and 40->52 all handled in one place).".format(LOG_PREFIX)
        )
        return False
    _orig_load_lora = current
    comfy.lora.load_lora = _patched_load_lora
    logging.info(
        "{} LoRA remap installed (28<->40, 28<->52, 40<->52, both directions). "
        "Set ANIMA_COMPAT_LORA_REMAP=0 to disable.".format(LOG_PREFIX)
    )
    return True
