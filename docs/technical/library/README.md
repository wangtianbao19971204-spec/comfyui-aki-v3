# 资料库技术档案

版本：2026-10-05.2。范围是网页/Word 导入、Tag 预览绑定、归属与语义引擎、共享选择器及其数据库接口，不包含 LoRA Patch。

本目录是技术索引，不是第二份源码。可维护实现以主仓 `snapshot/runtime/` 为准；一次性历史工具即使补入 Git，也不能直接作为新的生产发布命令。

## 分层入口

| 功能 | 技术档案 | 当前实现与证据边界 |
|---|---|---|
| 网页/所长法典/Word 采集与增量导入 | [web-import.md](web-import.md) | 通用门禁与维护实现已在主仓；历史采集、Word 解析及发布链已归档 |
| Tag 预览补齐、绑定、缩略图与图库消费 | [tag-previews.md](tag-previews.md) | 生产服务、批次图片验证代码和图库回执已在主仓；真实图片仍在外部 |
| 主题、父归属、细分与身份边界 | [taxonomy.md](taxonomy.md) | 生产引擎及历史回放/全量契约代码已归档；完整冻结输入仍需外部资料 |
| 六类选择器共享分类与来源筛选 | [selectors.md](selectors.md) | 当前实现、2026-10-02 专项测试/回执已归档；旧 before、数据 fixture 和环境未随附 |

本领域显式选单的 **203 份技术文件已全部归档**，逐项路径、来源和 SHA-256 见 [技术归档登记](../../../governance/technical-archive.json)，实际原件位于 `docs/technical/archive/benchmark_reports/`。这里的“已归档”指文件实际存在且哈希核对一致，不表示整个批次目录或全部运行输入已备份。历史源码不是 `snapshot/runtime/` 部署候选；源网页、Word、数据库、图片与未选定 fixture 仍按外部资料管理。

## 数据分层

| 层 | 权威位置/实现 | 维护规则 |
|---|---|---|
| 提示词资源正文、归属与关联 | `snapshot/library/json/`；WeiLin `prompt_selector/{prompt_selector,selector_library,shared_sync}.py` | 保留 ID、正文、收藏、备注、来源及修订；分片是实际内容，不是路径清单 |
| Tag、翻译热度、历史三库 | `snapshot/library/sql/`；[结构契约](../../../database/contract.json) | 一致 SQLite backup 后导出；在线 DB/WAL 不直接覆盖 |
| 可读结构、索引、触发器、fixture | [database/](../../../database/)；[数据库说明](../../DATABASE.md) | 当前是 v1 基线，不是通用在线迁移器 |
| Gallery 联邦词库 | Gallery `py/shared/db/weilin_tag_bridge.py` | 只读查询 WeiLin 身份，不把整库复制进 Gallery 缓存 |
| Gallery 独立词典／翻译／别名历史 | `snapshot/library/sql/gallery_tags_cache.db/` | 一致备份的规范 SQL 检查点；FTS5 索引可重建，正文与历史须完整保留 |
| 随机提示词模板 | `snapshot/library/random_templates/` | 两份经审查 JSON 原字节；新模板须审查登记，未登记时捕获失败提示 |
| 旧独立选择器正文／编辑日志 | `snapshot/library/legacy_selector/` | 保留独立旧资料及历史检查点，不自动合并／启用为现行共享库 |
| 输入补全 | WeiLin `autocomplete_api.py`；Custom Scripts `autocompleter.js` | 两条补全入口不是同一数据库；文字补全不等于 Tag 图片补齐 |
| 真实预览、源网页、Word、缓存与鉴权 | 运行目录/仓外状态 | 媒体不进 Git；API key、Cookie、登录配置不进说明、fixture 或历史 |

路径缩写：各页 `W/` 表示 `snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/`，`A/` 表示同层 `comfyui-anima-tools/`，`G/` 表示同层 `ComfyUI-Danbooru-Gallery-V50-GalleryOnly/`，`C/` 表示同层 `ComfyUI-Custom-Scripts/`。

## 验证与公开边界

2026-10-05 只读抽核的 18 个关键生产实现文件与主仓 SHA-256 一致；随后核对本领域 203 个归档文件，均与登记哈希一致。这不是所有功能的重新运行验收，也没有重启、运行导入、访问远端或重新生图。

数据库检查入口为 `database/tools/contract.py check --against-snapshot` 和 `tests/test_database_contract.py`。功能级验收见各页；不要以建仓工具测试替代浏览器、导入或语义验收。

真实提示词获准保留不等于所有上游内容都获准公开再分发。已归档的 [NovelAI-Tag LICENSE](../archive/benchmark_reports/2026-09-15_tag_folder_classification/repo_src/NovelAI-Tag-main/LICENSE)把软件与法典内容/图片/汇编结构分开：代码按其 MIT 条款保留署名；数据公开须另核授权。[资源边界](../../EXTERNAL_ASSETS.md)同样适用。

## 更新记录

- 2026-10-05：建立四份功能档案和数据库分层入口；随后完成 203 份显式技术文件归档及哈希核对，补齐可点击入口，保留外部输入、许可与重演限制。
