# 本地提交与上传检查

这里的 hooks 在 Git 提交或上传前运行主仓维护检查。新 clone 必须在该仓启用它们，设置方法见[开始使用](../docs/GETTING_STARTED.md)。

| 文件 | 做什么 |
|---|---|
| [pre-commit](pre-commit) | 检查真实暂存区的功能说明、文件与凭据 |
| [pre-push](pre-push) | 检查已跟踪技术入口和全部可达历史的上传载荷 |
| [run](run) | 选择解释器并调用对应工具；支持 `COMFYUI_MAINTENANCE_PYTHON` |

hook 失败先处理具体问题，不跳过检查。暂存快检只在严格条件下复用本地扫描缓存，上传仍检查完整历史。

本地 hooks 不代表 GitHub 已设置服务器保护，也不负责合并、部署或恢复运行数据。

维护细节：[安全门禁](../docs/SECURITY.md) · [日常流程](../docs/MAINTENANCE.md) · [发布技术说明](../docs/technical/operations/release.md)。
