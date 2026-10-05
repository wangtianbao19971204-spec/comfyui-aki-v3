# 维护版本、技术更新与发布

文档修订：2026-10-05.1。

## 版本角色

项目维护包使用独立 SemVer；不改 ComfyUI 本体、节点包、模型、资料发布和训练检查点各自版本。版本状态由 [version.json](../../../governance/version.json)登记，机制与命令见 [VERSIONING](../../VERSIONING.md)。旧日期式维护标签保持历史原义，不伪造当时不存在的版本。

普通开发记录 Unreleased 和功能短技术更新；显式准备发布时才按 patch/minor/major 自动计算下一个编号。准备说明、提交、打本地标签、打包、部署及在线验收是不同操作，不自动提交或推送。

## 实现与门禁

[release.py](../../../scripts/release.py)绑定预期 HEAD/版本、受审查发布说明和回滚材料；本地标签需另行显式执行，并通过完整快照、历史凭证及 Git 完整性门禁。[repository.py](../../../scripts/repository.py)生成经过完整历史检查的 bundle。

[technical_catalog.py](../../../scripts/technical_catalog.py)检查技术入口、实现/测试/证据与链接；提交时按最具体源码归属要求功能说明同步更新。全局 CHANGELOG 不替代单项功能文档。

归档目录与来源登记必须成对，445 份原件及固定 README 在工作树/暂存区分别校验精确清单、哈希和普通文件属性。打包入口与暂存/历史扫描共用训练触发词的窄审核逻辑，未提交登记不能批准发行载荷。

本地 pre-commit 对真实 index 检查对应功能说明，pre-push 检查已跟踪目录完整性，然后继续凭证门禁；CI 也检查已跟踪实现与文档链接。新 clone 必须显式启用 hooks；这些本地约定不等于 GitHub 受保护分支，管理员仍可绕过。

## 验证与回退

[test_release.py](../../../tests/test_release.py)和 [test_technical_catalog.py](../../../tests/test_technical_catalog.py)只使用临时仓验证行为。发布前仍须实际对应 commit 的测试与安全结果，不能沿用旧 179 项测试充当新增机制验收。

回滚记录区分 Git 恢复与生产恢复。引用旧 tag/commit 不授权 hard reset；生产恢复必须匹配同批源哈希、当前队列/服务、数据库状态和原件。未验收并行改动不能混入发布包。

## 更新记录

- 2026-10-05：增加独立维护版本、显式自动递增准备、本地标签门禁、回滚引用与功能文档检查；真实发布状态以版本文件和 tag 回执为准。
