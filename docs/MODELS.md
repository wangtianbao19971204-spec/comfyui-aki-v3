# 模型与 LoRA：下载、放置和维护

换机器或他人拉取后，从[下载来源清单](MODEL_SOURCES.md)补资源。权重留在 Git 外；主仓保存来源网址、确切版本、文件身份、相对位置、配套和备注。自训成品、已失效的转换文件和暂未确认的来源，仍需独立备份原权重。

现行 LoRA／生成底模按[统一分类与命名](MODEL_NAMING.md)维护：加载器目录内按家族／用途分层，文件名记录公开模型名、版本、精度及来源身份。`current_path` 是本次规范后的现行放置路径；`path` 保留首次捕获身份，历史 inventory 不重写。SAM 单列工具，目录型配套与插件内置固定文件名仍按各自加载器契约放置。

2026-10-07 已在运行区完成 306 个权重的分类与改名：286 个用户 LoRA、19 个图像底模、1 个 SAM 工具；690 件配套一起迁移，41 个主仓引用文件与 5 个运行区配置同步。保留来源页、下载原名和 4 个自训成品，15 个已删评估项不恢复。逐项内容摘要、加载器及缓存的实测范围见[标准化收据](receipts/model_standardization_20261007.json)。已打开的旧工作流需重新打开更新后的保存文件；本次路径验收不代替 GPU 推理验收。

随后已按同一规范导入 9 个下载的 LoRA，现有 **295 个用户 LoRA**。4 个画风为 YUNSANG-STYLE、Iumu、GYARI style、Anima-style-nai5；角色为信浓及“心”的 Anima／2.9B 两份；效果为 Empty Eyes、Condom Left Inside。来源版本、上游原名、完整 SHA 与触发词见[导入记录](receipts/lora_download_import_20261007.json)，现行位置仍查下载来源清单。GYARI 发布说明限制本地／Civitai 以外使用，已保留原文；整理和安装不表示取得新的使用许可。本次只核验文件、索引与来源，没有进行推理或自动选用这些 LoRA。

## 清单各负责什么

| 清单 | 用途 |
|---|---|
| [models.json](../snapshot/inventory/models.json) | 首次捕获的 384 项权重路径、大小和时间基线；不因新来源记录而改写旧事实 |
| [model_sources.json](../snapshot/inventory/model_sources.json)／[易读表](MODEL_SOURCES.md) | 全部基线、11 个特殊配套及后续新增资产的来源、版本、上游文件名、摘要和当前位置；以后在这里修订来源 |
| [workflow_models.json](../snapshot/inventory/workflow_models.json) | 捕获时保存工作流的静态引用；历史关系不代表当前每条流程都可执行 |

来源清单另绑定正式 UAP v2 原文件摘要，重新检查当前引用。“正式 UAP 所需”包括可选分支的静态引用，不代表所有资源每次都加载，也不改变分支、LoRA、种子或参数。节点还可能按目录或内置默认值加载 PixAI、BiRefNet 等资源，需查看备注与配套。

## 保留的自训成品与已删除的评估文件

2026-10-07 按用户明确要求，**15 个评估检查点已从运行模型目录与对应训练目录同时删除**，没有另存评估权重备份。另清理 15 个侧车、2 个相同内容的 fallback 和 4 个同检查点的训练 final 别名，共移除 51 个文件路径。4 个成品及其正式发布副本完整 SHA 保持一致。来源目录仍保留初次盘点的路径等历史信息，15 项现已标记不存在，不能据旧盘点将它们恢复或迁移。

精确文件／摘要和验收结果见[清理收据](receipts/model_checkpoint_cleanup_20261007.json)。两次较早的直接删除调用曾被环境策略阻止；本次用户再次要求直接执行后，受精确摘要约束的[清理工具](../scripts/remove_reviewed_eval_checkpoints.ps1)已执行成功。它拒绝越界／链接路径及非空队列，逐项重核摘要后直接删除，不创建评估权重副本。模型资料库与训练图片不在此范围。

清理工具只适用于这一次固定文件清单，不是日常缓存清理入口。执行时输出 `source_catalogue_updated: false`；主仓记录随后由本次独立验收更新，15 项 `observed_present: false`、当前 `local_sha256: null`，旧内容摘要保留于历史复核／清理收据。不能将这些文字收据理解为权重副本或可回滚的权重备份。

删除前盘点的 `local_derivative: 19` 是 **19 个权重文件路径**，不能理解成 19 个独立自训成品。逐项核对实际文件 SHA-256、训练头、训练输出和发布记录后，分为以下两类：

| 类别 | 文件数 | 内容 |
|---|---:|---|
| 已选出的角色使用版本 | 4 | Alicia Bell 晨星 Anima、晨星 Anima 2.9B、普通形态 Anima，以及 Rosasha Anima |
| 已删除的评估检查点 | 15 | Alicia Bell 初轮 4 个、晨星初轮／细训 7 个、普通形态 4 个；不迁移或恢复 |

删除前 19 个路径中有 **17 份不同内容**：晨星 Anima 使用版与 `自训评估/alicia_bell_morning_star_eval/step0150.safetensors` 完全相同，普通形态使用版与 `自训评估/alicia_bell_ordinary_eval/step0300.safetensors` 完全相同。清理按精确文件路径执行，保留这两个成品位置；不能按摘要无差别删除。以上仅统计此次已核对的清单，不扩大到其他历史训练轮。

迁移只保留这 4 个成品；本次已删除评估文件没有另存权重备份。原训练项目、数据集及其他未列入范围的历史资料不作连带清理。自训判断须有对应训练输出／发布记录与文件身份依据，不能单凭“自训”目录名、缺少 Civitai ID 或插件的 `from_civitai` 默认标记。此前计数与来源依据见[历史复核](receipts/model_source_recount_20261007.json)；清理状态以新的清理收据为准。

当前来源目录共 404 项，其中 389 项存在、15 项已删除。原 301 个 LoRA 路径中保留 286 项，后来新增 9 项，现有用户 LoRA 共 295 项，其中自训成品仍为 4 项。384 项原始权重与 11 项配套是初次捕获范围；新增项单独登记，不改写旧盘点。

## 换机怎么补

1. 按[恢复方法](RESTORE.md)先物化源码到全新运行根，查自己要用的分支，再查其他 LoRA／工具。所有 `ComfyUI/...` 和插件路径均相对这个运行根，不把权重加入主仓 `snapshot/runtime/`。
2. 打开稳定来源页，选择记录的版本／提交及上游原文件名。Civitai 按 model/version/file ID 和声明 SHA 选文件；一个版本有多种精度时，默认下载入口可能不是所需文件。未确认默认文件的条目只给版本页，下载链接留空。
3. 放到记录的 `current_path`（没有该字段才使用 `path`），保留规范本地名和家族／用途目录。上游原名不同的文件，按已确认的身份改成工作流使用的本地名称。例如 `anima_baseV10_txt.safetensors` 的同摘要上游原名为 `qwen_3_06b_base.safetensors`；中文检测模型也记录各自上游原名。不能只凭相近名称认定别名。
4. 核对大小并计算取得文件的 SHA-256。先与本机 `local_sha256` 比较，再与确切上游文件的 `declared_sha256` 比较；不相同就保留原件和候选，查版本、格式和来源，不自动替换。`null` 不表示验证成功。
5. 完整迁移配套。目录型模型保留同版本 config、tokenizer、processor、标签映射、分片 index 和全部 shard，审查其 Python 模型代码。PixAI／BiRefNet／衣服分割不能只下权重，视觉 GGUF 需要对应 mmproj。特殊文件见 [runtime-support.json](../governance/runtime-support.json)；不为清点而反序列化 `.pkl`／`.pt`。
6. 自训条目按上面的 4 个成品保留；本次用户指定清理的 15 个评估项不迁移或恢复。原项目、图片／caption 和配置另有用途，不与这批权重一起删除。训练器源码不能重建同一成品。历史 intrinsic 转换文件当前上游目录已不含原文件，要备份现件；原作者其他格式不能直接代替。
7. 登录／许可在网站完成，认证配置留在自己的仓外目录。清单不加 token、Cookie、账户配置或签名链接。社区镜像的同摘要只证明内容一致，不代替原作者许可审查。网址可能失效，网上资源也建议保留完整备份。
8. 依赖齐全后，在隔离目录和端口验收具体流程、加载器与 GPU 推理。静态检查或服务启动成功不等于画质验收。

校验自己取得的单个文件（使用本机实际路径）：

```powershell
$comfyAsset = 'D:\ComfyUI-runtime\ComfyUI\models\text_encoders\anima_baseV10_txt.safetensors'
(Get-Item -LiteralPath $comfyAsset).Length
(Get-FileHash -LiteralPath $comfyAsset -Algorithm SHA256).Hash.ToLowerInvariant()
```

这只读取指定文件，不下载、替换或执行工作流。本机私有根路径不作为公共默认值。

## 记录精度怎么读

| 字段／状态 | 含义 |
|---|---|
| `version_metadata` | 已存公开模型／版本资料，可含文件 ID 和声明摘要；未宣称当前站点可访问 |
| `upstream_mapping` | 节点声明、作者发布或上游文件记录提供来源；具体证据与本机摘要是否匹配见备注 |
| `local_derivative` | 本机自训／本地转换，需要原件或完整转换材料；父模型网址不等于成品下载 |
| `unresolved` | 缺可靠来源，保留位置与指纹，迁移原件后继续补查，不猜网址 |
| `sources[].declared_sha256` | 上游／保存元数据声称的摘要，不是本轮读取本机权重的结果 |
| `local_sha256` | 本轮实际完整计算的本机摘要；采集时间见清单，文件变化后必须重算 |
| `sources[].availability` | 实际核验范围；远端元数据存在不等于已下载、获许可或 GPU 通过 |

首轮没有为全部大模型重算摘要。“存在”与大小只代表采集时点，离线 `check` 不读取权重，也不证明新机器已经装好。新取得／替换的重要资源应记录实际 SHA，并复核远端版本和许可。

本次规范化另外对 306 个迁移权重计算完整摘要并进行迁移后核对，具体完成状态以[标准化收据](receipts/model_standardization_20261007.json)为准；此范围不扩展为全部编码器、目录配套或插件固定权重的重新验证。

原版 Anima LoRA／LLLite 与 Anima 2.9B 架构不同，转换或适配必须有自己的过程和验证，不混用原件与转换件。Krea2 的量化形式、Heretic 编码器和自定义 VAE 也不能换成相似命名的官方包后宣称同一实例。

## 以后更新留在同一主仓

新增、替换或查清来源时，修订 `snapshot/inventory/model_sources.json` 对应项，保持原相对路径／本地名，填写来源页、版本／提交、原文件名、大小、配套、家族证据与备注。`evidence` 留可公开的代码／文档或原侧车相对位置，不复制原缓存或自由备注正文。新增资产设 `captured_in_inventory: false`，不伪装成首版资源。原资产删除后保留记录，设 `observed_present: false`，当前 `local_sha256` 清空，旧摘要仍在 Git 历史。

规范移动时保持原 `path`，增加成对的 `current_path` 与 `standardization`，更新真实当前 SHA、当前配套引用及工作流摘要。来源原文件名和确切 ID 保留。校验器拒绝跨加载器根、目标碰撞、已删条目迁移、白名单之外字段和分类目录不一致；示例中的假想 ID／摘要不是可下载资产。

网上取得的模型即使放入“自训”目录，仍保留原来源网址和版本，不能按目录名清空 `sources` 或自动改为本地训练。真正自训的条目在 `derivation.notes` 写明成品／检查点身份、选中步数与训练／发布记录，统计时分别报告文件路径数、不同内容数和成品版本数。

来源页允许 Civitai 的数字 `modelVersionId` 参数，下载地址不得含 query。需要格式选择时，从稳定版本页手动选文件，不保存鉴权或签名 URL。未知来源保持 `unresolved`；不能把 sidecar 摘要填进 `local_sha256`。统计字段 `summary` 按实际条目更新；校验器会拒绝错误统计。

使用已按[开始使用](GETTING_STARTED.md)选择的 `$comfyPython`，在主仓执行：

```powershell
& $comfyPython -X utf8 -B scripts\model_sources.py render
if ($LASTEXITCODE -ne 0) { throw 'Model source render failed' }
& $comfyPython -X utf8 -B scripts\model_sources.py check
if ($LASTEXITCODE -ne 0) { throw 'Model source catalogue check failed' }
```

`render` 只重建本仓易读 MD，不联网、不扫描权重、不部署。`check` 验证路径／URL／摘要格式、384 项基线覆盖、统计与正式工作流摘要，并核对易读表同步。工作流改动使绑定失效时，先按新版重新审查引用和配套，再更新 `workflow_sha256`，不能只改摘要跳过审查。

来源 JSON 属快照 metadata：修订后在 `snapshot/manifest.json` 的 `metadata_files` 中只更新 `inventory/model_sources.json` 的字节数与 SHA，不顺带重认旧库、其他 inventory 或 payload。运行 `snapshot.py verify`、相关测试和暂存门禁，精确提交本批文件，更新[模型技术档案](technical/runtime/models.md)与 CHANGELOG。普通提交不加版本，不自动下载、部署或推送。

字段标注见[模型来源样例](../examples/external-assets/model-source.example.json)，外部放置、目录配套与许可边界见[外部资源](EXTERNAL_ASSETS.md)。

## 更新记录

- 2026-10-07：9 个新下载 LoRA 已分类命名并导入运行目录，完整摘要匹配 Civitai 确切文件，来源与当前路径登记在独立资料分支。原 286 项身份／侧车／个人缓存记录、4 个自训成品和正式图保持；当前 292 常规 + 3 排除 = 295。换机按版本／文件 ID、原名和 SHA 选择，不把权重、侧车或缓存上传 Git；未测下载端点或 GPU，见[收据](receipts/lora_download_import_20261007.json)。
- 2026-10-07：运行区 286 LoRA／19 底模／1 SAM 及 690 配套完成规范分类和改名，保存引用与运行配置按审核映射同步；来源目录用 `current_path` 指向现行位置，保留捕获身份和下载原名。个人字段、排除缓存及实测边界见[标准化收据](receipts/model_standardization_20261007.json)。
- 2026-10-07：受审查清理工具直接执行成功，51 个文件路径全部移除，4 成品的 8 个运行／发布位置摘要不变。来源目录与 manifest 同步实际缺失状态，不恢复或迁移已删评估项；没有创建评估权重备份。
- 2026-10-07：按用户明确指示准备删除运行区／训练原件的 15 个评估检查点、15 个侧车及 6 个相同检查点别名，保留 4 个成品。执行环境拒绝实际删除，所有目标仍在，未转存权重；新增默认预览的手动工具与真实未执行状态，不将计划冒充清理完成。
- 2026-10-07：纠正“19 个自训成品”的计数表述，实际为 4 个成品版本与 15 个评估文件、17 份不同内容；新增逐项训练来源、实际完整 SHA 与重复文件说明。保留全部权重和工作流，原来源审计为历史检查点，本次口径以[复核收据](receipts/model_source_recount_20261007.json)为准。
- 2026-10-07：补迁移来源、精确文件身份、配套与本机别名，增加离线校验和易读表生成，保留自训／历史转换原件及未实测边界；实际覆盖见[本轮收据](receipts/model_sources_20261007.json)。
