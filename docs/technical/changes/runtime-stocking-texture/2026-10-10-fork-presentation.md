# Fork 首页与改动说明

日期：2026-10-10。只调整上游导出文档与 fork 展示，不修改插件算法、界面实现、工作流内容或生产部署。

公开 fork 的默认首页此前显示原版 `main`，ComfyUI 接入说明仅附在分支 README 末尾，审查者难以发现改动。本轮给中英 README 前置简短接入说明，列出功能、安装/工作流入口、固定基线差异、实现入口和有边界的验证结果。AI 编写披露、原作者归属及 MIT 许可置于首页；完整原 README 留在后方，原版演示图片明确标为原作者演示。

唯一维护入口为 `snapshot/runtime/production_tools/stocking_fork_intro.md`、`stocking_fork_intro.en.md` 和 `stocking_upstream_README.md`，由 `export_stocking_upstream.py` 生成公开 README，不在投稿检出另行开发。导出仍为 38 个允许文件；与前一提案相比，仅根目录两份 README 和接入 README 内容变化。导出器既有合同增加“完整原 README 仍保留”的校验，另检查全部本地文档链接及导出清单。

本轮导出器 3 项合同通过；实际导出检查 66 个本地链接均存在，根目录两份 README 完整保留固定上游原文，35 个非 README 导出文件与前一投稿逐字节相同。原始结果位于仓外 `stocking-fork-presentation-20261010-01/DOCUMENT-CHECK.json`。

GitHub 展示范围限 `wangtianbao19971204-spec/stocking-texture-tool` 的简介、文档链接与默认展示分支 `feat/comfyui-integration`。这是自有 fork 的展示设置，不更改上游仓库或其 `main`，也不改变维护主仓默认分支。完成上传及 API 回读后，远端状态保存在仓外本轮交付收据；本说明本身不作为已上传证明。

实际已上传提交 `fa5819d650382d9d93440d4781947908e3770fe9`，GitHub 默认分支已切到接入分支，简介与文档链接更新。未指定 ref 的内容 API 读取三份 README，其 SHA256 与审核载荷一致。公开投稿检出的暂存区与完整可达历史扫描均为零发现；交付摘要见[收据](../../../receipts/stocking_fork_presentation_20261010.json)。

40 项 Python、17 项前端、18 组弯腿、此前 51 项 HTTP/54 组真实图与原版 114 通过/51 跳过，均引用上一轮已记录验收，未因文字更新重新记为新跑。上游 PR 仍未创建：先前 POST 被 GitHub 令牌权限拒绝，本轮先完善 fork 供审查，不扩大令牌权限。

回退可恢复前一公开分支提交与仓外保存的 GitHub 展示设置；不覆盖原图、模型、用户数据或生产实例。
