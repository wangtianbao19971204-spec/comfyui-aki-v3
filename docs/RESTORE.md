# 恢复与迁移

本页把已经取得的主仓还原成运行目录。先按[开始使用](GETTING_STARTED.md)拉取 GitHub 的 `main` 并检查文件，再按下面的步骤还原和补齐资源；收到离线包时，另看本页的 [Git bundle 恢复](#git-bundle-恢复)。

以下命令在克隆后的仓库根目录执行，沿用开始使用中已核验的 `$comfyPython` 完整解释器路径。运行目标必须是全新目录，例如仓库旁的 `..\comfyui-runtime`；含 `G:\` 的其他路径是原机器示例，换机器使用自己的路径。

## 只向全新目录物化

```powershell
& $comfyPython -X utf8 -B scripts\snapshot.py materialize --dest '..\comfyui-runtime'
if ($LASTEXITCODE -ne 0) { throw 'Materialization failed; retain evidence for inspection' }
```

目标目录必须不存在。工具拒绝直接写回 manifest 原运行根、原 ComfyUI 树和 snapshot 内部。它不会启动服务、执行模型或覆盖现有文件。

每轮使用全新目录，不重用上例中已经存在的目标。从已校验的 GitHub 克隆或离线 bundle 克隆执行还原，保留实际提交与 `RESTORE_RECEIPT.json`；使用离线包时，还须核对还原回执的 manifest SHA 与随包回执一致。取得主仓和还原文件都不代表外部资源、运行依赖和启动验收已完成。

- 普通源码/工作流：逐文件 SHA-256 一致。
- 上游 `.gitattributes` 在 Git 内以 `.gitattributes.upstream` 保存原字节，物化时恢复原名称，避免嵌套换行规则改写快照。原 `.gitignore` 保留。
- 大型 JSON：按清单合并 .part，恢复原始编码/换行/字节并核对整文件 SHA。
- SQLite：从已校验 SQL 分片新建数据库，核对 integrity_check、全部表行数和完整逻辑 SQL 哈希。数据库二进制页布局可不同，不宣称 .db 字节相同。
- Gallery 辅助词库：使用显式 `gallery_fts5_v1` SQL 格式保留全部业务内容、原行身份及历史，并从正文重建受审查 FTS5 索引、核对索引完整性；不能用普通 dump 或旧三库恢复逻辑代替。两份随机模板同样恢复到原相对路径。插件随附词表、分词器、系统提示词及受许可支持的几何数据从主 Git 物化；未捕获的模型、鉴权、用户字体和许可敏感资料另按外部清单补齐。
- 生成 `RESTORE_RECEIPT.json`。临时合并的 `.restore.sql` 保留在物化目录供检查；它不是线上数据库。

## 物化后还需要什么

1. 按 environment.json 准备 Python、ComfyUI 前端分发包、Torch/CUDA 和插件依赖。该文件是已装版本清单，不是经过新机器冷装验收的锁文件，不要无审核整批安装或降级。
2. 按[模型下载来源清单](MODEL_SOURCES.md)取得确切版本、精度和上游原文件名的网上模型／LoRA，或从自己的原备份恢复；相对路径均相对物化后的运行根。安装到 `current_path`，没有该字段才使用 `path`，保留规范本地名及家族／用途子目录；旧捕获路径只是历史身份。分类与改名规则见[分类命名](MODEL_NAMING.md)。config/tokenizer/processor 等配套按同版本完整恢复。自训成品与来源待补项必须另存原件，网址失效时也要保留备份；用户已明确删除的 15 个评估条目不恢复或迁移，历史清单中仍有其文字身份不表示需要补装。具体核验及更新方法见[模型维护](MODELS.md)。
3. 另行恢复 preview 与 preview_thumbnails，保持同名和相对路径，核对 library_media 清单。清单不是图片副本。
4. 根据仓外 `external-runtime` 清单安全补齐机器/认证配置，初版 `excluded_private_configs` 不是完整的后续清单。拉取者按[私有状态示例](../examples/private-state/README.md)在自己的仓外根建立计划和实例记录；示例只含占位值，不能覆盖正式库或成为另一套源码。API key 不写进 Git；远端 LLM 启动器配置放在仓外 `private-config/remote-llm/config.json`。详见 EXTERNAL_STATE.md。
5. 已补迁的插件、两套 Forge、Qwen Lab 与训练依赖源码以 manifest 和 PROJECT_MAP 为准；它们的模型、数据集、输出、依赖二进制及历史媒体仍需单独迁移。旧私有 Git、源网页原件和回滚材料仅供审查/恢复，不重新启用为开发来源。
6. 静态检查工作流节点/模型引用和 profile；修复缺失必须保留工作流原意，不自动启用旁路分支或换底模。
7. 用独立端口、隔离数据做启动/浏览器/中性样例验收；明确通过范围后再决定正式切换，不能直接覆盖正在运行的 8188。

隔离不能只改端口：现有 `production_tools/launch.py` 对非 8188 端口只另设 ComfyUI 自身的 SQLite 路径，插件仍可能访问系统用户资料。LoRA Manager 已提供 `LORA_MANAGER_SETTINGS_DIR`，应只在验证子进程中将它固定到全新验证树的私有目录，避免回落到真实用户配置及缓存。其只读路径解析已核对能跳过系统目录和旧配置回退；其他插件的可写位置、环境依赖与网络初始化仍须逐项核对。不要直接复用带真实绝对路径的 settings；这项路径检查不是完整隔离启动验收。

### 隔离启动实测（2026-10-06）

已按上面的方式完整走通一次：物化到全新目录（8,524 项校验），再用运行区 Python 从物化树启动 25 个生产白名单插件，全部写入限制在该树内。结果 5/5 工作台模块、76 节点、1,939 个注册节点类型、队列 0/0，HTTP 就绪约 180 秒；停机后运行区四个根的文件数、总字节和最新修改时间前后完全一致。证据见[隔离启动收据](receipts/isolated_boot_20261006.json)，原始日志在验证树的 `validation-logs/`。

同轮发现、重建新机器时必须先处理的环境行为：

- **导入期就可能自动装包**：统一包 WeiLin 的 `install_requirements()` 与 Impact-Pack 的 `ensure_onnx_package()` 都在 import 阶段检查，缺包会直接 `pip install`。本机已满足（`uuid7`/`aiosqlite`、`onnxruntime 1.23.2`）所以未触发；裸机首次启动会改解释器并联网，必须先预装。
- **导入期改进程环境**：`comfyui_controlnet_aux/__init__.py` 全局设置 `NPU_DEVICE_COUNT`、`MMCV_WITH_OPS`、`PYTORCH_ENABLE_MPS_FALLBACK`；RMBG 只在显式开启 `SDMATTE_CPU_ONLY` 时才清空 `CUDA_VISIBLE_DEVICES`。
- **启动期联网**：Danbooru Gallery 的标签同步会在启动阶段访问远端，本机失败但未阻断启动。
- 其余 `pip install` 调用点（controlnet_aux、easy-use、Comfyroll、RMBG 提示文字）在节点执行或模型加载时才触发，或已被注释。

已知缺口：`triton` 缺失（Windows 无官方轮子）使 RMBG 的 `SAM3Segment` 未注册，但 `vnccs-utils` 的 SAM3 节点正常，且当前 UAP 工作流只引用 RMBG/BiRefNet；Comfyroll 有 3 个节点在 `INPUT_TYPES` 阶段报错。冷缓存导入较慢（prompt-assistant 83 秒、统一包 129 秒，之后约 247 秒预热缓存）。这只是“能启动并注册节点”，不等于出图质量、GPU 推理或某个具体工作流通过。

## Git bundle 恢复

以下仅供收到离线交付包的使用者；从 GitHub 拉取主仓后，可直接使用上面的还原步骤。

仅使用随包交付回执确认通过的版本；包名、维护版本号、精确提交、manifest SHA、包 SHA 和隔离还原结果必须属于同一轮。当前交付目标为 `comfyui-v0.2.0-20261005.bundle`，对应 `comfyui-v0.2.0-20261005.delivery.json`；以该回执实际存在且 `pass: true` 为最终交付依据，文档中的目标名本身不是验收证明。后续发行沿用这一命名方式，替换为对应版本的实际文件名。

`comfyui-public-v3-20261005.bundle` 只覆盖 `f1e61294` 历史检查点，不包含后续 Anima 补丁、技术补档、维护命令及支持文件补录。它和旧验证目录保持历史身份，不充当最新版；旧 `comfyui.bundle` 含历史凭证，只能私有归档，不能公开复用。

本页 PowerShell 示例沿用[开始使用第 2 节](GETTING_STARTED.md)已选择并核验的 `$comfyPython` 完整解释器路径；先完成该项检查。收到 bundle 的父目录执行下面的克隆流程，进入仓根后执行维护工具。

```powershell
$comfyDelivery = Get-Content -LiteralPath .\comfyui-v0.2.0-20261005.delivery.json -Raw | ConvertFrom-Json
if ($comfyDelivery.pass -ne $true) { throw 'Delivery is not accepted' }
$comfyBundle = Join-Path (Get-Location) $comfyDelivery.bundle.filename
if ((Get-FileHash -LiteralPath $comfyBundle -Algorithm SHA256).Hash.ToLowerInvariant() -ne $comfyDelivery.bundle.sha256) { throw 'Bundle SHA256 mismatch' }
git clone -c core.longpaths=true -- $comfyBundle .\comfyui
if ($LASTEXITCODE -ne 0) { throw 'Clone failed; retain the partial directory for inspection' }
if ((git -C .\comfyui rev-parse HEAD).Trim() -ne $comfyDelivery.commit) { throw 'Restored commit differs from delivery receipt' }
git -C .\comfyui fsck --full
if ($LASTEXITCODE -ne 0) { throw 'Git integrity check failed' }
Set-Location -LiteralPath .\comfyui
& $comfyPython -X utf8 -B scripts\snapshot.py verify
if ($LASTEXITCODE -ne 0) { throw 'Snapshot verification failed' }
& $comfyPython -X utf8 -B scripts\security_guard.py --all-history
if ($LASTEXITCODE -ne 0) { throw 'History security check failed' }
git config --local core.hooksPath .githooks
```

克隆产生的 origin 只是本地 bundle 路径，不是在线远端。新克隆不继承原仓维护作者身份；提交前按开始使用配置自己的 repo-local user.name/user.email，不修改用户全局 Git 身份。

随包回执与包一样保存在仓外，完整详细证据见其 `evidence_id`。回执必须由实际结束的门禁和还原生成；未完成的 `prepared` 元数据、单独的 tag 或旧还原回执都不能替代。文档、版本说明先冻结并提交，最终 SHA/提交/验收结果写在仓外，避免为了把“本包最终 SHA”塞进本包而出现自引用或打包后再次改源码。

Windows 必须在初次检出前使用上面的 `-c core.longpaths=true`：整合插件目录较深，较长的父目录可能触发 `Filename too long`。该选项只设置新克隆仓库，不修改全局 Git 或系统注册表。已有仓库可用 `git config --local core.longpaths true`；失败的半成品克隆不要当作验收通过，也不要直接向生产恢复缺失文件。

## 不是完整灾备镜像

Git + 仓外私有状态共同组成工作流实际使用的完整实例。Git 可还原管理范围内的代码、保存工作流、提示词 JSON 与其检查点数据库逻辑数据；具体覆盖依所取得提交的 manifest，旧 bundle 不自动包含后续 Gallery/插件补齐。模型、预览、认证、Python/CUDA 运行环境、最新运行数据与旧历史媒资需要独立备份。建议把这些外部资源与 Git 交付一起离线存放，分别记录校验值并填写实例记录；不要把“Git 可克隆”误认为“全部数据已异地备份”。
