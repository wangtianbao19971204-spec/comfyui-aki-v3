# Tag 首次筛选/搜索加速与读取索引（2026-10-24）

- 问题：Tag 面板首次筛选/搜索在缓存的 `_PAGE_CACHE` 未命中时，要对 29.8 万行 `tag_tags` 逐行计算形状表达式、在 9.9 万条 meta JSON 上逐行 `json_each`，单次 0.2–1.3 s；旧的启动预热 cache key 与真实请求的 `known_collections` 不一致，导致预热无效。
- 改动：`tag_library.py` 增加表达式索引 `workbench_tag_read_scope`/`workbench_tag_read_shape` 与 `workbench_tag_themes`/`workbench_tag_collections` 派生表（6 个 meta 触发器维护），单事务构建（2.0–2.2 s）并把版本写入 `workbench_tag_read_meta`，失败可重试、未就绪自动回退旧 SQL；`tag_api.py` 按真实 `known_collections` 预热 16 个默认视图（列表 100/卡片 120 × scope × shape），缓存键与 `/tags/page` 一致。
- 效果（生产 532 MB 副本）：shape=group 508→6.5 ms、string 511→5.3 ms、默认视图 71→9.2 ms、collection 461→18 ms、theme 333→104 ms、q=hair 189→11.5 ms、q+group 1028→6.6 ms；构建一次 2.0–2.2 s、DB +48.9 MiB（+9.6%），warm 链首跑约 3.5 s。
- 语义：生产副本 32 组 filters/query 组合新旧 `items`/`total`/顺序完全一致，另 16 组与改动前原版逐字段一致；全测试 138 OK/1 skip。
- 未覆盖：theme/区域首次 70–110 ms；无 scope 整库搜索 157→178 ms（DB 增大后 LIKE 扫描略慢）；FTS5 评估后不采用（构建 38.5 s、DB +280 MiB、与 LIKE 语义不一致）。回退代码后新增索引/表残留但不影响旧查询。
- 本轮未部署生产；完整实现说明见 [工作台交互延迟优化](../runtime-workbench/2026-10-24-workbench-interaction-latency.md)。
