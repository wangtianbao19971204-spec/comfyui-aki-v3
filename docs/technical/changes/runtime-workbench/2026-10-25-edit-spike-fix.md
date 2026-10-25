# 编辑保存尖峰修复：语义缓存快照空闲化（2026-10-25）

- 问题：T16 post-fix 验收中主目标已 PASS（sqlite 模式正文编辑稳态 5.2–8.3 ms、立即 index 3.4–4.8 ms），但个别保存出现 **70–110 ms 尖峰**，日志时间戳与后台 `[Workbench] semantic cache stored in 0.9–1.1 s`（23 MB msgpack.zst 序列化/写盘）完全重合——后台快照与请求线程竞争 GIL/IO；另有进程内首次保存 77–100 ms（SQLite 首次 WAL 写）。用户要求编辑成本稳定可预期。
- 改动（仅 `prompt_selector.py` + 测试）：语义缓存快照由 1 s Timer 改为**编辑空闲触发**——`last_write_at` 记录最近写；距最近编辑不足 `UW_LIBRARY_SEMANTIC_STORE_IDLE_S`（默认 30 s）时用 `threading.Timer` 重新排到剩余时间；每次新编辑重置排程；批量/退出/重建路径可强制 flush。新增 `_semantic_store_idle_seconds` 与测试；`_schedule_semantic_store` 大库快照不再落在编辑窗口。
- 实测（隔离 8399，真实库，连续 60 次编辑压力）：编辑保存 **median 8.61 ms / p95 12.36 ms / max 26.35 ms，>50 ms = 0 次、>70 ms = 0 次**；稳态 7.6–8.6 ms；`semantic cache stored` 日志出现在压力窗口之前/之后（空闲触发）。函数级编辑仍 2.1–3.4 ms；全测试 **199 OK / 1 skip**；`py_compile` OK。
- 正确性：快照延迟只影响“重启后重用缓存”的及时性，崩溃/退出前有强制 flush；语义缓存缓存内容不变（既有测试覆盖）。首次保存一次性 WAL 开销评估后保留（不影响稳态指标）。
- 边界：空闲窗口默认 30 s，可通过 `UW_LIBRARY_SEMANTIC_STORE_IDLE_S` 调整（设为 0 恢复立即调度）；本轮未部署生产。
