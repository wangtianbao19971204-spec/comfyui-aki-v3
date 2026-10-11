"""Task 3 Part 2 -- physical Anima adapter expansion.

Unlike lora_patch.py / controlnet_patch.py (Part 1: remap block indices at
LOAD/APPLY time, leaving the source file untouched), this module produces a
NEW file whose tensors physically target a larger Anima architecture. This
is an experimental, offline, batch tool -- not a ComfyUI node, not installed
automatically, and not wired into anything ComfyUI runs during a session.

It reuses anima_arch.py (the same single source of truth Part 1 uses) for
every block-count mapping, so the runtime patch and this file-expansion tool
can never silently disagree about what "28->40" means.

Expansion strategy: SEQUENTIAL, not direct.
------------------------------------------
28->52 is performed as 28->40 followed by 40->52, never as one direct jump,
because that is how the real models themselves were built: Task 3 Part 1's
own tensor-level investigation proved every kept-from-2.9B block in
Anima-3.8B is bit-identical to the corresponding Anima-2.9B block (not to
some independently-re-expanded copy of the 28-block base) -- i.e. 3.8B is
architecturally "expand 2.9B", not "expand base again, differently, to reach
52". A direct 28->52 jump would also need a *third*, undocumented neighbor
relationship for the 12 blocks inserted at the 40->52 stage (their nearest
real neighbors are 2.9B-layout blocks, some of which only exist because of
the FIRST expansion) -- sequential expansion sidesteps that entirely by
reusing the exact same single-step algorithm twice, composing naturally.

Inherited blocks are always copied exactly, byte for byte -- verified by the
test suite. Only the newly-inserted blocks in each step receive synthesized
tensors, from that step's own immediate front/back neighbors (whatever their
own provenance -- inherited or previously-synthesized).

Tensor-type handling: LoRA vs ControlNet-LLLite
------------------------------------------------
Both are handled with the same generic mechanism -- group every tensor key
by (block_index, remainder-of-key), copy inherited blocks' tensor groups
verbatim, and for inserted blocks apply the configured combination mode to
every same-named tensor present in both neighbors. This makes no assumption
about which specific tensor "kinds" (LoRA down/up/alpha/diff/dora_scale,
LLLite down/mid/cond_to_film/up/depth_embed) exist -- whatever a real block
has, its inserted neighbors get an equivalent, shape-matched tensor.

That said, the underlying MATH is not identical in nature between the two
adapter types, and is worth stating explicitly (see README.md "Part 2" for
the full discussion):

- ControlNet-LLLite's down/mid/cond_to_film/up tensors are ordinary dense
  Linear weight matrices forming a small MLP. Linearly blending two such
  matrices produces a mathematically well-defined "interpolated" MLP -- the
  same kind of operation the reference blend-ratio technique this project
  studied performs on full checkpoint weights.
- A LoRA's down (A) and up (B) matrices are a low-rank FACTORIZATION of a
  weight-space delta (roughly delta = B @ A * scale). Blending A and B
  *separately* is only an approximation of "blend the resulting delta" --
  (r*A1+  (1-r)*A2) is not the same matrix as blending the two possible
  products B1@A1 and B2@A2 would suggest, since matrix multiplication does
  not distribute over that kind of elementwise mix. Front-copy (mode="front",
  reproducing one whole neighbor's factorization exactly, unchanged) has no
  such ambiguity and is the default for exactly this reason; "blend" mode is
  offered as an explicitly-labeled, mathematically approximate alternative,
  not a more "correct" default.
- `depth_embed` (ControlNet-LLLite) and `alpha` (LoRA) are treated the same
  generic way. Neither has a "correct" value derivable without retraining;
  front-copy or blend are both heuristics, not exact reconstructions.

Base-model mixing (the reference script's `extend_ratio`, blending a
synthesized tensor toward the TARGET checkpoint's own native weight at that
position) is deliberately NOT implemented here. There is no valid analog for
either adapter type: a full pretrained weight tensor and a LoRA low-rank
factor are different mathematical objects entirely (wrong shape/rank to even
compare), and there is no "native" LLLite module at a newly-inserted
position in any real checkpoint to blend toward -- the position never had
one. Adapter expansion here always operates purely in adapter space.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import torch
from safetensors import safe_open
from safetensors.torch import save_file

# Make `import anima_arch` work whether this file is imported as part of the
# ComfyUI-Anima-LoRA-ControlNet-Patch package or run directly as a standalone
# CLI script (python expand.py ...).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anima_arch

ADAPTER_LORA = "lora"
ADAPTER_CONTROLNET = "controlnet"

# Block-key patterns. Textually aligned with lora_patch.py's own
# _LORA_BLOCK_RES / _MODEL_BLOCK_RE (kept as separate compiled objects here
# since this module needs the prefix and suffix captured too, not just the
# index) -- if the naming conventions Part 1 recognizes ever change, update
# both places together.
_LORA_BLOCK_RES = (
    re.compile(r"^(lora_unet_blocks_)(\d+)(_.*)$"),          # kohya
    re.compile(r"^(diffusion_model\.blocks\.)(\d+)(\..*)$"),  # peft / generic
    re.compile(r"^(blocks\.)(\d+)(\..*)$"),                   # bare
)

# Matches comfy.ldm.anima.lllite.MODULE_PATTERN's own naming exactly:
# lllite_dit_blocks_{N}_{target} -- but target itself may have a further
# suffix (.down.weight etc.), so this captures up through the trailing "_"
# plus everything after as the suffix.
_LLLITE_BLOCK_RE = re.compile(r"^(lllite_dit_blocks_)(\d+)(_.*)$")

_LLLITE_SIGNATURE_KEY = "lllite_conditioning1.conv1.weight"


def parse_block_key(key: str, adapter_type: str) -> Tuple[Optional[str], Optional[int], Optional[str]]:
    if adapter_type == ADAPTER_CONTROLNET:
        m = _LLLITE_BLOCK_RE.match(key)
        if m:
            return m.group(1), int(m.group(2)), m.group(3)
        return None, None, None
    for rex in _LORA_BLOCK_RES:
        m = rex.match(key)
        if m:
            return m.group(1), int(m.group(2)), m.group(3)
    return None, None, None


def detect_adapter_type(state_dict: Dict[str, torch.Tensor]) -> str:
    if _LLLITE_SIGNATURE_KEY in state_dict:
        return ADAPTER_CONTROLNET
    return ADAPTER_LORA


def detect_source_block_count(state_dict: Dict[str, torch.Tensor], adapter_type: str) -> Optional[int]:
    indices = set()
    for key in state_dict:
        _, idx, _ = parse_block_key(key, adapter_type)
        if idx is not None:
            indices.add(idx)
    if not indices:
        return None
    return anima_arch.bucket_block_count(max(indices) + 1)


@dataclass
class ExpansionStats:
    adapter_type: str
    source_count: int
    target_count: int
    original_tensors: int
    output_tensors: int
    inherited_tensors: int = 0
    generated_tensors: int = 0
    unparsed_tensors: int = 0
    source_blocks: List[int] = field(default_factory=list)
    target_blocks_produced: List[int] = field(default_factory=list)
    missing_target_blocks: List[int] = field(default_factory=list)
    dtype_changes: List[str] = field(default_factory=list)
    shape_mismatches: List[str] = field(default_factory=list)

    def report(self) -> str:
        lines = [
            f"Input architecture:       {self.source_count}",
            f"Target architecture:      {self.target_count}",
            f"Adapter type:             {self.adapter_type}",
            f"Original tensors:         {self.original_tensors}",
            f"Output tensors:           {self.output_tensors}",
            f"Inherited tensors:        {self.inherited_tensors}",
            f"Generated tensors:        {self.generated_tensors}",
            f"Unparsed tensors:         {self.unparsed_tensors}",
            f"Source blocks detected:   {self.source_blocks}",
            f"Target blocks produced:   {self.target_blocks_produced}",
            f"Missing target blocks:    {self.missing_target_blocks}",
            f"dtype changes:            {self.dtype_changes}",
            f"shape mismatches:         {self.shape_mismatches}",
        ]
        return "\n".join(lines)


def _group_by_block(state_dict, adapter_type):
    """-> (grouped: {block_idx: {suffix: tensor}}, prefix, other_keys: {key: tensor})"""
    grouped: Dict[int, Dict[str, torch.Tensor]] = {}
    other: Dict[str, torch.Tensor] = {}
    prefix = None
    unparsed = 0
    for key, tensor in state_dict.items():
        p, idx, suffix = parse_block_key(key, adapter_type)
        if idx is None:
            other[key] = tensor
            continue
        prefix = prefix or p
        grouped.setdefault(idx, {})[suffix] = tensor
    return grouped, prefix, other, unparsed


def _combine(front: torch.Tensor, back: Optional[torch.Tensor], mode: str, blend_ratio: float) -> torch.Tensor:
    if mode == "front" or back is None or back.shape != front.shape:
        return front.clone()
    if front.dtype in (torch.float32, torch.float64):
        blended = front * blend_ratio + back * (1.0 - blend_ratio)
    else:
        # bf16/fp16: upcast for the blend, cast back to avoid precision loss
        blended = (front.float() * blend_ratio + back.float() * (1.0 - blend_ratio)).to(front.dtype)
    return blended


def expand_one_step(
    state_dict: Dict[str, torch.Tensor],
    adapter_type: str,
    source_count: int,
    target_count: int,
    mode: str = "front",
    blend_ratio: float = 1.0,
) -> Tuple[Dict[str, torch.Tensor], ExpansionStats]:
    """Perform exactly one verified expansion step (28->40 or 40->52)."""
    forward_map = anima_arch.get_mapping(source_count, target_count)
    if forward_map is None:
        raise ValueError(f"No known single-step mapping from {source_count} to {target_count} blocks.")

    grouped, prefix, other, unparsed = _group_by_block(state_dict, adapter_type)
    source_blocks = sorted(grouped.keys())

    new_grouped: Dict[int, Dict[str, torch.Tensor]] = {}
    inherited = 0
    for src_idx, tensors in grouped.items():
        dst_idx = forward_map.get(src_idx)
        if dst_idx is None:
            # Source references a block index this map doesn't know about
            # (e.g. a partial-coverage LoRA whose max index undershoots the
            # bucketed source_count but touches an index the *bucket*
            # doesn't actually cover for this mapping's domain -- shouldn't
            # happen when source_count was derived correctly, but don't
            # silently drop real tensors if it does).
            continue
        new_grouped[dst_idx] = {suffix: t.clone() for suffix, t in tensors.items()}
        inherited += len(tensors)

    inserted_targets = sorted(set(range(target_count)) - set(forward_map.values()))
    generated = 0
    for ins_idx in inserted_targets:
        placed_before = [i for i in new_grouped if i < ins_idx]
        placed_after = [i for i in new_grouped if i > ins_idx]
        if not placed_before and not placed_after:
            continue  # nothing to synthesize from -- adapter has no blocks at all
        front_idx = max(placed_before) if placed_before else min(placed_after)
        back_idx = min(placed_after) if placed_after else front_idx
        front_tensors = new_grouped[front_idx]
        back_tensors = new_grouped.get(back_idx, {})
        synthesized = {}
        for suffix, front_t in front_tensors.items():
            back_t = back_tensors.get(suffix)
            synthesized[suffix] = _combine(front_t, back_t, mode, blend_ratio)
        new_grouped[ins_idx] = synthesized
        generated += len(synthesized)

    out: Dict[str, torch.Tensor] = dict(other)
    for idx, tensors in new_grouped.items():
        for suffix, tensor in tensors.items():
            out[f"{prefix}{idx}{suffix}"] = tensor

    target_blocks_produced = sorted(new_grouped.keys())
    missing = sorted(set(range(target_count)) - set(target_blocks_produced)) if target_blocks_produced else []

    stats = ExpansionStats(
        adapter_type=adapter_type,
        source_count=source_count,
        target_count=target_count,
        original_tensors=len(state_dict),
        output_tensors=len(out),
        inherited_tensors=inherited,
        generated_tensors=generated,
        unparsed_tensors=unparsed,
        source_blocks=source_blocks,
        target_blocks_produced=target_blocks_produced,
        missing_target_blocks=missing,
    )
    return out, stats


def resolve_expansion_path(source_count: int, target_count: int) -> List[int]:
    known = anima_arch.ANIMA_BLOCK_COUNTS
    if source_count not in known or target_count not in known:
        raise ValueError(f"Unknown architecture in ({source_count}, {target_count}); known: {known}")
    if source_count >= target_count:
        raise ValueError(f"Only upward expansion is supported (got {source_count} -> {target_count}).")
    return [c for c in known if source_count <= c <= target_count]


def expand_adapter(
    state_dict: Dict[str, torch.Tensor],
    adapter_type: str,
    source_count: int,
    target_count: int,
    mode: str = "front",
    blend_ratio: float = 1.0,
) -> Tuple[Dict[str, torch.Tensor], List[ExpansionStats]]:
    """Public entry point: expand from source_count to target_count,
    SEQUENTIALLY through every known intermediate architecture (see module
    docstring for why), never as a single direct jump."""
    path = resolve_expansion_path(source_count, target_count)
    current = state_dict
    stats_list = []
    for i in range(len(path) - 1):
        current, stats = expand_one_step(current, adapter_type, path[i], path[i + 1], mode, blend_ratio)
        stats_list.append(stats)
    return current, stats_list


def verify_inherited_tensors_exact(
    original_state_dict: Dict[str, torch.Tensor],
    expanded_state_dict: Dict[str, torch.Tensor],
    adapter_type: str,
    source_count: int,
    target_count: int,
) -> List[str]:
    """Returns a list of problem descriptions (empty = all inherited tensors
    verified byte-identical). This checks the FULL (possibly multi-step,
    composed) source->target mapping directly against the final output,
    regardless of how many intermediate steps were taken internally."""
    forward_map = anima_arch.get_mapping(source_count, target_count)
    if forward_map is None:
        return [f"no known mapping {source_count}->{target_count}"]

    orig_grouped, orig_prefix, _, _ = _group_by_block(original_state_dict, adapter_type)
    new_grouped, new_prefix, _, _ = _group_by_block(expanded_state_dict, adapter_type)

    problems = []
    for src_idx, tensors in orig_grouped.items():
        dst_idx = forward_map.get(src_idx)
        if dst_idx is None:
            continue
        new_tensors = new_grouped.get(dst_idx, {})
        for suffix, orig_t in tensors.items():
            new_t = new_tensors.get(suffix)
            if new_t is None:
                problems.append(f"missing inherited tensor for source block {src_idx} -> {dst_idx}{suffix}")
            elif not torch.equal(orig_t, new_t):
                problems.append(f"inherited tensor changed: source block {src_idx} -> {dst_idx}{suffix}")
    return problems


# ----------------------------------------------------------------------------
# File-level safety + metadata + CLI
# ----------------------------------------------------------------------------

def resolve_safe_output_path(input_path: str, output_path: str, force: bool = False) -> Path:
    input_abs = Path(input_path).resolve()
    output_abs = Path(output_path).resolve()
    if input_abs == output_abs:
        raise ValueError(
            f"Refusing to write: output path is identical to the input path ({input_abs})."
        )
    if output_abs.exists() and not force:
        raise FileExistsError(
            f"Output file already exists: {output_abs}. Pass force=True / --force to overwrite it "
            "(the SOURCE file is never touched either way)."
        )
    return output_abs


def build_output_metadata(original_metadata: dict, adapter_type: str, source_count: int,
                           target_count: int, mode: str, blend_ratio: float, source_filename: str) -> dict:
    """Preserves every existing metadata key unchanged (some, like an Anima
    LLLite checkpoint's lllite.* keys, are load-bearing -- native ComfyUI
    reads architecture parameters from them) and adds new, distinctly
    prefixed informational keys."""
    meta = dict(original_metadata or {})
    meta["anima_compat.expanded_from_blocks"] = str(source_count)
    meta["anima_compat.expanded_to_blocks"] = str(target_count)
    meta["anima_compat.expansion_mode"] = mode
    meta["anima_compat.blend_ratio"] = str(blend_ratio)
    meta["anima_compat.source_file"] = source_filename
    meta["anima_compat.expanded_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["anima_compat.tool"] = "ComfyUI-Anima-LoRA-ControlNet-Patch/expand.py (experimental)"
    return meta


def expand_file(input_path: str, output_path: str, target_count: int, mode: str = "front",
                 blend_ratio: float = 1.0, force: bool = False) -> ExpansionStats:
    output_abs = resolve_safe_output_path(input_path, output_path, force=force)

    with safe_open(input_path, framework="pt", device="cpu") as f:
        metadata = f.metadata() or {}
        state_dict = {k: f.get_tensor(k) for k in f.keys()}

    adapter_type = detect_adapter_type(state_dict)
    source_count = detect_source_block_count(state_dict, adapter_type)
    if source_count is None:
        raise ValueError(f"Could not detect a source block count for {input_path} (no block keys found).")

    expanded, stats_list = expand_adapter(state_dict, adapter_type, source_count, target_count, mode, blend_ratio)

    problems = verify_inherited_tensors_exact(state_dict, expanded, adapter_type, source_count, target_count)
    if problems:
        raise RuntimeError(
            "Inherited-tensor verification failed (expansion aborted, nothing written):\n"
            + "\n".join(problems[:20])
        )

    out_meta = build_output_metadata(metadata, adapter_type, source_count, target_count, mode, blend_ratio,
                                      Path(input_path).name)
    output_abs.parent.mkdir(parents=True, exist_ok=True)
    save_file(expanded, str(output_abs), metadata=out_meta)

    # Combined stats across all steps for the top-level report, but the
    # source/target counts reflect the overall requested expansion.
    combined = ExpansionStats(
        adapter_type=adapter_type,
        source_count=source_count,
        target_count=target_count,
        original_tensors=stats_list[0].original_tensors,
        output_tensors=stats_list[-1].output_tensors,
        inherited_tensors=sum(s.inherited_tensors for s in stats_list),
        generated_tensors=sum(s.generated_tensors for s in stats_list),
        unparsed_tensors=stats_list[0].unparsed_tensors,
        source_blocks=stats_list[0].source_blocks,
        target_blocks_produced=stats_list[-1].target_blocks_produced,
        missing_target_blocks=stats_list[-1].missing_target_blocks,
    )
    return combined


def _main():
    parser = argparse.ArgumentParser(
        description="Task 3 Part 2 (experimental): physically expand an Anima LoRA or "
                    "ControlNet-LLLite adapter to a larger block-count architecture. "
                    "The source file is NEVER modified."
    )
    parser.add_argument("-i", "--input", required=True, help="Path to the source 28- or 40-block adapter")
    parser.add_argument("-o", "--output", required=True, help="Path for the new expanded file (must differ from input)")
    parser.add_argument("-t", "--target", type=int, required=True, choices=list(anima_arch.ANIMA_BLOCK_COUNTS),
                        help="Target block count (40 or 52)")
    parser.add_argument("--mode", choices=["front", "blend"], default="front",
                        help="Inserted-block synthesis mode (default: front = exact copy of the nearest neighbor)")
    parser.add_argument("--blend-ratio", type=float, default=1.0,
                        help="Only used with --mode blend: front*r + back*(1-r) (default 1.0 = same as front)")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output file")
    args = parser.parse_args()

    stats = expand_file(args.input, args.output, args.target, mode=args.mode,
                         blend_ratio=args.blend_ratio, force=args.force)
    print(stats.report())
    print(f"\nSaved: {Path(args.output).resolve()}")


if __name__ == "__main__":
    _main()
