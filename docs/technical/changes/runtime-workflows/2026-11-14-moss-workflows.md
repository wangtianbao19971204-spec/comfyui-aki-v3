# 2026-11-14 新增 MOSS-Image 文生图工作流

## 改了什么

新增两份工作流到 `snapshot/runtime/ComfyUI/user/default/workflows/`（运行区同名同步）：

| 文件 | 内容 |
|---|---|
| `MOSS_painterly_cine_LoRAManager.json` | MOSS 文生图主工作流：底模用 `Unet Loader (LoraManager)`，画风/角色 LoRA 用 `Lora Loader (LoraManager)` 行内选择（带预览图与触发词），触发词经 `Prompt (LoraManager)` 的 `trigger_words1` 自动前置 |
| `MOSS_painterly_cine_basic.json` | 同一套参数的核心节点版本（`UNETLoader` + `LoraLoaderModelOnly`），给不用管理器的场景 |

两份都是 1024×1280、40 步 / CFG 3.0 / euler + simple，底模 `MOSS Image Base BF16`、编码器 `Qwen3.5 9B BF16`（type `moss_image`）、VAE `Flux2 VAE FP32`；LoRA 行 `clipStrength=0`。

## 为什么

MOSS 的画面风格由 `@painterly cine` 触发词对应的画风 LoRA 决定，角色由角色 LoRA 决定，每次手抄触发词容易错位。用 LoRA 管理器的节点把"选 LoRA / 看预览 / 取触发词"并进工作流，触发词由节点输出直接接进提示词节点，换角色只换一行。

## 验证了什么

- 两份工作流都用 `/prompt` API 原样入队跑通：`MOSS_painterly_cine_LoRAManager.json` 在 8188（升级后的 0.42.0）与隔离 8190 各跑一次，均出图；`MOSS_painterly_cine_basic.json` 用于 v5 系列出图。
- LoRA 行名称按管理器缓存解析成功（`V ALIDATE_INPUTS` 未报缺失），触发词进入提示词后画面体现 `@painterly cine` 的厚涂笔触。
- 工作流已出现在 `ComfyUI/user/default/workflows/`，`/api/userdata?dir=workflows` 能列出这两份。

## 未验证 / 限制

- 只在 MOSS Image（Base / SFT）上验证，没测其它底模组合。
- LoRA 管理器节点的行内下拉、预览图与触发词面板属于前端交互，未做浏览器逐项点击验收（仅 API 路径验证）。
- 负向提示词不含官方默认的 `nsfw`（会与内容冲突），改用 `censored` 等去码词；这一点是刻意的，不是遗漏。

## 回滚依赖

删除上述两个 JSON 即可；不涉及核心代码与数据库。构建与验证脚本在仓外 `G:\ComfyUI-aki-v3\temp\build_lora_manager_workflow.py`、`build_painterly_workflow.py`。
