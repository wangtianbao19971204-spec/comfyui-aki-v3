# 文档导航

按任务选择入口；具体实现、测试、资料边界和日期式更新记录保存在对应技术说明中。

## 常用入口

| 要做什么 | 入口 |
|---|---|
| 首次拉取、选择 Python、启用检查 | [开始使用](GETTING_STARTED.md) |
| 查看目录和唯一源码归属 | [项目地图](PROJECT_MAP.md) |
| 本地开发、测试、上传分支和创建 PR | [日常维护](MAINTENANCE.md) |
| 维护目录自述、注释与技术说明 | [文档维护规则](DOCUMENTATION.md) |
| 迁移机器、核验交付包、备份和回滚 | [恢复方法](RESTORE.md) |
| 查阅尚未通过或尚未覆盖的项目 | [已知问题](KNOWN_ISSUES.md) |

## 按功能接手

| 范围 | 技术说明 |
|---|---|
| 本体、插件、五模块装配与启动 | [本体与装配](technical/runtime/core.md) |
| 工作台界面、检索、目标写入与运行控制 | [工作台](technical/runtime/workbench.md) |
| UAP 九分支、内嵌子图、部位细化与二放 | [工作流](technical/runtime/workflows.md) |
| 网页提示词直送工作台、图片反推标签 | [网页桥接](technical/runtime/browser-import.md)、[PixAI](technical/runtime/pixai.md) |
| 提示词、Tag、共享选择器、导入与预览绑定 | [资料库](technical/library/README.md) |
| 角色数据集、Anima LoRA 训练与兼容 | [训练工具](technical/training/README.md) |
| 独立 Qwen 等非生产服务 | [独立服务](technical/runtime/independent-services.md) |
| 主仓、发布、数据库与远端 LLM 维护工具 | [维护工具](technical/operations/README.md) |

[技术总索引](technical/README.md)与[功能登记](technical/catalog.json)将每项功能绑定到唯一实现、测试、示例和维护记录；历史脚本不作为默认执行入口。

## 资料与运行边界

| 内容 | 说明与示例 |
|---|---|
| 主仓、运行目录和仓外资料的关系 | [工作区](WORKSPACE.md)、[仓外状态](EXTERNAL_STATE.md)、[私有状态示例](../examples/private-state/README.md) |
| 提示词与 Tag 数据、SQL 检查点和迁移契约 | [数据库](DATABASE.md)、[资料库分层](technical/library/README.md) |
| 模型与 LoRA 的来源、分类和放置位置 | [下载来源](MODEL_SOURCES.md)、[命名规则](MODEL_NAMING.md)、[模型维护](MODELS.md) |
| 不入 Git 的图片、预览、缓存及标注 | [外部资源](EXTERNAL_ASSETS.md)、[图片与绑定示例](../examples/external-assets/README.md) |
| 本机鉴权配置与远端模型调用 | [远端 LLM](REMOTE_LLM.md) |
| 凭证扫描、公开范围与第三方许可 | [安全与许可](SECURITY.md) |

## 更新与历史

- [版本规则](VERSIONING.md)区分普通提交、维护版本、标签与交付包；[总更新日志](../CHANGELOG.md)记录维护变更。
- [对应技术说明](technical/README.md)保留日期式功能更新记录；新增专项说明按[功能登记](technical/catalog.json)归档。
- [旧 Git 历史](history/README.md)与[技术原件档案](technical/archive/README.md)用于追溯，不能从中直接重跑旧发布脚本。
- [验收收据](receipts/)只证明所列日期、范围与检查方式；线上是否生效须重新核对实际部署与运行状态。
