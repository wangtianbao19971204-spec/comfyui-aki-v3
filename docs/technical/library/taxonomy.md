# Tag 归属、语义规则与身份契约

版本：2026-10-05.2；当前生产源码标记 `REFINEMENT_VERSION = 2026-09-27.02`。核心实现与历史扫描/回放/查询合同代码已在主仓；历史冻结数据仍有外部依赖。

## 用途与入口

把资料的来源身份、人工归属、主题、父类、细分和独立筛选面分别维护。来源目录不是语义分类依据；raw Tag UUID 和 `codex-*` 提示词资源不是相似正文即可互相替代的身份。

路径缩写见 [索引](README.md)。关键入口：[semantic_refinements.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector/semantic_refinements.py)。

## 主仓实现链

| 文件（`W/prompt_selector/`） | 作用 |
|---|---|
| `semantic_taxonomy.py` | 主题、父归属、分类定义和非正向权重处理 |
| `semantic_projection.py` | `decision_for`、`selector_subcategories` 等，读取存储分类/投影并维护消费者契约 |
| `semantic_refinements.py` | `extract_refinements`：短语、上下文、最长匹配和否定/修饰关系边界 |
| `semantic_filter_counts.py`、`selector_library.py` | 筛选计数、集合类型及路由 |
| `prompt_selector.py` | `_library_entry` 把上述规则组合成实际服务索引；离线验证必须使用相同组合 |
| `tag_library.py`、`tag_identity_bridge.py`、`tag_links.py` | raw Tag 元数据、明确关联与只读身份桥；不自动合并资源 |

正文和人工 `_classification` 等资料在 `snapshot/library/json/`/`sql/`；引擎源码不能代替这些数据。父归属更改是数据事务，纯细分规则更改也须测量全库影响，不能只改一个关键词后宣布完成。

## 已归档的验证代码闭合链

1. 全量门禁：[full_coverage_scan.py](../archive/benchmark_reports/2026-09-25_full_coverage/full_coverage_scan.py)、[release_gate.py](../archive/benchmark_reports/2026-09-25_full_coverage/release_gate.py)、[strict_replay.py](../archive/benchmark_reports/2026-09-25_full_coverage/strict_replay.py)、[g6_current_source_contract.py](../archive/benchmark_reports/2026-09-25_full_coverage/g6_current_source_contract.py)。
2. [reviewer_backend_v3/verify_g6.py](../archive/benchmark_reports/2026-09-25_taxonomy_convergence/reviewer_backend_v3/verify_g6.py)：从历史 harness 提取与对应源码契约一致的 fixture，不自动代表今天的全库。
3. 三层 harness：[verify_filter_pool.py](../archive/benchmark_reports/2026-09-20_taxonomy_audit/verify_filter_pool.py) → [verify_backend.py](../archive/benchmark_reports/2026-09-20_topic_drilldown/verify_backend.py) → [verify_linkage_backend.py](../archive/benchmark_reports/2026-09-23_consecutive_backlog_wave1/verify_linkage_backend.py)。
4. [transaction_common.py](../archive/benchmark_reports/2026-09-23_consecutive_round135_batch2_expression_gaze_pose_release/transaction_common.py)及其 [historical_replay_amendment.py](../archive/benchmark_reports/2026-09-23_consecutive_round135_batch1_controlled_radius/historical_replay_amendment.py)已保留。47 份 `context_parent_rules.py` 从 [batch2 入口](../archive/benchmark_reports/2026-09-23_consecutive_round135_batch2_expression_gaze_pose_release/context_parent_rules.py)继承到[初始父类规则](../archive/benchmark_reports/2026-09-20_consecutive_parent_contexts/context_parent_rules.py)，另有 [review_amendments.py](../archive/benchmark_reports/2026-09-23_consecutive_backlog_wave1/review_amendments.py)；不是只保存一个事务助手。
5. `2026-09-27_taxonomy_one_shot/` 的顶层历史实现及 [test_strict_replay.py](../archive/benchmark_reports/2026-09-27_taxonomy_one_shot/test_strict_replay.py)、[test_exact_contract.py](../archive/benchmark_reports/2026-09-27_taxonomy_one_shot/test_exact_contract.py)、[boundary_tests.py](../archive/benchmark_reports/2026-09-27_taxonomy_one_shot/boundary_tests.py)已归档，报告入口见下文。

历史数据依赖包括不可变 round ledger、`replay_amendments.json`、批准操作、cycle 基线、源文本哈希与查询合同。当前归档只有显式选定的代码和小型证据，完整 fixture 并未随附：这是实现备份，不具备完整离线重演输入。工具有固定路径及写收据/事务副作用，不直接执行旧发布脚本。

## 测试与历史验收边界

主仓现有 `W/prompt_selector/tests/` 中的 Anima 分类/语义和 Tag 身份测试提供局部回归；不能替代全库回放。数据库结构测试见 [数据库契约](../../DATABASE.md)。

已归档的[集中修复与验收报告](../archive/benchmark_reports/2026-09-27_taxonomy_one_shot/集中修复与验收报告.md)及 [release_receipt.json](../archive/benchmark_reports/2026-09-27_taxonomy_one_shot/release_receipt.json)记录第 94 批：214 条分类变化、10,452 项严格历史回放、37 项边界测试，线上索引与离线重建一致。其 `2026-09-27.01` 版本后来有同日导入补强；当前源码是 `.02`，不能把旧哈希直接当今天的服务哈希。

已归档的[剩余分类 EXECUTION_STATE.json](../archive/benchmark_reports/2026-09-27_remaining_classification/EXECUTION_STATE.json)是 `review_complete_with_retained_holds`、0 新分类写入，仍有 1 个直接核对未决项；保留项不等于语义已正确。旧扫描器覆盖范围、人工复核与全库语义准确率也不能混用。

raw Tag 与 `codex-*` 的主题消费者仍是独立维护边界，见 [已知问题](../../KNOWN_ISSUES.md)。本次没有重新扫描全库或自动处理这些差异。

## 更新记录

- 2026-09-27：第 94 批集中规则/归属修复；同日来源导入后源码版本为 `.02`。
- 2026-10-02：六类选择器消费共享主题与父归属，不把来源目录冒充主题。
- 2026-10-05：补齐历史门禁、三层 harness、47 份父类规则链及专项报告的归档入口；保留残留保留项和重演输入缺口，未重新扫描全库。
