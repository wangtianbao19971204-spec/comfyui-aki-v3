# MOSS 家族入册、增量导入与缺失记录核对（2026-11-18）

## 改了什么

- `scripts/model_naming_rules.py`：`FAMILY_LABELS` 增加 `moss → Moss`；家族判定按版本级底模 `MOSS Image`／已审查的 `Moss`／`MOSS`／`moss` 根目录归入，跨家族标题（`krea2&MOSS&anima`）不改变归属。既有 Krea2、Anima 判定顺序与 2.9B 分流不变。
- `scripts/register_present_loras.py`（新增）：把运行区已存在、目录里没有登记的 LoRA 按 sidecar 认领——读取 `organization`／`civitai` 字段，逐个实测完整 SHA-256，`path` 取部署后的规范位置、上游原名留在 `sources[].filename`；默认只出计划，`--apply` 需开发分支并先通过目录契约校验。
- `scripts/reconcile_asset_presence.py`（新增）：把运行区已经不存在的记录标为删除。保留 `path`、`bytes`、`sources`、`notes`；清空 `local_sha256`、`current_path`、`standardization`（契约禁止缺失项带位置或本地摘要），并追加说明与仓外回执引用。
- `scripts/import_lora_downloads.py`：分支保护改为先调 `git`，缺失 Git 可执行文件时读 `.git/HEAD` 回退，避免本机没有 Git on PATH 时无法 `--apply`。
- 文档：`docs/MODEL_NAMING.md` 总数、家族表、目录与命名示例加入 MOSS；`docs/technical/runtime/lora-quick-import.md` 记录“先补登记再导入”的顺序与两个新入口。

## 为什么

2026-11-14 的 MOSS 库部署与之后的管理器改名直接写了权重、sidecar 和 LoRA Manager 缓存，没有回写 Git 目录，于是 136 个真实存在的权重在目录里“不存在”，而 2026-10-24 经用户授权永久删除的 Anima／Qwen 系列记录又仍标着“存在”。这两处偏差会让导入器把已部署的同一摘要当成新下载复制第二份，也让总数、家族统计与实际运行区不一致。

## 本轮结果

- 登记 136 个已部署权重：MOSS 117、Krea2 19；其中 `Moss__MOSS Image Edit LoRA` 无 Civitai 身份，按 `unresolved` 记录（来源为空、按摘要识别）。
- 导入 9 个新下载 LoRA（全 MOSS：画风与画师 8、服装与配饰 1），9 项完整 SHA 与 Civitai 确切版本文件一致。
- 标记 247 条缺失记录为删除，另 15 条早前已删除的评估检查点维持原状；Anima／Qwen 路径引用 2026-10-24 授权删除回执，其余记为管理器删除。
- 两个文件名含全角冒号（NFKC 后为 `:`）不满足目录契约，经管理器 `POST /api/lm/loras/rename` 改为 `-`，权重、sidecar、预览与缓存一起移动。
- 两个跳过的下载：`krea2CatTower_v20Raw_fp8`（13.4 GB，Civitai 类型 Checkpoint，不是 LoRA）与 `Pussy Mix - Krea2 ...`（按摘要查 Civitai 返回 404，无确切身份）；两者仍留在下载目录。一个 3.9 GB 的 `.crdownload` 尚未完成，未触碰。

## 验证了什么

- `tests/test_standardize_models.py` 含 4 个 MOSS 用例（底模优先、跨家族标题不改家族、已审查根目录、精度取所选文件）。
- 新增 `tests/test_register_present_loras.py`（6 项）与 `tests/test_reconcile_asset_presence.py`（5 项）。
- 目录契约：三次写入后都跑过 `validate_catalogue`（摘要、唯一路径、缺失项不许带位置／摘要、总数自洽）。
- 导入：复制后两侧完整 SHA 一致、卡片按摘要匹配 1 条、`LoraLoader` 枚举含新路径；预览下载成功。
- 未验证：GPU 推理、工作台内逐项点选、全库重扫与原图对比。加载器枚举只证明路径与索引，不等于出图通过。

## 回滚依赖

- 新登记与导入项可按仓外 `register-*`／`import-*` 收据里的路径与摘要逐条撤回；删除标记按 `presence-*` 收据里的原 `current_path` 与摘要恢复（权重已被永久删除的无法恢复）。
- 上传的是目录、脚本、测试与说明；权重、sidecar、预览与私有收据都不在 Git。
