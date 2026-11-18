# Krea2 Cat Tower v2.0 (Raw) 底模导入（2026-11-18）

## 改了什么

- 新增 `scripts/import_downloaded_model.py`：针对**单个**已命名的下载权重，校验 safetensors 容器与完整 SHA-256、确认与 Civitai 确切版本文件一致、按家族／用途落位、写 sidecar、登记管理卡片、取一张官方预览、并追加目录记录。默认只打印计划；`--apply` 需要开发分支，且先过目录契约校验。
- 容器分类：含 `first_stage_model.`／`cond_stage_model.` 张量的视为完整 checkpoint（`models/checkpoints`），否则视为 DiT 权重（`models/diffusion_models`）；`--kind` 可显式覆盖。加载器枚举按类选择 `CheckpointLoaderSimple` 或 `UNETLoader`。
- 校验链：复制前比对下载指纹，复制时算 SHA，复制后重读目标再算一次，卡片写入后用只读 SQLite 读回路径／名称／摘要，最后确认加载器枚举里有该相对路径；任一失败都保留下载原件。

## 为什么

`import_lora_downloads.py` 只处理 LORA／LoCon 类型并固定写在 `loras` 根下，底模走的是另一套加载器根与卡片类型（管理器把底模记作 `checkpoint`）。硬塞进 LoRA 入口会同时破坏两条契约，所以单独做一个窄入口。

## 本轮结果

- `krea2CatTower_v20Raw_fp8.safetensors`（14,125,465,720 B，`bf5f9955…be53`）→ `ComfyUI/models/diffusion_models/krea2/图像生成/Krea2__Krea2 Cat Tower__v2.0 (Raw)__FP8__cv3338554__f3229901.safetensors`。
- Civitai 身份：模型 2805913 `Krea2 Cat Tower`、版本 3338554 `v2.0 (Raw)`、文件 3229901，`baseModel = Krea 2`，文件 `fp = fp8`。
- 容器只有 `blocks.*`／`txtfusion.*` 等 DiT 张量（878 个），没有 VAE 或文本编码器，因此按 DiT 权重落位、走 `UNETLoader`；现网 v1.0 Turbo INT8 文件保持原样，两者并存。
- 卡片名 `【Krea2｜图像生成】Krea2 Cat Tower · v2.0 (Raw) · FP8`，组织字段 `kind=底模`、`binding_status=hash_verified`；官方预览已取到（`.webp`）。
- 目录：576 → 577 个资产，`observed_present` 314 → 315，图像底模 4 → 5。
- 下载原件按 `--keep-originals` 保留在下载目录（14.1 GB），没有替你删。

## 验证了什么

- `tests/test_import_downloaded_model.py` 9 项：容器分类（DiT／完整 checkpoint）、30 秒内新下载拒绝、截断容器拒绝、目标命名与来源身份、必须为 Checkpoint 类型源、必须精确命中文件摘要、sidecar 组织字段与公开身份、卡片读回需路径／名称／摘要一致。
- 运行区实测：两侧完整 SHA 一致；卡片写入后读回一条；`UNETLoader` 枚举含 `krea2\图像生成\Krea2__Krea2 Cat Tower__v2.0 (Raw)__FP8__…`；目录契约在导入前后各校验一次。
- 未验证：GPU 推理、工作台里实际选它出图、与 v1.0 的画面差异。枚举只证明路径可选。

## 回滚依赖

按仓外 `import-*-075346` 收据里的路径与摘要删除新权重、sidecar 与预览，并从目录移除该条记录即可；v1.0 与其它资产未被触碰。上传的只有脚本、测试、目录记录与说明，权重与预览不在 Git。
