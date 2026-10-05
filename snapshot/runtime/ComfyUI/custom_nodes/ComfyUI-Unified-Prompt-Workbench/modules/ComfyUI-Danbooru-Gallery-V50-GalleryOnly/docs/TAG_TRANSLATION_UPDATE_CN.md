# 标签缓存与中文翻译更新流程

本流程用于把许可清晰、版本可固定的公开标签快照导入本地
`py/shared/data/tags_cache.db`。更新只填补空翻译，不覆盖已有人工汉化。

## 数据源策略

- `artist`（category 1）永不进入翻译层；历史误写先记入
  `tag_translation_history`，再清空译文。允许汉化的类别固定为
  `general`、`copyright`、`character`、`meta`（0/3/4/5）。
- 人工整理的中文表优先，仅作本机导入，并记录其上游许可证与固定 revision。
- NEXTAltair `lang_zh` 作为补充源，只接受 `general`、`copyright`、`character`。
- NEXTAltair 自动补全还必须满足：post count 不低于 100、恰好一个中文候选、长度不超过
  64 个字符、不含日文假名、韩文或解释性括号。
- 固定版本的 Danbooru alias 数据只建立 `alias -> canonical_tag` 搜索关系，
  不删除、改名或合并原 tag，也不直接当作主显示翻译；canonical 为 artist 的关系不导入。
- BooruTagCart 等许可明确但质量不均的中文表只能作为候选参考；必须经过类别、
  六词上限、中文字符、日/韩文、括号身份和模型/人工复核，不能原表直灌。
- 本地模型生成结果必须保存模型 revision、许可证、权重 SHA-256、置信度和 review
  队列；试跑中发现的低质量模型或低置信度结果不得导入。
- Wikidata 只用于 `copyright`/`character` 的精确英文维基标题映射；允许确定性的
  大小写变体，但最终 enwiki sitelink 必须在 NFKC、空白归一和 casefold 后与原 tag
  完全一致。可用 `--limit` 按 post count 做可复现的高热度分批缓存，未命中项留待增量更新。
- Civitai 的自由文本 prompt、artist 名和存在歧义的候选不自动汉化。

## 标准更新步骤

1. 固定公开源 revision，保存原始快照、许可证说明与 SHA-256。
2. 使用 SQLite online backup 备份 `tags_cache.db`，同时备份本次会修改的代码文件。
3. 先用 `repair_artist_translations.py` 在 staging 清理 artist 译文并核验历史记录；
   再用 `import_tag_aliases.py` 导入可审计的非 artist 别名关系。artist 修复器写正式库时
   同样必须使用 `--apply --allow-live-db`。
4. 用 `build_public_tag_translation_pack.py` 或对应固定源构包器离线生成通用 CSV；
   构包器不联网，也不写 live 数据库。
5. 对每个 CSV 先运行 `import_tag_translations.py --dry-run`（省略模式参数时也默认 dry-run），
   检查拒绝行、歧义行和预计变更量。确认后仅可用显式 `--apply` 写 staging；正式
   `py/shared/data/tags_cache.db` 还必须同时提供 `--allow-live-db`。
6. 从 live 数据库再制作一份 staging 副本，按“已有人工译文 -> 严格公开源 ->
   已复核本地生成结果”的顺序导入。
7. 核验 staging 数据库后，停止确切的 ComfyUI 进程，在 live 库执行相同操作，再启动原命令行。
8. 等待 ComfyUI 健康检查通过，调用单标签、批量翻译、中文反查与 alias 补全接口；
   同时检查括号限定、一对多同译名、artist 屏蔽和原 tag 身份不变。

## 每次必须通过的核验

- `PRAGMA integrity_check` 返回 `ok`。
- `hot_tags` 与 `hot_tags_fts_docsize` 的真实 FTS 索引文档数一致；不得以 external-content
  `SELECT COUNT(*) FROM hot_tags_fts` 代替索引完整性核验。
- 翻译导入只更新 `hot_tags` 中已存在的 tag；CSV 中不存在于目标数据库的 tag 全部拒绝，
  目标数据库 category 为权威，category 1 永不写入译文。
- category 1 的 `translation_cn` 非空数必须为 0，所有清理前的值都能在历史表或备份中恢复。
- 导入前所有非空 `translation_cn` 在导入后保持原值。
- `tag_aliases` 不含 artist canonical 或不存在的 canonical，且导入前后 `hot_tags`
  逐行差集为 0。
- 相同 source URL、revision 和 SHA-256 再次导入是幂等操作。
- `tag_translation_imports` 保存来源、许可证、revision、SHA-256、时间和变更计数。
- Python 测试、JavaScript 测试和隔离 ComfyUI 四站点 API 探针全部通过；交付脚本对
  live SQLite 使用前后 online snapshot 的逻辑指纹比较，必须能检测 WAL 中已提交的变化。
- live ComfyUI 重启后，8188 端口由新进程监听，接口健康且新增汉化可查询。

## 回滚

若 live 核验失败，先停止确切的 ComfyUI 进程，将本轮导入器生成的
`*.pre_tag_translation_*.db` 恢复为 `tags_cache.db`，再使用原启动参数启动服务。
不要在 ComfyUI 正在持有数据库连接时直接替换数据库文件。
