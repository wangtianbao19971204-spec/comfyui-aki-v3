# Tag 预热移出启动路径（2026-10-24）

- 问题：生产启动 273 s 中 Tag catalog 预热占 90–136 s；代码里 5 次 `page()` 预热的缓存键与真实请求传入的 `known_collections` 不一致，基本没有命中收益，却各付一次全表扫描。
- 改动：`tag_api.py` 的 `_warm_tag_catalog()` 只保留 `categories()`（目录树 + string_layout），改由 `startup_hooks.register_after_start()` 在 ComfyUI HTTP app 启动后执行；`tag_library.py` 按 tags DB revision 把目录树持久化到 `user_data/prompt_selector/cache/tag_categories.v1.json`（tmp+`os.replace` 原子写，revision/规则不符或损坏即忽略重算，`UW_DISABLE_TAG_CATEGORY_CACHE=1` 可禁用）。
- 不变：Tag 字典数据、接口与节点契约不变；缓存只影响启动/首开耗时，数据权威仍是 tags DB。
- 验证：`prompt_selector/tests/` 全目录 99 tests OK（1 个既存 skip），含新增 `test_tag_warm_deferral.py` 10 项；隔离 A/B 与启动数据见 [启动期零重活与派生语义缓存](../runtime-workbench/2026-10-24-startup-warmup-cache.md)。
- 本轮未部署生产。
