# 模型、LoRA 管理与资源配套

文档修订：2026-10-07.6。

## 实现与资源

统一包内 `modules/comfyui-lora-manager/` 是当前管理实现；模块入口通过 [modules.json](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules.json)登记。[模型说明](../../MODELS.md)、[模型清单](../../../snapshot/inventory/models.json)和 [工作流模型引用](../../../snapshot/inventory/workflow_models.json)提供路径、用途及捕获时依赖。

模型/LoRA 的实际权重、预览和大型 Civitai 缓存保持仓外；清单的 `sha256: null` 不表示已校验。目录模型还需 config/tokenizer/processor/index 等同版本伴随文件，不能只搬单个权重。

[公开来源目录](../../../snapshot/inventory/model_sources.json)覆盖 384 个已捕获权重、11 个特殊配套及后来新增的 9 个 LoRA；[易读下载表](../../MODEL_SOURCES.md)由 [model_sources.py](../../../scripts/model_sources.py)离线生成。每项记录相对运行根路径、来源页／版本／文件身份、上游声明摘要、实际本机摘要、家族、目录配套和备注。来源字段从公开元数据和节点／发布说明提取，原始插件缓存、登录值、私密备注正文与权重不入库。

来源目录绑定旧 inventory 与当前正式 UAP v2 摘要，当前 23 个静态引用资产均有候选。目录型／节点默认模型另在配套项登记；历史 workflow_models 继续保留捕获身份。本地训练项删除前是 19 个文件路径、17 份内容：4 个成品使用版本与 15 个评估检查点；当前只保留 4 个成品，15 个评估项已删。逐项训练头、输出／发布记录与历史复制关系见[计数复核](../../receipts/model_source_recount_20261007.json)，当前事实以[清理收据](../../receipts/model_checkpoint_cleanup_20261007.json)为准。4 个历史 intrinsic 转换文件当前上游已不含同文件；旧 T5 词表仅确认家族参考，保持来源待核对并迁移原件。网址、父模型和源码都不能代替这些文件备份。

`render` 只写固定 MD；`check` 仅读主仓，拒绝 URL 鉴权／任意 query、绝对／穿越路径、错误摘要、重复项、基线遗漏和表格漂移。来源 JSON 单项 metadata 登记在 manifest，既有源码、库和其他 inventory 的哈希不改。[26 项隔离回归](../../../tests/test_model_sources.py)检查这些边界和现行路径契约；换机实际放置与更新流程见[模型维护](../../MODELS.md)。

用户随后要求删除 15 个评估检查点，两处原件及相关别名一并清理，迁移只保留 4 个成品。初次删除被审批阻止；本次再次明确请求后，[精确清理工具](../../../scripts/remove_reviewed_eval_checkpoints.ps1)已执行成功，51 个目标全无、4 成品共 8 个运行／发布位置完整摘要保持。来源目录按现场清空已删 15 项的当前 SHA 并设 `observed_present: false`，保留历史清单身份，实际存在总数 380、LoRA 286；不建议备份、恢复或迁移这些已删条目。脚本默认只预览，执行模式不自动改主仓或操作服务／GPU／数据库；本次主仓记录另行完成独立验收。两个历史矩阵工具及七份历史 evaluation manifest 使用旧路径，属于历史记录，清理后不能原样重跑。

## 现行分类与命名

[model_naming_rules.py](../../../scripts/model_naming_rules.py)生成九字段公开白名单；[standardize_models.py](../../../scripts/standardize_models.py)提供候选、审查、主仓修改、受保护运行迁移与后验核对。按 loader 根内的家族／用途组织，文件名保存公开名称、可靠版本、精度与来源身份；规则及后续维护步骤见[分类命名](../../MODEL_NAMING.md)。`current_path` 与 `standardization` 成对登记，保留原 `path`、inventory 绑定和上游下载原名，拒绝跨加载器根、重名及已删资源迁移。

本次实际完成 **306 = 286 个用户 LoRA + 19 个图像底模 + 1 个 SAM 工具**的规范分类和改名；690 件配套一起迁移，41 个主仓引用文件和 5 个运行配置同步。两套 Anima 分开，Platinum 归回 Anima，SAM 单列工具。编码器、VAE、目录型配套和插件 intrinsic 固定权重仍按加载器契约管理。

[47 项迁移回归](../../../tests/test_standardize_models.py)检查命名优先级、白名单隐私、字面配套匹配、下载声明与训练发布副本保持、精确引用、Windows 目录大小写及失败恢复、分页遗漏／漂移与常规／排除集合身份。全量实测摘要、个人字段和 4 个成品／发布副本的核验结果见[标准化收据](../../receipts/model_standardization_20261007.json)。LoRA Manager 的 283 个常规项和 3 个排除项须分别核对；3 项排除缓存已从现行 sidecar 全量重建索引，排除状态保持。此路径／缓存验收不代表全部 UI 交互或 GPU 推理通过。

## 维护与隐私

新增下载项沿用同一来源／命名契约，不重写 `models.json` 的旧捕获范围。2026-10-07 的 9 项先以完整 SHA 匹配匿名 Civitai 确切文件，再从公开白名单生成真实侧车，用现行 `save-metadata` 接口逐项登记缓存；没有全库扫描、重启或推理。现有 286 项权重状态／侧车摘要、283 常规及 3 排除缓存记录保持，4 个自训成品摘要保持。当前为 **295 用户 LoRA（Anima 204、2.9B 2、Krea2 89）**；新增项实际路径、来源身份与限用备注见[导入收据](../../receipts/lora_download_import_20261007.json)。

LM Civitai 前后端兼容、插件版本和下载队列是独立边界，不能仅更新网页脚本就假定后端支持。真实配置和缓存可能含 key；公开示例只放格式，认证从仓外读取。运行中的 SQLite/WAL 不以旧副本覆盖。

本次技术整理不下载、切换模型，不测试真实 key，不改已有 LoRA 参数。模型输入的许可与法典图文资料的许可分别核对。

## 验证与限制

核对已部署插件哈希/版本、模型文件存在及家族、节点加载依赖和服务状态。管理界面正常不代表权重可推理；需要实际比较时锁定 prompt、seed、分辨率、采样器和步数，使用隔离输出及同一组配套。

大文件放置与小样例见 [外部资源](../../EXTERNAL_ASSETS.md)。不能把来源目录当成已备份资源，或仅据文件名断定模型架构。

历史比较流程留有 [比较规程](../archive/benchmark_reports/MODEL_COMPARISON_RUNBOOK.md)、[批量比较实现](../archive/benchmark_reports/2026-08-24_anima_anima29_krea2/scripts/run_benchmark.py)和 [三模型报告](../archive/benchmark_reports/2026-08-24_anima_anima29_krea2/report/三模型详细对比报告.md)。脚本含旧机器路径及真实队列/卸载操作，只作实现参考，不能照旧运行；权重、图片、raw trace 与环境仍需外部输入。

2026-10-07 [最终验收](../../receipts/final_workflow_acceptance_20261007.json)：Krea2 三个初始黑图在复合模型／执行缓存清理后用相同输入恢复。当前与历史正常记录的实际 UNET/VAE 均为 BF16，当前进程未强制其精度；原生 latent 类也有成功反证。本轮不盲改 dtype、latent 或正式参数，不能把冷态恢复称为根因永久修复。现行模型检查绑定此前完整摘要，不重复认证全部权重。

## 更新记录

- 2026-10-07：导入 9 个新下载 LoRA，4 画风／3 角色权重／2 效果，8 原版 Anima／1 发布者 2.9B remap；全部完整 SHA、文件身份、AutoV3、触发词、管理缓存及 loader 枚举通过。原来源项、inventory 与正式工作流绑定保持，只更新来源 metadata 摘要；真实侧车／缓存／备份外置。原核验在源文件移除前因 Windows 分隔符比较停止，随后按绑定续验完成，没有重复复制或登记；未做下载端点或 GPU 验收，GYARI 原用途限制已记录，见[收据](../../receipts/lora_download_import_20261007.json)。
- 2026-10-07：运行区与 Git 对照补齐已随插件分发的词表、分词器和系统提示词，统一 LoRA Manager 的 pytest 快照支持也按原字节保存。完整精确选单见 [插件支持登记](../../../governance/plugin-support-20261007.json)；easy-use ChatGLM 词表由外部引用转为 Git 支持，模型权重／用户预览／大型 Civitai 缓存继续外置。维护回归及快照还原通过，不改模型身份、权重、加载器行为或生产配置，未下载或启用额外插件。边界见 [内容复核](../../receipts/github_content_reconciliation_20261007.json)。

- 2026-10-07：最终回归发现 LoRA 广播的 UAP 单一目标保护引用了不存在的变量；改用已经过滤启用状态的 `targetNodes`，保留多目标拒绝与普通图兼容广播。隔离回归覆盖零／多／唯一目标、禁用目标保持及替换强度，验收范围见[最终收据](../../receipts/final_workflow_acceptance_20261007.json)。
- 2026-10-07：全量 286 LoRA／19 底模／1 SAM 完成规范分类、改名与配套迁移；同步保存引用和运行配置，修正 Windows 家族目录大小写及 3 项排除缓存索引。增加现行路径契约、26 项来源回归与 47 项迁移回归；原 inventory、下载身份、个人字段、4 成品和已删 15 项边界保留，实测范围见[标准化收据](../../receipts/model_standardization_20261007.json)。
- 2026-10-07：精确清理脚本已直接执行，移除 15 运行评估、15 训练原件、15 侧车和 6 别名，共 51 路径；成品哈希、正式工作流及运行队列保持。更新 actual presence、当前摘要、总数与恢复说明，历史计数／审批阻止状态保留在先前提交，不作为现行状态。
- 2026-10-07：准备按用户要求不备份地清理 15 个评估条目及两处副本／别名，保护 4 成品；新增受路径、链接、摘要及空队列约束的手动工具。批量及单文件删除均被环境策略拒绝，现场 51 目标全在；仅更新待清理资料与说明，未对外声称删除完成。
- 2026-10-07：复核并纠正此前“19 自训成品”的口径，按 4 成品／15 评估文件登记来源和完整 SHA，两个使用版本与相应评估文件内容相同。以本机训练输出及发布记录证明来源，不再以目录名称或 Civitai 默认布尔字段推断；旧审计收据保持历史摘要，本次说明以[复核收据](../../receipts/model_source_recount_20261007.json)为准。未删除／替换权重、改工作流或运行区。
- 2026-10-07：补换机／他人拉取所需公开来源清单、版本／原文件名／配套与字段样例，保留 384+11 资源及 301 个 LoRA 的原位置。来源状态为 302 已存版本、73 上游映射、19 本地训练文件路径、1 旧词表待核；初轮 15 项本机完整 SHA 与上游文件元数据一致，其他声明摘要不冒充本机实测。匿名查询仅取元数据，Civitai 请求连接超时并保留未验证可用性状态。未下载模型、改工作流、运行区、在线库或服务；初轮验证与限制见[来源收据](../../receipts/model_sources_20261007.json)，计数与训练证据以本次复核为准。
- 2026-10-05：补入 LoRA Manager [vite.config.mts](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-lora-manager/vue-widgets/vite.config.mts)，保留现有 Vue 构建的 app/api、settings 模块外置修正；只复制已用原件，不重建或替换在线 bundle。特殊后缀纳入收录回归，模型/分词资源另按 [支持文件契约](../../../governance/runtime-support.json)登记仓外路径。

- 2026-10-05：登记统一管理实现、模型清单与仓外资源边界；将维护包版本与插件/模型版本分开。
