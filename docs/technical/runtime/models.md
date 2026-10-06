# 模型、LoRA 管理与资源配套

文档修订：2026-10-07.1。

## 实现与资源

统一包内 `modules/comfyui-lora-manager/` 是当前管理实现；模块入口通过 [modules.json](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules.json)登记。[模型说明](../../MODELS.md)、[模型清单](../../../snapshot/inventory/models.json)和 [工作流模型引用](../../../snapshot/inventory/workflow_models.json)提供路径、用途及捕获时依赖。

模型/LoRA 的实际权重、预览和大型 Civitai 缓存保持仓外；清单的 `sha256: null` 不表示已校验。目录模型还需 config/tokenizer/processor/index 等同版本伴随文件，不能只搬单个权重。

[公开来源目录](../../../snapshot/inventory/model_sources.json)覆盖 384 个已捕获权重与 11 个特殊配套；[易读下载表](../../MODEL_SOURCES.md)由 [model_sources.py](../../../scripts/model_sources.py)离线生成。每项记录相对运行根路径、来源页／版本／文件身份、上游声明摘要、实际本机摘要、家族、目录配套和备注。来源字段从公开元数据和节点／发布说明提取，原始插件缓存、登录值、私密备注正文与权重不入库。

来源目录绑定旧 inventory 与当前正式 UAP v2 摘要，当前 23 个静态引用资产均有候选。目录型／节点默认模型另在配套项登记；历史 workflow_models 继续保留捕获身份。19 个自训 LoRA 需要独立保存成品；4 个历史 intrinsic 转换文件当前上游已不含同文件；旧 T5 词表仅确认家族参考，保持来源待核对并迁移原件。网址、父模型和源码都不能代替这些文件备份。

`render` 只写固定 MD；`check` 仅读主仓，拒绝 URL 鉴权／任意 query、绝对／穿越路径、错误摘要、重复项、基线遗漏和表格漂移。来源 JSON 单项 metadata 登记在 manifest，既有源码、库和其他 inventory 的哈希不改。[20 项隔离回归](../../../tests/test_model_sources.py)检查这些边界；换机实际放置与更新流程见[模型维护](../../MODELS.md)。

## 维护与隐私

LM Civitai 前后端兼容、插件版本和下载队列是独立边界，不能仅更新网页脚本就假定后端支持。真实配置和缓存可能含 key；公开示例只放格式，认证从仓外读取。运行中的 SQLite/WAL 不以旧副本覆盖。

本次技术整理不下载、切换模型，不测试真实 key，不改已有 LoRA 参数。模型输入的许可与法典图文资料的许可分别核对。

## 验证与限制

核对已部署插件哈希/版本、模型文件存在及家族、节点加载依赖和服务状态。管理界面正常不代表权重可推理；需要实际比较时锁定 prompt、seed、分辨率、采样器和步数，使用隔离输出及同一组配套。

大文件放置与小样例见 [外部资源](../../EXTERNAL_ASSETS.md)。不能把来源目录当成已备份资源，或仅据文件名断定模型架构。

历史比较流程留有 [比较规程](../archive/benchmark_reports/MODEL_COMPARISON_RUNBOOK.md)、[批量比较实现](../archive/benchmark_reports/2026-08-24_anima_anima29_krea2/scripts/run_benchmark.py)和 [三模型报告](../archive/benchmark_reports/2026-08-24_anima_anima29_krea2/report/三模型详细对比报告.md)。脚本含旧机器路径及真实队列/卸载操作，只作实现参考，不能照旧运行；权重、图片、raw trace 与环境仍需外部输入。

## 更新记录

- 2026-10-07：补换机／他人拉取所需公开来源清单、版本／原文件名／配套与字段样例，保留 384+11 资源及 301 个 LoRA 的原位置。来源状态为 302 已存版本、73 上游映射、19 自训、1 旧词表待核；15 项本机完整 SHA 与上游文件元数据一致，其他声明摘要不冒充本机实测。匿名查询仅取元数据，Civitai 请求连接超时并保留未验证可用性状态。未下载模型、改工作流、运行区、在线库或服务；验证与限制见[来源收据](../../receipts/model_sources_20261007.json)。
- 2026-10-05：补入 LoRA Manager [vite.config.mts](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-lora-manager/vue-widgets/vite.config.mts)，保留现有 Vue 构建的 app/api、settings 模块外置修正；只复制已用原件，不重建或替换在线 bundle。特殊后缀纳入收录回归，模型/分词资源另按 [支持文件契约](../../../governance/runtime-support.json)登记仓外路径。

- 2026-10-05：登记统一管理实现、模型清单与仓外资源边界；将维护包版本与插件/模型版本分开。
