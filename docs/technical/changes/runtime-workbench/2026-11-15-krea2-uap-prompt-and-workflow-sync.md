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
   - 将运行区精简后的 5 分支 `UAP统一生产工作台_v2.json`（`k2`、`ext04`、`ext05`、`ext06`、`ext07`，移出旧内置 Anima 分支）与阶段 1~3.2 前端（`canvas_write.js`、`uap_erase_ui_v2.js`、`uap_selfcheck.js`、`uap_rewrite_guard.py` 等，退休旧 `anima_control.js` / `workbench.js`）纳入主仓快照；
   - 补齐 `UAP统一生产工作台_v2.json`（含 `templates/`）与 `Krea2_精简生产_v1.json` 中 `#1233` 的 `"widget": {"name": "prompt"}` 元数据；
   - 规范化 `k2` 分支 `nodeIds`（`130163` 整数化），恢复 24 个可选反推/预览/图库工具节点的默认 `mode = 2` 并补齐 `properties.uap_default_mode`；
   - **默认关闭 Krea2 Depth 控制链**：`#1187`（`[02G-MODEL-AUTO]`）默认设为 `["原始K2 LoRA模型_自动回退", "priority", 0]`，`#130163`、`#1160`、`#1161` 及子图内 `#1159` 默认 `mode = 2`，开箱即纯文生图，勾选「启用控制」时一键切回 `strict` 控制路径；
   - **替换 `ext04` 已删底模**：将 UAP `#1234` 与独立 `生产扩展_04_Krea2_指令编辑.json`（含 `templates/`）`#1` 引用的已删 `CuteDisaster v2 Turbo UC__BF16` 更新为现存同系列 `krea2\图像生成\Krea2__🧊💀 DaSiWa Krea2 - Turbo - Raw 💀🧊__DarkDesire V3 Turbo UC__BF16__cv3362930__f3250905.safetensors`；
   - 同步刷新 `snapshot/inventory/model_sources.json` 与 `docs/MODEL_SOURCES.md` 的 `workflow_sha256`。
   - 全程保持用户的提示词正文、LoRA 列表、种子与采样参数零改动。

## 验证与边界

- **静态与单测**：`uap_rewrite_guard.py`（R1/R2/R3 全部 0）、10 套 Node `.cjs` 回归（含 `test_uap_daily_controls.cjs`、`test_uap_navigation.cjs`、`test_control_switches.cjs` 500 轮循环、`test_model_quick_switch.cjs`、`test_workspace_mount.cjs`、`test_run_controls.cjs`）、`validate_uap_workflow.py`、`test_uap_browser_retirement.py`、`test_validate_profiles.py`、主仓顶层 `unittest` 全集、`snapshot.py verify`、`technical_catalog.py check`、`model_sources.py check`、`maintain.py check-staged` 均通过。
- **边界声明**：本轮不重启生产服务、不清队列、不释放显存、不提交 GPU 生图任务；运行区写回前对被改文件做 SHA-256 完整备份，并在 `http://127.0.0.1:8188/?uapcheck=1` 通过无队列 `app.graphToPrompt()` 与 UI 实页核验，不据本轮结构修复更新任何模型画质结论。
