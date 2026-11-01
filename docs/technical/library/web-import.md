# 网页、所长法典与 Word 导入

版本：2026-11-01.3；状态：参数化网站差量与历史来源维护分别审查、暂存和验收；历史执行链仍只作参考。此页不是对任意生产库的覆盖授权。

## 用途与入口

把固定网站发布版和 Word 原件逐项对齐，区分短 Tag 与完整提示词资源，保留已有身份和个人字段，再完成图片验证、隔离暂存、受控发布与在线验收。

主仓入口：[网站与 Word 导入交付流程](../../../snapshot/runtime/benchmark_reports/source_update_flow/网站与Word导入交付流程.md)。旧文档内部相对路径按原件保留；对应批次现在位于下列技术归档入口，分类入口见 [分类工作入口](../archive/benchmark_reports/分类工作入口.md)、[分类标准](../archive/benchmark_reports/分类标准.md)及[变更记录](../archive/benchmark_reports/分类标准变更记录.md)。不要把旧相对路径直接当作当前部署路径。

## 实现链

当前纯网站差量入口为 `source_update_flow/{audit_current,fetch_current_images,stage_current,publish_current,accept_current}.py`，对应测试为 `tests/test_current_source_{audit,stage,publish}.py`。实际操作、来源范围与限制见 [2026-11-01 更新记录](../changes/library-web-import/2026-11-01-current-source-delta.md)。旧 `freeze_batch.py` / `flow_gate.py` 仍是网站与 Word 联合批次门禁；本轮没有 Word 输入，不伪造 Word 覆盖收据，也不把该旧门禁称为已通过。

历史维护另用 `stage_maintenance.py` 补齐经逐项批准的完整来源说明、逐图参数及负面词快照；`stage_body_maintenance.py` 只接受绑定旧来源 A、当前来源 B、本地正文 C 的明确表示形式及 `C == A` 见证。默认尾清理调用冻结的原站实现，编码和分类例外逐项审阅；不把规范化相似、同名或缺失来源元数据当作正文覆盖许可。旧来源、个人字段、原始 ID、图片及非目标数据保持，分类变化单独声明。来源说明的实际显示由[只读详情功能](source-notes.md)负责，不拼入个人备注。

`stage_display_maintenance.py` 处理仍逐字等于旧来源标题的显示名称，重新审查所有当前来源归属与新标题一致性；资源 `alias` 与 Tag `desc` 是各自的显示字段，正文和个人备注独立保留。来源路径只存入完整原文，不按原站重排本地分类。缺少当前来源证明的唯一已绑定记录可单独补当前快照，既有当前快照不重复追加；标题冲突、不同的本地命名和其他身份保留不自动覆盖。

用户明确要求继续逐条裁决时，可使用两个严格的审阅分支：正文的 `legacy_url_cleaned_main` 需要原始维护函数/逐 ID 清单和物理旧库证明，采用当前源时保留同一去链接处理；显示名的 `origin-naming-authority/v1` 需要冻结上游、独立检查点、真实导入边及保留 journal，按已证明的原始命名来源维护 alias，不能按后来自动变化的 primary 决定名称。两者均不降低默认规则；裁决、验证及保留边界见[剩余项逐条复核](../changes/library-web-import/2026-11-01-remaining-reconciliation.md)。

受控发布可在同一回滚组内携带主仓 seal 中明确批准的少量源码：逐文件绑定当前线上旧哈希、新哈希和清单哈希，新文件回滚恢复为缺席。异常改动先留私有证据再恢复；安装和验收均核对已审查哈希。未部署的 Tag/词典也可声明为只读数据库，接口检查后取一致副本确认未变。资源库验收比较全部表，唯一允许的启动差异为原生备份操作时间戳。对应测试包括 `test_historical_{source,body}_maintenance.py`、`test_source_companion_publish.py` 和 `test_current_source_accept.py`。

Tag 名称修订产生的两条原生搜索日志可被启动索引正常消费。验收只允许显式批准的两行完整原文删除，其余 Tag 表、修订和序列严格相等；有消费时核对一致缓存副本的格式、已应用序列及 FTS 词项位置与列 token 数。缓存为 contentless FTS，不声称读取了不存在的正文列。既存搜索缓存另作仅回滚备份，失败时与旧 Tag 库一起恢复，防止新索引游标越过已恢复的旧库。

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

- 2026-11-01：按已验收的 2026-10-31 来源检查点逐字段比对当前 v2 网站与联动 legacy 发布，新增 25 条资源对应 29 条来源、5 条缺失译名；349 条评级/更新标记变化逐条处置，329 条可定位更新，15 条沿用排除，5 条身份歧义保留。离线门禁、完整来源/个人字段保护及线上状态见[本轮记录](../changes/library-web-import/2026-11-01-current-source-delta.md)。

- 2026-09-27：完成全站/Word 对照与来源更新批次。
- 2026-09-28：固定版渡鸦 816 条增量正式验收，连接关闭故障的首次回滚单独保留。
- 2026-10-05：补齐历史采集/解析/发布链及验证回执的实际归档链接；原件不改写，完整输入与环境仍需外部准备，未再次执行导入。
