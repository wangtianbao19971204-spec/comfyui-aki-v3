# 提示词编辑内存 patch O(1) 定位（2026-10-25）

- 背景：SQLite 权威存储让单条编辑持久化降到 1–3 ms，但隔离 HTTP 保存仍 169.3 ms——`_cache_prompt_data` 全量扫描 324,891 条定位 changed_ids（146.3 ms）、`_patch_derived_caches` 再次全量扫描（64 ms），move 还重复解析 projection（107 ms）。用户要求编辑成本与库大小解耦，内存 patch 也必须 O(1)。
- 改动：`prompt_selector.py` 在 `_LIBRARY_STATE` 维护 `locations`（id→(category_position, prompt_index)）与 `total_prompts`（rebuild 构建、reset 清理），新增 `_locate_prompt`/`_state_row_location`/`_reindex_prompt_locations`；`_cache_prompt_data` 走 hint→旧映射→单次扫描回退（含删除零扫描与陈旧检测）；`_patch_one_changed_row`/`_patch_derived_caches` 不再扫描；缓存 projection、大库语义缓存快照移到后台 Timer。
- 实测（真实 324,891 条）：正文编辑中位 **2.48 ms**（min 2.13/max 3.44）、恢复 2.18–2.27 ms、move 3.66 ms；`_cache_prompt_data` 146→0.8 ms；与全量 rebuild 深相等（24 项）；全测试 196 OK/1 skip。
- 遗留：删除/重置类仍约 100–150 ms；projection 缓存 ~14.5 MB、定位映射 ~30–40 MB；本轮未部署生产。
