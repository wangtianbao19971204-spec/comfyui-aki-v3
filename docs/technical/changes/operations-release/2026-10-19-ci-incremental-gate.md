# CI 拆分快检与增量历史门禁

日期：2026-10-19。

`Maintenance integrity` 原来把单测、快照、契约、两个目录检查和全历史凭证门禁放在同一个 job 里，任何一步慢都拖住整个检查。本轮按[可移植增量门禁](../operations-source-of-truth/2026-10-19-incremental-history-gate.md)拆分：

- `verify` job 保留原有五项检查，`timeout-minutes` 收到 30；历史门禁改为 `needs: verify` 的独立 `history` job，上限提到 90 分钟。
- `history` 在推送和 PR 上用 `--all-history --cache-file … --incremental`，缓存用 `actions/cache/restore`／`save` 存取 `runner.temp` 下的 11.1 MB 元数据文件，key 以仓库名与提交为前缀并允许按前缀还原。
- 缓存只在 `push` 成功后保存；`pull_request` 只还原、从不写入，避免 PR 侧污染缓存。
- 新增每周 `schedule`（周日 18:17 UTC）与 `workflow_dispatch` 的 `full_history_scan` 布尔输入，两者都跑不带缓存参数的完整扫描，作为与缓存无关的独立复核。
- 增加 `concurrency`：同 ref 的新推送取消过期运行（只在 PR 上启用取消）；凭证门禁报告作为 artifact 保留 14 天。

未改动的边界：仍是 `fetch-depth: 0` 的完整 clone，checks 名称与 `verify` 保持一致；不新增 secret、不申请写权限，`permissions` 仍只有 `contents: read`。本记录不代表远端分支保护或必需检查已配置。
