# Phase 3 公开来源复核标签包（2026-07-22）

本批用于补充 Gallery 搜索联想中的高频中文标签，并修复旧 Danbooru 别名快照与当前 canonical 方向不一致的问题。

## 冻结范围

- 61 条 A 级人工复核翻译：Meta 36、通用 3、作品 13、角色 9。
- 17 条定向别名操作：7 条删除旧关系，10 条新增或重定向当前 active 关系。
- 2 条旧 alias identity 译文精确清理：`pokemon_sm` 与 `pokemon_bw`。只有当前值与清单中的预期旧值完全一致时才能清理。
- 2 条术语冲突继续 hold：`eye_mask`、`two-tone_gloves`。
- category 1 艺术家标签始终排除。

## 来源与许可边界

翻译文本为本插件维护者人工复核后编写的简体中文短标签，随插件按 MIT 许可提供。CSV 中的外部链接仅用来核对标签语义、当前 canonical 关系和官方中文实体名；未复制或打包外部 Wiki 正文、图片或无许可证词库。

主要证据来自：

- Danbooru Wiki 与公开 Tag/Tag Alias API：核对标签语义、类别、别名状态和 canonical 方向。
- 游戏或作品官方中文页面：核对角色名、作品名和简体中文写法。
- 既有 MIT WeiLin 数据仅作辅助交叉检查；机器翻译和 GPL 数据不作为本批最终译文来源。

## 写入规则

1. 默认仅 dry-run；正式写入必须显式启用 apply，并对直播库再次确认。
2. 写入前使用 SQLite Backup API 创建一致性备份并验证。
3. 翻译只允许填入空白字段，不覆盖已有非空译文。
4. 别名必须一跳直达存在的 canonical；禁止 alias 链和自环。
5. 旧 identity 译文只能按 `expected_identity_translation` 精确匹配后清理，并写入历史表。
6. 全部操作在单一事务内完成，随后重建 FTS 并执行完整性、行数和目标值核验。
7. `phase3_held_terms_20260722.csv` 只用于后续术语成组修复，不得导入。

## 交付文件

- `tools/data/phase3_reviewed_tags_20260722.csv`
- `tools/data/phase3_alias_updates_20260722.csv`
- `tools/data/phase3_held_terms_20260722.csv`
- `tools/apply_phase3_reviewed_tag_pack.py`
- `tests/test_phase3_reviewed_tag_pack.py`

正式交付报告、数据库前后快照和回滚说明保存在：

`G:\ComfyUI-aki-v3\_codex_backups\DANBOORU_GALLERY_PHASE3_20260722_224250`
