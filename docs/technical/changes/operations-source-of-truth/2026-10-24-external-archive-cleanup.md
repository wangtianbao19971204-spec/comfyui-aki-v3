# 仓外历史归档永久退役与恢复说明修正

2026-10-24。用户在明确选择后授权**永久删除、无归档、无备份**：外部私有资料根中的 2026-09-28 历史工作流快照归档 payload、TAG_INTEGRATION 旧 LLM 权重、Colab-ni 验证证据等 15 个目标，共 **2,426 文件 / 94,571,215,064 B（94.58 GB）**。本仓库本次提交只修正文档与补收据，不触碰运行区、服务、模型或该外部根。

## 变更

- `production_tools/README.md`：移除“207 个旧快照已可恢复归档”的现行说法，改为已永久删除、仅外部收据保留元数据与 SHA-256 清单，`resource_archive.py` 的 verify/restore 不再可用。
- `production_tools/资源维护入口.md`：入口表“恢复历史快照”行改为“历史快照归档（已退役）”并指向外部收据。
- `production_tools/项目使用指南.md`：启动与维护段同步改为不可再从该路径还原。
- 新增[仓外归档收据](../../receipts/external_archive_cleanup_20261024.json)与 `CHANGELOG` 条目；其余日期式历史文字不改写。

## 授权、范围与证据

- 授权：用户选择清理 2026-09-28 旧快照归档与旧 LLM 权重，并“一并清理” validation/receipts 中的 Colab-ni Anima 训练证据；明确为永久删除、无备份。
- 删除目标（外部根相对路径）：TAG_INTEGRATION 下 5 个旧权重目录、`_archives/2026-09-28_workflow_cleanup`、Colab-ni 8 个验证目录、`receipts/ni-colab-download-cleanup-20261015`，共 15 项。
- 仓外收据 `external-private-receipts/comfyui-local-cleanup-20261024`：manifest.json `4d9c996f…`、VERIFIED.json `02f8fe6d…`、DELETION_RESULT.json `97767949…`；保留 1,536 个元数据文件 / 28,389,998 B（2026-09-28 的 manifest/operations/README、ni-colab 小 JSON/脚本、colab-ni json/md/txt/log ≤1 MB）。
- 磁盘：G: 可用 258,892,402,688 B → 353,468,731,392 B，实际释放 94,576,328,704 B（94.58 GB）。清理后外部资料根约 **101.03 GB**（archives 26.45、validation 56.76、receipts 15.73、releases 1.69、staging 0.37，其余 <0.1）。
- 保留：TAG_INTEGRATION sources 根标签/文本 CSV 与许可证、retired Git、release bundles、manifests/plans/private-config、`2026-09-30_lora_duplicates` 归档及外部收据本身。

## 验证与边界

- 仓外 VERIFIED：15 个目标全部不存在、2,426 文件/字节数与 manifest 吻合、服务操作 false；文件级摘要见外部收据。
- 本 PR 仅仓内文档+收据：`project.py seal` 只更新三份生产工具说明的源码身份并标记未部署；未写运行区、未重启/清队列/生图、未改模型。
- 限制：该归档无法再用 `resource_archive.py` 验证或还原；repo 中带日期的历史说明保留原样，不据此认为当前仍可恢复。
