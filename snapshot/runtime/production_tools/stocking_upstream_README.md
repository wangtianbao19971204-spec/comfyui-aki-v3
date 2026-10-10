> **AI disclosure / AI 修改说明：This ComfyUI integration was written almost entirely by an AI coding agent at a user's request. It is an experimental contribution, not a claim of complete human review. 核心算法、六种纹理样式、编辑器及原有功能均属于 Silvermoong 与原项目贡献者；此提案主要添加宿主适配。**

# Optional ComfyUI integration

This hosts the existing Stocking Texture Tool editor inside ComfyUI and provides an independent fabric-repair workflow. The original `stocking/` algorithms and browser assets are read directly from this repository; they are not duplicated or modified by this integration. The MIT license and original attribution continue to apply. This is a draft proposal for maintainer feedback, not an assertion of maintainer endorsement.

## Install and try

1. Place a checkout of this repository under `ComfyUI/custom_nodes/stocking-texture-tool`. Avoid installing another copy exposing the same `StockingTexture*` nodes/routes.
2. In the **Python environment that runs ComfyUI**, install the missing dependencies from `integrations/comfyui/requirements.txt`. Review the requirements first; importing the plugin never installs packages or downloads models. ComfyUI already supplies Torch and aiohttp.
3. Restart ComfyUI and load [examples/stocking-repair.json](examples/stocking-repair.json). It contains `StockingTextureStudio`, two standard `SaveImage` nodes and a note; it requires no workbench, diffusion model or upscaler.
4. Click **打开完整编辑器** (Open full editor). Import PNG/JPG/PSD, select the fabric, correct the mask and draw at least one course guide for each region. Choose a texture in the Look tab. Click **Apply to node**, close the editor and queue the workflow.
5. The two SaveImage nodes write the finished image and a separate RGBA fabric layer. Guide PSD export is available in the editor. The input artwork is never overwritten.

Alternatively connect a single IMAGE and run the node once to supply its editor image. Connect an optional same-size depth IMAGE with near surfaces brighter. The legacy Guides/Render nodes also remain available for batch/soft-mask workflows.

## Original features available through the adapter

| Original capability | Adapter coverage |
|---|---|
| Six styles: lines, knit, coil, loops, grain, experimental oily | Original renderers, density/tilt/auto or manual strength |
| SAM point selection, small/medium/large candidates, add/subtract | Local SAM ViT-B on CPU; painting remains available without weights |
| Pixel brush/eraser, regions, split/trace/auto-split/merge, undo/redo | Original Document operations and editor controls |
| Course guides, mirroring, manual dividers and depth walls | Original solve and editing behavior |
| Depth, bright, even and PSD-painted sparkles; color exclusion | Original look controls and rendering |
| Preset save/replace/load/undo-load/delete | Per-ComfyUI-user storage |
| Live full/split/100%/200%/problem previews | Original UI adapted to ComfyUI routes |
| PNG/JPG/PSD input, finished PNG, RGBA fabric, guide PSD | Browser upload/download; PSD can restore artwork and guides |
| Chinese/English UI, keyboard controls | Original language assets, per-request translation |

## Differences, missing coverage and known limits

- This is **not complete desktop/host equivalence**. The standalone installer/updater, native OS file dialog/path save, Reveal in folder, drag-to-launch and independent process shutdown are replaced by ComfyUI service management and browser upload/download.
- Built-in SAM/depth inference uses CPU and releases model references after calls; it is slower than the standalone GPU path and does not retain SAM embeddings across clicks. No automatic download is provided. Manually place SAM ViT-B at `models/sams/sam_vit_b_01ec64.pth`, and Depth Anything V2 Small HF at `models/stocking_texture/Depth-Anything-V2-Small-hf/` (`config.json`, `preprocessor_config.json`, `model.safetensors`). Exact sources/hashes: [MODEL_SOURCES.json](MODEL_SOURCES.json).
- **Dark adaptation defaults OFF in this upstream proposal**, matching the original renderer. The optional additional dark-weave enhancement changes results intentionally. For parity, use the same input, region masks, guides, dividers, depth and look parameters, and keep this option off.
- Pixel parity does not establish selection accuracy. In real illustration checks, small SAM candidates fit a simple white/near-black leg reasonably; crossed legs had missing areas, the medium candidate included a shoe, and large candidates included the whole character. Manual brush/eraser and splitting are still necessary. No claim of automatic correct selection for every color/pose is made.
- Near-black multiplicative textures can be nearly invisible; pure black remains black. Excessively dense textures fade to avoid aliasing; oily is experimental; small images can miss depth walls. These original limits remain.
- Full Studio preserves the original renderer's edge behavior: oily can change a small number of pixels outside the selected fabric. It does not promise the legacy nodes' strict outside-mask protection.
- Full Studio supports one image, up to 24 million pixels, 32 regions, 4 editor sessions and 24 MiB project JSON. The older nodes support batches and soft masks with a stricter outside-mask contract. Their edge behavior is not identical to full Studio.
- Workflow JSON contains compressed masks/guides/settings, but input/depth assets are SHA256-named files in `input/stocking_studio/assets`. Copy those assets when moving a saved project, or export/reopen a guide PSD. A blank example workflow includes no private image or asset reference. PSD restores artwork/guides; look parameters belong in the workflow or presets.
- Real visual tests cover three existing illustrations: white bent leg, black crossed legs, near-black standing legs. Other colors/poses have synthetic coverage, **not** comprehensive real-image acceptance. Author-private samples and arbitrary complex third-party PSD/PSB files were unavailable. Multi-user deployment, OS/browser variations and heavy concurrent use need wider review.

## Review and tests

All added host code lives in this directory. A small repository-root `__init__.py` exposes nodes only in a ComfyUI environment. `vendor/__init__.py` adds `stocking/` to a host-local module search path; the sole local override is request-local i18n, avoiding the standalone settings file. `studio_assets.py` reads original assets and makes checked, fail-closed substitutions for browser upload/download and the Apply bridge. This is pinned to [UPSTREAM.json](UPSTREAM.json); future UI changes may require adapter updates.

Run from the repository root with the required dependencies available:

```shell
python -m unittest discover -s integrations/comfyui/tests -p "test_*.py" -v
node --test integrations/comfyui/tests/test_editor.cjs integrations/comfyui/tests/test_studio_editor.cjs
python integrations/comfyui/tests/feature_acceptance.py --upstream . --out /new/private/acceptance-directory
python -m pytest -q
```

The last command runs the standalone suite. Some tests require the author's unshared `sample.png` / `sample-guides.psd`; skips must be reported as skips. Real-image/model runners accept caller-owned fixtures and local weights; they neither download nor publish them. Three fresh repeated runs of three real illustrations × six styles (54 cases) matched standalone full/crop/problem previews exactly with dark adaptation off. Fresh SAM candidates/scores and depth matched on all three illustrations. Those private fixtures are not redistributed in this PR; the synthetic API runner is included for reproduction.

`tests/bend_acceptance.py` accepts caller-owned baseline/split/divider-and-arc project snapshots and an immutable assets directory. It checks that splitting preserves the selection union, direction actually changes, and all six rendered styles and solved fields match an independently obtained upstream. The tested bent-leg sequence passed all 18 stage/style cases; its final Studio → SaveImage output matched the original exactly, and the RGBA layer recomposed without pixel error. This is a bounded regression check, not proof that SAM selects every bent or crossed leg correctly.

Drafts/presets/exports live in the current ComfyUI user's `stocking_texture` directory. The editor checks same-origin mutations, per-session ownership, stale inputs and Apply acknowledgements. This is not a substitute for ComfyUI authentication or public-Internet hardening.
