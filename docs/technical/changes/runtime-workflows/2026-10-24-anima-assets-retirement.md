# Anima 工作流与 UAP 分支退役

2026-10-24。按用户明确请求，主仓退役全部 Anima 模型工作流与 UAP 分支，只保留 Krea2 与通用图片处理链。

## 变更

- 删除工作流：`生产套件_01_Anima原版_LoRA生产_v2.json`、`生产套件_02_Anima2.9B_动漫生产_v2.json`、`生产扩展_05_Anima2.9_裁剪精修回贴.json`、`生产扩展_07_Anima原版_左右扩图.json`、`生产扩展_10_部位细化_Anima.json`；删除对应模板 01、02、05、07（10 无模板）。
- 删除 UAP v2 与权威模板内的分支 `a1`、`a29`、`ext05`、`ext07`：155 个根节点、240 条连线、67 个分组、22 个根级内嵌子图实例与 2 个 `高级 · 擦线与导出` 嵌套定义随之移除；保留 `k2/ext04/ext06/ext08/ext09`，默认与活动分支改为 `k2`。正式图与模板逐字节相同（`9f547db3…`）。
- 同步元数据：`extra.uap_workbench`、`qgn_navigation_groups`（11→7）、`production_suite`（source_stats 9→5、integrated_modes、navigation_slots）、`codex_uap_integration`（默认分支、静音清单、model_families、utility_extensions）、`uap_model_contracts`（17→7，仅 Krea2）、移除 `anima_model_url`/`anima_model_version_id`。
- 删除 Anima 专用实现：`production_tools/simplify_anima_control.py`、`fix_anima_erase_mask.py`、`test_anima_control.cjs`、`web/anima_control.js`、`tests/test_anima_control_workflow.py` 与 `tests/fixtures/anima_control_before.json`；`connect_standalone_krea2_control.py` 内联所需 `node()` 辅助。
- 更新 `merge_unified_workflow.py` 的 `SOURCES`（9→5）与紧凑布局微调、`validate_profiles.py`、`validate_uap_workflow.py`（默认分支 Krea2、退役分支拒绝、按分支实际 mode 检查静音）、`test_validate_profiles.py`、`test_control_switches.cjs`（Krea2 UAP/独立 03）、`test_uap_browser_retirement.py`（改为断言退役 UUID/节点不存在，通用子图检查改用 Krea2 子图）；同步 `web/runtime_controls.js`、`control_switches.js`、`prompt_inspector.js`、`workspace.js`、`task_activity.js` 中的 Anima 专用提示与面板。
- 文档与目录同步：工作流/工作台/本体/模型/反推说明、项目地图、README、已知问题、UAP 说明、使用指南、插件融合说明、工作流状态表、production_tools README、`CHANGELOG.md`、`catalog.json`、`model_sources.json` 的 UAP 文件摘要（`c4eb1072…`→`9f547db3…`）及快照元数据摘要。

## 结构计数

| 项 | 之前 | 之后 |
|---|---|---|
| 根节点 | 272 | 117 |
| 连线 | 363 | 123 |
| 分组 | 112 | 45 |
| 内嵌子图定义 | 25 | 1 |
| 分支 | 9 | 5 |
| QGN 导航槽 | 11 | 7 |
| 模型配套（contracts） | 17 | 7 |

## 验证

- `merge_unified_workflow.py --validate`：通过（117 节点/123 连线/45 分组/1 子图/7 QGN）。
- `validate_uap_workflow.py --report <仓外临时文件>`：通过（默认分支 `[03] Krea2 生产`，退役分支不存在，非默认分支静音）。
- `test_uap_browser_retirement.py`（14 项）、`test_validate_profiles.py`（5 项）、`test_control_switches.cjs`、`test_uap_daily_controls.cjs`、`test_uap_compact_widgets.cjs`、`test_plugin_fusion.cjs`、`test_uap_navigation.cjs`、`test_stocking_workflow.cjs`：通过。
- `model_sources.py render/check`、`snapshot.py verify`、`technical_catalog.py check`、`maintain.py check-staged`：见提交前门禁输出。

## 边界与回滚

- 本轮仅主仓源码与文档；**未写入运行区** `G:\ComfyUI-aki-v3`，未重启、清队列、释放模型或执行生图。运行区部署与删除属单独授权与回执。
- 历史版本 `Anima_推荐版_*.json` 三份、`UAP统一生产工作台_v1.json`、既有收据和 `docs/technical/archive` 保持只读，不随本次清理改写。
- Anima 插件、白名单、训练工具与模型/LoRA 权重的处置不在本轮；`model_sources.json` 的 `observed_present` 与资产身份不变。
- 代码回滚可回到基线提交 `899541bfb`；被删工作流仍可从此前 Git 历史取回（摘要见[收据](../../receipts/anima_workflow_retirement_20261024.json)），本次不建立工作树副本。

## 部署状态（2026-10-24 更新）

运行区部署已完成（2026-10-24 16:45–16:48，task-3）：16 份文件写入运行区，11 份 Anima 工作流/模板/脚本从运行区删除；运行区 UAP 与模板 SHA-256 `9f547db3…`（240,208 B），workflows 目录保留 8 份 JSON（UAP v2、03、99、04/06/08/09、丝袜），模板目录 9 项，五分支默认 Krea2。服务在部署前后均未运行，未重启、未清队列、未生图。运行区与主仓 HEAD 逐字节一致（16/16）。仓外部署收据 `anima-workflow-deployment-20261024`：VERIFIED.json `fc18a969…`、DEPLOY_RESULT.json `3fd4ae90…`。
