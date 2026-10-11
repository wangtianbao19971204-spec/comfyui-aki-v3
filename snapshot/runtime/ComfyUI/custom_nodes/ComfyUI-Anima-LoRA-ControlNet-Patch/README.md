# ComfyUI-Anima-LoRA-ControlNet-Patch

A single, unified patch that makes Anima LoRAs and ControlNet-LLLite checkpoints trained for one block-count Anima architecture (28, 40, or 52 transformer blocks) work correctly on a *different* one — larger or smaller — automatically, without converting any files, and without any new workflow node.

This supersedes maintaining separate single-purpose patches for each Anima generation ([`ComfyUI-Anima-2.9B-loraPatch`](#acknowledgements), [`ComfyUI-Anima-2.9B-controlnetPatch`](#acknowledgements)) with one package that covers the full 28↔40↔52 chain, both directions, for both LoRAs and ControlNets.

## Why Anima architectures need block remapping

Anima 2.9B and Anima 3.8B are each a **depth-expansion** of the previous, smaller Anima model — new transformer blocks are spliced into specific positions of an otherwise byte-identical, relocated copy of every block from the smaller model:

```
Anima Base: 28 blocks  --(insert 12 new blocks)-->  Anima 2.9B: 40 blocks  --(insert 12 more)-->  Anima 3.8B: 52 blocks
```

ComfyUI's own LoRA loader and its native Anima LLLite (ControlNet) implementation both address transformer blocks by a plain numeric position (`blocks.N`). Since block *N* means something different in each of the three architectures once you get past index 1, a LoRA or ControlNet trained against one model's block positions lands on the **wrong** physical block if applied to a different-sized model without translation — usually silently, since the target block still exists, it's just not the same block anymore.

## The 28→40→52 progression and exact block mappings

**28→40** (established by [sparklingcoffee777](#acknowledgements)'s `ComfyUI-Anima-2.9B-loraPatch`, and independently re-verified in this project's own development via direct `torch.equal()` weight comparison):

```
base   0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27
2.9B   0  1  3  4  6  7  9 10 12 13 15 16 18 19 20 22 23 25 26 28 29 31 32 34 35 37 38 39
```

**40→52** (independently derived from scratch for this project, via a brute-force, all-pairs `torch.equal()` search across every real transformer block in `Anima-2.9B-preview-v1.safetensors` and `Anima-3.8B.safetensors` — every one of the 40 blocks matched exactly one 3.8B block, across four different weight-tensor types per block, with zero collisions and zero misses. This result happens to exactly match the insertion tuple used, without in-repo weight verification, by [Lakeside529](#acknowledgements)'s `ComfyUI-Anima-3.8B-LoRA-Bridge` — useful cross-confirmation, not the source of this table):

```
2.9B   0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39
3.8B   0  1  2  4  5  6  8  9 10 12 13 14 16 17 18 20 21 22 24 25 26 28 29 30 32 33 34 36 37 38 40 41 42 44 45 46 48 49 50 51
```

**28→52** is never hand-written — it is always *derived by composing the two tables above* (`anima_arch.py`'s `MAP_28_52`), so there is exactly one place that could disagree with itself. The composed result matches the flattened literal `ComfyUI-Anima-3.8B-LoRA-Bridge`'s own test suite asserts.

**Downward directions** (40→28, 52→28, 52→40 — e.g. a genuinely 40-block LoRA applied to the 28-block base model) use the exact same tables, read the other way: `get_reduction_mapping(K, M)` for `M < K` is simply `get_mapping(M, K)`. No separate mapping data exists or is needed for the downward case.

## What this package does

Two independent monkeypatches, installed once at import, **both directions** (a smaller-architecture adapter applied to a larger model, e.g. a 28-block LoRA on the 40-block model; and a larger-architecture adapter applied to a smaller model, e.g. a genuinely 40-block LoRA, native or physically expanded, applied to the 28-block base model):

1. **LoRA** — wraps `comfy.lora.load_lora` (the same target `ComfyUI-Anima-2.9B-loraPatch` patches). Detects the LoRA's source architecture from the highest DiT block index its own keys reference, detects the model's target architecture from its key_map, looks up the correct mapping, and rewrites the LoRA→model key_map before handing off to the original, unmodified `load_lora`.
   - *Upward* (source < target): rewrites `to_load`'s **values** (the model-side target key) from the naive block number to its correct destination.
   - *Downward* (source > target): rewrites `to_load`'s **keys** (the LoRA-side lookup template) from the host's naive block number to the adapter's real, larger-architecture number — the model-side value is already correct (it's the real host parameter); it's the *lookup into the adapter file* that needs correcting. Reuses the exact same verified tables, just applied in the direction they always encoded.
   Works with ComfyUI's standard `LoraLoader`/`LoraLoaderModelOnly` nodes — nothing to replace.

2. **ControlNet / Anima LLLite** — wraps ComfyUI's native `AnimaLLLiteApply.apply_patch` and `comfy.ldm.anima.lllite.AnimaLLLite.apply` (the same targets `ComfyUI-Anima-2.9B-controlnetPatch` patches). At `apply_patch` time (the only point that has both the checkpoint's own block count and the live host model's block count), decides whether remapping is needed and installs a translation table directly on the loaded checkpoint object; `AnimaLLLite.apply` consults it on every forward call. Both directions produce the exact same shape of map (`host_block_index -> checkpoint_module_index`), so the consuming wrapper needs no direction-awareness at all — only *which* `anima_arch` function builds the table differs (`get_inverse_mapping` upward, partial — 12 host positions per step have no checkpoint-trained counterpart and correctly no-op; `get_reduction_mapping` downward, total — every smaller-host position has a real, verified ancestor in the larger checkpoint). Works with ComfyUI's standard native "Load Model Patch" / "Apply Anima LLLite" nodes, and by extension any custom node (like `ComfyUI-UltimateSDUpscale-FLS-LLLite`) that calls the same native path.

Both halves share one **central mapping module** (`anima_arch.py`) — pure data and pure functions, no ComfyUI/torch dependency, fully unit-testable on its own. Neither half hard-codes its own copy of the block tables.

## How automatic detection works

- **Architecture is never inferred from a filename.** Detection is purely structural: the number of transformer blocks a LoRA's own keys reference, or a ControlNet-LLLite checkpoint's own trained module count, or the live host model's actual block list length.
- A LoRA/ControlNet's source architecture is *bucketed* to the smallest known architecture (28/40/52) that could structurally contain the highest block index it references — this correctly handles partial coverage (most real LoRAs/ControlNets don't touch every single block).
- The model's target architecture requires an exact, complete `0..N-1` block set for a known count — a real loaded model always has this, so there's no partial-coverage ambiguity on that side.
- Source == target → nothing to do (native match).
- Source < target → **expand** (`get_mapping`/`get_inverse_mapping`).
- Source > target → **reduce** (`get_reduction_mapping`).
- No known mapping for the (source, target) pair (an architecture outside 28/40/52) → left completely untouched, with a log message explaining why.

## When remapping is intentionally skipped

| Situation | Behavior |
|---|---|
| Source and target are the same architecture | Pass through unchanged |
| Non-Anima LoRA/model | Pass through unchanged |
| Unknown/unrecognized block-count layout on either side | Pass through unchanged + log message |
| Either count outside {28, 40, 52} | Pass through unchanged + log message |
| A LoRA/ControlNet already expressed in the target's own numbering (already converted, or genuinely native) | Pass through unchanged — detection is re-derived from the actual keys present on every call, not from stored state, so there is no separate "already remapped" flag needed and no risk of double-remapping *within this package* |

**Coexistence with the older, single-purpose patches**: if `ComfyUI-Anima-2.9B-loraPatch` and/or `ComfyUI-Anima-2.9B-controlnetPatch` are *also* installed, this package detects their markers at startup and **declines to install** the corresponding half (with a clear warning), rather than risk double-remapping the 28→40 case both would otherwise try to handle. Disable/remove the older, narrower patches once you're happy with this one — they're fully superseded (28→40 behaves identically; 28→52, 40→52, and every downward direction are new).

## Installation

1. Put this folder into `ComfyUI/custom_nodes/`
2. Restart ComfyUI
3. Use ComfyUI's standard LoRA and ControlNet/Anima-LLLite nodes exactly as normal

**Nothing appears in the Add Node menu** — this is a pure startup patch. The log lines below are the only way to confirm it's active.

## Verifying it works

Startup log:
```
[Anima LoRA/ControlNet Patch] LoRA remap installed (28<->40, 28<->52, 40<->52, both directions). Set ANIMA_COMPAT_LORA_REMAP=0 to disable.
[Anima LoRA/ControlNet Patch] ControlNet-LLLite remap installed on 2 AnimaLLLiteApply class object(s) (28<->40, 28<->52, 40<->52, both directions). Set ANIMA_COMPAT_CONTROLNET_REMAP=0 to disable.
```
(Seeing "on 2 AnimaLLLiteApply class object(s)" is expected and correct — see the code comment in `controlnet_patch.py` for why ComfyUI can end up with two distinct copies of that class.)

When a LoRA or ControlNet actually gets remapped:
```
[Anima LoRA/ControlNet Patch] 28-block LoRA on 40-block Anima host: remapped 1040 target keys (up).
[Anima LoRA/ControlNet Patch] 40-block LoRA on 28-block Anima host: remapped 1040 target keys (down).
[Anima LoRA/ControlNet Patch] 28-block Anima ControlNet-LLLite on 52-block host: block-index remap installed (up).
```

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `ANIMA_COMPAT_LORA_REMAP` | `1` | Set to `0` to disable LoRA remapping |
| `ANIMA_COMPAT_CONTROLNET_REMAP` | `1` | Set to `0` to disable ControlNet/LLLite remapping |

## Testing

All tests are CPU-only (`[CPU ONLY]`) — no GPU, no real model checkpoint required for any of them:

- `tests/test_anima_arch.py` — pure mapping-table tests (bijectivity, exact destination indices against the reference tables above, `get_reduction_mapping`'s totality and its identity with `get_mapping` read backwards, identity/unknown-pair handling, bucketing).
- `tests/test_lora_patch.py` — detection logic for the full bidirectional matrix (28↔40/28↔52/40↔52 both ways, non-Anima, unknown layout, already-native), exact remap destinations for both directions, sibling-patch conflict detection, and end-to-end runs through ComfyUI's real `comfy.lora.load_lora` — including a direct reproduction of a real downward failure mode (a 40-block LoRA's own "block 5" tensor is a *different* physical block than the 28-block host's block 5) proving the fix lands the correct tensor.
- `tests/test_controlnet_patch.py` — the same bidirectional matrix against ComfyUI's real native `AnimaLLLiteApply`/`AnimaLLLite` classes (using tiny synthetic checkpoints and minimally-configured real `Anima`/`MiniTrainDIT` instances), plus exact submodule-routing checks (both directions) and sibling-patch conflict detection.

Run with the same Python ComfyUI itself uses, from a ComfyUI checkout, e.g. `python custom_nodes/ComfyUI-Anima-LoRA-ControlNet-Patch/tests/test_anima_arch.py`.

Beyond the CPU test suite, the 28→40, 28→52, and 40→52 ControlNet mappings (upward) have each been validated with real generations (`[GPU REQUIRED]`, not part of the automated test suite) comparing the real `animaTileRepair_v20.safetensors` checkpoint applied to the real `Anima-2.9B-preview-v1.safetensors` / `Anima-3.8B.safetensors` models against the same checkpoint's native behavior on the 28-block base model, and against the same pairing with remapping disabled. The downward direction (40→28 LoRA) was likewise validated with a real generation producing coherent output, and every direction/architecture pair has additionally been confirmed multiple times in real, independent end-to-end GUI usage across two separate ComfyUI installations.

## Known limitations

- **Partial-coverage ambiguity in the shared low-index range**: blocks 0–27 exist (at some position) in every Anima architecture. A LoRA/ControlNet that only ever references indices in that shared low range is structurally indistinguishable, from indices alone, between "trained on the 28-block base" and "trained natively on a larger model but only happens to touch one of its low-numbered blocks." Detection always resolves this toward the *smallest* architecture consistent with what it sees — correct for the normal case (real Anima LoRAs/ControlNets typically cover most/all of their source model's blocks), but a deliberately narrow, low-range-only LoRA/ControlNet trained natively on a larger architecture could be misclassified.
- If the *same* loaded ControlNet-LLLite checkpoint object is applied to two host models with *different* block counts within a single workflow graph, only the most-recently-executed decision is in effect (the flag lives on the shared checkpoint object). Workaround: use two separate "Load Model Patch" node instances.
- Tracks ComfyUI's native Anima LLLite implementation, which is currently marked `EXPERIMENTAL` upstream. An upstream change could silently stop the ControlNet half from installing (it degrades to a logged warning, never crashes).
- Only 28/40/52 are known architectures; any future Anima size is untouched until its own expansion mapping is verified the same way (see `anima_arch.py`'s module docstring for how to extend it).
- Malformed, intentionally partial, or exotic/non-standard LoRA and ControlNet formats; unusual manually-edited checkpoints; automatic repair of corrupted model files; and text-encoder/CLIP-side LoRA remapping are all out of scope.

## Physical adapter expansion (experimental, separate tool)

`expand.py` is a separate, offline, batch CLI tool (not a ComfyUI node, not installed automatically, not run during a ComfyUI session) that takes a real 28-block Anima LoRA or ControlNet-LLLite `.safetensors` file and produces a **new** file whose tensors physically target a larger architecture, instead of remapping block indices at load time the way the rest of this package does. The source file is never modified.

```bash
python custom_nodes/ComfyUI-Anima-LoRA-ControlNet-Patch/expand.py \
  -i models/loras/my_lora.safetensors \
  -o models/loras/my_lora_expanded40.safetensors \
  -t 40 --mode front
```

**Why sequential, not direct, for 28→52**: always performed as 28→40 then 40→52, never as one jump, because that mirrors how the real models were built — every 3.8B block kept from 2.9B is bit-identical to the *2.9B* block, not to an independently-re-expanded copy of the 28-block base. A direct 28→52 jump would also need an undocumented third neighbor relationship for the 12 blocks inserted at the 40→52 stage. Sequential expansion reuses one single-step algorithm twice and composes naturally instead.

**Inserted-block synthesis**: every newly-inserted block's tensors are copied (`--mode front`, the default) or linearly blended (`--mode blend --blend-ratio r`) from that block's immediate front/back neighbors in the layout being built — whatever their own provenance (an original inherited tensor, or a tensor synthesized in an earlier step). `front` mode reproduces one whole neighbor's adapter tensors exactly, unchanged; there is no reference value in the world for what an inserted block's adapter tensor is "supposed" to be, so front-copy is the safest, least-surprising default.

**Not implemented, deliberately**: base-model mixing (blending a synthesized tensor toward the target checkpoint's own native weight at that position, as a full-checkpoint expansion technique might). There is no valid analog here for either adapter type — a LoRA's low-rank factor and a full pretrained weight tensor are different mathematical objects (wrong shape/rank to even compare), and no real checkpoint has ever had a trained LLLite module at a brand-new inserted position to blend toward. Expansion here always stays purely in adapter space. See `expand.py`'s own module docstring for the full mathematical discussion, including why blending LoRA A/B factors separately is only an approximation of "blend the resulting weight delta" (matrix multiplication doesn't distribute over that kind of elementwise mix) — another reason `front` is the default rather than `blend`.

**Generated files are automatically safe from this package's own remapping**: they present as structurally native for their new block count (same detection logic, same central tables), so the LoRA/ControlNet patches above correctly leave them alone instead of double-remapping.

**File safety**: input and resolved output paths are compared and refused if identical; an existing output file is refused unless `--force` is passed; the source is opened read-only and never written to.

Real adapters have been expanded and validated this way (all `[CPU ONLY]`, see `tests/test_expand.py` for the equivalent synthetic-data tests): 0 missing target blocks, exact `torch.equal()` match between every inherited tensor and its source, load-bearing metadata (e.g. a ControlNet-LLLite checkpoint's `lllite.*` architecture keys) preserved unchanged, and expanded ControlNet files load cleanly through the real native `comfy.ldm.anima.lllite.AnimaLLLite` class with zero missing/unexpected keys. A real `[GPU REQUIRED]` end-to-end comparison (a runtime-remapped 28-block LoRA vs. its physically-expanded 40-block copy, identical seed/prompt/steps otherwise) showed outputs close but not identical (mean pixel diff 7.5/255) — consistent with the expected mechanism, since physical expansion also applies LoRA correction to the newly-inserted blocks that runtime remapping leaves untouched entirely. This is an experimental finding, not a pass/fail result.

This tool remains experimental and is not a replacement for the runtime remapping above, which is the primary, GUI-validated compatibility path.

## Acknowledgements

This project builds directly on prior community research and code:

- **sparklingcoffee777** — `ComfyUI-Anima-2.9B-loraPatch`, which established the 28→40 block mapping (via direct weight comparison) and the monkeypatch-based, no-workflow-node approach this package's LoRA half follows.
- **Lakeside529** — `ComfyUI-Anima-3.8B-LoRA-Bridge`, whose `mapping.py` independently uses the same 40→52 insertion positions this package derived from scratch via weight comparison, and which first demonstrated composing the 28→40 and 40→52 steps for a full 28→52 path.
- The Anima developers/researchers responsible for the original Anima architecture and models, and for the Anima 2.9B and Anima 3.8B expansions.
- The `count_blocks`-based dynamic block-count detection in ComfyUI core (`comfy/model_detection.py`, PR #15555) that made loading any of these block counts possible in the first place.

The 28→40 and 40→52 block mappings are **not original discoveries of this project** — see above for their provenance. What is original here is: independent re-verification of both mapping tables via direct tensor comparison against the real checkpoints, extending the tables to a downward (larger-to-smaller) direction with no new data required, the ControlNet/Anima-LLLite remapping mechanism (a materially different integration point than LoRA's, generalized from `ComfyUI-Anima-2.9B-controlnetPatch`), and unifying both into one architecture-agnostic patch with a single source of truth for the mapping tables.

## License

GPL-3.0, matching ComfyUI itself and `ComfyUI-Anima-2.9B-loraPatch`, since this patch hooks ComfyUI internals directly.
