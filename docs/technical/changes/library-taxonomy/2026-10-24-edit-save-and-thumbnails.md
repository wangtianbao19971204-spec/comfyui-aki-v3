# 提示词保存与派生语义缓存交互优化（2026-10-24）

- 问题：单条提示词编辑保存 3.9–5.2 s（每次重新解析 462 MB `data.json`、全量兼容遍历、整库 JSON 重写、每次备份 copy 462 MB），保存后自动触发的整库 warm 持锁使紧接着的 `library/index` 阻塞约 2.8–3.1 s。
- 改动：单条写路径复用已解析缓存并做 copy-on-write（不污染共享缓存、失败/冲突不落盘）；跳过全量 `_ensure_data_compatibility`；单条写备份按 180 s 节流；`_atomic_save_json` 新增 `schedule_warm`，可增量补丁的写不再触发整库 warm；缩略图生成改 draft+按需转换+快速 WEBP 并提升服务端并发。
- 效果（生产 462 MB 副本 A/B）：保存 2.57–2.66 s→0.78–0.94 s；可补丁写保存后首次 GET index 2.79–3.14 s→0 ms（page 0.13 s）；不可补丁写保留旧 warm 路径（约 1.9 s，语义正确优先）；缩略图单张 1.64×、16 张首屏 3.14×。
- 验证：`tests/test_edit_save.py`（18）、`tests/test_thumbnail_opt.py`（9）；全测试 138 OK/1 skip；与 `_semantic` 缓存逐字段相等校验。
- 未覆盖：不可增量补丁的编辑仍付一次约 1.9 s 的首次刷新；正文编辑导致 binding 变化时的增量 index 重建留待后续。
- 本轮未部署生产；实现与完整数据见 [工作台交互延迟优化](../runtime-workbench/2026-10-24-workbench-interaction-latency.md)。
