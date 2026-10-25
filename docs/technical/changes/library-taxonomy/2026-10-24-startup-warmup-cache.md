# 词库派生语义缓存与启动优化（2026-10-24）

- 问题：词库已增长到约 36 万条 / 462 MB，插件 import 期逐条重算语义投影（refinements 实测 0.5–1.0 ms/条），library 预热 236–292 s，且没有任何跨重启持久化缓存，每次启动全量重算并与其他插件 import 抢 GIL。
- 改动：`prompt_selector.py` 把 462 MB `data.json` 的解析与时间戳升级延迟到首次读取；启动预热改由 `startup_hooks.register_after_start()` 在 HTTP app 启动后执行；新增 `derived_cache.py` 按 `prompt id + binding` 持久化每条 `_semantic`（msgpack+zstd，缓存格式/`REFINEMENT_VERSION`/projection 签名分级失效，单条 binding 不符只重算该条，损坏自动回退，`UW_DISABLE_SEMANTIC_CACHE=1` 可禁用）。
- 不变：分类、子类、refinement 规则与输出不变；缓存只复用派生字段，数据权威仍是 `data.json` + `semantic_projection.json`。改语义规则时需 bump `derived_cache.CACHE_FORMAT`。
- 验证：新增 `test_semantic_cache.py` 12 项 + 全目录 99 tests OK（1 个既存 skip）；隔离 A/B 数据见 [启动期零重活与派生语义缓存](../runtime-workbench/2026-10-24-startup-warmup-cache.md)。
- 本轮未部署生产。
