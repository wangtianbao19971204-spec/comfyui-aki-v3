# 独立丝袜纹理修复工作流

日期：2026-10-10

新增 `生产扩展_丝袜纹理修复.json`，源码与模板分别保存于 `snapshot/runtime/ComfyUI/user/default/workflows/` 和 `snapshot/runtime/production_tools/templates/`。构建入口为 `production_tools/build_stocking_workflow.py`，只允许写入全新文件，不重建原 UAP。

工作流只有完整编辑器、成品 SaveImage、透明图层 SaveImage 和操作说明。直接在编辑器导入 PNG/JPG/PSD，应用后运行，输出至 `StockingRepair/finished` 与 `StockingRepair/stockings`。首次使用无需预先排队载入原图。空项目的工作台运行会提示先导入并应用。PSD 在编辑器内单独导出，原图不改写。

`web/repair_workflow.js` 将修复入口插入两处任务选择器，位置在 `ext08`/`ext09` 放大之前，与精修等选项同级。它打开独立文件的原生标签页，不向原 UAP 的九分支或其余历史工作流插入节点；原 JSON、开关、模型、种子及提示词保持。修复页提供返回主工作台及精修、2×/4× 入口，放大仍由用户载入成品并单独运行。完整工作台只显示修复任务及专用编辑控件。

ComfyUI 1.49.6 的 `workflowStore.openWorkflow` 只切换标签元数据。接入按当前原生 workflow service 调用 `workflow.load()` 与 `app.loadGraphData(activeState, true, true, workflow, options)`，带入实际工作流对象，从而保存旧标签的 change tracker 并恢复新标签的草稿。异步过程中检查活动标签是否改变。首次隔离实测发现的仅切换标题问题已修复；正常列表打开、同级入口往返、保存后重开、291 节点的值/模式/连接/子图保持与双 PNG 实际执行均单独核验。

测试：`production_tools/test_stocking_workflow.cjs` 覆盖独立模板、双输出、同级顺序、空项目拦截、精确目标、标签加载、旧图保留、缺文件与过期选择；原导航、常用控件、紧凑布局回归继续运行。隔离环境只加载本轮需要的插件，主 UAP 的缺模型/节点提示不代表生产故障，也不用于证明主 UAP 生成能力。

限定部署、哈希、服务身份、数据库一致副本及原图保持证据见 `docs/receipts/stocking_texture_complete_20261010.json`。新增工作流、五个工作台 JS 文件属于本轮部署范围；不以源清单 seal 的标记宣称整个运行环境已重新部署。

生产保护检查另发现 `uap_daily_controls.js` 已有未纳入本分支的常用尺寸/宽高互换实现。保留现场完整哈希和差异，在仓外候选中三方合并本次 13 行新增入口（外加换行规范化），再做隔离与生产验证；不将运行文件反向覆盖主仓。该文件部署哈希与主仓完整文件不同，收据分别记录两者，后续整文件发布须先处理这一既有差异。其余本轮部署文件与主仓逐字节相同。

生产 1 次独立修复实跑成功；编辑器导出的成品与 SaveImage 逐像素相等，RGBA 叠回原图最大误差 0，合成样例 44,669 像素有变化。主 UAP 291 节点往返后，仅 OlmDragCrop 的原有 `drawing_version` 重载时间戳更新，其余参数、模式、连接和子图一致。新工作流文件保持空项目模板，实测项目留在验收标签草稿和仓外证据。

保护检查的严格逐字节结果保留为未完全相等：Tag 库 WAL 与 VNCCS 自动刷新的仓库元数据发生运行活动；五库一致备份的逻辑内容均相同，原图保持。快速往返主 UAP 还见原 Gallery 初始化提示，未将该模块或主 UAP 生图纳入此次通过结论。
