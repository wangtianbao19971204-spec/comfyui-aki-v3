# Krea2 底模快切与已安装底模登记

## 问题

1. 完整工作台面板（`mountRuntimeControls`）的「模型」区只有一行只读的「模型配套检查」，没有底模切换器；切换 Krea2 底模必须先跳到 `CORE-02A` 的 `[02C]` 节点改 `unet_name`。
2. 常用控制台的「当前分支模型 → 基础模型」下拉会把未登记在 `uap_model_contracts.models` 的文件标成「（不兼容/未核验）」并禁用，而清单是 2026-10-05 的 7 条，本机 8 个底模里有 4 个不在其中：`Krea2-Anime v3.0 BF16/FP8`、`LUSTIFY v10 BF16/INT8`。用户当前在用的 `v3.0 FP8` 正好是其中之一，表现为「无法选择底模」。

## 修复

### 1. 底模快切（`web/runtime_controls.js`）

「模型」区新增一节「底模快切 · 当前分支」：

- 下拉列出当前分支启用中的 `UNETLoader` 的 `unet_name` 全部候选；选中即写入该节点的 widget 并提示「采样参数不随底模自动调整」。
- 未登记的底模仍显示但禁用，并标注「（不兼容/未核验）」，不会误写。
- 模型名由连线提供（`unet_name` 有 link）、分支未启用、当前值不在本机列表时，下拉禁用并给出对应说明。
- 新增「刷新列表」按钮：从 `/object_info/UNETLoader` 重读本机底模，不用重开页面。
- 关闭面板时随 `mountRuntimeControls` 一起销毁，不新增全局状态。

选择器实现为独立导出的 `mountModelSwitch(host,app,branch,nodes,isCurrent)`：`mountRuntimeControls` 内部调用它，**完整工作台面板**（`web/workspace.js`）也直接调用，并挂在「参数与输入」栏的**最上方**（`控制与擦线` 之上）。第一版只加在 `mountRuntimeControls` 里，而该函数只在常用控制台与面板参数区渲染，用户在生图页看不到，因此改为面板直接挂载。没有 `UNETLoader` 的分支（如超分、抠图）不渲染这一节。

### 2. 已安装底模登记（`extra.uap_model_contracts.models`）

按既有做法读取每个文件的 safetensors 头核对键数与块数，登记 4 个 `family=krea2`、`blocks=28` 的底模：

```text
Krea2__Krea2-Anime__v3.0__BF16__cv3435333__f3334576.safetensors   keys=430  blocks=28
Krea2__Krea2-Anime__v3.0__FP8__cv3435333__f3334536.safetensors    keys=878  blocks=28
Krea2__LUSTIFY! …__v10 (Krea 2)__BF16__cv3112728__f3015315        keys=430  blocks=28
Krea2__LUSTIFY! …__v10 (Krea 2)__INT8-ConvRot__cv3112728__f2996235 keys=686  blocks=28
```

`verified_at` 更新为 2026-11-07；旧条目全部保留（重装旧文件仍可用）。运行区清单 7→11 条，主仓 17→21 条（主仓版本仍含 Anima 条目）。

### 3. 文件夹即来源

底模不再要求先登记：`modelOptionIssue('unet_name', …)` 只在清单**明确登记为其它架构**时拒绝，未登记文件直接可用；选项上的「（架构不符）」标注也仅用于这种显式不匹配。

模型列表本身来自 ComfyUI 的 `unet_name` 枚举，所以放进 `models/diffusion_models`（可带子目录）后点「刷新列表」或重开页面就能在列表里选中，不需要改工作流 JSON。切换后仍需按新底模调整步数 / CFG；CLIP、VAE 的配套校验保持不变。

## 验证

- 新增 `production_tools/test_model_quick_switch.cjs`：6 项离线 DOM 用例通过——列表与当前值、未登记模型标注且不写入、合法切换只写一次、连线控制时禁用、非启用分支时禁用、刷新列表不改动已保存底模。
- 新增 `production_tools/test_workspace_mount.cjs`：用桩件挂载完整工作台外壳，断言挂载不抛错、只创建一个模型切换宿主、可正常 dispose。该用例在把宿主插到 `controlHost` 之前（会触发 `ReferenceError`）的坏版本上确实失败，用来自查这类构建期引用错误——本轮第一次部署正是因为这一处顺序错误让整个面板空白。
- `node --check` 两个 `runtime_controls.js` 均通过。
- `/object_info/UNETLoader` 返回的 8 个底模现在全部通过 `uap_model_contracts` 校验（此前 4 个不通过）。
- 未提交生图；底模切换后的实际出图与画质未验证。

## 文件与摘要

| 范围 | 文件 | before | after |
| --- | --- | --- | --- |
| 运行区 | `ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/web/runtime_controls.js` | 见收据 | 见收据 |
| 运行区 | `ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json` | `342c6ca72869` | `bf92f26adf98` |
| 主仓 | `.../ComfyUI-Unified-Prompt-Workbench/web/runtime_controls.js` | 见收据 | 见收据 |
| 主仓正式图/模板 | `UAP统一生产工作台_v2.json` | `2f85a35d25db`（两份同） | `d9a0529d0481` |

主仓的 `runtime_controls.js` 仍是 Anima 退役前版本（运行区自 2026-10-25 起已领先且未入库）；本特性在两份文件里用同一段代码加入，尚未对齐其余差异，后续合并需以运行区为基线重做。

## 生效与回退

工作流 JSON 与前端 JS 都不需要重启服务：刷新页面（Ctrl+F5）后重新载入 `UAP统一生产工作台_v2` 即生效。回退是把备份的两份文件写回。
