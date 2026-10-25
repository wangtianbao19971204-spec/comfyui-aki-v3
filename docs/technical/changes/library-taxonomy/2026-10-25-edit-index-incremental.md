# 正文编辑后的单行增量 index 刷新（2026-10-25）

- 问题：修改提示词正文会改变语义 binding，使 `_cache_prompt_data` 判定不可按“收藏/使用计数”级别补丁，回退整库 rebuild 并触发 `_request_library_warm`；保存后第一次 `GET library/index` 要等整库 warm 3.0–3.5 s、`prompts` 页 1.1–1.3 s。
- 改动：`prompt_selector.py` 增加单行增量路径（`_patch_library_index_for_row` / `_patch_one_changed_row` 等）：从缓存的 index payload 反推 `label_owners`，对变更行做 ±1 增量并刷新 `filter_pool/semantic_subcategories/total_prompts/review_counts/categories/selector_groups`；views/rows 支持行内替换、离开正常视图、pending 行进入视图，并同步 `view_index/rows/ranges/row_index/review_counts` 两套视图；仅在形态不安全/多行/异常时回退旧的清空+warm。为使增量与全量逐字段一致，index `filter_pool` 并列计数改为确定性排序（值不变）。
- 效果（真实 462 MB 副本函数级 A/B）：正文编辑后首次 `index` 1.58/2.86/3.17 s → **0.000 s**（带分类/不带分类/pending 确认三形态），`prompts` 1.09 s→0.13 s；保存本身 1.11–1.22 s→1.03–1.15 s（无退化）；单行 patch 约 1.6 ms（仅语义）~90 ms（行进出视图）。
- 正确性：4 个真实场景 index/page/两套 view/rows/ranges/view_index/row_index/review_counts 与“reset+全量重建”逐项 ALL EQUAL；异常/多行路径回退旧行为且不污染已提交文件。
- 未覆盖：`include_filter_counts=1` 的 prompts 页仍会重建 filter_masks（约 3 s，旧同）；本轮未部署生产。
