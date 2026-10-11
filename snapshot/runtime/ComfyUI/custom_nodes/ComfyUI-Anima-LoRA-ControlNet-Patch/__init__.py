"""
ComfyUI-Anima-LoRA-ControlNet-Patch

A unified patch that lets Anima LoRAs and ControlNet-LLLite checkpoints
trained for one block-count architecture (28, 40, or 52 transformer blocks)
work correctly when applied to a model of a *different* architecture --
larger or smaller -- without converting any files and without any new
workflow node. Both halves are pure monkeypatches installed once, at import
time, on top of ComfyUI's own LoRA loader and its native Anima LLLite
implementation.

See README.md for the full explanation, the block mapping tables, supported
conversions, and credits. In short: Anima 2.9B and Anima 3.8B are each a
depth-expansion of the previous, smaller Anima variant -- new transformer
blocks are spliced into specific positions of an otherwise byte-identical,
relocated copy of every block from the smaller model. A LoRA or
ControlNet-LLLite trained against one model's block *positions* therefore
needs those positions translated before it can correctly land on the same
(relocated) blocks in a different-sized model, whichever direction that is.

Nothing in this package overrides ComfyUI's own LoRA loader nodes or its
native "Load Model Patch" / "Apply Anima LLLite" nodes -- use those exactly
as normal; this package only changes what happens inside the functions they
already call.

Also includes expand.py: an optional, separate, offline CLI tool that
physically expands an adapter file to a larger architecture instead of
remapping it at load time -- see README.md's "Part 2" section.
"""

from . import controlnet_patch, lora_patch

lora_patch.install()
controlnet_patch.install()

# No workflow nodes: this is a load-time / call-time patch only.
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}
