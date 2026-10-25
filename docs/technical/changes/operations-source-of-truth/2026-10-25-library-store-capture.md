# 提示词库 SQLite 权威库的维护捕获与恢复

日期：2026-10-25。状态：开发分支验证中，未部署、未重启生产。

## 问题

提示词库原先把约 462 MB 的 `data.json` 当权威存储，每次编辑都全量重写。第三轮把运行权威改为 `user_data/prompt_selector/library.sqlite3`（WAL；表 `library_meta` / `categories` / `category_orders` / `prompts`，payload 为 JSON 文本），`data.json` 降级为按需导出快照。维护侧的 `snapshot.py` 仍只捕获 `data.json`，且 `data.json` 不会在运行时被更新；若继续按旧方式捕获/恢复，归档会悄悄停留在过期内容，恢复后无法复现当前库。

## 改动

1. `scripts/library_sql.py`
   - 新增 `prompt_library_store_v1` 语义 profile：`LIBRARY_STORE_PROFILE` / `LIBRARY_PROFILES` / `LIBRARY_SCHEMA_VERSIONS` / `LIBRARY_STORE_TABLES`；`library_store_summary(conn)` 校验必需表与列、`__schema_version__`（仅支持 1）、`library_meta.last_modified`、分类 position 唯一、payload 与其行 id 一致、`category_orders` 与 `categories` 一一对应、order 覆盖全部提示词且不跨分类/不重复、`PRAGMA foreign_key_check` 与 `integrity_check`，返回可写入 manifest 的摘要。
   - 该文件不 import 运行期插件代码（维护工具不在插件包内），契约以常量形式固定，schema 升级时必须同步评审。
2. `scripts/snapshot.py`
   - 新增 `library_export_plan(root)`：`library.sqlite3` 存在时运行权威为 sqlite，`data.json` 变为可选兼容导出（存在才捕获，entry 标 `role=compatibility_export`）；不存在时保留 json 模式旧行为（`data.json` 为权威，manifest `library_authority=json`）。
   - 新增 `sqlite_export(...)`：把三个 tag DB、Gallery 辅助库与提示词库统一为“只读源 → SQLite backup API 一致副本 → 逻辑 SQL dump → 分片 + 摘要 + 源 main/WAL 漂移校验”的同一路径；提示词库额外记录 `library_profile` 与 `library_store` 摘要。
   - capture 的 manifest 增加 `library_authority`（sqlite/json）与 `library_json_export`（authority/compatibility_export/absent）；`manifest_path_failures` 拒绝未评审的 profile、被放到其他 source 的 profile、以及不一致的 profile 摘要；`materialize` 重建数据库后重新计算摘要并与捕获记录逐字段比较，不一致即失败、不写 `RESTORE_RECEIPT.json`。
3. `tests/test_snapshot_library_store.py`：小样本 fixture 数据库（按评审 schema 自建）覆盖摘要字段、缺失表/列、schema 版本不符、缺 revision、order/外键/引用不变量、json-only 与 sqlite 捕获计划、data.json 可选性、SQL 导出 + manifest 校验、materialize 往返（含兼容 data.json 与 `.restore.sql` sidecar）、profile 摘要不符/截断 dump/未知 profile/伪造 authority 的拒绝路径。
4. 文档：`docs/SNAPSHOT.md`、`docs/RESTORE.md`、`docs/DATABASE.md` 更新权威来源、捕获/恢复校验与回退边界。

## 兼容与边界

- json 回退模式（未迁移运行区）捕获/恢复行为不变；旧快照仍可照原方式恢复。
- 提示词库 SQL dump 与三个 tag DB 一样只保留逻辑内容（DDL + 行 + 索引），不要求数据库页布局或 WAL/SHM 字节相同；恢复后的库首次由运行期打开时才切 WAL。
- 捕获仍要求“安静窗口”：从备份到 dump 完成若源 main/WAL 变化会报错重试，与现有三库行为一致。
- 捕获 `library.sqlite3` 时校验 schema 版本；运行期升级 schema 需先更新 `library_sql.py` 的支持版本并能重放，否则捕获失败而不是归档未知语义。
- 外部读取方（未在本轮改动、需要实现阶段跟进）：`app/server/prompt_api/prompt_selector_bridge.py` 直接读 `data.json` 并以它的存在性发现库；`comfyui-anima-tools/nodes.py` 的 shared prompt 读取按 `data.json` 的 mtime/size/hash 做缓存失效；`prompt_selector/tools/*` 与 `tools/membership|krea2_mood/*` 等维护脚本默认读写 `data.json`。SQLite 权威模式下这些路径会读到过期或被缺失的导出，详见 `temp/startup-warmup/snapshot-library-store.md` 的“外部读取方清单”；在切换到 sqlite 权威前必须给出只读存储接口/导出刷新策略。
- 测试与验证仅使用临时目录和自建 fixture，不读写在线库、不启动 ComfyUI；本轮未在真实运行区执行 capture/materialize。

## 验证

- 新增 `tests/test_snapshot_library_store.py` 16 项；`tests/test_snapshot.py` 17 项、`tests/test_library_sql.py` 11 项通过；维护测试全目录以仓库现有 Python 环境加 Git 到 PATH 运行（基线 703 OK / 11 skip），结果见本轮交付报告。
- 只读扩展：`python -B scripts/snapshot.py verify` 仍对既有 `snapshot/` 全量生效；本轮未重新捕获主仓快照，下一轮发布前需按实际 SQLite 转换状态重新 capture。
