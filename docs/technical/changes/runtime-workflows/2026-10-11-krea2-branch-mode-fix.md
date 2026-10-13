# 2026-10-11：K2 分支模式表漂移导致 Depth 控制与姿势工作室被静默关闭

## 现象

从别的分支切到「Krea2 生产」后，K2 Depth 控制与 VNCCS 姿势工作室**不再参与采样**，没有任何报错、日志或 UI 提示；出图看起来"正常"，只是控制没了。

## 根因（可复现）

工作台的分支切换由 `ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/ComfyUI-Danbooru-Gallery-V50-GalleryOnly/js/quick_group_navigation/uap_workbench.js` 的 `activateBranch` 实现，L124-129：

```js
for (const b of c.branches)
  for (const id of b.nodeIds) {
    const node = app.graph.getNodeById(id);
    if (node) node.mode = b.id === branchId ? b.modes[id] ?? 0 : 2;
  }
```

即**目标分支的 `modes` 表决定切换后的运行时 mode**。而 `branches[k2].modes` 把这条链记成静音：

| 节点 | 作用 | 表 | 文件 |
|---|---|---|---|
| `1160` | Krea2ControlLoRALoader | 2 | 0 |
| `1161` | Krea2ControlApply | 2 | 0 |
| `1172` | VNCCS_PoseStudio | 2 | 0 |
| `1149` | VNCCS 姿势参考输入 | 2 | 0 |

后果链：`1161` 静音 → `resolveOutput` 返回 undefined → `1187 DazzleSwitch` 的 `input_01` 被丢弃 → 它在 `priority` 模式下回退 `input_02`（`1173` 原始 LoRA 模型）→ 采样器拿到未挂 Control LoRA 的模型。同时 `1172` 静音 → 子图实例 `130163.lineart` 失去姿势来源 → 子图内 `130161` 姿势深度永不执行。

复现脚本：`local/reproduce_branch_activation.py`（按 `activateBranch` 的循环驱动，然后导出）。实测结果：

| 时刻 | `1160`/`1161` | `1172`/`1149` | `1187` 解析 | `1161` 是否在 prompt |
|---|---|---|---|---|
| 切换前（文件态） | 0 | 0 | — | 是 |
| **切换后（修复前）** | **2** | **2** | 仅 `input_02`（原始模型） | **否** |

之所以"有时又能用"：`activateBranch` 在 L115 `if (c.activeBranch === branchId) return;` 提前返回，若当前已是 k2 则不重放表，走的就是文件里的启用态——**同一份工作流出现两种行为**，取决于进入路径。

## 修复

`production_tools/keep_krea2_control_enabled.py`：

- 把 `branches[k2].modes` 中 `130163`/`1161`/`1160`/`1172`/`1149` 改为 `0`（启用），并同步这些节点的自身 `mode`，避免"改了 mode 但没切分支就保存"再次漂移；
- 其余节点记录**不动**（预览类仍保持关闭：`1163`/`1150`/`1228`/`1182`）；
- 不改任何连线或参数。

## 验证

隔离实例，按 `activateBranch` 的循环切换分支后：

| 检查 | 修复前 | 修复后 |
|---|---|---|
| `1161` 在导出中 | 否 | **是** |
| `1172` 在导出中 | 否 | **是** |
| `1187` 解析 | 仅 `input_02` | **`input_01 ← 1161`（控制）+ `input_02 ← 1173`（回退）** |
| 子图展开 | — | 23 个内部节点 |
| 渲染 | — | `success` → `_codex_qa/krea2_modes_fix/krea2_00001_.png` |

## 附带发现（来自同轮三方只读审计，未在本轮改动）

1. **a1/a29 的姿势控制默认关闭**且同样依赖 `priority` 回落：`a1.modes` 把 `1022`（`[05]`）与 `1004`（`[09]`）记为 2，`1023` 的 `select=(none)`，故默认出图等于"无控制"。这与既有文档"控制分支默认关闭"一致，属设计而非缺陷；但**打开了 SW-05 会同时改变出图尺寸**（`1025` 优先取参考图 latent 尺寸）。
2. **a1 的姿势控制只有一种预处理**（`[05]` 内单个 `DepthAnythingV2`），四种预处理（PyraCanny/HED/Manga/Depth）只在 K2 子图里；a1 侧没有"姿势 vs 参考"的二选一。
3. `[05B6]` 的 `select` 当前是 `input_01`（非 `(none)`）：只要擦除后线稿可解析就选它，姿势只在断链时回退。若要"姿势优先"需显式改选择。
4. `[05B5]` 的 `select` 值 `细致线稿` 不是合法槽名，实际退化为 `priority` → `input_01`（PyraCanny），结果与设计意图一致但属巧合对齐。
5. 两处小问题：擦线遮罩引用 `input/clipspace/` 临时目录下的文件；`1189` 与 `130162` 标题前缀同为 `[05V4]`。
6. 三条分支的擦除实现各自独立（a1/a29 用 `[05]` 内的 `高级 · 擦线与导出`，K2 用 `K2 线稿与控制图` 内的擦除链），遮罩文件一致；`a2` 的 `AnimaLLLiteApply.mask` 未接线但该 3 通道权重本就不使用 mask，故无影响。

## 限制

- 只验证到"控制链进入 prompt 且渲染成功"，未做画面级的控制强度验收（同一姿势不同强度/不同种子的成图对比）。
- 未改动 a1/a29 的默认开关策略；`priority` 回退仍是"静默"的，若希望被静音时显式失败需另行改为 `strict`。
