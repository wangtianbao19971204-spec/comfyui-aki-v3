# 工作台 UI、主题与交互

文档修订：2026-10-05.1。

## 代码入口

统一包 `web/` 是外层工作台唯一实现。主要入口：[workbench_shell.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/workbench_shell.js)、[workbench.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/workbench.js)。主题/图标为 [ui_theme.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/ui_theme.js)、[ui_identity.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/ui_identity.js)、[anime.css](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/anime.css)。

交互按职责拆分：`modal_focus.js` 处理弹窗焦点，`prompt_target.js` 解析真实提示词目标，`pending_prompts.js` 管理待采用内容，`prompt_optimizer.js` 对接已有优化服务，`run_controls.js` 与 `runtime_controls.js` 管理提交反馈与运行状态，`refinement_controls.js` 编辑原节点的细化参数。不要在 UI 再造一份隐形参数状态。

## 交互契约

常用/完整工作台共用真实工作流；窄屏切换输入/结果，进入子图隐藏父导航，返回恢复。生成输入与无下游草稿分开，后者必须明确采用。关闭分支里编辑参数不能自动启用分支。队列回执、执行结束、缓存复用和检测命中是不同状态，不能虚构命中/重绘统计。

提示词优化依赖 prompt-assistant 的配置/请求/取消服务；其没有在用画布节点不代表可移除。模型配套和任务目标校验还由 [工作流档案](workflows.md)说明。

## 验证与限制

基础回归：[test_uap_navigation.cjs](../../../snapshot/runtime/production_tools/test_uap_navigation.cjs)、[test_uap_daily_controls.cjs](../../../snapshot/runtime/production_tools/test_uap_daily_controls.cjs)、[test_uap_compact_widgets.cjs](../../../snapshot/runtime/production_tools/test_uap_compact_widgets.cjs)。历史 [动漫 UI 交付](../../../snapshot/evidence/20261005_workbench_anime_polish/REPORT.txt)与 [工作流交互交付](../../../snapshot/evidence/20261005_workflow_product_repair/REPORT.txt)分别记录具体覆盖。

修改后用全新页面核对实际 served 文件和磁盘 SHA，检查主题、窄屏、键盘、焦点与提示词保持性。模拟 composition/事件不是物理 IME；浏览器拦截入队不等于 GPU 推理，历史测试数量不是今天自动通过的证明。

## 更新记录

- 2026-10-06：随网页桥接迁移，现行 UAP v2 和权威模板清理图内旧接收部件，网页提示词经工作台待采用区处理；保留 PixAI 反推及原参数，见[工作流专项说明](workflows.md)。

- 2026-10-06：新增独立网页临时来源及页面接收器，正负稿保留原文、编辑和既有目标复核/撤销；服务暂存与领取确认另见 [网页桥接](browser-import.md)。本次候选不等于线上已安装/部署，验证边界以该功能收据为准。

- 2026-10-05：补入 [主题交互测试](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_workbench_anime_polish/test_candidate.cjs)与 [浏览器回执](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_workbench_anime_polish/browser_acceptance.json)；[M9 测量实现](../archive/benchmark_reports/2026-10-02_workbench_hourly/runs/20261002_214157/browser_measurement.js)、[生命周期采集](../archive/benchmark_reports/2026-10-02_workbench_hourly/runs/20261002_214157/lifecycle_collector.js)及 [历史浏览器验收](../archive/benchmark_reports/2026-10-02_workbench_hourly/runs/20261003_015012_R1_autonomous/UI_FINAL_ACCEPTANCE.json)用于接手。未携带的基线、fixture、浏览器轨迹仍依赖仓外原件，不把本轮归档叫作重新 UI/物理 IME 验收。

- 2026-10-05：保留彩色动漫主题、轻量图标和布局；登记常用参数、任务状态、弹窗及结果交互的真实实现与验收边界。
