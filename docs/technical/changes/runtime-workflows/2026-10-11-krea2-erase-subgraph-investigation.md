# 2026-10-11：擦线"真正的子图化"调查与结论

用户要求把 Krea2 的擦除段做成子图（不再用根级平铺链），并且两个分支各自持有自己的子图实例。实施后**在真实前端里失败**，原因已定位，本文件记录证据与结论，避免重复走这条路。

## 目标形态

- Anima 分支：继续用 `[05] 线稿与姿态控制` 子图内部的 `高级 · 擦线与导出`；
- Krea2 分支：新建 `K2 擦线与导出` 子图（内部为 `[05C2]~[05C7]` + `[05V1]~[05V7]`），实例常驻 k2 分支，输出接 `[05B6] Depth 来源选择.input_01`；
- 根级平铺链删除。

## 尝试过的手工定义（失败）

`production_tools/krea2_erase_subgraph.py` 按前端格式手写子图定义（`nodes`/`links`/`inputNode`/`outputNode`/`inputs`/`outputs`）。结构自检 0 问题（12 节点、15 连线、端口与连线完全对称，与可正常工作的 `高级 · 擦线与导出` 定义逐项一致），前端也能加载（补上 `inputNode/outputNode.bounding` 后不再报 `SubgraphInputNode.configure` 错误），但：

- 导出 API 图时 `130160` 只剩 `input_02`，`input_01` 整条被剪掉；
- 三种遮罩（编辑器 RGBA / 重复 / 无 alpha）+ 反相探针，控制图**逐像素完全相同**。

## 改用前端自己的转换器（仍然失败，但定位了原因）

`local/frontend_build_k2_subgraph.py` 在页面内调用 `app.rootGraph.convertToSubgraph(new Set(nodes))`，由前端生成定义，再对**序列化数据**做改名与元数据收尾（k2 分支 `nodeIds`/`modes`、实例位置）。转换结果：

- 定义与实例生成正确：实例 `130163`，输入 `image←1157`、`hed←1142`、`canny←1141`、`manga←1143`、`depth←1191`，输出 `IMAGE→130160.input_01`；
- 重新加载后图内连线与文件**完全一致**（338024~338029 六条）；
- 但在**同一个页面会话内**转换后立即 `graphToPrompt()`：`130160` 的输入里 `input_01` 与 `input_02` **都消失了**（只剩 `select`/`mode`/`select_override`）。

**判定实验**（页面内转换 + 只换遮罩跑两次）：
遮罩 = `clipspace-painted-masked-*.png`（真透明）与 `krea2-mask-opaque.png`（无 alpha），控制图 `[05K-PREVIEW]` 哈希**相同**（`9eaf73ce…`）⇒ 子图输出没有进入编码器，`DazzleSwitch` 静默回退到姿势深度。

## 结论（可复现的技术原因）

**ComfyUI 前端的导出阶段无法把"子图实例的输出"解析给 `DazzleSwitch` 这类动态输入（DYN/`*`）节点**：连线在图中存在、加载后也在，但 `graphToPrompt` 不产出该输入，`DazzleSwitch` 的 `priority` 模式随即回退到下一个可用输入。因此在界面上手工执行"Convert to Subgraph"也会得到同样结果——这不是文件格式或工具实现的问题。

## 当前处置（已恢复）

- 主仓与运行区都回到**已验证可用**的形态：k2 用根级 `[05C*]` 擦除链（已修好并验证生效），Anima 用 `[05]` 子图内的 `高级 · 擦线与导出`；
- 两个分支各自持有实现、互不依赖（不会因为分支切换被静音而丢控制图）；
- Anima 那套的遮罩控件此前指向无 alpha 的旧文件（空操作），已由 `production_tools/fix_anima_erase_mask.py` 修正为编辑器保存的 RGBA 遮罩；
- 手工子图工具 `krea2_erase_subgraph.py`、`consolidate_krea2_erase.py` 已从源码树移除，调查脚本保留在 `local/`（不入库）。

## 若要继续推进子图化，可行方向

1. **不经过 `DazzleSwitch`**：让子图输出直接喂一个静态类型消费者（例如 `Krea2ControlImageEncode.control_image`），把"参考图/姿势"的选择改为在子图内部或另一个开关之前完成。这避开了 DYN 输入的限制，但会改变选择器的语义位置。
2. **等前端修复**：该行为属于前端导出对子图输出的处理，若上游修好，同一套转换流程可直接复用（本文件的脚本仍在 `local/`）。
3. **保持现状 + 视觉归组**：根级擦除链折叠成一个分组、并入 k2 分支，界面上不再显得"外面另有一套 05C"。
