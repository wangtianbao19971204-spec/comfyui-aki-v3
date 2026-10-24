# Anima/Qwen 模型资产退役与来源清单更新

2026-10-24。按用户明确授权永久删除运行区 Anima 原版、Anima 2.9B、Qwen-Image-2.1 系列模型与 LoRA 权重（6 目录 + 8 文件，809 文件 / 125,367,967,479 B），不归档、不备份；Krea2 系列与通用工具权重保留。

## 清单处理

- `snapshot/inventory/model_sources.json`：238 项被删资产设 `observed_present:false`，清除 `local_sha256` 并移除 `current_path` 与配套 `standardization`（规则要求二者成对）；原放置路径、标准名与来源身份写入备注保留历史。
- 移除 9 份已退役 Anima 工作流/模板的引用（70 条引用），保留 UAP 与其余历史工作流引用；`workflow_sha256` 维持新 UAP 摘要 `9f547db3…`。
- 汇总重算：资产 431，观察存在 178、已不存在 253，工作流关联 23，缺失工作流引用 0；`models.json`/`workflow_models.json` 捕获身份不重写。
- `docs/MODEL_SOURCES.md` 重新生成（SHA-256 `52f5a35f15fce556ecd536d81acb2120640af83091c012b8cd48e63087751a21`），`snapshot/manifest.json` 的 `metadata_files` 摘要同步后 seal。

## 保留与恢复边界

Krea2 的 `diffusion_models/krea2`（21 文件）与 `loras/krea2`（322 文件）、`qwen3-vl-4b-heretic`、`krea2RealVae_v10`、OmniSR、RMBG/BiRefNet/SAM、检测器、tagger、排序器等未动。5 个自训 Anima LoRA 删除前与 `anima_lora_forge/releases/` 副本逐字节一致，唯一规范副本保留在 releases；训练 runs/datasets 与 `character_lora_forge` 未动。恢复须重新下载并按 `MODEL_SOURCES.md` 核验，不能从已删除运行路径恢复；本次删除不可回滚。

## 证据

仓外 task-2 收据 `anima-assets-deletion-20261024`（manifest.json `2040f9e8…`、SUMMARY.json `371d42a6…`、VERIFIED.json `eb16c740…`）与主仓[资产退役收据](../../../receipts/anima_asset_retirement_20261024.json)。运行区部署状态见[工作流变更](../runtime-workflows/2026-10-24-anima-assets-retirement.md)。
