# 维护测试入口

本目录验证主仓维护工具。先按[开始使用](../docs/GETTING_STARTED.md)选择 `$comfyPython`，在主仓根目录执行：

```powershell
& $comfyPython -X utf8 -B -m unittest discover -s tests -v
& $comfyPython -X utf8 -B -m unittest discover -s tests -p test_snapshot.py -v
```

第二条只运行一个模块；按变更选相关测试，完整提交／上传门禁见[日常维护](../docs/MAINTENANCE.md)。

## 维护状态

- `test_maintain.py`、`test_backup_status.py`：Git／标签／hooks 状态与已登记备份回执边界，不认证在线实例。
- `test_workspace_audit.py`、`test_workspace_guard.py`、`test_workspace_history.py`：唯一开发入口、外部目录和旧 Git 归属；[工作区](../docs/WORKSPACE.md)。
- `test_archive_workspace.py`、`test_history_migration.py`：私有归档及历史迁移保护；[历史入口](../docs/history/README.md)。

## 快照恢复

- `test_snapshot.py`：清单、分片、哈希、链接拒绝及新目录恢复；[恢复方法](../docs/RESTORE.md)。
- `test_project.py`：源码差异、seal 与只读部署计划，维护文档不代表线上已生效。
- `test_repository.py`：候选比较、审核摘要、接纳与离线包门禁；[源码权威](../docs/technical/operations/source-of-truth.md)。
- `test_import_workspace_sources.py`、`test_plugin_support.py`、`test_registered_sources.py`、`test_source_support.py`：受审源码和配套文件的精确保留范围。

## 安全门禁与发布

- `test_security_guard.py`、`test_security_names.py`、`test_security_review_fixtures.py`：凭证、路径、压缩载荷与审核例外；[安全说明](../docs/SECURITY.md)。
- `test_staged_scan_cache.py`：暂存缓存绑定实际字节、规则变更失效及损坏回退。
- `test_technical_catalog.py`、`test_technical_archive.py`：技术归属、必备说明／示例／链接及历史来源哈希；[技术目录](../docs/technical/README.md)。
- `test_release.py`：显式 release 分支准备、用户接受后 main 标签与完整门禁；[版本规则](../docs/VERSIONING.md)。

## 资料与模型

- `test_library_sql.py`、`test_database_contract.py`：SQL 导出／隔离恢复、数据保全及结构契约；[数据库说明](../docs/technical/operations/database.md)。
- `test_native_workflow_acceptance.py`：工作流结构与模式，不证明采样画质或真实模型加载成功。
- `test_model_sources.py`、`test_standardize_models.py`、`test_training_trigger_reviews.py`：来源登记、命名路径与成品训练触发词；[模型维护](../docs/MODELS.md)。

## 外部状态与验收边界

- `test_external_state.py`、`test_remote_llm_config.py`：仓外清单、私有配置、隔离物化及鉴权读取；[外部状态](../docs/EXTERNAL_STATE.md)。
- 测试使用临时目录和隔离资料；通过测试不授权覆盖在线库、上传、合并、部署或生成图片。
- 插件自身测试在 `snapshot/runtime/.../tests`，按[功能目录](../docs/technical/catalog.json)找到对应入口；本目录不替代它们。
- GPU、真实浏览器、物理输入法、冷安装和现场运行仍需专项验收；结果按实际覆盖范围记录。
