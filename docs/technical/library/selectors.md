# 六类选择器共用分类与来源筛选

版本：2026-10-05.2；实现契约 `shared-selector-library-v2`。生产实现、常规测试及 2026-10-02 专项代码/回执已在主仓；旧 fixture 和测试环境并未整包复制。

## 用途与入口

UAP 工作台中的角色、服装、姿势、背景、画师、画风/质量六类资料选择器共用资料库的大主题、小主题名称、顺序和父归属。来源保留稳定 ID，作为独立筛选轴与分类取交集，不是语义分类的替代品。

这是提示词选择器，不是图像的服装/背景细化分支；维护这些 UI 不会自动启用图像细化。

## 主仓实现链

路径缩写见 [索引](README.md)。后端入口：[A/nodes.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/comfyui-anima-tools/nodes.py)。

| 层 | 文件 | 实现职责 |
|---|---|---|
| 共享后端 | `A/nodes.py` | `_parse_shared_prompt_filters`、`_shared_prompt_item_matches_filters`、`_build_reviewed_shared_payloads` 和稳定画师分页 |
| 归属消费者 | `W/prompt_selector/{semantic_projection,semantic_taxonomy,selector_library}.py` | 使用当前资料绑定和正式父归属，生成主题/小主题/来源集合 |
| 共享前端 | `A/js/anima_shared_prompt_data.js`、`anima_selector_ui.js` | 合并主题与来源控件、缓存修订、交集过滤及清除筛选 |
| 选择器界面 | `A/js/anima_{character,clothing,pose,background,artist}_selector.js` | 各类搜索/标签/分页；画风质量入口由 `anima_prompt_composer.js` 及共享数据层消费 |
| 静态映射与契约 | `A/data/weilin_category_taxonomy.json`、`weilin_anima_classification_contract.json` | 兼容路由及契约数据，不能用旧备份覆盖当前文件 |

画师继续后端每页 60 条加载；不能为分类把全部正文拉入浏览器。服装/背景附加标签与分类、来源取交集；本轮共享到大主题和小主题，未加入资料库更深细分层。

## 数据与私密边界

选择器消费真实资料导出/运行库，但不通过界面美化改写正文、ID、收藏、工作流或提示词。缓存以源数据、投影与运行实现指纹失效，不应保存凭证。正式数据比快照新时，不从 Git 反向覆盖它。

## 测试、已归档证据和外部依赖

- 主仓常规测试：`A/tests/anima_shared_prompt_data.test.mjs`、`anima_selector_ui.test.mjs`、`test_style_quality_selector.py`、`test_weilin_taxonomy_manifest.py`。
- `2026-10-02_selector_taxonomy_shared/` 已归档：[后端专项](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/test_canonical_selector_backend.py)、[前端专项](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/test_canonical_selector_frontend.mjs)、[画师分页契约](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/test_artist_page_contract_adapted.py)、[快照保护测试](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/test_snapshot_guards.py)及对应历史回执。
- 后端专项测试读取本批 `before/nodes.py` 作比较；前端专项测试读取 `library_index_body.json`，并显式引用旧测试 runtime 的 jsdom。只复制测试文件不能宣布可运行；旧 `node_modules` 不入 Git，应登记依赖版本并改为受控测试环境。
- 本批 [snapshot_contract.py](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/snapshot_contract.py)和 [source_snapshot_final/manifest.json](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/source_snapshot_final/manifest.json)、[README.txt](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/source_snapshot_final/README.txt)、[rollback.py](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/source_snapshot_final/rollback.py)已归档。索引与回退工具不等于完整 before/source payload；上一轮 `2026-10-02_character_selector_audit/source_snapshot_final` 仍是外部依赖，旧回退包不是今天可直接执行的回退授权。

已归档的[交付说明](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/交付说明.txt)记录 2026-10-02 后端 51 项、前端 16 组、额外 17 项边界和 77 项实时接口检查；新浏览器 35 项观察通过。22 份已服务前端资源与磁盘一致，18 份正式工作流和 3 份资料 SHA 未变。原始证据为 [browser_acceptance.json](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/browser_acceptance.json)、[live_api_acceptance.json](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/live_api_acceptance.json)及 [final_live_guard.json](../archive/benchmark_reports/2026-10-02_selector_taxonomy_shared/final_live_guard.json)。

这些是当时验收，不是本次再次浏览器操作。没有因该验收声称应用/撤销写入、收藏写入或 GPU 生成通过；模拟事件也不是物理 IME 验收。

## 更新记录

- 2026-10-02：六类选择器共用正式主题/父归属与稳定来源筛选，保留画师分页。
- 2026-10-05：补齐专项测试、回执与快照工具的实际归档链接；保留 before/索引 fixture、jsdom 和完整回退输入的外部依赖，未改选择器功能或重跑历史验收。
