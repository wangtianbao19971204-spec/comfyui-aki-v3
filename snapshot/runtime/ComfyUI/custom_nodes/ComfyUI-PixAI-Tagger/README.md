# PixAI Tagger v1.0

Local adapter for https://huggingface.co/pixai-labs/pixai-tagger-v1.0.
The pinned model, processor, and reviewed upstream Python code live in
`ComfyUI/models/taggers/pixai-tagger-v1.0`; inference does not download files.

The first output is a tag string per image; the second is JSON with scores
for all six categories. Default prompt output includes character and general
tags. Add copyright/style/meta/rating through `categories` when wanted.
The official per-category thresholds are used. Exclusions accept underscores
or spaces. Existing connections use output 0 unchanged.

Weights load once per input batch and are released afterwards. BF16 is used
on supported devices, otherwise FP32. All runs use ComfyUI's execution queue.
An imported WD14 graph is migrated to PixAI when configured in the browser;
its old thresholds are replaced with PixAI defaults, formatting and exclusions
are preserved. Save an imported graph to persist the migration.

Dependencies: existing PyTorch, torchvision, transformers, timm, Pillow, NumPy.
Model revision: `9fe10addf9326e292da8a85a98ea74cd91b41771` (Apache-2.0).
