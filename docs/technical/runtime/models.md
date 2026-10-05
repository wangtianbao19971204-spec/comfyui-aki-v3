# 模型、LoRA 管理与资源配套

文档修订：2026-10-05.1。

## 实现与资源

统一包内 `modules/comfyui-lora-manager/` 是当前管理实现；模块入口通过 [modules.json](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules.json)登记。[模型说明](../../MODELS.md)、[模型清单](../../../snapshot/inventory/models.json)和 [工作流模型引用](../../../snapshot/inventory/workflow_models.json)提供路径、用途及捕获时依赖。

模型/LoRA 的实际权重、预览和大型 Civitai 缓存保持仓外；清单的 `sha256: null` 不表示已校验。目录模型还需 config/tokenizer/processor/index 等同版本伴随文件，不能只搬单个权重。

## 维护与隐私

LM Civitai 前后端兼容、插件版本和下载队列是独立边界，不能仅更新网页脚本就假定后端支持。真实配置和缓存可能含 key；公开示例只放格式，认证从仓外读取。运行中的 SQLite/WAL 不以旧副本覆盖。

本次技术整理不下载、切换模型，不测试真实 key，不改已有 LoRA 参数。模型输入的许可与法典图文资料的许可分别核对。

## 验证与限制

核对已部署插件哈希/版本、模型文件存在及家族、节点加载依赖和服务状态。管理界面正常不代表权重可推理；需要实际比较时锁定 prompt、seed、分辨率、采样器和步数，使用隔离输出及同一组配套。

大文件放置与小样例见 [外部资源](../../EXTERNAL_ASSETS.md)。不能把来源目录当成已备份资源，或仅据文件名断定模型架构。

历史比较流程留有 [比较规程](../archive/benchmark_reports/MODEL_COMPARISON_RUNBOOK.md)、[批量比较实现](../archive/benchmark_reports/2026-08-24_anima_anima29_krea2/scripts/run_benchmark.py)和 [三模型报告](../archive/benchmark_reports/2026-08-24_anima_anima29_krea2/report/三模型详细对比报告.md)。脚本含旧机器路径及真实队列/卸载操作，只作实现参考，不能照旧运行；权重、图片、raw trace 与环境仍需外部输入。

## 更新记录

- 2026-10-05：补入 LoRA Manager [vite.config.mts](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-lora-manager/vue-widgets/vite.config.mts)，保留现有 Vue 构建的 app/api、settings 模块外置修正；只复制已用原件，不重建或替换在线 bundle。特殊后缀纳入收录回归，模型/分词资源另按 [支持文件契约](../../../governance/runtime-support.json)登记仓外路径。

- 2026-10-05：登记统一管理实现、模型清单与仓外资源边界；将维护包版本与插件/模型版本分开。
