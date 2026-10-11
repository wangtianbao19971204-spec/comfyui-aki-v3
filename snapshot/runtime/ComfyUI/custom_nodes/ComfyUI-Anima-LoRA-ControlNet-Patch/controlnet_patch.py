"""ControlNet / Anima LLLite compatibility: monkeypatches ComfyUI's native
`comfy_extras.nodes_model_patch.AnimaLLLiteApply.apply_patch` and
`comfy.ldm.anima.lllite.AnimaLLLite.apply`.

Generalizes ComfyUI-Anima-2.9B-controlnetPatch (Task 2 of this line of work)
from the single 28->40 pair to the full 28/40/52 chain, in BOTH directions
(a smaller-checkpoint-on-larger-host "expand" case, and a
larger-checkpoint-on-smaller-host "reduce" case -- e.g. a genuinely
40-block-trained ControlNet-LLLite, or one physically expanded by
expand.py, applied to the 28-block base model), driven by the central
tables in anima_arch.py. See that project's own docstring for the detailed
mechanics this builds on; the key points, restated for all three
architectures and both directions:

  - AnimaLLLite.apply(x, cond_emb, block_index, target, strength) resolves a
    raw, UNMAPPED block_index (the host DiT's own physical block position)
    against a checkpoint-native module name -- there is no remapping
    anywhere in ComfyUI core.
  - The only place that ever has both the checkpoint (with its own
    block_count) and the host model (with its own live block list) at the
    same time is AnimaLLLiteApply.apply_patch -- so that is where the
    "does this pairing need remapping, and to what table" decision is made,
    once per apply_patch call (recomputed every call, not cached once,
    because model_patch.model is a shared object that is NOT cloned by
    apply_patch and could in principle be reused against a different host).
  - AnimaLLLite.apply itself is patched separately to consult whatever
    mapping (if any) was decided, and translate block_index through it
    before delegating to the original, unmodified apply().

Known gotcha (see also the code comment at the patch-installation site
below): ComfyUI loads comfy_extras/*.py files itself via
importlib.util.spec_from_file_location() under a mangled sys.modules key --
NOT via a normal `import comfy_extras.nodes_model_patch` statement. The class
object actually sitting in nodes.NODE_CLASS_MAPPINGS["AnimaLLLiteApply"]
(what execution.py actually calls) can therefore be a DIFFERENT object from
whatever a plain dotted import resolves to. We patch every distinct class
object we can find, with the live node registry as the authoritative source.
"""

from __future__ import annotations

import logging
import os

import torch

from . import anima_arch

LOG_PREFIX = "[Anima LoRA/ControlNet Patch]"
_PATCH_MARKER = "_anima_compat_cnet_patch"
_REMAP_ATTR = "_anima_compat_cnet_remap"

# Markers used by the older, single-purpose ComfyUI-Anima-2.9B-controlnetPatch
# (Task 2). If that patch is already installed underneath us on either target,
# installing on top of it risks double-remapping the 28->40 pair it already
# understands (its own remap would run again on top of ours, or vice versa).
_SIBLING_APPLY_PATCH_MARKER = "_anima29b_cnet_patch"
_SIBLING_LLLITE_APPLY_MARKER = "_anima29b_cnet_patch"


def _enabled() -> bool:
    return os.environ.get("ANIMA_COMPAT_CONTROLNET_REMAP", "1").strip().lower() not in ("0", "off", "false", "no")


try:
    import comfy.ldm.anima.lllite as _lllite_mod
except Exception:
    _lllite_mod = None

try:
    import comfy.ldm.anima.model as _anima_model_mod
except Exception:
    _anima_model_mod = None

try:
    import comfy_extras.nodes_model_patch as _nodes_model_patch_mod
except Exception:
    _nodes_model_patch_mod = None

try:
    import nodes as _comfy_nodes_mod
except Exception:
    _comfy_nodes_mod = None


def _get_host_blocks(model_patcher):
    """Live nn.ModuleList of the host model's transformer blocks, or None."""
    try:
        diffusion_model = model_patcher.model.diffusion_model
        blocks = diffusion_model.blocks
    except AttributeError:
        return None
    if not isinstance(blocks, torch.nn.ModuleList):
        return None
    return blocks


def _is_anima_dit(model_patcher) -> bool:
    if _anima_model_mod is None:
        return False
    try:
        diffusion_model = model_patcher.model.diffusion_model
    except AttributeError:
        return False
    anima_cls = getattr(_anima_model_mod, "Anima", None)
    return anima_cls is not None and isinstance(diffusion_model, anima_cls)


def _clear(lllite):
    if hasattr(lllite, _REMAP_ATTR):
        try:
            delattr(lllite, _REMAP_ATTR)
        except Exception:
            pass


def _maybe_install_remap(model, model_patch):
    """Called at the top of every apply_patch call. Always resolves the
    correct state for THIS call -- never trusts a previous call's leftover
    flag, since model_patch.model is shared (not cloned) and could have been
    used against a different host before."""
    if _lllite_mod is None:
        return
    anima_lllite_cls = getattr(_lllite_mod, "AnimaLLLite", None)
    lllite = getattr(model_patch, "model", None)
    if anima_lllite_cls is None or not isinstance(lllite, anima_lllite_cls):
        return

    if not _enabled():
        _clear(lllite)
        return

    checkpoint_block_count = getattr(lllite, "block_count", None)
    host_blocks = _get_host_blocks(model)
    host_count = len(host_blocks) if host_blocks is not None else None

    if checkpoint_block_count is None or host_count is None or not _is_anima_dit(model):
        _clear(lllite)
        return

    if host_count not in anima_arch.ANIMA_BLOCK_COUNTS:
        logging.info(
            "{} unknown Anima block layout on the host model ({} blocks); "
            "leaving ControlNet-LLLite untouched.".format(LOG_PREFIX, host_count)
        )
        _clear(lllite)
        return

    source_count = anima_arch.bucket_block_count(checkpoint_block_count)
    if source_count is None:
        logging.info(
            "{} ControlNet-LLLite checkpoint references block index {}, beyond every "
            "known Anima architecture; leaving it untouched.".format(LOG_PREFIX, checkpoint_block_count - 1)
        )
        _clear(lllite)
        return

    if source_count == host_count:
        _clear(lllite)  # already native for this host -- nothing to do
        return

    # Both directions produce the exact same shape of map --
    # host_block_index -> checkpoint_module_index -- so the consuming
    # wrapper (_patched_lllite_apply below) needs no direction-awareness at
    # all; only the choice of which anima_arch function to call differs:
    #   - checkpoint smaller than host ("expand", e.g. 28-ckpt on 40-host):
    #     get_inverse_mapping -- partial, 12 host positions per step have no
    #     checkpoint-trained counterpart and correctly no-op.
    #   - checkpoint larger than host ("reduce", e.g. 40-ckpt on 28-host,
    #     including a genuinely-native-40-block checkpoint or one produced
    #     by expand.py): get_reduction_mapping -- total, every host position
    #     has a real checkpoint ancestor.
    if source_count < host_count:
        remap = anima_arch.get_inverse_mapping(source_count, host_count)
    else:
        remap = anima_arch.get_reduction_mapping(source_count, host_count)

    if remap is None:
        logging.info(
            "{} no known mapping between a {}-block ControlNet-LLLite checkpoint and a "
            "{}-block host; leaving it untouched.".format(LOG_PREFIX, source_count, host_count)
        )
        _clear(lllite)
        return

    setattr(lllite, _REMAP_ATTR, remap)
    direction = "up" if source_count < host_count else "down"
    logging.info(
        "{} {}-block Anima ControlNet-LLLite on {}-block host: block-index remap installed ({}).".format(
            LOG_PREFIX, source_count, host_count, direction
        )
    )


# --- Patch 1: AnimaLLLiteApply.apply_patch ----------------------------------

_apply_classes = []
_seen_apply_cls_ids = set()


def _add_apply_class_candidate(cls):
    if cls is not None and id(cls) not in _seen_apply_cls_ids:
        _seen_apply_cls_ids.add(id(cls))
        _apply_classes.append(cls)


if _comfy_nodes_mod is not None:
    _add_apply_class_candidate(getattr(_comfy_nodes_mod, "NODE_CLASS_MAPPINGS", {}).get("AnimaLLLiteApply"))
if _nodes_model_patch_mod is not None:
    _add_apply_class_candidate(getattr(_nodes_model_patch_mod, "AnimaLLLiteApply", None))


def _make_patched_apply_patch(orig_apply_patch):
    def _patched_apply_patch(self, model, model_patch, image, strength, start_percent, end_percent, mask=None):
        try:
            _maybe_install_remap(model, model_patch)
        except Exception as err:
            logging.warning("{} ControlNet gating check failed, leaving model_patch untouched: {}".format(LOG_PREFIX, err))
        return orig_apply_patch(self, model, model_patch, image, strength, start_percent, end_percent, mask=mask)

    setattr(_patched_apply_patch, _PATCH_MARKER, True)
    return _patched_apply_patch


def _install_apply_patch_hooks() -> int:
    if not _apply_classes:
        logging.warning(
            "{} AnimaLLLiteApply (nodes.NODE_CLASS_MAPPINGS / comfy_extras.nodes_model_patch) "
            "not found; this ComfyUI version is not supported by the ControlNet half of "
            "this patch.".format(LOG_PREFIX)
        )
        return 0

    installed = 0
    for cls in _apply_classes:
        orig = getattr(cls, "apply_patch", None)
        if orig is None:
            logging.warning("{} {}.apply_patch not found; skipping.".format(LOG_PREFIX, cls))
            continue
        if getattr(orig, _PATCH_MARKER, False):
            continue  # already installed on this exact class object
        if getattr(orig, _SIBLING_APPLY_PATCH_MARKER, False):
            logging.warning(
                "{} ComfyUI-Anima-2.9B-controlnetPatch is already active on {}.apply_patch. "
                "Installing this unified patch on top of it would risk double-remapping the "
                "28->40 case. Skipping this class -- please remove or disable "
                "ComfyUI-Anima-2.9B-controlnetPatch (this package supersedes it).".format(LOG_PREFIX, cls)
            )
            continue
        cls.apply_patch = _make_patched_apply_patch(orig)
        installed += 1
    return installed


# --- Patch 2: AnimaLLLite.apply ----------------------------------------------

def _install_lllite_apply_hook() -> bool:
    if _lllite_mod is None:
        logging.warning(
            "{} comfy.ldm.anima.lllite not found; this ComfyUI version is not supported "
            "by the ControlNet half of this patch.".format(LOG_PREFIX)
        )
        return False

    lllite_cls = getattr(_lllite_mod, "AnimaLLLite", None)
    if lllite_cls is None:
        logging.warning("{} comfy.ldm.anima.lllite.AnimaLLLite not found; skipping.".format(LOG_PREFIX))
        return False

    orig_apply = getattr(lllite_cls, "apply", None)
    if orig_apply is None:
        logging.warning("{} AnimaLLLite.apply not found; skipping.".format(LOG_PREFIX))
        return False
    if getattr(orig_apply, _PATCH_MARKER, False):
        logging.info("{} AnimaLLLite.apply hook already installed; skipping.".format(LOG_PREFIX))
        return True
    if getattr(orig_apply, _SIBLING_LLLITE_APPLY_MARKER, False):
        logging.warning(
            "{} ComfyUI-Anima-2.9B-controlnetPatch is already active on AnimaLLLite.apply. "
            "Installing this unified patch on top of it would risk double-remapping the "
            "28->40 case. Skipping -- please remove or disable "
            "ComfyUI-Anima-2.9B-controlnetPatch (this package supersedes it).".format(LOG_PREFIX)
        )
        return False

    def _patched_lllite_apply(self, x, cond_emb, block_index, target, strength):
        remap = getattr(self, _REMAP_ATTR, None)
        if remap is None:
            return orig_apply(self, x, cond_emb, block_index, target, strength)
        mapped = remap.get(block_index)
        if mapped is None:
            return x  # a newly-inserted host block with no source counterpart
        return orig_apply(self, x, cond_emb, mapped, target, strength)

    setattr(_patched_lllite_apply, _PATCH_MARKER, True)
    lllite_cls.apply = _patched_lllite_apply
    return True


def install():
    n_apply_patch = _install_apply_patch_hooks()
    lllite_ok = _install_lllite_apply_hook()
    if n_apply_patch and lllite_ok:
        logging.info(
            "{} ControlNet-LLLite remap installed on {} AnimaLLLiteApply class object(s) "
            "(28<->40, 28<->52, 40<->52, both directions). Set ANIMA_COMPAT_CONTROLNET_REMAP=0 to disable.".format(
                LOG_PREFIX, n_apply_patch
            )
        )
        return True
    return False
