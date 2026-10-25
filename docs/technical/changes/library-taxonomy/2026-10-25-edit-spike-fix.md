# 编辑保存尖峰消除：语义缓存快照空闲调度（2026-10-25）

- 背景：sqlite 模式下正文编辑稳态已 5–8 ms，但个别保存出现 70–110 ms 尖峰，与后台语义缓存快照（23 MB msgpack.zst，0.9–1.1 s）重合；用户要求编辑成本稳定可预期。
- 改动：`prompt_selector.py` 将语义缓存快照从 1 s Timer 改为“最近编辑后空闲 ≥`UW_LIBRARY_SEMANTIC_STORE_IDLE_S`（默认 30 s）才启动”，新编辑重置排程，批量/退出可强制 flush；不影响缓存内容与恢复语义。
- 实测：连续 60 次编辑 median 8.61 ms / p95 12.36 / max 26.35 ms，无 >50 ms 样本；函数级仍 2.1–3.4 ms；全测试 199 OK/1 skip。
- 边界：延迟只影响重启后缓存复用及时性；`UW_LIBRARY_SEMANTIC_STORE_IDLE_S=0` 可恢复立即调度。本轮未部署生产。
