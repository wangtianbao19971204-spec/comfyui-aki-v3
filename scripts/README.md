# 维护工具入口

在唯一主仓根目录执行；先按[开始使用](../docs/GETTING_STARTED.md)选择 `$comfyPython`。工具不因存在于此目录就获准部署，流程见[日常维护](../docs/MAINTENANCE.md)。

## 维护状态

- `& $comfyPython -X utf8 -B scripts/maintain.py status`：只读查看 Git、版本、hooks 与已登记备份，不检查在线运行状态。
- `maintain.py history` / `backup-policy`：只读查看维护主线／备份保留规则；[备份登记](../docs/MAINTENANCE.md)。
- `project.py status`：只读比较源码与清单；`seal --note "变更说明"` 更新源码清单并标记未部署。
- `project.py deploy-plan --runtime <运行根>`：只读列出部署差异与待审删除候选；[源码权威](../docs/technical/operations/source-of-truth.md)。
- `workspace_audit.py`、`workspace_guard.py`、`workspace_history.py`：核对工作区边界及旧 Git 归属；[工作区](../docs/WORKSPACE.md)。

## 快照恢复

- `& $comfyPython -X utf8 -B scripts/snapshot.py verify`：只读校验快照结构、分片与哈希。
- `snapshot.py capture --runtime <运行根> --out <新候选目录>`：读取现场并创建新候选，不反向覆盖主仓。
- `snapshot.py materialize --dest <全新空目录>`：只按受审快照恢复源码和资料；[恢复步骤](../docs/RESTORE.md)。
- `repository.py compare` / `adopt`：比较候选／按审核摘要接纳明确恢复或已验收部署；[范围与参数](../docs/MAINTENANCE.md)。
- `repository.py bundle`：在仓外创建新离线包；默认携带所有 refs，分发须核对[随包回执](../docs/RESTORE.md)。
- `history_migration.py`、`archive_workspace.ps1`、`import_workspace_sources.py`：受审历史迁移／工作区归档／源码补迁；[历史说明](../docs/history/README.md)。

## 安全门禁与发布

- `& $comfyPython -X utf8 -B scripts/maintain.py check-staged --fresh`：检查实际暂存字节及技术说明，不使用扫描缓存。
- `security_guard.py --staged` / `--all-history --report <仓外报告>`：暂存检查／完整历史凭证扫描；[安全与许可](../docs/SECURITY.md)。
- `technical_catalog.py check --require-tracked`：检查功能实现、测试、示例和说明链接；`technical_archive.py` 管理历史技术来源；[技术目录](../docs/technical/README.md)。
- `release.py prepare`：在显式 `--expected-branch release/<名称>` 上准备版本元数据，需 HEAD、审核及回滚参数；[版本规则](../docs/VERSIONING.md)。
- `release.py tag`：仅在用户接受后的干净 `main` 通过完整门禁创建本地标签；上传分支、合并与部署分别按日常维护执行。

## 资料与模型

- `library_sql.py`：导出／检查／隔离恢复 SQLite 资料，保留正文和个人字段；[数据库契约](../docs/technical/operations/database.md)。
- `native_workflow_acceptance.py`：默认只读预检；显式 `--execute` 会提交隔离 QA 任务并生成图片，执行须有相应授权；[验收范围](../docs/technical/runtime/workflows.md)。
- `& $comfyPython -X utf8 -B scripts/model_sources.py check`：核对模型来源清单；[来源网址](../docs/MODEL_SOURCES.md)。
- `standardize_models.py`、`model_naming_rules.py`：按已审计划规范模型分类和路径；[命名规则](../docs/MODEL_NAMING.md)。
- `remove_reviewed_eval_checkpoints.ps1`：仅清理已审核训练评估副本，保留成品；[模型维护](../docs/MODELS.md)。

## 外部状态

- `external_state.py inventory` / `verify-dry-run` / `materialize`：按仓外真实计划登记、只读核验或物化到新目录；[外部状态](../docs/EXTERNAL_STATE.md)。
- `extract_remote_llm.py`：把远端鉴权从可公开源码分离到私有配置；[远端调用](../docs/technical/operations/remote-llm.md)。
- 配置、模型和预览原件在仓外；[格式示例](../examples/private-state/README.md)是占位样例，引用清单不是资源备份。
- 恢复外部 overlay 不自动覆盖在线库；生产部署需明确范围、回滚和现场验收。

新下载 LoRA：[一行整理说明](../docs/technical/runtime/lora-quick-import.md)，`Import-DownloadedLoras.ps1 -Apply` 仅移动新增并登记工作台。
