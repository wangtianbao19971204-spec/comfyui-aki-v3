# 资料库结构、导出与迁移

文档修订：2026-10-05.1。

## 实现与数据

[contract.json](../../../database/contract.json)描述当前三库表/索引/触发器契约；[contract.py](../../../database/tools/contract.py)检查和验证隔离测试资料。真实 JSON/SQL 分片在 `snapshot/library/`，并非只有一个空数据库结构。

一致 SQLite 副本通过 backup API 产生，再导出逻辑 SQL；恢复校验完整逻辑 SQL 与表行数，不要求页布局或二进制 DB 字节相同。原有 ID、正文、来源、个人字段及关联必须保留，不能靠相似文字合并。

## 未来开发

结构/索引/触发器变更与迁移登记先进主 Git，准备向前迁移、备份及回退策略，隔离测试后才安排现场窗口。当前基线契约不等于通用、自动、在线迁移引擎已经实现。

代码版本和数据检查点版本分开。在线库若晚于 Git 导出，以现场数据为准；不要把“唯一代码来源”解释为旧 SQL 可以覆盖新资料。

## 验证与限制

[test_database_contract.py](../../../tests/test_database_contract.py)与 `contract.py check --against-snapshot`检查基线。文件/SQLite 保护见 [workspace_guard.py](../../../scripts/workspace_guard.py)。备份连接必须显式关闭，不在线替换 DB/WAL/SHM，也不因为发现 WAL 就删除它。

## 更新记录

- 2026-10-05：保留三库实际数据导出和契约/fixture，明确未来迁移入口与在线数据优先边界。
