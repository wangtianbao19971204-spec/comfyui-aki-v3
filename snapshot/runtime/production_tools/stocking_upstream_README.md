> **AI disclosure / AI 修改说明：This ComfyUI integration was written almost entirely by an AI coding agent at a user's request. It is an experimental fork, not a claim of complete human review. 核心算法、六种纹理样式、编辑器及原有功能均属于 Silvermoong 与原项目贡献者；本 fork 添加宿主适配与可选 GPU 加速。**

# Independent ComfyUI integration

This hosts the existing Stocking Texture Tool editor inside ComfyUI and provides an independent fabric-repair workflow. The original algorithms and browser assets are preserved as a fixed, unmodified dependency in `upstream/stocking/`, pinned to `{{UPSTREAM_COMMIT}}`. The MIT license and original attribution continue to apply. This adapter is maintained independently; the upstream project does not maintain or endorse this integration.

**中文快速上手：** 将本仓库放入 `ComfyUI/custom_nodes/stocking-texture-comfyui`，在运行 ComfyUI 的 Python 环境中补齐本目录 `requirements.txt` 的依赖，重启后载入[独立工作流](examples/stocking-repair.json)。打开完整编辑器，导入图片、修正选区、画走向，再“应用到节点”并执行工作流。SAM/深度权重需按 [MODEL_SOURCES.json](MODEL_SOURCES.json) 事先放置；手绘选区无需 SAM 权重。请勿同时安装另一份同名节点。

**Review map / 审查入口：** [host API](studio_api.py) · [node bridge](studio_nodes.py) · [storage](studio_store.py) · [original-module bridge](vendor/__init__.py) · [tests](tests/). Rendering, selection and editor capabilities are credited to the original project; this contribution provides the ComfyUI host and workflow integration.

## Install and try

1. Place this independent repository under `ComfyUI/custom_nodes/stocking-texture-comfyui`. The pinned upstream dependency is already included; no recursive clone is needed. Avoid installing another copy exposing the same `StockingTexture*` nodes/routes.
2. In the **Python environment that runs ComfyUI**, install the missing dependencies from `integrations/comfyui/requirements.txt`. Review the requirements first; importing the plugin never installs packages or downloads models. ComfyUI already supplies Torch and aiohttp.
3. Restart ComfyUI and load [examples/stocking-repair.json](examples/stocking-repair.json). It contains `StockingTextureStudio`, two standard `SaveImage` nodes and a note; it requires no workbench, diffusion model or upscaler.
4. Click **打开完整编辑器** (Open full editor). Import PNG/JPG/PSD, select the fabric, correct the mask and draw at least one course guide for each region. Choose a texture in the Look tab. Click **Apply to node**, close the editor and queue the workflow.
5. The two SaveImage nodes write the finished image and a separate RGBA fabric layer. Guide PSD export is available in the editor. The input artwork is never overwritten.

Alternatively connect a single IMAGE and run the node once to supply its editor image. Connect an optional same-size depth IMAGE with near surfaces brighter. The legacy Guides/Render nodes also remain available for batch/soft-mask workflows.

## Original features available through the adapter

| Original capability | Adapter coverage |
|---|---|
| Six styles: lines, knit, coil, loops, grain, experimental oily | Original renderers, density/tilt/auto or manual strength |
| SAM point selection, small/medium/large candidates, add/subtract | Local SAM ViT-B, GPU by default with a CPU option/fallback; painting remains available without weights |
| Pixel brush/eraser, regions, split/trace/auto-split/merge, undo/redo | Original Document operations and editor controls |
| Course guides, mirroring, manual dividers and depth walls | Original solve and editing behavior |
| Depth, bright, even and PSD-painted sparkles; color exclusion | Original look controls and rendering |
| Moire effect switch, strength and area; updated oily continuity across occlusions | Pinned upstream `{{UPSTREAM_COMMIT}}`; moire defaults off and requires depth, including for export and node execution |
| Preset save/replace/load/undo-load/delete | Per-ComfyUI-user storage |
| Live full/split/100%/200%/problem previews | Original UI adapted to ComfyUI routes |
| PNG/JPG/PSD input, finished PNG, RGBA fabric, guide PSD | Browser upload/download; PSD can restore artwork and guides |
| Chinese/English UI, keyboard controls | Original language assets, per-request translation |

## Differences, missing coverage and known limits

- This is **not complete desktop/host equivalence**. The standalone installer/updater, native OS file dialog/path save, Reveal in folder, drag-to-launch and independent process shutdown are replaced by ComfyUI service management and browser upload/download.
- The editor's **Compute device / 计算设备** selector defaults to **GPU** and can be switched to CPU. It controls SAM, built-in depth and guide solving; the actual backend and fallback reason are shown. SAM/depth use ComfyUI's PyTorch. For optional guide acceleration on CUDA 13, install the missing packages from [requirements-cuda13.txt](requirements-cuda13.txt) in ComfyUI's Python environment. The validated combination is Torch 2.9.1+cu130, CuPy 14.2.0, CUDA runtime headers 13.0.96 and Numba 0.63.1. Other CUDA versions require a matching CuPy/runtime combination and separate validation; do not install multiple CuPy distributions together.
- Guide solving accelerates sparse Cholesky, batch contours and nearest-neighbor queries. Topology, line assembly and OpenCV remain on CPU. Missing dependencies, a busy generation queue, low VRAM or failed numerical checks trigger CPU fallback. The task's private GPU pool is released after solving. First CUDA use initializes libraries/kernels and can be slower; it is not representative of warm performance.
- SAM/depth move back to CPU after each inference. While the editor is active, models and image features stay in RAM for reuse. Closing or leaving the last active editor clears those caches, after any running inference finishes. Returning preserves drafts and computed depth but loads models again when needed. A crashed/disconnected page expires in about 60–75 seconds. General framework allocators and CUDA contexts may retain process memory even after model objects are collected.
- No automatic model download is provided. Manually place SAM ViT-B at `models/sams/sam_vit_b_01ec64.pth`, and Depth Anything V2 Small HF at `models/stocking_texture/Depth-Anything-V2-Small-hf/` (`config.json`, `preprocessor_config.json`, `model.safetensors`). Exact sources/hashes: [MODEL_SOURCES.json](MODEL_SOURCES.json).
- **Dark adaptation defaults OFF in this independent distribution**, matching the original renderer. The optional additional dark-weave enhancement changes results intentionally. For parity, use the same input, region masks, guides, dividers, depth and look parameters, and keep this option off.
- Pixel parity does not establish selection accuracy. In real illustration checks, small SAM candidates fit a simple white/near-black leg reasonably; crossed legs had missing areas, the medium candidate merged both legs and the foreground foot, and large candidates included the whole character. Manual brush/eraser and splitting are still necessary. No claim of automatic correct selection for every color/pose is made.
- Before judging a finished result, inspect the full visible fabric at 100%: both legs, stocking tops, feet and overlaps. Split limbs along the actual overlap, remove clothing/background spill, and add guides to every disconnected piece. Partial-mask regression inputs exercise rendering but are not finished demonstrations. After incomplete masks and unnatural seams were identified, the candidates were corrected and visually reviewed. Three selected comparison panels are published in [the gallery](SHOWCASE.md), with parameters and complete selection overlays. They are actual plugin outputs, with manual mask correction; the original author's demonstrations remain separately attributed in the root README.
- Near-black multiplicative textures can be nearly invisible; pure black remains black. Excessively dense textures fade to avoid aliasing; oily is experimental; small images can miss depth walls. These original limits remain.
- Full Studio preserves the original renderer's edge behavior: oily can change a small number of pixels outside the selected fabric. It does not promise the legacy nodes' strict outside-mask protection.
- Full Studio supports one image, up to 24 million pixels, 32 regions, 4 editor sessions and 24 MiB project JSON. The older nodes support batches and soft masks with a stricter outside-mask contract. Their edge behavior is not identical to full Studio.
- Workflow JSON contains compressed masks/guides/settings, but input/depth assets are SHA256-named files in `input/stocking_studio/assets`. Copy those assets when moving a saved project, or export/reopen a guide PSD. A blank example workflow includes no private image or asset reference. PSD restores artwork/guides; look parameters belong in the workflow or presets.
- Real visual tests cover three existing illustrations: white bent leg, black crossed legs, near-black standing legs. Other colors/poses have synthetic coverage, **not** comprehensive real-image acceptance. Author-private samples and arbitrary complex third-party PSD/PSB files were unavailable. Multi-user deployment, OS/browser variations and heavy concurrent use need wider review.

## Review and tests

Current integration validation on 2026-10-11, pinned to **`{{UPSTREAM_COMMIT}}`**: **78 Python tests passed with no skips, including the optional CUDA contracts; 17 frontend tests, 51 synthetic HTTP comparisons and 5 source-export tests passed**. The T0–T5 fixes remain: independent packaging, pristine pinned sources, seams/snap forwarding, request-field coverage, temporary-file retention, and LF/pin-derived version reporting. Exact upstream comparisons explicitly select CPU.

Across three real illustrations and six styles (18 comparisons), CPU pixels and solved fields matched the independent upstream exactly. All GPU regions actually used CUDA and released their private pool. GPU arithmetic was not bit-identical: the maximum channel difference was **9/255** (near-black oily; 411 channels exceeded 2/255); white-leg loops reached 6/255. Side-by-side inspection of the largest-difference crops found no obvious structural change, but this is bounded visual review, not a universal error guarantee. Choose CPU for exact upstream comparison. These renderer comparisons reused fixed depth assets; separate browser checks ran real GPU SAM and depth inference.

The exported plugin was also exercised in isolated ComfyUI: CPU/GPU switching, SAM candidates with fill-seams, depth calculation, editor close/reopen, and navigation away. After navigation the active-editor count, cached model flags and feature count were all zero, while computed depth remained ready. Returning and clicking reloaded SAM. Activity ordering, multiple editors and deferred release are covered by automated contracts; this run did not separately demonstrate browser tab hiding, a crashed browser, or model weak-reference collection.

Historical GPU/lifecycle validation before integration, against upstream `f74c8ac` on 2026-10-11: **65 Python contracts passed**, with 2 optional CUDA tests skipped in the default run and both passed separately on CUDA; **17 frontend tests passed**. CUDA checks include 126 contour cases and topology/pool cleanup. Six real-image styles differed by at most 2/255 between CPU and GPU. On the tested RTX 5090 D, warm same-page guide solves took 0.86/1.00 seconds on CPU and 0.46/0.66 seconds on GPU; this is a bounded measurement, not a hardware-independent speed guarantee. Real browser checks covered device switching, SAM/depth, leaving/returning and closing. Weak references confirmed actual model collection; process RSS returning to baseline is not claimed.

Recorded validation on 2026-10-10 against **`f74c8ac0190ec43b2cdfcb13db86f35a83283311`**: **44 Python tests, 17 frontend tests, 51 HTTP checks, 108 moire/style comparisons and 18 bent-leg stage/style comparisons passed**. The updated standalone suite returned **285 passed / 52 skipped**; unavailable author fixtures and other skip conditions remain outside this acceptance. The actual ComfyUI editor also exercised moire controls, presets, Apply and SaveImage. These functional checks do not certify the visual quality of the chosen masks.

All added host code lives in this directory. A small repository-root `__init__.py` exposes nodes only in a ComfyUI environment. `vendor/__init__.py` adds `stocking/` to a host-local module search path; the sole local override is request-local i18n, avoiding the standalone settings file. `studio_assets.py` reads original assets and makes checked, fail-closed substitutions for browser upload/download and the Apply bridge. This is pinned to [UPSTREAM.json](UPSTREAM.json); future UI changes may require adapter updates.

Run from the repository root with the required dependencies available:

```shell
python -m unittest discover -s integrations/comfyui/tests -p "test_*.py" -v
node --test integrations/comfyui/tests/test_editor.cjs integrations/comfyui/tests/test_studio_editor.cjs
python integrations/comfyui/tests/feature_acceptance.py --upstream /path/to/pristine-upstream --out /new/private/acceptance-directory
cd /path/to/pristine-upstream
python -m pytest -q
```

The last command runs the standalone suite. Some tests require the author's unshared `sample.png` / `sample-guides.psd`; skips must be reported as skips. Set `STOCKING_TEST_CUDA=1` to include the optional GPU contracts when compatible CUDA dependencies are installed. Real-image/model runners accept caller-owned fixtures and local weights; they neither download nor publish them. `tests/studio_compare.py --moire` checks three real illustrations × six styles × six switch/slider combinations (108 cases), including full/crop/problem previews with dark adaptation off. The existing independently checked depth inputs were reused for that renderer update; SAM/depth was separately exercised for the 2026-10-11 GPU/lifecycle change. Private fixtures are not redistributed in this repository; the synthetic API runner is included for reproduction.

`tests/bend_acceptance.py` accepts caller-owned baseline/split/divider-and-arc project snapshots and an immutable assets directory. It checks that splitting preserves the selection union, direction actually changes, and all six rendered styles and solved fields match an independently obtained upstream. The tested bent-leg sequence passed all 18 stage/style cases; its final Studio → SaveImage output matched the original exactly, and the RGBA layer recomposed without pixel error. This is a bounded regression check, not proof that SAM selects every bent or crossed leg correctly.

Drafts/presets/exports live in the current ComfyUI user's `stocking_texture` directory. The editor checks same-origin mutations, per-session ownership, stale inputs and Apply acknowledgements. This is not a substitute for ComfyUI authentication or public-Internet hardening.


## Storage and retention

`ComfyUI/user/<current-user>/stocking_texture/exports/` and `drafts/` are temporary storage. Creating an editor session removes adapter-owned files older than 7 days unless any open session references them. Recently written files and a draft currently being reopened are retained. Set `STOCKING_STUDIO_RETENTION_DAYS` before starting ComfyUI to change the number of days; `0` disables cleanup. Only direct PNG/PSD exports and JSON drafts are considered; unknown files and subdirectories are preserved. Preferences/presets are never expired.

`ComfyUI/input/stocking_studio/assets/` contains SHA256-named original images and depth arrays referenced by saved workflow JSON. **Assets are never deleted automatically.** Back up this directory together with workflows, and use the folder's Properties to inspect its size. For manual cleanup, first close the editors, retain a backup, and check every workflow and draft you intend to keep for `asset` and `depth_asset` references. Move only confirmed unreferenced files to a recoverable archive; do not clear the folder merely because an editor session ended. Guide PSD is an additional portable export, not a replacement for all workflow settings.

The iframe embeds trusted same-origin code with both `allow-scripts` and `allow-same-origin`; it is **not a security sandbox**. Exported text files use LF via `.gitattributes`, including under Windows `core.autocrlf=true`. The `/api/ping` version is derived from the pinned `UPSTREAM.json` commit.
