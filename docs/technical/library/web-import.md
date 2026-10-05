# 网页、所长法典与 Word 导入

版本：2026-10-05.2；状态：通用门禁和历史执行链均已入主仓，历史链保存在技术归档而非部署源码中。此页不是可直接执行的生产发布教程。

## 用途与入口

把固定网站发布版和 Word 原件逐项对齐，区分短 Tag 与完整提示词资源，保留已有身份和个人字段，再完成图片验证、隔离暂存、受控发布与在线验收。

主仓入口：[网站与 Word 导入交付流程](../../../snapshot/runtime/benchmark_reports/source_update_flow/网站与Word导入交付流程.md)。旧文档内部相对路径按原件保留；对应批次现在位于下列技术归档入口，分类入口见 [分类工作入口](../archive/benchmark_reports/分类工作入口.md)、[分类标准](../archive/benchmark_reports/分类标准.md)及[变更记录](../archive/benchmark_reports/分类标准变更记录.md)。不要把旧相对路径直接当作当前部署路径。

## 实现链

| 环节 | 当前维护入口/边界 | 已归档的历史实现 |
|---|---|---|
| 固定来源与阶段门禁 | `source_update_flow/freeze_batch.py`、`flow_gate.py` | 门禁仍在 `snapshot/runtime/`，不代替采集器 |
| 网页/Word 采集与解析 | 历史批次仅作参考 | [acquire_web.py](../archive/benchmark_reports/2026-09-27_codex_update/acquire_web.py)、[fetch_catalog.py](../archive/benchmark_reports/2026-09-27_codex_update/fetch_catalog.py)、[extract_documents.py](../archive/benchmark_reports/2026-09-27_codex_update/extract_documents.py)、[parse_documents.py](../archive/benchmark_reports/2026-09-27_codex_update/parse_documents.py) |
| 全量匹配、暂存、来源与图片安装 | `source_update_flow/newer_source_policy.py` | [audit_matching.py](../archive/benchmark_reports/2026-09-27_codex_update/audit_matching.py)、[update_common.py](../archive/benchmark_reports/2026-09-27_codex_update/update_common.py)、[prepare_stage.py](../archive/benchmark_reports/2026-09-27_codex_update/prepare_stage.py)、[finalize_stage.py](../archive/benchmark_reports/2026-09-27_codex_update/finalize_stage.py)、[fetch_images.py](../archive/benchmark_reports/2026-09-27_codex_update/fetch_images.py)及同批验证脚本 |
| 渡鸦增量处理 | 固定版本的增量批次 | 顶层 9 个 Python 文件已保留；入口为 [stage_increment.py](../archive/benchmark_reports/2026-09-28_raven_increment/stage_increment.py)、[release.py](../archive/benchmark_reports/2026-09-28_raven_increment/release.py)、[live_acceptance.py](../archive/benchmark_reports/2026-09-28_raven_increment/live_acceptance.py) |
| 增量来源审计 | 旧版审计不代表今天的网站 | [audit_web_images.py](../archive/benchmark_reports/2026-09-28_web_image_reaudit/audit_web_images.py)、[current_gap.py](../archive/benchmark_reports/2026-09-28_web_image_reaudit/current_gap.py) |

同正文合并只允许经过验证的完全相同/规范等价正文；固定来源身份、发布先后与图片哈希后，更新主来源/主预览并保留旧来源、收藏、个人备注。不同正文和不明确修订必须裁决，不按“看起来相似”覆盖。

## 代码依赖闭合

已保留 `2026-09-27_codex_update` 互相依赖的 27 个顶层 Python 文件，不只有 `release.py`；Raven 的发布与在线验收引用该批 [db_fingerprint.py](../archive/benchmark_reports/2026-09-27_codex_update/db_fingerprint.py)，图片准备会复制该批 `fetch_images.py`。静态依赖闭合不等于可直接在新机器重演。

Word 解析加载的 [convert.py](../archive/benchmark_reports/2026-09-15_tag_folder_classification/repo_src/NovelAI-Tag-main/tools/convert.py)、延迟导入的 [codex_update_match.py](../archive/benchmark_reports/2026-09-15_tag_folder_classification/repo_src/NovelAI-Tag-main/tools/codex_update_match.py)与 [migrate_suozhang_char_prompts.py](../archive/benchmark_reports/2026-09-15_tag_folder_classification/repo_src/NovelAI-Tag-main/tools/migrate_suozhang_char_prompts.py)已连同 [LICENSE](../archive/benchmark_reports/2026-09-15_tag_folder_classification/repo_src/NovelAI-Tag-main/LICENSE)保留。环境仍需 `python-docx`、Pillow；上游网站缓存和数据不是解析代码的一部分。

分类验证继续依赖 `2026-09-25_full_coverage/{release_gate,strict_replay,full_coverage_scan,g6_current_source_contract}.py` 和 `2026-09-25_taxonomy_convergence/reviewer_backend_v3/verify_g6.py`，后者会读取更早的三层 fixture harness 及事务助手，详见 [taxonomy.md](taxonomy.md)。这些源码与冻结数据是两种依赖，必须分别登记。

## 数据、安全与重演条件

冻结网页 JSON、Word 原件、来源账本、图片收据、语义裁决、数据库基线、stage/backup 和 round ledger 不是代码。大图片、缓存、鉴权和真实运行 DB 不因源码补迁进入 Git。只保留外部引用时，必须明确新机器仍缺哪些输入。

历史工具含日期、固定哈希、绝对路径、计数和生产服务操作；部分模块导入时就建立目录或读取现场库。不能把“能 import/编译”当作只读，也不能直接执行它们重放旧发布。新批次应先参数化、绑定新基线，在隔离目录验证，获得部署范围后才执行。

NovelAI-Tag 的 LICENSE 对软件采用 MIT，但明确排除法典原文、原始分类、配图与汇编结构的再分发授权。复制解析代码时保留 LICENSE；源数据和已有库里的上游资料公开前另核授权。

## 验证与历史证据

- 主仓已有 `historical_replay_result.json` 和 `current_scope_rejection.json`：证明门禁能接受固定旧版、拒绝以旧版冒充当前全站；不是当前网站状态证明。
- 已归档 [stage_validation.json](../archive/benchmark_reports/2026-09-28_raven_increment/stage_validation.json)：816 张图片验证、811 个目标、445 新 Tag、366 已有主记录更新，回滚演练通过。
- 同批 [live_acceptance.json](../archive/benchmark_reports/2026-09-28_raven_increment/live_acceptance.json)：2026-09-28 的 811 个 Tag API、816 个图片 HTTP 与 stage/live 逻辑指纹通过；[release_receipt.json](../archive/benchmark_reports/2026-09-28_raven_increment/release_receipt.json)是当时正式发布证据。
- 冻结版为 `r-9a4bf4049f141be7d4d9`。未重新请求今天的网站指针，不声称当前网站全部同步。

## 更新记录

- 2026-09-27：完成全站/Word 对照与来源更新批次。
- 2026-09-28：固定版渡鸦 816 条增量正式验收，连接关闭故障的首次回滚单独保留。
- 2026-10-05：补齐历史采集/解析/发布链及验证回执的实际归档链接；原件不改写，完整输入与环境仍需外部准备，未再次执行导入。
