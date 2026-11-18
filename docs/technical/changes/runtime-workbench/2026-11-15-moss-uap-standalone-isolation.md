# 独立 MOSS 工作流接入 UAP 外壳与 Krea2/MOSS 双向零干扰隔离（2026-11-15）

## 目标与架构选型

按「方案 A（独立轻量工作流接入 UAP 壳）」将 `MOSS_精简生产_v1.json` 纳入主仓受控快照并补齐完整 UAP 外壳与模型契约，保持 `UAP统一生产工作台_v2.json`（及模板）**零字节改动**，同时从工作流标签页、输出目录、底模/编码器/VAE 契约到 LoRA 全入口与 CLIP 通道建立 Krea2 ↔ MOSS 双向防干扰机制。

## 改动范围

1. **独立受控工作流与物理 CLIP 隔离（`build_moss_workflow.py` + `MOSS_精简生产_v1.json`）**：
   - 新增可复现构建脚本 `snapshot/runtime/production_tools/build_moss_workflow.py`，生成字节一致的 `snapshot/runtime/ComfyUI/user/default/workflows/MOSS_精简生产_v1.json` 与 `snapshot/runtime/production_tools/templates/MOSS_精简生产_v1.json`（`id: "moss-lean-production-v1"`，13 节点、11 连线、4 个无重叠分组）。
   - **保留用户原参数**：正向提示词、负向提示词、默认底模 `Moss__MOSS Image__Base__BF16`、种子 `100002`、尺寸 `1024×1280`、CFG `3`、`euler` / `simple` 零改动；统一 `#8` 采样步数序列化值为 `40`，修复 `#12 Note` 乱码，将 `#10 SaveImage` 前缀隔离为 `Production_MOSS/moss`。
   - **物理 model-only 双重保险**：断开 `#4 Lora Loader (LoraManager)` 的可选 `clip` 输入槽，`#2 CLIPLoader`（`type = moss_image`，Qwen3.5 9B）直连 `#5 Prompt (LoraManager)` 与 `#6 CLIPTextEncode`，同时保留 `#4.trigger_words` → `#5.trigger_words1`，从连线层杜绝任何 LoRA 文本层污染 Qwen3.5 9B。
   - 补齐 `extra.uap_workbench`（`activeBranch: "moss"`，`modelFamily: "moss"`，三阶段导航）与 `extra.uap_model_contracts`（登记本机 3 个 MOSS 底模、2 个 Qwen3.5 9B 编码器、Flux2 VAE，同时显式标记 Krea2 底模/编码器/VAE 为 `family: "krea2"` 供双向拒绝）。

2. **原生多标签页无损互跳与 UAP 节点全适配**：
   - `repair_workflow.js`：新增 `MOSS_PATH`（`workflows/MOSS_精简生产_v1.json`）与 `@workflow:moss`（`MOSS 图像生成`），主工作台在 `k2`/`ext04` 后插入该入口，MOSS 页提供 `@main`（`返回统一生产工作台`）、`@main:ext08`、`@main:ext09`、`@workflow:stocking`，调用 ComfyUI 原生标签页打开并保留各自未保存草稿。
   - `uap_daily_controls.js`、`workspace.js`、`static_prompt_inspector.js`、`prompt_inspector.js`、`resource_actions.js`：完整兼容 `Unet Loader (LoraManager)`、`Prompt (LoraManager)` 与 `EmptyFlux2LatentImage`（MOSS 专属 16 倍数预设 `1024×1024`、`1024×1280`、`1280×1024`），展示 `type = moss_image` 编码器说明，向所有含 `modelFamily` 的分支开放「立即释放模型与缓存」（`/free`）按钮，并在 `listPromptTargets` / `NON_EDITABLE_PROMPT_TYPES` 中排除 `Lora Loader (LoraManager)` 的 `text` 字段，防止资料库写入破坏 `<lora:...>` 语法。

3. **Krea2 ↔ MOSS 全入口 LoRA 防混用与 `clipStrength = 0` 锁定**：
   - `runtime_controls.js`：新增 `inferredLoraFamily` 与 `loraCompatibilityIssue`（优先按首段目录 `moss/`、`krea2/`、`anima/` 判定，无目录时按 `moss__` / `krea2__` 文件名前缀判定，正确处理中间含多家族说明字样的 `Moss__*` 文件），扩展 `modelOptionIssue('lora_name', ...)` 并在 `workflowGuardIssue` 入队前拦截异构启用 LoRA。
   - `uap_daily_controls.js`：`#uap-local-loras` `<datalist>` 与 `loraCard` `+` 添加按钮均按当前分支 `modelOptionIssue('lora_name', ...)` 过滤/阻断；在 `moss` 分支或未接 `clip` 的 `Lora Loader` 上新增条目默认 `clipStrength = 0`，调整模型强度时保持 `clipStrength = 0` 不联动。
   - `workflow_targets.js` & `autocomplete.js`：节点「浏览器」按钮在 MOSS 分支锁定 `lm_folder=moss`；UAP 分支下画布 `<lora:...>` 自动补全直接注入 `folder=<family>&recursive=true`（不叠加跨标签页残留的 `ActiveFiltersStore`），且在 `moss` 分支无显式 CLIP 建议值时默认补全为 `<lora:name:strength:0>`。

## 验证与边界

- **离线回归与主仓门禁**：新增 `snapshot/runtime/production_tools/test_moss_workflow.cjs`，与既有全部 12 套 `.cjs` 单测、`uap_rewrite_guard.py`（R1/R2/R3 全部 0）、主仓 `unittest`、`snapshot.py verify`、`model_sources.py check`、`technical_catalog.py check --staged --enforce-changes`、`maintain.py check-staged` 全部通过。
- **运行区限定部署与实页 + GPU 验收（`http://127.0.0.1:8188/`）**：
  - 将 13 个受控文件备份原件至 `G:\ComfyUI-local\temp\backup-moss-uap-20261115\` 后部署到运行区，`UAP统一生产工作台_v2.json` 磁盘 SHA-256（`A84B6014…`）零改动，无需重启后端服务；
  - 实页验证 Krea2 ↔ MOSS 原生标签互跳及 Krea2 未保存提示词草稿完好保持（测后精确还原）；Krea2 与 MOSS 的底模快切、编码器、VAE 与 `#uap-local-loras`（MOSS 141 项全为 `moss\`，Krea2 0 混入）双向隔离生效；
  - 实测 MOSS 控制台填入 `krea2\画风与画师\NIJISIS_krea2_V2.safetensors` 点击 `+` 被精确阻断（`#4` 保持 `[]`），填入 `moss\...` LoRA 点击 `+` 默认 `clipStrength === 0`、改强度为 `0.8` 后 `clipStrength` 仍为 `0`（测后移除恢复 `[]`）；
  - 实跑 1 次默认参数真实 MOSS GPU 生图（`prompt_id = 60faacd7-11dc-4520-b0bb-c6e8bae32a74`，40 步 `1024×1280`，耗时 `47.36s`），成功落盘 `ComfyUI/output/Production_MOSS/moss_00001_.png` 并通过人工画面核验。
