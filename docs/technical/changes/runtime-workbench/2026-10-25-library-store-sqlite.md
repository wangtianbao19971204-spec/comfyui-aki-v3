# 提示词库改 SQLite 权威存储：消除编辑后的全量重写（2026-10-25）

状态：开发分支验证中，未部署。用户要求：编辑后的全量重写不可接受（成本随库增大），单条编辑成本必须与库大小解耦。

## 问题

单条提示词编辑原为“解析/持有全库 → 全库序列化 462 MB → 写盘 + fsync → 备份 copy2”，即 ORJSON 序列化 318 ms + 写 462 MB 382 ms + 首存备份 130 ms，合计 ~1.0 s 且全部 O(库)；更早还有 1.6 s 的全库解析。

## 方案（详见 temp/startup-warmup/library-store-design.md）

- 新增 `prompt_selector/library_store.py`：SQLite 权威存储（WAL + `synchronous=FULL`），表 `library_meta`（revision/version/顶层字段）、`categories`+`category_orders`（612 行）、`prompts`（324,891 行，payload 为原 prompt JSON）、`library_journal`（行级 before/after）。
- 读模型不变：启动从 SQLite `load_document()` 加载成与原 data.json 同构的 dict（分块 + `gc.disable`），library index/page、语义缓存、ETag/409、Tag 搜索等上层全部不变。
- 写路径：19 个 `_atomic_save_json(DATA_FILE)` 写点全部接入 `ChangeSet`——单条编辑只提交 1 行 prompt + order + revision + journal（与库大小无关）；批量/导入/合并/整库替换单事务多行并**事务前用 SQLite backup API 全量备份**；正常编辑不再写 data.json、不再 copy2 462 MB。
- data.json 降级：仅显式导出/兼容/维护捕获时由 `export_json()` 原子生成（后台自动导出策略：编辑空闲 debounce 10 s、节流 15 min）。
- 自动保护（不依赖用户记忆）：自动导出 data.json、自动 SQLite backup（启动 >24h/每 30 min/每 200 写/批量前/优雅退出，保留 5 份）、行级 journal（7 天/2 万条，HTTP GET/POST 恢复）、`GET /prompt_selector/library/store-status` 暴露最后成功导出/备份时间与 overdue/error 告警。
- 灰度/回滚：`UW_LIBRARY_STORE=json|sqlite`（默认 json 保持旧路径），DB 缺失时显式迁移；`scripts/migrate_library_store.py`（dry-run/apply、逐字段深比较、SHA256 回执、幂等）；迁移不动旧 data.json，可回退 json 模式。
- 维护捕获：`scripts/snapshot.py`/`scripts/library_sql.py` 把 `library.sqlite3` 纳入与 tag DB 相同的 SQL dump 捕获/restore 机制（`prompt_library_store_v1` 摘要：schema/行数/分类顺序/外键/revision）；data.json 降级为可选兼容导出。

## 实测（真实 462 MB / 612 分类 / 324,891 条，隔离副本）

| 项 | 结果 |
|---|---|
| 迁移 data.json → library.sqlite3 | 8.81 s；DB 599.8 MB；逐字段 equal；源 data.json SHA 不变 |
| 二次 apply | 3.7–4.0 s 幂等 |
| 启动加载 document | 2.17–2.71 s（JSON 解析 1.93–2.05 s 对照） |
| **单条编辑提交（WAL+FULL，含 journal）** | **中位 1.59 ms**（热 1.45–1.68 ms；与库大小无关） |
| 批量 20k 行 update_order | ~203 ms（单事务） |
| 自动导出（后台） | 462 MB ≈ 1.6 s；自动备份 600 MB ≈ 1.0–1.1 s |
| 正常编辑写 data.json | 不再发生（mtime 不变） |

- 测试：`tests/test_library_store.py` 29 项；全测试目录 **188 OK / 1 skip**；`py_compile` OK。
- 隔离 HTTP A/B（json vs sqlite 两次启动、编辑/立即 index/启动/首屏/Tag/强杀恢复/回滚/snapshot 往返）由 T16 验证，结果见 `temp/startup-warmup/library-store-verify.md`（提交时回填）。

## 边界与未覆盖

- 默认仍为 json 模式，生产启用需先迁移并设置 `UW_LIBRARY_STORE=sqlite`，另行授权。
- 外部仍直读 data.json 的运行时代码（`prompt_selector_bridge.py`、`comfyui-anima-tools/nodes.py` 的 mtime/size 缓存）在 sqlite 模式下需改走导出快照/API，已列入风险清单（`temp/startup-warmup/snapshot-library-store.md`），本轮未改其业务语义。
- `data.json` 在 sqlite 模式下最多落后一个自动导出窗口（默认 ≤15 min），但权威 DB + 自动备份 + journal 保证 RPO：断电 0、DB 损坏 ≤30 min、误编辑按条回滚。
- 本 PR 未部署生产；真实运行区 capture/materialize 未执行。
