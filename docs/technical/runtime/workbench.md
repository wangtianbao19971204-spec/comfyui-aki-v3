# 工作台 UI、主题与交互

文档修订：2026-10-07.1。

## 代码入口

统一包 `web/` 是外层工作台唯一实现。主要入口：[workbench_shell.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/workbench_shell.js)、[workbench.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/workbench.js)。主题/图标为 [ui_theme.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/ui_theme.js)、[ui_identity.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/ui_identity.js)、[anime.css](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/anime.css)。

交互按职责拆分：`modal_focus.js` 处理弹窗焦点，`prompt_target.js` 解析真实提示词目标，`pending_prompts.js` 管理待采用内容，`prompt_optimizer.js` 对接已有优化服务，`run_controls.js` 与 `runtime_controls.js` 管理提交反馈与运行状态，`refinement_controls.js` 编辑原节点的细化参数。不要在 UI 再造一份隐形参数状态。

## 交互契约

常用/完整工作台共用真实工作流；窄屏切换输入/结果，进入子图隐藏父导航，返回恢复。生成输入与无下游草稿分开，后者必须明确采用。关闭分支里编辑参数不能自动启用分支。队列回执、执行结束、缓存复用和检测命中是不同状态，不能虚构命中/重绘统计。

提示词优化依赖 prompt-assistant 的配置/请求/取消服务；其没有在用画布节点不代表可移除。模型配套和任务目标校验还由 [工作流档案](workflows.md)说明。

## 宽高与常用尺寸

“尺寸 · 种子 · 采样”中，宽度与高度之间的 **⇄** 按钮互换两值；各自旁边的“常用”下拉提供 `512、640、768、832、896、960、1024、1152、1216、1280、1344、1536、2048` 像素。数字框仍可手动输入，打开页面保持当前尺寸。顶部方图／竖图／横图预设继续可用。

唯一实现是 [uap_daily_controls.js](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_daily_controls.js)，布局在 [studio.css](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/studio.css)。选择项按来源及目标控件当前范围、`step2` 实际步长筛选；互换／成对预设先核对两维，再通过现有共享写入回调及嵌套事务一次提交。失效、重接、跨分支或兼作其他参数的共享来源拒绝写入，需检查原节点并刷新。原生回调失败会尝试恢复原数值；第三方回调的任意额外副作用不在这项恢复保证内。

变更只涉及界面，批量、种子、提示词、模型与分支默认值均保持。大尺寸仍需按模型及显存选择；下拉选项不是 GPU 可运行保证。

## 验证与限制

基础回归：[test_uap_navigation.cjs](../../../snapshot/runtime/production_tools/test_uap_navigation.cjs)、[test_uap_daily_controls.cjs](../../../snapshot/runtime/production_tools/test_uap_daily_controls.cjs)、[test_uap_compact_widgets.cjs](../../../snapshot/runtime/production_tools/test_uap_compact_widgets.cjs)。历史 [动漫 UI 交付](../../../snapshot/evidence/20261005_workbench_anime_polish/REPORT.txt)与 [工作流交互交付](../../../snapshot/evidence/20261005_workflow_product_repair/REPORT.txt)分别记录具体覆盖。

修改后用全新页面核对实际 served 文件和磁盘 SHA，检查主题、窄屏、键盘、焦点与提示词保持性。模拟 composition/事件不是物理 IME；浏览器拦截入队不等于 GPU 推理，历史测试数量不是今天自动通过的证明。

尺寸回归：`node snapshot/runtime/production_tools/test_uap_dimensions.cjs`。隔离实页：安装 Playwright 并具备 Chrome 后运行 `node snapshot/runtime/production_tools/test_uap_dimensions_browser.cjs`；可用 `UAP_TEST_BROWSER_CHANNEL` 指定已安装的其他浏览器通道，`UAP_DIMENSIONS_EVIDENCE` 指定截图输出目录。页面使用真实候选 JS/CSS，其他服务和图变化跟踪为隔离替身，不连接正式 ComfyUI，也不生图；一次撤销边界按前端嵌套事务语义检查，尚不等于生产页面原生撤销或 GPU 验收。

## 更新记录

- 2026-10-07：新增居中的宽高互换与两维常用尺寸下拉，保留手输和初始值；成对预验、来源身份保护及失败恢复避免半组改值。18 组尺寸行为回归与三主题／三屏宽隔离实页通过，原导航与常用控件回归通过。经用户明确允许，两个界面文件已部署；服务端文件摘要、五模块就绪、空队列与 9,484 路径保护通过，保留四库一致备份及精确回退副本。生产页面原生撤销与 GPU 未测，见[尺寸控件收据](../../receipts/workbench_dimensions_20261007.json)。

- 2026-10-07：最终隔离回归修复测试中退休插件目录与单条 import 假设，统一读取主仓 modules；导航 fixture 补现行阶段/控件契约，常用控制台调用真实共享写入 helper。融合测试保留 LoRA 零 CLIP/锁、异步提示词与过期目标校验，并覆盖 UAP 零/多目标拒绝、唯一目标成功、普通广播及禁用目标保持。测试修复不部署界面或修改正式工作流，来源网页、物理 IME 与 GPU 仍须独立验收。

- 2026-10-06：经用户明确请求，将网页桥接、UAP 清理与维护保护共 11 文件部署到运行区，保留启动参数重载后端。真实收件、正负方向采用/序列化/撤销、新版 UAP 实页加载与三份执行源码摘要通过；五模块就绪、队列为空、保护范围与数据库逻辑内容保持。Chrome 油猴安装、五站当前网页 GM 发送及生产整页刷新仍为单独边界，见[运行区部署收据](../../receipts/browser_live_deployment_20261006.json)。

- 2026-10-06：随网页桥接迁移，现行 UAP v2 和权威模板清理图内旧接收部件，网页提示词经工作台待采用区处理；保留 PixAI 反推及原参数，见[工作流专项说明](workflows.md)。

- 2026-10-06：新增独立网页临时来源及页面接收器，正负稿保留原文、编辑和既有目标复核/撤销；服务暂存与领取确认另见 [网页桥接](browser-import.md)。本次候选不等于线上已安装/部署，验证边界以该功能收据为准。

- 2026-10-05：补入 [主题交互测试](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_workbench_anime_polish/test_candidate.cjs)与 [浏览器回执](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_workbench_anime_polish/browser_acceptance.json)；[M9 测量实现](../archive/benchmark_reports/2026-10-02_workbench_hourly/runs/20261002_214157/browser_measurement.js)、[生命周期采集](../archive/benchmark_reports/2026-10-02_workbench_hourly/runs/20261002_214157/lifecycle_collector.js)及 [历史浏览器验收](../archive/benchmark_reports/2026-10-02_workbench_hourly/runs/20261003_015012_R1_autonomous/UI_FINAL_ACCEPTANCE.json)用于接手。未携带的基线、fixture、浏览器轨迹仍依赖仓外原件，不把本轮归档叫作重新 UI/物理 IME 验收。

- 2026-10-05：保留彩色动漫主题、轻量图标和布局；登记常用参数、任务状态、弹窗及结果交互的真实实现与验收边界。
