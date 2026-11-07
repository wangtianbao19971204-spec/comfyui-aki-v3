# Krea2 最终预览与保存改为串联

## 问题

`[00W-5] Krea2 一体化最终预览`（PreviewImage）与 `[00W-6] 保存 Krea2 最终图`（SaveImage）原本是 `[12] 可选显存释放` 的**两个并列下游**：两条连接都从同一槽位出发。同一次完整执行里两者拿到同一个 tensor，图必然相同；但 ComfyUI 1.49 前端的「执行到选定的输出节点」（选中输出节点后出现的悬浮 ▶ / 命令 `Comfy.QueueSelectedOutputNodes`）会带 `partial_execution_targets` 提交，后端 [execution.validate_prompt](../../../../ComfyUI/execution.py) 只把名单内的 `OUTPUT_NODE` 计入 `outputs_to_execute`，再据此建执行闭包。于是**只选 `[00W-5]` 时 `[00W-6]` 不进入闭包，保存节点一次都不执行**。

2026-11-07 08:19–08:25 的四次提交就是这种情况：

| 提交 | 提交图节点数 | `outputs_to_execute` | 产物 |
| --- | ---: | --- | --- |
| `04591509` | 46（含 1136、1138） | `['1138']` | `temp/ComfyUI_temp_gqxad_00001_.png` |
| `abcc7267` | 46 | `['1138']` | `temp/…_00002_.png` |
| `eea8458c` | 46 | `['1138']` | `temp/…_00003_.png` |
| `dbc353b4` | 46 | `['1138']` | `temp/…_00004_.png`（与前一张逐像素相同，命中缓存） |

`output/` 目录里最新的 Krea2 成品仍是 11-02 22:54 的 `Production_Krea2_Integrated_00033_.png`（1344×768、8 步、`shinomiya kaguya` 那版提示词），与这四次 768×1344 / 12 步的新图不是同一张，所以「资产里看到的最终图」和 `[00W-5]` 不一致。

## 修复

只改一条连接：把 `[00W-6]` 挪到 `[00W-5]` 的上游。

```text
修复前  [12] ─┬→ [00W-6] SaveImage
              └→ [00W-5] PreviewImage

修复后  [12] → [00W-6] SaveImage → [00W-5] PreviewImage
```

- 以 `[00W-5]` 为唯一目标的局部执行，会先执行上游 `[00W-6]`，保存的 PNG 与预览显示的是同一个 tensor。
- 以 `[00W-6]` 为目标的执行仍只保存、不预览。
- 工作台「开始生图」与主 Queue 的目标集 `[00W-6, 00W-5, [12]]` 不变，两者照旧先后执行。

节点、参数、提示词、LoRA、种子、尺寸、开关、分组与 `extra` 全部保持；逐字段比较只有下面六处变化：

| 位置 | 修复前 | 修复后 |
| --- | --- | --- |
| `.last_link_id` | 338040 / 338033 / 667 | 338041 / 338041 / 668 |
| 预览连接行 | `[10294, 1226, 0, 1138, 0, "IMAGE"]` | `[338041, 1136, 0, 1138, 0, "IMAGE"]`（03 为 `[661…]` → `[668, 89, 0, 13, 0]`） |
| 保存节点输出表 | `[]` / `null` | `[338041]`（03 为 `[668]`） |
| 预览节点输入 | `10294`（03 为 `661`） | `338041`（03 为 `668`） |
| `[12]` 输出表 | `[10294, 10295]` | `[10295]`（03 为 `[662]`） |

## 源码与运行区

本次改动的六份文件（同一处改接，各按原序列化格式写回，未重排其余字段）：

| 范围 | 文件 | before sha256 | after sha256 |
| --- | --- | --- | --- |
| 运行区 | `ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json` | `7986e55ae5c116463278ac5c1a2250177a4703536c1ad3b8dcf70645c7b0c85c` | `342c6ca728695bec17714a8d5dd6c48d350aed3632f5be8bfcd17ce6a716272e` |
| 运行区 | `ComfyUI/user/default/workflows/生产套件_03_Krea2_一体化生产_v2.json` | `d44eb8d07abcb45f2d8ac48d9990adf0cc22070840b8f43c94b86076b318bacd` | `3125f69da2c615ec1b6531f1eca307b8c9519c1a997c7d37a44cf7c18637024e` |
| 主仓正式图 | `snapshot/runtime/ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json` | `c4eb1072b8742afb55675e1bb0f9136a10a01c99921bb53d6e9fd1173ad80267` | `2f85a35d25db381c6780b5683b69abc005a9e763ec5a8d4df2a28853a89d767b` |
| 主仓模板 | `snapshot/runtime/production_tools/templates/UAP统一生产工作台_v2.json` | 同上 | 同上（与正式图保持一致） |
| 主仓正式图 | `snapshot/runtime/ComfyUI/user/default/workflows/生产套件_03_Krea2_一体化生产_v2.json` | `30cf66fe43ca785b902aa679373fa6ca4355f88f350ae1a2e65368c9da6d6935` | `cf3c1aa746ff7a264e508513984e2025a6b3494b1f4b690b6a487af2e7149898` |
| 主仓模板 | `snapshot/runtime/production_tools/templates/生产套件_03_Krea2_一体化生产_v2.json` | `440498398d0d27b796399c3c0d701426d21aed8ed07cbbf508570a3fef881538` | `3a0b1553885ca97152cde6cce3942babe1985207b343759d6c8c6018f0a7b6d0` |

运行区的 UAP v2 是 2026-10-25 重建的 K2-only 变体（113 节点／118 连接），与主仓 272 节点九分支变体不是同一份导出；两者节点 ID 相同，因此按同一 ID 做同一处改接，互不覆盖对方的布局、参数与用户资料。03 的正式图、模板与运行区副本本来就是三份不同导出，同样只按 ID 改这一处。

## 验证

- 图完整性：全部连接两端回指一致（origin 输出表列出该 ID、target 输入槽指向该 ID），连接 ID 唯一，节点数与连接数不变。
- 闭包：以 `[00W-5]` 为目标的输入闭包含 `[00W-6]`、`[12]`、采样与编码链，保存节点确实在上游。
- 结构校验：主仓 `production_tools/validate_uap_workflow.py` 在改后的正式图上 `validation: passed`、`errors: []`，正式图与模板 sha256 相等。
- 未执行 GPU 生图；「单点 `[00W-5]` 同时落盘」需要重新载入工作流后在页面上实测，详见[收据](../../../receipts/krea2_preview_save_chain_20261107.json)。

## 回退

六份原件已保留在仓外 `production-backups/2026-11-07-k2-preview-save-chain/`，同目录副本留在忽略的 `local/k2_preview_save_chain_20261107/before/`。回退即把原件按原路径写回；工作流 JSON 的回退不需要重启服务。
