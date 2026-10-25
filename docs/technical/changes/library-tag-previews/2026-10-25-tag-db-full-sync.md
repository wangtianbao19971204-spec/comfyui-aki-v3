# Tag 用户库写连接升级 synchronous=FULL（2026-10-25）

- 问题：`app/server/dao/dao.py` 的 tags 池连接此前 `WAL + synchronous=NORMAL`，断电/系统崩溃时可能丢最后一次已提交 tag 编辑；与“SQLite 权威存储提交即落盘”的语义不一致。
- 改动：`dao.py` 新增 `_WRITE_SYNCHRONOUS`/`write_synchronous_pragma(db_type)` 策略：tags 用户库 = **WAL + synchronous=FULL**（`_get_connection`/`_reconnect_after_error` 两处共享写连接）；history/danbooru 维持 NORMAL；只读/校验/迁移临时连接不动。真实 tag 编辑走 `TagLibrary.connection` 本来即 FULL，本次把 dao 池策略显式化并兜底未来写路径。
- 实测（532 MB 生产 tags DB 副本，各 100 次单条编辑事务）：NORMAL 中位 0.05 ms/P95 0.08/max 0.11；FULL 中位 1.37 ms/P95 1.50/max 1.69（+1.3–1.4 ms）；只读查询不受影响，journal_mode 保持 WAL。
- 验证：新增 `tests/test_dao_full_sync.py` 3 项（tags 池连接 wal+synchronous=2、提交后可读、history 仍 NORMAL、重连后仍 FULL）；全测试目录 188 OK/1 skip（基线 156 + 本轮新增）。
- 说明：进程崩溃（非断电）下 NORMAL 也安全，FULL 的差异在断电语义；以 PRAGMA 实值断言 + SQLite 官方语义为准。本轮未部署生产。
