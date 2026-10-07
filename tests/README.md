# 维护测试入口

本目录验证主仓维护工具。先按[开始使用](../docs/GETTING_STARTED.md)选择基础解释器 `$comfyPython`，在主仓根目录创建独立测试环境：

```powershell
$comfyTestEnv = '..\comfyui-maintenance-tests' # 换成自己的全新目录
if (Test-Path -LiteralPath $comfyTestEnv) { throw '测试环境目录已存在，请使用新目录' }
& $comfyPython -m venv $comfyTestEnv
if ($LASTEXITCODE -ne 0) { throw '测试环境创建失败' }
$comfyTestPython = (Resolve-Path -LiteralPath (Join-Path $comfyTestEnv 'Scripts\python.exe')).Path
& $comfyTestPython -m pip install -r .github/requirements.txt
if ($LASTEXITCODE -ne 0) { throw '维护测试依赖安装失败' }
& $comfyTestPython -X utf8 -B -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw '维护测试未通过，请保留输出检查' }
```

依赖仅安装到这个虚拟环境，不修改基础／生产解释器。后续继续使用该环境的 `Scripts\python.exe`，无需重新创建。只运行某个模块时可执行 `& $comfyTestPython -X utf8 -B -m unittest discover -s tests -p test_snapshot.py -v`；按变更选相关测试，完整提交／上传门禁见[日常维护](../docs/MAINTENANCE.md)。

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
