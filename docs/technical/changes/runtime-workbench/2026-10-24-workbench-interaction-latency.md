# 工作台交互延迟优化：提示词保存、Tag 读取与缩略图（2026-10-24）

状态：开发分支验证中，未部署。范围：统一包内 WeiLin 词库/Tag 面板/预览缩略图的请求路径。

## 问题（生产实例只读实测）

- 修改一条提示词：`POST /prompt_selector/prompts/upsert` **3855–5232 ms**；其中重新解析 462 MB `data.json` 约 1.65 s、`orjson.dumps` 0.37 s、write+fsync 0.36 s、每次备份 copy2 0.37 s，另有 `_ensure_data_compatibility` 全量遍历；保存后自动触发的整库 `_warm_library_caches`（约 5 s）持锁，导致紧接着的 `GET library/index` 阻塞 **2788–3141 ms**、`library/prompts` **1992–2658 ms**。
- 打开 Tag 面板后的首次筛选/搜索（冷 `_PAGE_CACHE`）：`shape=group` 508–2304 ms、`shape=string` 511–724 ms、`theme` 333–1297 ms、`q=` 189–1206 ms；重复查询 2–35 ms。原因：形状筛选逐行算逗号数表达式扫 29.8 万行；theme/收藏组在 9.9 万条 meta JSON 上逐行 `json_each`；搜索一次要跑 3 次 count + 最多 3 次排序查询。
- Tag 卡片视图缩略图：生产 preview 152,161 个文件但只有 39,630 个缩略图（约 74% 需现场生成）；旧管线 25–28 ms/张、服务端并发仅 2。

## 改动

1. `prompt_selector.py`：单条编辑保存路径复用已解析缓存（copy-on-write：只拷贝 categories 列表/目标分类/目标 prompt），跳过全量 `_ensure_data_compatibility`；单条写路径的备份改为按 180 s 间隔节流；`_atomic_save_json` 增加 `schedule_warm` 开关，可增量补丁的写不再触发整库 warm；缩略图改为按需 EXIF 旋转 + `Image.draft()` 预缩 + LANCZOS + WEBP method2，服务端缩略图并发 2→4。
2. `tag_library.py`：一次性建立 2 个表达式索引（`workbench_tag_read_scope`/`workbench_tag_read_shape`）与 theme/收藏组派生表（6 个 meta 触发器维护），`prepare_read_index()` 单事务、版本记录在 `workbench_tag_read_meta`，失败不落版本可重试；未就绪/`UW_DISABLE_TAG_READ_INDEX=1` 时自动回退旧 SQL。筛选/搜索改走索引范围与单遍窗口查询。
3. `tag_api.py`：Tag 后台 warm 内先建读取索引，再按与 `/tags/page` 完全一致的 `known_collections` 缓存键预热默认视图（列表 100 / 卡片 120 两种页长，scope×shape 共 16 个）。
4. `scripts/pregenerate_preview_thumbnails.py`（维护工具）：离线批量补齐缺失/过期缩略图（sha1 命名、mtime 新鲜度、原子写、可中断续跑；默认 dry-run，需 `--apply`；`--fast` 走新管线）。示例估算：仅补 11.25 万张 `--fast --jobs 4` 约 6.5–8 分钟、磁盘 +2.0–2.2 GB。
5. 测试：`tests/test_edit_save.py`（18）、`tests/test_tag_read_speed.py`（12）、`tests/test_thumbnail_opt.py`（9）。

## 验证（生产数据副本，同口径）

| 场景 | 改前 | 改后 |
|---|---|---|
| 单条编辑保存 | 2.57–2.66 s | 0.78–0.94 s（首存 2.63→1.20 s） |
| 保存后首次 GET index（可补丁路径） | 2.79–3.14 s | 0 ms（warm 不再请求）；page 0.13 s |
| 保存后首次 GET index（不可补丁/旧 warm 路径） | — | 保留旧路径（约 1.9 s，正确性优先） |
| Tag `shape=group` 首次 | 508 ms | 6.5 ms |
| Tag `shape=string` / 默认视图 | 511 / 71 ms | 5.3 / 9.2 ms |
| Tag `q=hair` / `q+group` | 189 / 1028 ms | 11.5 / 6.6 ms |
| Tag `collection` / `theme` | 461 / 333 ms | 18 / 104 ms |
| 16 张缩略图首屏（冷） | 182 ms | 58 ms（3.14×） |
| 缩略图单张（串行） | 25.4 ms | 15.5 ms（1.64×） |

- 一次性成本：Tag 读取索引构建 2.0–2.2 s、tags DB +48.9 MiB（+9.6%），在 server ready 后的 warm 线程执行；warm 链首跑约 3.5 s（原 Tag warm 89.9–136 s）。
- 语义等价：生产副本 32 组 filters/query 组合新旧 `items`/`total`/顺序完全一致，另 16 组与改动前原版逐字段一致；全测试目录 **138 OK / 1 skip**，`py_compile` 通过。

## 隔离实例 HTTP 端到端 A/B

同树同数据（生产数据副本）、8399 独立端口、串行单实例；before = 仅启动优化提交 `9b8639b5b`，after = 本提交。原始 JSON 见 `G:\ComfyUI-local\validation\startup-warmup-20261024\results\interaction-*.json`，汇总见 `temp/startup-warmup/interaction-bench.md`。

| 场景 | before | after |
|---|---|---|
| 启动→listen | 38.6 s | 23.0 s |
| warm 总等待 | 14.1 s | 13.6 s |
| 编辑保存（description，不可补丁） | 5232 ms | 1125 ms |
| 保存后立即 `library/index` | 3141 ms | 2543 ms（保留旧 warm 路径） |
| 保存后立即 `library/prompts` | 2658 ms | 1020 ms |
| 收藏切换（可补丁） | 1190 ms | 874 ms |
| 可补丁写后立即 `library/index` | — | **22 ms** |
| Tag 首次 `shape=group` | 700 ms | 16.3 ms |
| Tag 首次 `shape=string` | 724 ms | 4.0 ms |
| Tag 首次 `shape=atomic` | 232 ms | 16.7 ms |
| Tag 首次 `theme` | 447 ms | 56.8 ms |
| Tag 深 offset 3000 | 66 ms | 11.3 ms |
| Tag `q=hair` / 空结果 q | 228 / 444 ms | 192 / 347 ms |
| Tag complete | 226 ms | 196 ms |
| 16 张缩略图冷并发生成 | 288.5 ms | 48.7 ms |
| 首屏串行（status+index+tags/index） | 9.2 ms | 30.1 ms |

方差说明：同代码基线三跑 save 4055/3527/5232 ms、保存后 index 2788/2831/3141 ms（±30–50%），after 以同轮相对幅度判读。剩余热点：无 scope 整库搜索约 192 ms、Tag 首次 favorite 4→15 ms 小回退、首屏 tags/index 4→26 ms（仍远低于人眼阈值）。

## 边界与未覆盖

- 不可增量补丁的编辑（如只改正文导致语义 binding 变化）仍保留启动式整库 warm，保存本身已快但随后首次刷新仍可能等待约 1.9 s；后续可做增量 index 重建。
- 无 scope 的整库搜索从 157→178 ms（DB 增大后 LIKE 全表扫略慢）；theme/区域首次约 70–110 ms，仍在目标内但未做更进一步。
- 缩略图批量预生成工具默认不写运行区；生产使用需显式 `--apply` 且另行授权，本次未对生产执行。
- 本改动不改变节点/工作流/提示词内容/API 契约；Tag DB 仅新增派生索引与表，回退代码时它们残留但不影响旧 SQL。
