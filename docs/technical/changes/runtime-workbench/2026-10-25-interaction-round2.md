# 工作台交互第二轮：搜索与正文编辑后刷新（2026-10-25）

状态：开发分支验证中，未部署。范围：统一包内 Weilin Tag 搜索索引与提示词编辑后的 index 增量刷新。

## 问题

上一轮交互优化后（PR #33 `adaf6bc8c`）仍有两处热点（隔离 HTTP 端到端）：

- 无 scope/shape 的 Tag 子串搜索与自动补全仍走 `LIKE '%term%'` 全表扫：`q=hair` 190–227 ms、空结果 355–405 ms、`/tags/complete` 206–232 ms。
- 修改提示词正文（语义 binding 变化）后保存本身已 ~1.1–1.4 s，但保存后自动触发的整库 warm 使第一次 `GET library/index` 阻塞 3014–3452 ms、`prompts` 页 1155–1305 ms。

## 改动

1. `tag_library.py`/`tag_api.py`：trigram FTS5 放进可重建 cache 库（`user_data/prompt_selector/cache/tag_search.v1.db`，约 288 MiB），用户 tags 库只加变更日志表 + 3 触发器；搜索前增量回放日志；total/顺序仍用 FTS 命中集 + text 索引 + 内存 `create_time` 顺序表复刻旧三层顺序；构建在 post-ready Tag warm（不阻塞启动），版本化、失败重试、`UW_DISABLE_TAG_SEARCH_INDEX=1` 回退旧 SQL。
2. `prompt_selector.py`：正文编辑走单行增量 patch（index payload 的 ±1 增量、views/rows/view_index/row_index/ranges/filter 同步），不再触发整库 warm；不安全/多行/异常回退旧路径。
3. 测试：`tests/test_tag_read_speed.py` +14（共 26）、`tests/test_edit_save.py` 22。

## 验证

- 生产副本函数级/同口径：q=hair **178→18.6 ms**、complete **168.6→19.5 ms**、空结果 **326→3.9 ms**、q+group **180→63.7 ms**；正文编辑后首次 index **1.58/2.86/3.17 s→0.000 s**、prompts **1.09→0.13 s**、保存本身无退化。
- 语义等价：Tag 165 组 query×page + 12 组筛选 + 12 组边界分页与改动前实现逐字段 0 mismatch；编辑后 index/page/view/rows 与 reset+全量重建逐项 ALL EQUAL。
- 成本：Tag 搜索 cache 首建 12.9–15.8 s（post-ready daemon，完整 Tag warm 首跑约 17 s，后续启动 +0.15 s）；cache 288 MiB 可删重建；用户 tags DB 体积/`integrity_check` 基本不变；tag 写 +0.09 ms/次。
- 隔离 HTTP A/B（before = `adaf6bc8c`，after = 本轮；隔离树同数据、端口 8399、每侧两次独立运行；原始 JSON 见 `G:\ComfyUI-local\validation\startup-warmup-20261024\results\interaction-round2-*.json`，汇总见 `temp/startup-warmup/interaction-bench2.md`）：

| 场景 | before#2 | after#2 |
|---|---|---|
| Tag `q=hair` | 189.8 ms | **36.4 ms** |
| Tag `q=apple_zx`（空结果） | 355.0 ms | **15.6 ms** |
| `/tags/complete?search=hair` | 206.1 ms | **19.6 ms** |
| `q=hair + group` | 55.2 ms | **14.7 ms** |
| `q=hair + scope=tags` | 15.7 ms | 34.6 ms（噪声，仍 <100） |
| `q=hair + scope=strings` | 286 ms | 265 ms（未覆盖） |
| 2 字符 `q=ab` | 旧 LIKE | 205–213 ms（回退旧路径，未覆盖） |
| 正文编辑保存 | 1442.5 ms | **1033 ms** |
| 保存后立即 `library/index` | 3013.7 ms | **2.7 ms** |
| 保存后立即 `library/prompts` | 1155.3 ms | **12 ms** |
| 改回保存 | 1105–1197 ms | 818–922 ms |
| 启动 child→listen | 45.1 / 24.3 s | 31.7 / 20.4 s（不退化） |
| Tag warm 首跑 / 二跑 | 15.2 / 11.3 s | **24.0 / 11.2 s**（首跑含搜索 cache 12.6 s，daemon 不阻塞 listen） |
| Library warm | 15.2 / 11.1 s | 11.0–11.3 s |
| 首屏串行 | 35.2 / 42.7 ms | 11.8 / 18.7 ms |

- after 编辑后日志确认不再出现保存触发的整库 `Library caches warmed`（before 为 4.1 s，根因消除）。Tag 搜索 cache 文件 `cache/tag_search.v1.db` 301,907,968 B（287.9 MiB），tags 用户库体积/`integrity_check` 基本不变。

## 边界与未覆盖

- 1–2 字符 Tag 查询仍回退旧 LIKE（140–205 ms）；无 scope 的 `q+theme/collection` 仍走旧路径（230–290 ms）。
- `include_filter_counts=1` 的 prompts 页仍重建 filter_masks（约 3 s，旧同）。
- 部署后首次启动会在后台多建一次 Tag 搜索 cache（约 13–15 s）与读取索引（约 2 s），不阻塞 listen；本轮未部署生产。
