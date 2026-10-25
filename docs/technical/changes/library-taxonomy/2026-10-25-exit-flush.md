# 退出强制 flush 语义缓存（2026-10-25）

- 背景：优雅退出时 23 MB 语义缓存快照因 `derived_cache.store()` 的 2 s 去抖 Timer 未落盘；数据正确性不受影响，仅下次启动多算少量行。
- 改动：`derived_cache.store(flush_now=True)` 同步写路径（取消 Timer、返回前完成序列化+原子 replace）；`_flush_semantic_cache_snapshot(force, sync)`；`_library_store_shutdown` pending 分支 `force=True, sync=True`；注册 aiohttp `app.on_cleanup` 兜底；Ctrl+C/正常退出经 atexit 生效。
- 验证：真实 462 MB 库退出后 cache 同步重写（24,170,536 B、324,891 条完整、binding/semantic 逐字段一致）；新增 4 测试；全测试 203 OK/1 skip。
- 限制：`production_tools/launch.py --stop` 的 TerminateProcess 不执行 Python 钩子（数据不丢、重启重算少量行）；优雅退出多约 1–1.2 s（仅退出时）。本轮未部署生产。
