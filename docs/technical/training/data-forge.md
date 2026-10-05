# 角色黄金集与可续跑生成

文档修订：2026-10-05.2。

## 入口与实现链

[forge.py](../../../snapshot/runtime/character_lora_forge/forge.py)是 CLI；[pipeline.py](../../../snapshot/runtime/character_lora_forge/character_forge/pipeline.py)实现计划、续跑、修复、评分与提升；[matrix.py](../../../snapshot/runtime/character_lora_forge/character_forge/matrix.py)产生可复现任务/种子；[workflow.py](../../../snapshot/runtime/character_lora_forge/character_forge/workflow.py)计算输出反向依赖闭包和绑定；[scoring.py](../../../snapshot/runtime/character_lora_forge/character_forge/scoring.py)与 `vlm.py` 区分技术评分和视觉语义审核。

流程为视觉身份契约 → 分层候选计划 → ComfyUI 队列生成 → 技术与可选 VLM 评分 → 人工审核 → 配额/差异检查 → caption 配对 → 黄金集。`machine_gold` 不自动等于最终训练集；续跑保留 prompt ID、seed、输入与拒绝原因，不能靠文件名重新推断身份。

## 数据和私密边界

真实角色目录有源材料、视觉规格、参考组、种子集、候选、拒绝记录和正式数据集。大图片、逐图输出和训练权重仓外保留，关键规格、参数和发布评估可作为受审查技术参考，不复制 provider key。

## 已归档的角色技术契约

训练/角色联合选单共 49 份小文件，**47 份已归档**并与[来源/哈希登记](../../../governance/technical-archive.json)一致：17 份训练 profile、15 份发布文档、15 份角色契约/说明。该目录属于 `docs/technical/archive/` 历史参考，不是自动部署或执行输入。

| 范围 | 实际归档入口 |
|---|---|
| Alicia 角色与黄金集计划 | [character.json](../archive/character_lora_forge/characters/alicia_bell/character.json)、[gold_package_plan.md](../archive/character_lora_forge/characters/alicia_bell/gold_package_plan.md)、[选择策略](../archive/character_lora_forge/characters/alicia_bell/gold_selection_strategy_review_20260818.md)、[候选轮次计划](../archive/character_lora_forge/characters/alicia_bell/selection_campaign_20x200_plan.json) |
| 视觉规格与形态/服装边界 | [visual_spec.json](../archive/character_lora_forge/characters/alicia_bell/01_visual_spec/visual_spec.json)、[dual_form_base_spec.json](../archive/character_lora_forge/characters/alicia_bell/01_visual_spec/dual_form_base_spec.json)、[形态/服装矩阵](../archive/character_lora_forge/characters/alicia_bell/01_visual_spec/form_outfit_separation_matrix_20260818.md)、[分形态 LoRA 契约](../archive/character_lora_forge/characters/alicia_bell/01_visual_spec/split_lora_contract_20260822.md)及同目录其余设计说明 |
| Rosasha 说明 | [README.md](../archive/character_lora_forge/characters/rosasha/README.md)；对应训练/发布文档见 [LoRA 档案](lora-forge.md) |

另外两份候选原件 `character_lora_forge/characters/rosasha/character.json`、`character_lora_forge/characters/rosasha/01_visual_spec/visual_spec.json` 的硬链接数均为 2，按保护契约未复制，仍在外部角色目录。没有为凑齐 49 份解除硬链接或修改原件；Rosasha README/训练 profile 不能冒充缺少的完整视觉契约。

18 份文件中的训练 `trigger_token` 经语义核实后按[精确路径/整文件 SHA 登记](../../../governance/training-trigger-reviews.json)保留原值，只处理指定 literal 规则误报；没有把鉴权 token 或整个目录列为例外。真实图集、caption 数据集、逐图评分和环境仍需外部输入，不能凭 47 份文字档案重建全部候选或直接续跑旧任务。

VLM 评分会向所选服务发送候选与参考图片，必须属于当前授权；`--no-llm` 仅做技术评分，不能冒充一致性判断。不同角色/形态的固定特征、可变服装、配额、淘汰条件分别记载，不以漂亮或高分替代可训练性。

## 验证与接手

[test_core.py](../../../snapshot/runtime/character_lora_forge/tests/test_core.py)与 [test_recovery_tools.py](../../../snapshot/runtime/character_lora_forge/tests/test_recovery_tools.py)提供工具级回归。[README](../../../snapshot/runtime/character_lora_forge/README.md)记录命令，但其中角色数量、推荐流程是当时基线；新角色不能照抄旧审美/年龄/配额设定。

日常先 doctor/plan，生成和外部评分需另有授权。原始图集与 caption、选择/淘汰 manifest 成组保留。不可重跑旧修复脚本覆盖后来的人审结果。

## 更新记录

- 2026-10-05：将可复用生成、依赖闭包、评分/人审、恢复工具与真实图片资源分层登记；本轮未生成、上传图片或重建训练集。
- 2026-10-05：接入 47/49 联合技术档案的实际链接与哈希核对结果；明确两份 Rosasha 硬链接原件仍在外部，未将目录引用当作图片/数据备份。
