# 数据库维护：一个主仓库，结构与资料分开维护

用户允许本仓库保留真实提示词资料。`snapshot/library/json/` 的字节分片和 `snapshot/library/sql/` 的逻辑 SQL 分片仍然是资料内容；`database/` 只增加可阅读的结构与小型安全测试入口，不把真实库退化为示例，也不复制第二套生产数据库。

## 当前数据库契约

三库在实际运行目录中的共同父路径（相对运行根）：

`ComfyUI/custom_nodes/ComfyUI-Unified-Prompt-Workbench/modules/WeiLin-Comfyui-Tools-V52-FullPromptSelector/user_data/`

| 文件 | 当前作用 | 纯结构 |
|---|---|---|
| `userdatas_zh_CN_tags.db` | 分组、子组、词条、资料元信息、目录关联、修订与文本标记 | 11 表、11 显式索引、24 触发器 |
| `userdatas_zh_CN_danbooru.db` | 标签翻译/热度、更新与版本元信息 | 3 表 |
| `userdatas_zh_CN_history.db` | 历史、收藏历史、版本元信息 | 3 表 |

纯 DDL 与验收过的 SQL 分片逐项核对；源路径和 SQL 摘要见 `database/contract.json`。`sqlite_sequence` 等 SQLite 自动对象不单独导出；由 `AUTOINCREMENT` 表自然产生。版本基线保留索引和触发器，不能只留 CREATE TABLE。

## 不触碰生产的检查

在仓库根使用 Python 3.10+（SQLite 须支持 JSON 函数）：

```powershell
python -B database/tools/contract.py check
python -B database/tools/contract.py check --against-snapshot
python -B database/tools/contract.py init --name empty-v1
python -B database/tools/contract.py init --name example-v1 --fixtures
python -B database/tools/contract.py verify --name example-v1
python -B -m unittest discover -s tests -p test_database_contract.py -v
```

`init` 只能创建仓库 `local/database-checks/<name>/` 下尚不存在的新目录，拒绝路径参数、父级穿越、符号链接/目录联接及覆盖。这个目录被 Git 忽略。收据 `DATABASE_RECEIPT.json` 记录结构、行数和文件摘要；`verify` 以只读方式核验。没有接受任意数据库路径的参数，不会访问在线库、启动 ComfyUI 或恢复真实资料。

`--against-snapshot` 流式检查 SQL 分片及完整 SQL 哈希，仅在内存执行 CREATE 定义，不执行生产 INSERT。空库全部表行数为零；带 fixtures 的库只含虚构内容。`schema_version` 和真实更新时间不从生产复制，因此这些库是开发契约样例，**不能直接覆盖运行库，也不代表插件完整冷启动已验收**。

## 后续修改入口

### Gallery 辅助词典检查点

主三库的 v1 DDL／迁移契约仍只覆盖上述三库。Gallery 的 `tags_cache.db` 另以 `gallery_fts5_v1` 规范 SQL 存在 `snapshot/library/sql/gallery_tags_cache.db/`，由 `scripts/library_sql.py` 和 `tests/test_library_sql.py` 验证；不能声称三库的 contract 工具已经验证第四库。

该库保留热词、译文、官方别名、同步元信息和两类导入／修订历史。普通 `iterdump` 对它的虚拟表 schema 无法直接还原，因此新格式保留全部业务数据与行身份、结构、索引、触发器、自增计数，并从内容表重建派生 FTS5 shadow 存储。恢复检查完整规范 SQL SHA、逻辑表行数、数据库完整性和 FTS 一致性；不要求派生索引分段、虚表 DDL 空白或数据库页布局相同。未知虚拟表／分词器/schema 拒绝，库二进制与在线 WAL/SHM 不入 Git。现场库仍是最新可变数据，SQL 仅作时间点检查点。

本次源一致备份的普通 `integrity_check` 通过，但 FTS5 外部内容一致性检查失败；因此显式登记 `fts_source_consistent: false` 和 `rebuild_from_preserved_content` 策略。保留业务全文及私有原始备份，恢复库的 FTS 一致性通过；不能声称所有陈旧索引查询与重建结果相同。这次不修复在线索引。新格式需要 SQLite 3.37+ 和 FTS5 支持。

新增表、索引、查询、资料格式、缓存或数据库服务相关源码都在此主仓库修改；新增业务功能需要需求明确后再实现。保持 `database/migrations/` 不可变的有序迁移记录，并按其中 README 增加适用版本、测试和恢复门禁。当前仅实现 v1 基线检查/初始化，不存在通用生产升级器。

资料变更继续保留原 ID、正文、收藏/备注和来源绑定，不按相似名称自动合并。资料内容修改后，需要重新导出/核验 snapshot 数据；结构变化还必须更新契约与专项测试，不能靠修改哈希掩盖未验收变更。

生产库要先用 SQLite backup API 得到一致副本，再在隔离副本运行迁移和验收。禁止直接拷贝在线 `.db`，禁止覆盖 WAL/SHM，禁止把浏览器缓存、API key、Cookie、令牌或含鉴权 URL 写入公开 fixture、SQL、日志或收据。公开前的凭证扫描覆盖当前文件及可达 Git 历史；允许提示词公开不等于允许凭证公开。
