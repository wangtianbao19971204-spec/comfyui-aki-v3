# 网页提示词收件库契约

这是新接口的仓外可变 SQLite 数据，不是 Git 中正式提示词资料的检查点。实际实例为 `COMFYUI_EXTERNAL_ROOT/mutable-data/browser-import/inbox.sqlite3`，正文/数据库二进制不入 Git。源码运行的路径不明确时必须显式配置仓外根；不能在源码树产生收件缓存。

当前 `PRAGMA user_version=1`，格式见 [schema.sql](schema.sql)，创建和受限访问由[后端](../../snapshot/runtime/ComfyUI/custom_nodes/ComfyUI-Danbooru-Browser-Import/danbooru_browser_import.py)管理，不手工运行示例 SQL 覆盖在线库。

| 表 | 内容与生命周期 |
|---|---|
| inbox | 最多 32 条未确认的标准化正文，连同短领取租约；满时新 POST 返回 409，不覆盖旧稿 |
| accepted | 最近 128 个确认 ID、接收者和租约凭据；用于重复确认/旧事件去重，不保留提示词正文 |
| state | 仅一条最近标准化正文和接收时间，供旧节点兼容读取；不是完整历史 |

领取通过同一数据库事务检查未确认条目、租约状态与接收者；过期租约恢复可领取，过期 lease token 不能确认新的租约。ACK 后移出 inbox 并登记 accepted。正文通过受限本机接口和同服务事件传递；GET 可列出未确认稿，实际加入待用区仍须先成功领取。新接口拒绝跨源普通网页读写。

未来 schema 变更须增加 `user_version` 并提供受测迁移；遇到未知版本必须拒绝，不默默重建或删除既有收件。连接显式关闭；若需要备份，使用 SQLite backup API 产生新副本，不能运行时覆盖 DB/WAL/SHM。

旧 `latest_danbooru_browser_import_v05.json` 原件保留字节；新版写仓外收件库，不向 Git 源文件写入新稿。旧节点/兼容 GET 在可用时读取较新的外部 latest，代码回退不自动替换或清理此库。重要稿请明确存入正式资料库，临时收件和浏览器会话并非备份。

更新：2026-10-06，首次登记五站网页桥接的 schema 1、容量/租约/确认契约与外部边界。
