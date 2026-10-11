# Stocking Texture Tool · ComfyUI integration

Use [Silvermoong's Stocking Texture Tool](https://github.com/silvermoong/stocking-texture-tool) inside ComfyUI: open the full editor, correct selections, draw guides and adjust texture, then run an independent workflow to save the finished image and a transparent texture layer.

**[Install and try](integrations/comfyui/README.md#install-and-try) · [Example workflow](integrations/comfyui/examples/stocking-repair.json) · [Gallery and settings](integrations/comfyui/SHOWCASE.md) · [中文](README.md)**

- Reuses the original six styles, SAM selection, brush/eraser, guides/dividers, presets, PSD and live previews.
- `StockingTextureStudio → two SaveImage nodes` writes the finished image and a separate RGBA layer. No UAP/workbench extension, diffusion model or upscaler is required.
- Includes **upstream `f74c8ac`'s moire switch, strength/area controls and revised oily rendering**, checked on 2026-10-10. Moire defaults off and requires depth when enabled.
- Adds **CPU/GPU selection, defaulting to GPU**, for selection, depth and guide solving. Leaving the last active editor releases dedicated model/image-feature caches while preserving drafts and computed depth.

## Actual output

**Input → corrected full selection, with separate legs → plugin output**. The foreground fabric-covered foot is included and regions follow the curved overlap. Oily density 75, manual strength 35; dark adaptation, sparkles and moire off.

![ComfyUI crossed-leg example: input, complete selection and actual oily output](integrations/comfyui/docs/images/black-crossed-before-mask-after.png)

This project was applied from the real editor, saved through SaveImage, restored and rerun. See the [white bent-leg and near-black standing examples with settings](integrations/comfyui/SHOWCASE.md). Masks were manually corrected; these images do not claim automatic SAM selection accuracy. Oily remains experimental.

## For the original author and reviewers

| Area | Entry point and scope |
|---|---|
| Changes | Adds [`integrations/comfyui/`](integrations/comfyui/) and root [`__init__.py`](__init__.py); reuses unchanged `stocking/` files, with optional GPU solving inside the integration |
| Code review | [All changes relative to `f74c8ac`](https://github.com/wangtianbao19971204-spec/stocking-texture-tool/compare/f74c8ac0190ec43b2cdfcb13db86f35a83283311...feat/comfyui-integration) |
| Validation | [Dated checks and reproduction](integrations/comfyui/README.md#review-and-tests): 65 Python, 2 CUDA and 17 frontend tests passed for this update; six styles differed by at most 2/255 on CPU/GPU. Earlier moire and bent-leg checks are listed separately |
| Limits | Complex SAM selections need manual correction; first GPU use initializes kernels, and missing dependencies or busy resources fall back to CPU; near-black weave is subtle; weights must be supplied locally. The three existing comparison panels are unchanged; original projects and weights are not distributed |

> **Attribution and AI disclosure:** The algorithms, editor, styles and original features belong to Silvermoong and the original contributors, under the retained MIT license. The integration was almost entirely written by an AI coding assistant under the user's direction. This fork is maintained independently, is not an upstream PR and does not claim upstream endorsement. Pixel comparisons describe the tested compatibility range, not universal selection accuracy or visual quality.

For ComfyUI, start with the installation link above. The `install.bat` instructions below belong to the standalone application.

---

## Original project README

The complete original documentation, demonstration images and attribution are preserved below. Those images demonstrate the author's application.
