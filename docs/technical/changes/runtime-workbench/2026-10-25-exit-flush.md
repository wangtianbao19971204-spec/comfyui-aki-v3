# 退出强制 flush 语义缓存（2026-10-25）

- 问题：T19 补充验证发现优雅退出时 23 MB 语义缓存快照未落盘——`_library_store_shutdown` 的 `force=True` 只调用 `derived_cache.store()`，而后者仅挂 2 s 去抖 Timer，进程退出前不会触发；`production_tools/launch.py --stop` 的 `TerminateProcess` 又不执行任何 Python 退出钩子。数据正确性不受影响（重启按 binding 重算少量行），但“退出即落盘”的语义未兑现。
- 改动：`derived_cache.store(..., flush_now=False)` 增加同步写路径（`flush_now=True` 时取消去抖 Timer，返回前完成 msgpack+zstd+原子 replace，默认行为不变）；`_flush_semantic_cache_snapshot(force=False, sync=False)`，退出路径传 `sync=True`；`_library_store_shutdown` pending 分支改 `force=True, sync=True`（`last_flush_at` 防重复写）；导入时幂等注册 aiohttp `app.on_cleanup` 兜底 flush。ComfyUI `main.py` 不调用 `AppRunner.cleanup`，Ctrl+C/正常退出走 **atexit**（已验证生效）。
- 实测（真实 462 MB 隔离库）：退出前仍有 pending idle Timer 时，正常退出后 cache 被同步重写（mtime/size 变化，24,170,536 B），解压 324,891 条完整，目标提示词的 binding/semantic 与退出前内存逐字段一致。测试新增 4 项（同步 flush 文件/内容/无残留 timer、失败仅告警、on_cleanup 幂等、重启 load 复用）；全测试 **203 OK / 1 skip**；`py_compile` OK。
- 限制（已文档化）：`production_tools/launch.py --stop` 使用 TerminateProcess，强杀下不执行 Python 钩子，缓存可能落后；数据不丢、仅重启重算少量行。后续可把 `--stop` 改为 `CREATE_NEW_PROCESS_GROUP` + `CTRL_BREAK_EVENT` 宽限退出（属生产工具，本轮未改）。优雅退出在有 pending 编辑时会多约 1–1.2 s（仅退出时）。本轮未部署生产。
