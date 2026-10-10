# Stocking Texture Tool · ComfyUI integration

Use [Silvermoong's Stocking Texture Tool](https://github.com/silvermoong/stocking-texture-tool) inside ComfyUI: select and correct regions, split fabric, draw course guides, then run an independent workflow to save the finished image and a transparent texture layer.

> **AI disclosure:** The added ComfyUI integration was almost entirely written by an AI coding assistant under the submitting user's direction. The checks below were run; human review is still needed. The original algorithms, editor, styles and features belong to Silvermoong and the original contributors, under the retained MIT license. This is an experimental proposal, not an endorsed or merged upstream feature.

**[Install and try](integrations/comfyui/README.md#install-and-try) · [Example workflow](integrations/comfyui/examples/stocking-repair.json) · [Review the diff](https://github.com/wangtianbao19971204-spec/stocking-texture-tool/compare/6c0c620d1bfa6a2c2691cb2313e928d9c7244ee5...feat/comfyui-integration) · [中文](README.md)**

## What this branch adds

- **The full editor inside ComfyUI:** a new host adapter exposes the existing six styles, SAM selection, brush/eraser, guides/dividers, bent-leg corrections, presets, PSD and live previews.
- **An independent repair workflow:** `StockingTextureStudio → two SaveImage nodes`, saving RGB and a separate RGBA layer. No UAP/workbench extension, diffusion model or upscaler is required.
- **ComfyUI storage and interaction:** browser import/download, per-user drafts/presets, Apply-to-node and workflow restoration. Separate Guides/Render nodes also support batches and soft masks.

## For the original author and reviewers

| Review area | Entry point and scope |
|---|---|
| Added code | [`integrations/comfyui/`](integrations/comfyui/) and root [`__init__.py`](__init__.py); no changes to `stocking/` algorithms or static UI files |
| Setup and differences | [Integration guide](integrations/comfyui/README.md); SAM/depth weights must be supplied locally, with no automatic downloads |
| Validation | [Checks and reproduction](integrations/comfyui/README.md#review-and-tests): 40 Python tests, 17 frontend tests and 18 bent-leg comparisons passed; earlier checks covered 51 HTTP operations and 54 real-image comparisons |
| Coverage limits | Standalone tests: 114 passed, 51 skipped for unavailable author-private fixtures. Pixel parity does not imply automatic selection accuracy. Private artwork and weights are not redistributed |

Checked against upstream `6c0c620` on 2026-10-10. Parity requires identical inputs, masks, guides and settings with dark adaptation OFF. Crossed legs may need manual correction; near-black textures, dense-texture fading and experimental oily rendering retain upstream limitations. See the integration guide for exact boundaries and commands.

For ComfyUI, start with the installation link above. The `install.bat` instructions below belong to the standalone application.

---

## Original project README

The original documentation, demonstration images and attribution are preserved below. Those images demonstrate the author's application; they are not evidence of this fork's added integration.

