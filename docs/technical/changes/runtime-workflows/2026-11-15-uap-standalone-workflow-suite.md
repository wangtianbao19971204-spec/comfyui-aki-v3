# 八流程对等独立轻量 UAP 工作流体系拉齐、Krea2 去深度控制与图片反推独立拆分（2026-11-15）

## 目标与架构调整

按对等独立轻量架构将日常生产套件统一拉齐为 **8 个独立单分支 UAP 工作流**，通过 UAP 顶栏流程下拉（`@workflow:<id>`）在 ComfyUI 原生多标签页间无损互跳并保留各自草稿：

1. `Krea2_精简生产_v1.json`（`k2` · `Krea2 图像生成`）
2. `MOSS_精简生产_v1.json`（`moss` · `MOSS 图像生成`）
3. `生产扩展_04_Krea2_指令编辑.json`（`ext04` · `Krea2 指令编辑`）
4. `工具_图片反推_提示词提取.json`（`caption` · `图片反推 · 提示词提取`）
5. `生产扩展_06_透明素材_抠图导出.json`（`ext06` · `透明素材抠图导出`）
6. `生产扩展_08_超分_二倍交付.json`（`ext08` · `超分二倍交付`）
7. `生产扩展_09_超分_四倍素材.json`（`ext09` · `超分四倍素材`）
8. `生产扩展_丝袜纹理修复.json`（`stocking` · `丝袜纹理修复`）

同时将主仓 `UAP统一生产工作台_v2.json` 与 `生产套件_03_Krea2_一体化生产_v2.json` 作为历史快照原样保留以兼容既有契约测试，在运行区日常侧边栏仅部署上述 8 个清爽独立工作流。

## 改动范围

1. **可复现构建器与工作流精简重构（`build_uap_standalone_suite.py` + `build_moss_workflow.py`）**：
   - **`Krea2_精简生产_v1.json`（含同名模板）**：移除深度控制节点（`#1160`、`#1161`、`#1187`、`#1190`、`#130163`）与子图 `945c8bd5-57ab-4054-ae97-da28ca17ccfc`，将 `#1173 Lora Loader` 的 `MODEL` 直接接入 `#1200 KSampler` 与 `#1192 UltimateSDUpscale`，精简为 **36 节点 / 47 连线 / 0 子图 / 5 个无重叠分组**；补齐 `extra.uap_workbench`（`depthControl: false`、`dailyRows`）与 `extra.uap_model_contracts`；用户的正负提示词、LoRA 栈、底模、种子与采样数值零改动。
   - **`工具_图片反推_提示词提取.json`（含同名模板）**：从原合集工作流 Krea2 分支独立提取 `SW-01C` 本地 PixAI 标签反推（默认启用 `mode=0`）、`SW-01D` 本地 JoyCaption 三路反推（默认 `mode=2`）与 `SW-01B` 在线五模型并发反推 + Judge（默认 `mode=2`），配套 `#1206` 参考图输入、`#1233` 正向整理草稿框与 `Fast Groups Muter` 开关（22 节点 / 17 连线 / 4 分组，`defaultTask: "caption"`）。
   - **独立扩展工作流 UAP 壳拉齐（`04` / `06` / `08` / `09`）与 `MOSS_精简生产_v1.json` 阶段对齐**：补齐完整单分支 `extra.uap_workbench` 与阶段分组互不重复契约，重新排布无重叠节点与分组坐标，保留原推理参数不变（`生产扩展_丝袜纹理修复.json` 保持原件字节不变）。

2. **UAP 前端对等导航、输入图控件与独立反推适配**：
   - `repair_workflow.js`：定义 `STANDALONE_WORKFLOWS` 8 项对等独立流程列表与 `@workflow:<id>` 选择器；单分支独立流程统一渲染同一顺序的 8 项菜单，且在运行区退休 `UAP统一生产工作台_v2.json` 后对旧 `@main` / `@main:ext08` / `@main:ext09` 无损回退到独立文件。
   - `uap_daily_controls.js`：为所有含已启用 `LoadImage` 节点的独立流程在常用控制台新增「输入图片」下拉选择与「上传图片」按钮（双向同步原节点并附 `原节点 ↗` 定位）；当 `defaultTask === "caption"` 时主按钮自动切换为「运行当前反推任务」。
   - `task_activity.js` & `runtime_controls.js`：支持 `taskPlan(app, "caption")` 无参聚合当前已启用反推输出并校验 `LoadImage`；纯反推工作流默认激活「提示词反推」页签并隐藏无生成输出的「生成」页签；「追加到正向」在无生成正向节点时自动支持 `#1233` 草稿框；`installWorkflowGuard` 按 `activeBranch.defaultTask` 自动入队反推目标。
   - `uap_erase_ui_v2.js`、`workbench_shell.js`、`workspace.js`：当 `depthControl === false` 时静默退出擦线回退注入并隐藏「定位控制与擦线」按钮，更新空状态说明与 `caption` 流程简介。

## 验证与运行区部署边界

- **离线单测与门禁**：新增 `snapshot/runtime/production_tools/test_uap_standalone_suite.cjs`，连同既有全部 `.cjs` 测试（14 套全绿）、`uap_rewrite_guard.py`（R1/R2/R3 全部 0）、`production_tools` Python 单测（25 项 OK）及主仓全量门禁全部通过。
- **运行区限定热部署与实机 UI + GPU 验收（`http://127.0.0.1:8188/`）**：
  - 备份运行区原文件至 `G:\ComfyUI-local\temp\backup-uap-standalone-suite-20261115\` 后部署 7 个前端 JS 与 8 个独立 UAP 工作流，将遗留重复合集工作流与 `历史版本` 目录归档移出运行区 `ComfyUI/user/default/workflows/`，左侧工作流栏清爽仅展示 8 个独立流程；
  - 实页逐一核验 8 个独立流程通过 UAP 顶栏下拉跨标签互跳、控制台挂载与输入图/提示词同步，全程浏览器 Console 新增 UAP 报错为 0；
  - **实机 GPU 采样验收 1（`Krea2_精简生产_v1.json`）**：默认参数执行纯文生图（`prompt_id = 930cc911-7e3a-43e9-81d5-13a5d4b0d437`，耗时 `44.3s`），成功落盘 `Production_Krea2_Integrated_00049_.png`（`768×1344`）并通过画面核验；
  - **实机本地模型验收 2（`工具_图片反推_提示词提取.json`）**：点击「运行当前反推任务」实跑 PixAI 反推（`prompt_id = 7676ce75-dbf5-4cb1-9746-b18d1fc70c21`，耗时约 `7s`），`#1171` 输出英文标签，且「追加到正向」成功写入 `#1233` 草稿框（测后不保存关闭恢复原文件哈希）。
