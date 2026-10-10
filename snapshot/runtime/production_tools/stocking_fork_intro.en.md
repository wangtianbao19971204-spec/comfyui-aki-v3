# Stocking Texture Tool · ComfyUI integration

Use [Silvermoong's Stocking Texture Tool](https://github.com/silvermoong/stocking-texture-tool) inside ComfyUI: select and correct regions, split fabric, draw course guides, then run an independent workflow to save the finished image and a transparent texture layer.

> **AI disclosure:** The added ComfyUI integration was almost entirely written by an AI coding assistant under the submitting user's direction. The checks below were run; human review is still needed. The original algorithms, editor, styles and features belong to Silvermoong and the original contributors, under the retained MIT license. This is an experimental proposal, not an endorsed or merged upstream feature.

**[Install and try](integrations/comfyui/README.md#install-and-try) · [Example workflow](integrations/comfyui/examples/stocking-repair.json) · [Review the diff](https://github.com/wangtianbao19971204-spec/stocking-texture-tool/compare/f74c8ac0190ec43b2cdfcb13db86f35a83283311...feat/comfyui-integration) · [中文](README.md)**

## What this branch adds

- **The full editor inside ComfyUI:** a new host adapter exposes the existing six styles, SAM selection, brush/eraser, guides/dividers, bent-leg corrections, presets, PSD and live previews.
- **An independent repair workflow:** `StockingTextureStudio → two SaveImage nodes`, saving RGB and a separate RGBA layer. No UAP/workbench extension, diffusion model or upscaler is required.
- **ComfyUI storage and interaction:** browser import/download, per-user drafts/presets, Apply-to-node and workflow restoration. Separate Guides/Render nodes also support batches and soft masks.
- **Current upstream effects:** includes the moire switch, strength/area controls and revised oily rendering from `f74c8ac`. Moire defaults off and requires depth when enabled.

## For the original author and reviewers

| Review area | Entry point and scope |
|---|---|
| Added code | [`integrations/comfyui/`](integrations/comfyui/) and root [`__init__.py`](__init__.py); no changes to `stocking/` algorithms or static UI files |
| Setup and differences | [Integration guide](integrations/comfyui/README.md); SAM/depth weights must be supplied locally, with no automatic downloads |
| Validation | [Checks and reproduction](integrations/comfyui/README.md#review-and-tests): 44 Python tests, 17 frontend tests, 51 HTTP checks, 108 moire/style comparisons and 18 bent-leg comparisons passed |
| Coverage limits | Updated standalone suite: 285 passed, 52 skipped for unavailable fixtures or conditions. Pixel parity proves rendering compatibility, not complete masks or presentation quality. Private artwork and weights are not redistributed |

Checked against upstream `f74c8ac` on 2026-10-10. Parity requires identical inputs, masks, guides and settings with dark adaptation OFF. Check stocking tops, feet and overlaps separately and correct crossed-leg masks with the brush/eraser. Near-black textures, dense-texture fading and experimental oily rendering retain upstream limitations. Partial-mask regression images are not presentation examples; this integration currently publishes no result gallery. See the integration guide for exact boundaries and commands.

For ComfyUI, start with the installation link above. The `install.bat` instructions below belong to the standalone application.

---

## Original project README

The original documentation, demonstration images and attribution are preserved below. Those images demonstrate the author's application; they are not evidence of this fork's added integration.
