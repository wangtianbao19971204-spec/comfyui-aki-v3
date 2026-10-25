# 提示词库持久化改为 SQLite 权威存储（2026-10-25）

- 背景：单条提示词编辑原需序列化并写 462 MB `data.json`（+备份 copy2），成本随库增长；用户要求消除编辑后的全量重写。
- 改动：新增 `prompt_selector/library_store.py`（WAL + `synchronous=FULL`；表 `library_meta`/`categories`/`category_orders`/`prompts`/`library_journal`）；`prompt_selector.py` 读路径从 SQLite 加载成同一 dict，19 个写点接入 `ChangeSet`（单条编辑 1 行 + order + revision + journal；批量事务前 backup）；`UW_LIBRARY_STORE=json|sqlite` 灰度，默认 json；`scripts/migrate_library_store.py` 迁移（dry-run/apply、逐字段深比较、SHA256 回执、幂等）；`scripts/snapshot.py`/`scripts/library_sql.py` 将 `library.sqlite3` 纳入 SQL dump 捕获/restore。
- 自动保护：后台自动导出 data.json（debounce 10 s/节流 15 min）、自动 SQLite backup（启动>24h/30 min/200 写/批量前/退出，保留 5）、行级 journal（7 天/2 万条）、`store-status` 暴露最后成功时间与告警。
- 实测：迁移 8.81 s、DB 599.8 MB、逐字段 equal；启动加载 2.17–2.71 s（旧 JSON 解析 1.93–2.05 s）；**单条编辑 1.59 ms 中位**（原 ~1033 ms，且不再随库增长）；批量 20k 行 203 ms；测试 188 OK/1 skip。
- 边界：默认 json 模式；sqlite 需显式迁移+启用；外部直读 data.json 的 `prompt_selector_bridge.py`/`comfyui-anima-tools` 缓存读取方需后续改造（清单见 snapshot-library-store 报告）；本轮未部署生产。
- 完整说明见 [SQLite 权威存储](../runtime-workbench/2026-10-25-library-store-sqlite.md)。
