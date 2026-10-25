# 启动期零重活与派生语义缓存（2026-10-24）

状态：开发分支验证中，未部署。范围：统一包内 WeiLin 词库（prompt_selector）与 Tag 预热的启动行为。

## 问题

生产实测 2026-10-24：Python 子进程 21:16:29 启动，HTTP 8188 监听建立于 21:21:02，即 **273 s** 启动耗时。历史 2026-10-05～10-19 生产启动日志同样稳定出现：library 缓存预热 236–292 s、Tag 预热 90–136 s、统一包 import 108–137 s；`prompt-assistant` 等同代码插件导入从无工作台时的 0.5–0.7 s 被放大到 56.8–81.0 s。

根因：词库已增长到约 36 万条 / 462 MB，而启动路径在插件 import 阶段同步解析该 JSON，并启动两个 daemon 预热线程逐条重算语义投影（refinements 实测 0.5–1.0 ms/条），且**没有任何跨重启持久化缓存**，每次启动全量重算；预热线程与导入主线程争抢 GIL，放大了全部导入时间。

## 改动

1. `prompt_selector/prompt_selector.py`
   - `initialize_data_file()` 不再在 import 期解析 462 MB `data.json`：只保留文件存在性/缺省库复制；时间戳升级检查延迟到首次读取并带一次性标志。
   - 启动预热从 import 期移到 `startup_hooks.register_after_start()`（ComfyUI aiohttp app 启动时起后台线程），且启动预热不再生成整库 packed gzip（`include_packed=False`）。
   - 派生语义缓存：按 `prompt id + binding` 持久化每条 `_semantic`（`user_data/prompt_selector/cache/semantic_cache.v1.msgpack.zst`，msgpack+zstandard）。重建时命中直接复用、只重算变更行；投影签名 / `REFINEMENT_VERSION` / 缓存格式版本不符则整体失效；单条 binding 不符只重算该条；缓存损坏自动回退全量重算；`UW_DISABLE_SEMANTIC_CACHE=1` 可禁用（A/B 用）。
   - 增量保存（`_cache_prompt_data`）后同步更新缓存映射并异步原子落盘。
2. `prompt_selector/startup_hooks.py`（新增）
   - `register_after_start(callback, delay)`：在 ComfyUI aiohttp app 启动后起 daemon 线程执行重活；无 app 环境用定时器兜底，保证 import 期不阻塞。
3. `prompt_selector/tag_api.py`
   - Tag 预热移出 import 期，改由 `register_after_start` 在 ready 后执行；删除 5 次与真实请求缓存键不符的 `page()` 全表预热，仅保留 `categories()`（含 string_layout）目录树预热。

## 验证

- 单测（生产 Python 3.13.11）：`py_compile` 通过；`prompt_selector/tests/` 全目录 **99 tests OK（1 个既存 skip）**，其中新增 `test_semantic_cache.py` 12 项（缓存 roundtrip/原子写、binding 全命中复用、单条变更只重算、projection 失效、损坏回退、与禁用缓存结果等价、增量保存同步、惰性初始化与升级一次、import 不启动预热线程、`UW_SKIP_LIBRARY_WARMUP` 不注册）与 `test_tag_warm_deferral.py` 10 项。
- 隔离 A/B（物化树 + 生产 data.json/tags DB，不复制 26 GB preview；生产 Python 同参数、独立端口 8399；同树同数据串行单实例，生产 8188 全程未受影响）：
  - 基线（`main` 代码）：t0→Listen **368.9 s**（子进程 366.4 s）；library warm **312.4 s**、Tag warm **109.0 s**；import 块 t+289 s、Starting server t+368.9 s；首开 `/prompt_selector/library/index` 2.9 ms（预热已在启动期完成）。隔离树全新且无 pyc，整体比生产 273 s 基线慢，仅作同口径对照。
  - 补丁版冷缓存（首次、无 cache）：t0→Listen **49.3 s**（子进程 46.8 s）；ready 后后台重建 library **320.6 s**、Tag **53.6 s**；首开（ready 后立即请求）**321.4 s** 等后台重建完成，之后 26.5 ms；写出 `semantic_cache.v1.msgpack.zst` **23.1 MB / 324,891 条** 与 `tag_categories.v1.json` 44.5 KB。
  - 补丁版热缓存（第二次）：t0→Listen **26.3 s**（子进程 23.8 s）；`semantic cache loaded in 1.7 s`、Tag 目录缓存 0.2 s、library 后台重建 **10.8 s**；ready 后立即首开 **9.8 s**，warm 完成后 2.9 ms。
  - 结论：热启动 Listen 约快 **13.9×**（366.4→23.8 s 子进程口径）、首开从"启动期付 236–292 s"变为"后台约 11 s 内完成、立即打开最多等约 10 s"；冷缓存首启仍要付一次全量重建（见边界）。
- 部署后 A/B：需用户授权重启与部署后另行记录，不用隔离结果冒充。部署后建议先启动一次并等 `semantic cache stored` 日志出现，再开始日常使用，这样从第二次启动起即为热缓存路径。

## 边界

- 首次运行（无缓存）时语义重建仍会花费分钟级（隔离实测约 5–6 分钟），并且已移到 ready 之后的后台线程；此时若立刻打开资料库面板，会等后台重建完成（隔离实测 321 s）。部署流程应在上线后等待首次预热完成并写出缓存，再从下一轮起享受快速启动；日常使用不刷新缓存则每次热启动约 15–30 s 可用。
- 缓存只存派生字段，不替代 `data.json`/`semantic_projection.json`；数据权威仍在原文件，删除缓存只会退化为全量重算。
- 内存：`_SEMANTIC_ENTRIES` 常驻约 +80–100 MB；冷重建峰值多一份缓存快照（序列化时约 300 MB 级），热启动不触发整库 gzip（旧实现启动峰值 -681 MB）。
- 本改动不改变节点、工作流、提示词内容或 API 契约；不涉及模型加载与显存策略。
