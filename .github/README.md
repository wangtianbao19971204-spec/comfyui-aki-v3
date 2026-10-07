# GitHub 仓库检查

[maintenance.yml](workflows/maintenance.yml)在上传、PR 和手动触发时检查仓库，不访问本机运行区。

它运行维护测试、快照哈希、数据库契约、技术目录、模型来源目录和全历史凭据门禁。实际运行状态在 GitHub **Actions → Maintenance integrity** 查看。

自动事件没有生成记录时，可选择 **Run workflow** 并指定要检查的分支。没有运行记录或没有读取权限时，不能标为 CI 通过。

PR 合并按[日常维护](../docs/MAINTENANCE.md)的用户授权执行；本地与远端主线同步后，运行部署仍单独处理。私有仓的服务器保护能力取决于套餐和实际设置。

改变检查步骤时同步[发布技术说明](../docs/technical/operations/release.md)，保留必要检查，不把 CI 成功当作 GPU、浏览器或新机迁移验收。
