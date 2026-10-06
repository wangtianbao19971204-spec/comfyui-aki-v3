# Tag 预览补齐与图库消费

版本：2026-10-05.2；状态：服务、界面、历史图片批次代码和专项回执已在主仓；真实图片、旧 fixture 和环境继续作为外部输入。

## 用途与入口

这里的“补全预览图”指给 Tag 安装并绑定来源图片，不是输入框的文字自动补全，也不是自动生成新图。

路径缩写见 [资料库索引](README.md)。主实现为 [W/prompt_selector/prompt_selector.py](../../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/prompt_selector/prompt_selector.py)。

## 实现链

| 层 | 主仓文件 | 作用 |
|---|---|---|
| Tag 身份和图片绑定 | `W/prompt_selector/tag_library.py`、`tag_api.py` | `preview` 存在 Tag 元数据中，与收藏/备注分开维护；以 UUID 定位 |
| 资源统一输出 | `W/prompt_selector/prompt_selector.py` | Tag 视图取其 `preview`，提示词资源保留自身 `image`；不按相似正文挪图 |
| 原图/缩略图服务 | 同文件 `_safe_preview_source`、`_ensure_preview_thumbnail` | 安全限定原图目录；按源图状态生成 480×360 范围 WebP 缩略图并原子落盘 |
| HTTP | `/prompt_selector/preview/{filename}`、`/prompt_selector/thumbnail/{filename}` | 原图和缩略图为不同接口；文件存在与绑定正确都需验证 |
| 工作台及选择器 | 统一包 `web/resource_results.js`、`web/prompt_resource.js`；`A/nodes.py` 的预览 URL 构建 | 消费已有绑定，不重新复制资料身份 |
| Gallery 词库/图片卡 | `G/py/shared/db/weilin_tag_bridge.py`；`G/js/danbooru_gallery/{danbooru_gallery,gallery_dialog}.js` | 联邦词库身份与网页图库卡片不是同一来源集合 |

来源图片下载/安装历史实现已归档：[全站 fetch_images.py](../archive/benchmark_reports/2026-09-27_codex_update/fetch_images.py)、Raven 的 [prepare_images.py](../archive/benchmark_reports/2026-09-28_raven_increment/prepare_images.py)、[fetch_images.py](../archive/benchmark_reports/2026-09-28_raven_increment/fetch_images.py)、[validate_increment.py](../archive/benchmark_reports/2026-09-28_raven_increment/validate_increment.py)、[live_acceptance.py](../archive/benchmark_reports/2026-09-28_raven_increment/live_acceptance.py)。闭合依赖见 [网页导入](web-import.md)；这些旧脚本不是当前生产执行入口。

## 与文字补全的区别

WeiLin `autocomplete_api.py` 直接查询自己的 Danbooru 翻译/热度库，返回 tag、译文、分类、热度及 alias；`autocomplete_ui.js`/`autocomplete_cache.js` 消费这些接口。当前该 API 不返回 Tag 图片字段。

Custom Scripts 的 `C/web/js/autocompleter.js`、`common/autocomplete.js` 使用 `/pysssss/autocomplete` 和自己的词表/分组入口。它不等于 WeiLin Tag 元数据，也不能用它的成功证明所有 Tag 已有预览。

## 数据与私密边界

Gallery 另有 `G/py/shared/data/tags_cache.db`，用于热度词/译文等补全缓存；它不是 WeiLin 的三库 SQL 检查点，也不是预览图片。已加入仓外 v5 计划的 `mutable_db` + `reference` 项。保留现场库；将来复制须用 SQLite backup API 并检查 WAL，不删除后盲目重建，也不从 Git 的旧库导出覆盖它。放置路径见 [支持文件契约](../../../governance/runtime-support.json)。

真实图位于 WeiLin `user_data/prompt_selector/preview/`，缩略图在 `preview_thumbnails/`。Git 保留正文、绑定信息、模型/媒体位置清单及一个中性格式样例，不含全量图片 payload；见 [外部资源](../../EXTERNAL_ASSETS.md)。

下载 URL 不保存签名参数或鉴权；图库 Cookie、API key、插件缓存不进档案。图片改绑应保留来源与个人选择，不能因正文重复就删除第二来源图。

## 测试与证据

- Gallery 的两套现行契约通过 `tests/run_isolated.py` 执行：需要已安装 pytest，将 collection 包装与 SQLite fixture 放全新临时目录，并禁用第三方 pytest 自动加载。这样避免 pytest 为收集子目录测试导入生产统一包 `__init__`；不启动 ComfyUI、不访问生产数据库。

- 主仓有 Gallery `tests/test_weilin_tag_bridge.py`、`tests/test_tag_translation_runtime.py`，以及 WeiLin `prompt_selector/tests/test_tag_{identity_bridge,api_identity}.py`；它们验证身份/接口边界，不覆盖全量图片安装。
- 已归档 [test_tag_http.py](../archive/benchmark_reports/2026-09-13_tag_import/test_tag_http.py)与 [tag_import_ui.test.mjs](../archive/benchmark_reports/2026-09-13_tag_import/tag_import_ui.test.mjs)，包含预览元数据/导入合同；测试依赖的旧 fixture 和服务桩未因此齐备，不应直接指向生产执行。
- Raven 的 [stage_validation.json](../archive/benchmark_reports/2026-09-28_raven_increment/stage_validation.json)与 [live_acceptance.json](../archive/benchmark_reports/2026-09-28_raven_increment/live_acceptance.json)记录 816 张安装图和 811 个主预览通过。另 5 张是同正文第二来源，单预览 UI 不同时显示。
- 同批 [current_site_audit.json](../archive/benchmark_reports/2026-09-28_raven_increment/current_site_audit.json)保留 4,186 张额外旧多图的来源链接，不是本地多图交付完成。
- 已归档 [图库 verification.json](../archive/benchmark_reports/2026-10-01_gallery_card_fix/verification.json)，记录 13 项旧前端测试、40 卡片在两尺寸无重叠/越界及来源链接/键盘焦点通过；这是历史图库 UI 证据，不是当前 Tag 图覆盖率证据。

## 更新记录

- 2026-10-07：最终回归修复 Gallery 隔离 collection 入口并重跑 15 项身份/分页/翻译契约；WeiLin Tag API 测试补现行字符串桶常量，用临时中性候选而非向父目录回读运行 benchmark。7 项身份契约通过，缺失仓内历史候选的 1 项明确跳过。验证保证候选接口不写源文件/在线 Tag 库；不代表真实图片全量安装或当前图库 UI 已重新验收。

- 2026-10-05：补登记当前服务打开的 Gallery `tags_cache.db`；只核对文件身份与外部归属，不导出正文、不覆盖/清理数据库或重新验收图库 UI。

- 2026-09-28：增量图片与主预览绑定完成固定批次验收。
- 2026-10-01：图库卡片布局与来源链接交互修复。
- 2026-10-05：区分预览补齐、文字补全、Gallery 与真实媒体备份；补上批次代码和专项回执的归档链接，未下载、重建预览或重新运行旧测试。
