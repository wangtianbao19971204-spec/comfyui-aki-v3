# 历史迁移与公开基线

这个目录只包含可公开的提交映射、校验结果和迁移说明；不包含原始 `.git`、reflog 内容、私有配置或任何凭证原值。

- [完整说明](PUBLIC_HISTORY_IMPORT_NOTES.md)：哪些历史保留、为什么少量 SHA 必须变化，以及原签名如何归档。
- `core-public-map.json` / `workbench-public-map.json` / `main-public-map.json`：全部原提交及 refs 到公开提交的映射。
- `*-public-verify.json`：逐提交元数据、消息、父节点顺序与变化树核验。
- `core-archive-receipt.json`：已构造的历史聚合节点与覆盖证明。

## 更换主仓 Git 数据库，保留工作树

活动维护仓不能只重指向 `main` 后就沿用旧对象库，因为旧凭证仍可能留在其他 refs、reflogs 或不可达 objects 内。已选定的迁移路径是：

1. 完整私有备份旧主仓 `.git`，核对每个文件的 SHA-256；保留旧 refs、objects、reflogs 供恢复，不上传这些材料。
2. 从已脱敏的本地 `public-main.git` 镜像，使用 `git clone --no-checkout --no-hardlinks` 克隆到**新的空 staging 目录**；不 checkout 文件、不共享硬链接对象。
3. 在 staging 仅运行 `git read-tree HEAD` 建立新 index，校验根提交、脱敏对象、tag 以及对象库安全门禁。删除 clone 自动生成的本地 `origin` 配置，避免把临时镜像当日后的 GitHub 远端。
4. 核实所有路径和工作树变更后，将当前维护仓旧 `.git` **可恢复移动**到仓外私有归档，再把 staging 的干净 `.git` 移入维护仓。工作树文件一律不移动、不 checkout、不 reset，现有未提交的代码和文档保留。
5. 从下面的安全聚合分支接入全部 legacy 历史，提交本轮维护变更，再执行最终全历史凭证扫描、对象大小门禁、快照校验和 bundle 克隆复验。

以上步骤只作用于 `maintenance/comfyui` 的 Git 数据库；不替换生产运行目录、工作流、数据库、模型或服务。迁移操作的具体完成状态以最终交付回执为准，本页不是“已替换活动主仓”的证明。

## 已准备的安全历史入口

Core 聚合入口：`e67e9981220834adb7c2921d669251c3e58d7071`，位于隔离镜像的 `refs/heads/history-archive`。它使用空 tree，13 个说明性聚合提交覆盖全部 754 个 tips，单提交最多 64 个 parents；共可达 10,857 个提交，其中原公开 legacy commits 为 10,844 个。

Workbench 安全入口：`cc3bc63d55843f94b79f4e16042e03eccbfcc56e`，可达 2 个原始提交。Core 的 197 个原 tags 使用 `legacy/core/tags/*` 前缀导入，唯一 annotated tag 对象保持原 SHA。

在已切换到安全对象库的维护仓内，以下命令只从本地安全镜像导入，不联网：

```powershell
git fetch --no-tags ./local/history-audit/public-core.git refs/heads/history-archive:refs/import/core-history 'refs/tags/*:refs/tags/legacy/core/tags/*'
git fetch --no-tags ./local/history-audit/public-workbench.git refs/heads/master:refs/import/workbench-history
```

接入时使用保留当前维护 tree 的 `ours` 合并策略，且明确允许不相关历史；不要把旧 Core 空树或旧 Workbench 工作树覆盖当前文件。两个 `refs/import/*` 是临时引用，不是日常开发分支。删除它们前必须验证两个入口均为 `main` 的祖先。最终日常开发分支仍为 `main`，没有把 757 个旧远端分支放进工作分支列表。

映射结构验证在聚合前完成；`history_migration.py verify` 的“全部可达对象恰好等于映射集合”门禁适用于未追加聚合节点的隔离镜像。聚合后的额外 13 个提交由 `core-archive-receipt.json` 单独记录，最终发布仍需扫描最终整个可达历史。
