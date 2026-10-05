# UAP、子图、部位细化与二放

文档修订：2026-10-05.1。

## 唯一构建入口

[正式 UAP v2](../../../snapshot/runtime/ComfyUI/user/default/workflows/UAP统一生产工作台_v2.json)与 [权威模板](../../../snapshot/runtime/production_tools/templates/UAP统一生产工作台_v2.json)各自保存并核对哈希。构建/校验用 [merge_unified_workflow.py](../../../snapshot/runtime/production_tools/merge_unified_workflow.py)、[validate_uap_workflow.py](../../../snapshot/runtime/production_tools/validate_uap_workflow.py)。子图内嵌在完整 JSON，不拆成丢失连线/模式的孤立备份。

九分支覆盖两套 Anima、Krea2 生产、Krea2 编辑、裁剪精修、透明抠图、左右扩图和二倍/四倍独立超分。独立旧流是历史快照，不承诺与 UAP 双向同步；构建工具默认权威模板，无参数拒绝写入，导出只允许全新候选。

## 细化与参数链

两套 Anima 次序为手 → 脚 → 区域标准/快速互斥 → 脸 → 眼 → 可选 1.5× 分块二放。细化和二放继续默认关闭，由用户在工作台选择；不新增头发、四肢、人体、服装或独立皮肤支路。

检测器、分割器、裁剪/回贴、局部采样是不同职责；精确节点类型和参数以保存图为准，不把检测模型当成细化底模。常用 UI 直接映射子图原阈值、上下文、降噪、种子与模式；高级采样和缝补仍保留原控件。独立 08/09 超分不是主流程自动续段。

## 模型与数据契约

模型、编码器 type/文件、VAE 按已核对家族匹配；静态家族清单需要新增或同名替换模型后复核。LoRA 兼容与效果不能由底模家族校验代替。正式图和模板中的提示词、LoRA、种子、开关属于用户数据，UI 修复不得顺便改值。

## 验证与剩余问题

热门流程比较保留为 [当时研究报告](../archive/civitai_workflow_study/报告-Civitai近三月热门工作流人体部件与NSFW细化分析.md)、[检测器到细化器链](../archive/civitai_workflow_study/检测器到细化器数据流.json)和 [逐流程明细](../archive/civitai_workflow_study/逐工作流明细.json)。它们不是持续更新的实时热度榜。原始 4.55 MB 元数据与其他大输入仅登记外部位置。

维护实现备份包括 [组件目录生成器](../archive/benchmark_reports/2026-10-04_full_workflow_review/build_component_catalog.py)、[整改结构测试](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_workflow_product_repair/test_structure.py)、[交互测试](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_workflow_product_repair/test_candidate.cjs)和 [真实执行验收实现](../archive/benchmark_reports/2026-10-04_part_refinement_pipeline/runs/20261005_native_e2e_acceptance/acceptance.py)。这些是当时路径/fixture 的历史实现；重用必须先适配到隔离环境，不能直接向生产队列运行。

[产品整改回执](../../../snapshot/evidence/20261005_workflow_product_repair/FINAL_DELIVERY.json)区分结构/保持性、浏览器和 GPU；[真实执行报告](../../../snapshot/evidence/20261005_native_e2e_acceptance/REPORT.txt)是另一轮有限样例。现存 ext05 背景矩形/横带、ext07 扩图接缝问题见 [已知问题](../../KNOWN_ISSUES.md)。区域分支不能以结构检查冒充已实跑，单种子结果也不保证所有风格/遮挡/LoRA。

## 更新记录

- 2026-10-05：明确九分支、内嵌子图与实际细化顺序，修正阶段对比/镜像描述、提交目标及窄屏交互；保持用户参数和默认关闭策略。
