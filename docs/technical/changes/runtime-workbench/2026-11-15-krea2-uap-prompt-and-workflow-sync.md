# Krea2 主提示词绑定修复、全链路核验与五分支 UAP 同步（2026-11-15）

## 背景与根因

用户在 UAP 菜单（`#uap-daily-desk`「常用控制台」及 `#unified-workbench`「生成」「画布控制」内嵌控制台）切换至 Krea2（`k2`）或指令编辑（`ext04`）时，主正向提示词输入框缺失或被只读节点抢占，存在两层叠加根因：

1. **工作流元数据丢失**：精简导出 `UAP统一生产工作台_v2.json` 与 `Krea2_精简生产_v1.json` 时，节点 `#1233`（`[00W-1] 最常用正向提示词`，`CR Prompt Text`）的 `inputs[0]` 丢失了 `"widget": {"name": "prompt"}` 标记，在 ComfyUI 前端被还原为无文本 widget 的外接槽。
2. **常用控制台解析器缺少类型过滤与上游回溯**：`uap_daily_controls.js` 原先仅在 `CLIPTextEncode` 节点自身查找 `text` / `positive` / `negative`，既无法沿 `CLIPTextEncode.text` 输入连线回溯到上游 `CR Prompt Text` 的 `prompt` 控件，又会被标题含「正面提示词」的 `ShowText|pysssss` 预览节点（如 `#1169`、`#1227`）误抢占后静默隐藏；同时未识别 `WeiLinPromptUI` 与 `Krea2EditGroundedEncode`（`instruction` / `negative_prompt`）。

## 修复与同步范围

1. **提示词目标解析修复（`uap_daily_controls.js`）**：
   - 新增 `preferredPromptWidget`、`promptWidgetSource` 与 `resolveBranchPromptNodes`，显式排除 `ShowText|pysssss` / `ShowText` / `MarkdownNote` / `Note` / `PreviewAny` 只读节点及已被连线占用的同名输入槽；
   - 支持沿编码器输入槽回溯至上游未连线的 `CR Prompt Text.prompt`，优先匹配 `[00W-1]` / `[00W-1P]` 正向主节点与 `[00W-1N]` 负向主节点，并兼容 `WeiLinPromptUI` 与 `Krea2EditGroundedEncode`（`#1236` / `#1237`）；
   - `render()` 与 `readPlan()` 共用同一解析入口，`loraOptions` 兼容 ComfyUI `0.42.0` 的 V1/V3 `COMBO` `/object_info` 结构。
2. **跨架构底模拦截增强（`runtime_controls.js` & `uap_model_contracts`）**：
   - 在 `UAP统一生产工作台_v2.json` 的 `extra.uap_model_contracts` 中登记本机 3 个 `moss\图像生成\*.safetensors` 底模为 `family: "moss"`；
   - 在 `runtime_controls.js` 的 `modelOptionIssue` 增加目录前缀家族推断兜底（`moss\`、`anima\`、`krea2\` 等），在 Krea2 分支禁用异构底模并标注 `（架构不符）`，同时兼容 V3 `COMBO` 刷新返回。
3. **Krea2 工作流与五分支 UAP 同步**：
   - 将运行区精简后的 5 分支 `UAP统一生产工作台_v2.json`（`k2`、`ext04`、`ext06`、`ext08`、`ext09`，移出旧内置 Anima 分支）与阶段 1~3.2 前端（`canvas_write.js`、`uap_erase_ui_v2.js`、`uap_selfcheck.js`、`uap_rewrite_guard.py` 等，退休旧 `anima_control.js` / `workbench.js`）纳入主仓快照；
   - 补齐 `UAP统一生产工作台_v2.json`（含 `templates/`）与 `Krea2_精简生产_v1.json` 中 `#1233` 的 `"widget": {"name": "prompt"}` 元数据；
   - 规范化 `k2` 分支 `nodeIds`（`130163` 整数化），恢复 24 个可选反推/预览/图库工具节点的默认 `mode = 2` 并补齐 `properties.uap_default_mode`；
   - **默认关闭 Krea2 Depth 控制链**：`#1187`（`[02G-MODEL-AUTO]`）默认设为 `["原始K2 LoRA模型_自动回退", "priority", 0]`，`#130163`、`#1160`、`#1161` 及子图内 `#1159` 默认 `mode = 2`，开箱即纯文生图，勾选「启用控制」时一键切回 `strict` 控制路径；
   - **替换 `ext04` 已删底模**：将 UAP `#1234` 与独立 `生产扩展_04_Krea2_指令编辑.json`（含 `templates/`）`#1` 引用的已删 `CuteDisaster v2 Turbo UC__BF16` 更新为现存同系列 `krea2\图像生成\Krea2__🧊💀 DaSiWa Krea2 - Turbo - Raw 💀🧊__DarkDesire V3 Turbo UC__BF16__cv3362930__f3250905.safetensors`；
   - 同步刷新 `snapshot/inventory/model_sources.json` 与 `docs/MODEL_SOURCES.md` 的 `workflow_sha256`。
   - 全程保持用户的提示词正文、LoRA 列表、种子与采样参数零改动。
4. **实机全按钮与生图点检检出的 3 项前端交互缺陷修复**：
   - **「待用列表 · 组合预览」幂等打开与中途关闭防空引用（`workbench_shell.js` + `uap_daily_controls.js`）**：`openWorkbench` 改用局部 `instance` 引用持有工作台实例，避免 `await renderSidebar()` 期间关闭弹窗把模块级 `current` 置空导致 `Cannot read properties of null (reading 'showPending')`；新增幂等 `openPendingPanel()` 并在 `navigate({openPending: true})` 中同步帧渲染待用列表（关闭态安全返回 `false`）。新增 `test_workspace_mount.cjs` 常态与竞态单测。
   - **ComfyUI `0.42.0` `/jobs` API 下「停止当前运行」中断兼容（`run_controls.js`）**：在读取 `queue.Running[0]` 任务 ID 时补充 `|| item.id`，兼容 `0.42.0` 前端 `fetchQueue` 返回的 `{id, status: 'in_progress'}` 结构，消除 `无法确认正在运行的任务` 报错。新增 `test_run_controls.cjs` 回归断言。
   - **嵌套 `controls.mount()` 释放时恢复外层内嵌状态（`uap_daily_controls.js`）**：保存并恢复 `previousMounted` 与 `previousClose`，修复统一工作台从「画布控制 → 定位控制与擦线」切回「生成」页后 `#uap-daily-desk` 丢失 `data-workbench-mounted` 退化为底部 `position: fixed` 悬浮条的问题。

## 验证与边界

- **静态与单测**：`uap_rewrite_guard.py`（R1/R2/R3 全部 0）、10 套 Node `.cjs` 回归（含 `test_uap_daily_controls.cjs`、`test_uap_navigation.cjs`、`test_control_switches.cjs` 500 轮循环、`test_model_quick_switch.cjs`、`test_workspace_mount.cjs`、`test_run_controls.cjs`）、`validate_uap_workflow.py`、`test_uap_browser_retirement.py`、`test_validate_profiles.py`、主仓顶层 `unittest` 全集、`snapshot.py verify`、`technical_catalog.py check`、`model_sources.py check`、`maintain.py check-staged` 均通过。
- **实机 UI 全按钮与 GPU 生图点检（`http://127.0.0.1:8188`）**：
  - 顶栏导航、常用控制台、统一工作台全页签与按钮、6 类提示词选择器、底模快切（含 MOSS 异构拦截）、LoRA 增删改、擦线蒙版编辑器、6 个分支/独立流程入口（含 `丝袜纹理修复` 跳转与 Studio iframe 编辑器打开/关闭）全部实点通过；
  - `k2`（Krea2 生产）4 条真实 GPU 链路落盘像素核验通过：纯文生图 `(768, 1344)`（`mean=137.51, std=83.47`，`24.2s`）、开启 Depth 控制同种子 `(768, 1344)`（与关闭态逐像素 `MAD = 65.302`，`26.5s`）、1.5× 分块二放 `(1152, 2016)`（`mean=138.03, std=82.69`，`82.5s`）、PixAI 标签反推真实完成；
  - 其余 4 个内嵌扩展分支真实 GPU 落盘像素核验全部通过：`ext04` 指令编辑 `(768, 1024)` RGB（`mean=167.86, std=93.18`，相对输入图 `MAD = 14.517`，`28.28s`）、`ext06` 透明素材抠图 `(768, 1024)` RGBA 四通道（`alpha_min=0, alpha_max=255`，透明区 `61.97%` / 主体不透明区 `30.84%`，`2.72s`）、`ext08` 超分二倍交付 `(1536, 2048)` RGB（精确 `2.0×`，`mean=174.64, std=91.99`，`2.92s`）、`ext09` 超分四倍素材 `(3072, 4096)` RGB（精确 `4.0×`，`mean=174.65, std=92.20`，`1.66s`）；全部测试输出图已归档至 `output/_codex_qa/uap_live_20261115/`，正式 `UAP统一生产工作台_v2.json` 磁盘 SHA-256 保持未变。
  - 点检「JoyCaption · 三路反推」时检出 `ComfyUI-Olm-JoyCaption` 在 Krea2 驻留显存下触发磁盘卸载（单任务耗时 `53m15s`）与无法快速响应中断的问题，已同步在 `olm_joycaption.py` 修复（见[JoyCaption 显存与中断保护](../runtime-core/2026-11-15-joycaption-vram-and-interrupt-guard.md)），待生产服务下次重启后加载新 Python 模块生效。不据本轮功能回归更新模型画质结论。
