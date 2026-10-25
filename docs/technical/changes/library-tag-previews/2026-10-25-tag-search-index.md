# Tag 子串搜索/自动补全加速：trigram FTS 缓存库（2026-10-25）

- 问题：上一轮后无 scope/shape 的 Tag 搜索仍走 `LIKE '%term%'` 全表扫：生产副本 `q=hair` 178 ms、空结果 326 ms、`/tags/complete` 168.6 ms；1.2–2 万条命中的排序/计数让首访 170–350 ms。
- 方案：在**可重建 cache 库** `user_data/prompt_selector/cache/tag_search.v1.db`（约 288 MiB）建 FTS5 `tag_text/tag_desc`（`content=''`, `contentless_delete=1`, trigram, 存 `lower()` 文本，与 SQLite LIKE 的 ASCII 折叠一致）；用户 tags 库仅新增变更日志表 + 3 个触发器（<64 KiB，`PRAGMA integrity_check` 维持 6.4 s 量级）。搜索前若日志非空先回放（或本请求回退旧 SQL 并调度后台增量同步）；cache 版本/基准 revision/缺表/超阈值自动重建；`UW_DISABLE_TAG_SEARCH_INDEX=1` 完全回退旧 LIKE。
- total/顺序仍由 FTS 命中集 + `tag_tags.text` 索引 + 内存 `create_time` 顺序数组（1.2 MB）复刻旧三层顺序（exact→prefix→其余），不依赖 FTS 排序。
- 效果（532 MB 生产副本、生产同口径）：`q=hair` 178→18.6 ms、`complete` 168.6→19.5 ms、空结果 326→3.9 ms、`q=group` 180→63.7 ms、q+shape 5.5 ms、q+scope 11 ms；语义 165 组 query×page + 12 组筛选 + 12 组边界分页与改动前实现逐字段 0 mismatch。
- 成本：首次 warm 一次性 +13–15 s（post-ready daemon，不阻塞启动；完整 Tag warm 首跑约 17 s），后续启动 +0.15 s；cache 288 MiB 可删重建；tag 写 +0.09 ms/次。
- 未覆盖：1–2 字符查询仍回退旧 LIKE（140–205 ms）；无 scope 的 `q+theme/collection` 仍走旧路径（230–290 ms）。本轮未部署生产。
