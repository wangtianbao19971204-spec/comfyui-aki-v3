# 主仓规则与审核登记

这里保存唯一主 Git 的规则、版本、受审查文件范围和历史映射。
这些文件用于维护与核验；实际密钥、模型、预览及最新运行数据在仓外保管。

## 关键文件

| 文件 | 用途 |
|---|---|
| [RUNTIME_AGENTS.md](RUNTIME_AGENTS.md) | 运行区 AGENTS 的版本化原件，规定唯一开发入口 |
| [version.json](version.json) | 维护包版本与准备状态；按[版本规则](../docs/VERSIONING.md)更新 |
| [workspace-layout.example.json](workspace-layout.example.json) | 目录角色示意；不是实际外部计划或机器路径配置 |
| [retention-policy.json](retention-policy.json) | 备份与历史保留规则；文件本身不执行备份或清理 |
| [runtime-support.json](runtime-support.json) | 特殊支持文件和仍需外补资源的精确边界 |
| [plugin-support-20261007.json](plugin-support-20261007.json) | 已审查插件配套文件、来源、许可及摘要 |
| [retired-git.json](retired-git.json) | 已退休 Git 的映射；旧原件保留在私有档案 |
| [technical-archive.json](technical-archive.json) | 技术原件归档的角色、来源和哈希 |

源码补迁回执：[workspace-source-import.json](workspace-source-import.json)、[runtime-support-import.json](runtime-support-import.json)、[trainer-portable-source-import.json](trainer-portable-source-import.json)。
精确规则审核：[security-review-fixtures.json](security-review-fixtures.json)、[training-trigger-reviews.json](training-trigger-reviews.json)；它们不批准其他路径或字节。

## 编辑边界

- 按对应维护工具和技术说明更新规则／登记，并保留范围、摘要及审核来源。
- 不手工伪造版本、已部署、已备份或已验收状态；不修改归档摘要来掩盖原件变化。
- 不放凭据、真实认证配置、权重、媒体、缓存、原始 `.git` 或私有 bundle。
- 规则改动不自动部署运行区、覆盖在线库或授权公开私有资料。

详情看[唯一来源](../docs/technical/operations/source-of-truth.md)、[工作区](../docs/WORKSPACE.md)、[日常维护](../docs/MAINTENANCE.md)及[安全与许可](../docs/SECURITY.md)。

## 更新记录

- 2026-10-07：新增规则与登记导航，明确格式示意、历史回执和实际运行状态的边界。
