# 正式17工作流与UAP九分支只读矩阵（纠正版）

本表17份文件含16份独立工作流及UAP v2；旧UAP v1另外完成独立库存及视觉分组和目标表，见legacy_uap_v1_matrix.md。本表取代修订前17份矩阵。全部正式JSON在审计前后SHA一致。旧10份矩阵及冻结包未改；UAP v2九分支拓扑复用已完成库存，只补保存mode/字段连线拒绝信息。

source可写只指已知保存STRING字段、mode和输入连线条件；不代表真实浏览器readonly、最终动态编码正文、生成实跑或模型标签语义通过。02上一轮GUI收据列于JSON，本轮不重复验收。

| 正式文件 | 节点/短SHA | 实际正向与字段守卫 | 实际负向与字段守卫 | 六类适用性 |
|---|---|---|---|---|
| [Anima_推荐版_官方2.9B_BF16_发布页骨架版_细化可选_K2预览外显_无LoRA.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/Anima_推荐版_官方2.9B_BF16_发布页骨架版_细化可选_K2预览外显_无LoRA.json) | 64 / 8b9f0b94b7ad | #107.positive → #134（源可写；编码linked_field） | #6.text → #6（源可写；编码直接字段可写） | 正向技术可适配；GUI待核 |
| [Anima_推荐版_细化可选_手动候选.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/Anima_推荐版_细化可选_手动候选.json) | 62 / 2854a1f73ea6 | #107.positive → #134（源可写；编码linked_field） | #6.text → #6（源可写；编码直接字段可写） | 正向技术可适配；GUI待核 |
| [Anima_推荐版_细化可选_手动候选_K2预览外显_无LoRA.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/Anima_推荐版_细化可选_手动候选_K2预览外显_无LoRA.json) | 63 / 00fc313de02e | #107.positive → #134（源可写；编码linked_field） | #6.text → #6（源可写；编码直接字段可写） | 正向技术可适配；GUI待核 |
| [Krea2_图生图_改图_v1.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/Krea2_图生图_改图_v1.json) | 96 / 91030df500c1 | #107.positive → #134（源可写；编码linked_field） | #542.prompt → #6（源可写；编码linked_field） | 正向技术可适配；GUI待核 |
| [Krea2_工作流.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/Krea2_工作流.json) | 95 / 9819790683d4 | #107.positive → #134（源可写；编码linked_field） | #542.prompt → #6（源可写；编码linked_field） | 正向技术可适配；GUI待核 |
| [▶▷Krea2-高清生图优化流(整合).json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/▶▷Krea2-高清生图优化流(整合).json) | 64 / 731a0989be55 | #164.text → 采样#158.positive；字段可写，资源方向unknown | #164条件 → ZeroOut#140 → #158.negative；无独立负向正文 | 当前算法无识别为正向的六类目标 |
| [生产套件_01_Anima原版_LoRA生产_v2.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产套件_01_Anima原版_LoRA生产_v2.json) | 63 / a5ab2207dbc6 | #107.positive → #134（源可写；编码linked_field） | #6.text → #6（源可写；编码直接字段可写） | 正向技术可适配；GUI待核 |
| [生产套件_02_Anima2.9B_动漫生产_v2.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产套件_02_Anima2.9B_动漫生产_v2.json) | 64 / d3a5ede95868 | #107.positive → #134（源可写；编码linked_field） | #6.text → #6（源可写；编码直接字段可写） | 上一轮六入口GUI证据；本轮静态保全 |
| [生产套件_03_Krea2_一体化生产_v2.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产套件_03_Krea2_一体化生产_v2.json) | 105 / 8e1d2cb98edd | #107.positive → #134（源可写；编码linked_field） | #542.prompt → #6（源可写；编码linked_field） | 正向技术可适配；GUI待核 |
| [生产套件_99_释放模型显存_v2.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产套件_99_释放模型显存_v2.json) | 2 / 2262c4dce241 | 不适用 | 不适用 | 不适用 |
| [生产扩展_04_Krea2_指令编辑.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产扩展_04_Krea2_指令编辑.json) | 16 / d919567c8e60 | #4.prompt → #4（源可写；编码直接字段可写） | #5.prompt → #5（源可写；编码直接字段可写） | 编辑指令字段；语义未验收 |
| [生产扩展_05_Anima2.9_裁剪精修回贴.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产扩展_05_Anima2.9_裁剪精修回贴.json) | 19 / d1762b60dba9 | #4.text → #4（源可写；编码直接字段可写） | #5.text → #5（源可写；编码直接字段可写） | 正向技术可适配；GUI待核 |
| [生产扩展_06_透明素材_抠图导出.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产扩展_06_透明素材_抠图导出.json) | 6 / aa27f6cb1458 | 不适用 | 不适用 | 不适用 |
| [生产扩展_07_Anima原版_左右扩图.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产扩展_07_Anima原版_左右扩图.json) | 17 / f323989a60d1 | #4.text → #4（源可写；编码直接字段可写） | #5.text → #5（源可写；编码直接字段可写） | 正向技术可适配；GUI待核 |
| [生产扩展_08_超分_二倍交付.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产扩展_08_超分_二倍交付.json) | 8 / caabbd785fe7 | 不适用 | 不适用 | 不适用 |
| [生产扩展_09_超分_四倍素材.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/生产扩展_09_超分_四倍素材.json) | 7 / 0659024d4f62 | 不适用 | 不适用 | 不适用 |
| [UAP统一生产工作台_v2.json](G:/ComfyUI-aki-v3/ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json) | 308 / 9c5885654e68 | 九分支见下表 | 九分支见下表 | 随当前分支目标 |

## UAP v2 九分支

保存activeBranch=a1。其他分支源mode2属于未激活状态；分支切换恢复后的mode0只是静态预期。本轮不操作分支，不跨分支猜写。

| 分支 | 节点 | 正向源 | 负向源 | 六类适用性 |
|---|---:|---|---|---|
| a1 Anima 原版生产 | 63 | #1063.positive → #1029（源可写；编码linked_field） | #1030.text → #1030（源可写；编码直接字段可写） | 正向技术可适配；GUI待核 |
| a29 Anima 2.9B 生产 | 64 | #1105.positive → #1100（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch,linked_field） | #1101.text → #1101（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch） | 正向技术可适配；GUI待核 |
| k2 Krea2 生产 | 105 | #1233.positive → #1179（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch,linked_field） | #1185.prompt → #1178（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch,linked_field） | 正向技术可适配；GUI待核 |
| ext04 Krea2 指令编辑 | 16 | #1236.prompt → #1236（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch） | #1237.prompt → #1237（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch） | 编辑指令字段；语义未验收 |
| ext05 Anima2.9 裁剪精修回贴 | 19 | #1253.text → #1253（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch） | #1254.text → #1254（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch） | 正向技术可适配；GUI待核 |
| ext06 透明素材抠图导出 | 6 | 不适用 | 不适用 | 不适用 |
| ext07 Anima 原版左右扩图 | 17 | #1278.text → #1278（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch） | #1279.text → #1279（源拒绝：disabled_or_inactive_branch；编码disabled_or_inactive_branch） | 正向技术可适配；GUI待核 |
| ext08 超分二倍交付 | 8 | 不适用 | 不适用 | 不适用 |
| ext09 超分四倍素材 | 7 | 不适用 | 不适用 | 不适用 |

## 明确拒绝与边界

- 正向WeiLin→CLIP链应写WeiLin positive；CLIP text已linked，拒绝直写。Krea2负向应写CR Prompt Text：独立#542，UAP k2#1185；其CLIP text同样linked。
- 两份旧Krea2工作流均有#381 CLIPTextEncode（mode2，text linked→mode2的#207导入节点）。该辅助编码器拒绝写入，不作为主生成目标。其#550 AnimaPromptPlusClipEncode无输出连线，保留为未连入主链的辅助工具。
- 旧▶▷Krea2整合#164.text mode0字段可写，同时供正向和ZeroOut负向，因此当前resource_actions下游传播判unknown；六类只接positive目标，不能认证该流已有六类可写入口。#173虽标题负面条件但输出断连、方向unknown，不参与采样。#255/#264/#300 mode4旁路，拒绝写入。
- 释放显存99、抠图06、纯超分08/09均无提示词生成链，六类选择器明确不适用。扩展04为编辑指令字段，普通标签语义未验收。
- 推荐版的角色/服装/姿势节点已存在不等于六类前端入口齐全；不以选择器节点存在来认证正式正向链。

全部SHA、保存字段守卫、潜在生成路径、其他编码器、上一轮02收据及拒绝状态见workflow_inventory_all_17_corrected.json。本轮生产写入、正式工作流写入、浏览器动作、队列动作均为0。[最终只读守卫](G:/ComfyUI-aki-v3/benchmark_reports/2026-10-01_workflow_matrix/final_live_guard.json)确认本表17份加旧UAP v1共18工作流、3份正式资料均前后SHA一致，22/22服务资源与磁盘源码一致，队列0/0；不认证真实浏览器写入。
