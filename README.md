# comfyui

ComfyUI 相关源码、工作流/子图、提示词资料检查点和维护工具的**唯一开发主仓**。在本仓修改、验证和提交；运行目录只接收明确范围的部署。仓外资料保管密钥、大资源和最新运行数据。

第一次取得仓库、换机器或后续拉取更新，先看[开始使用](docs/GETTING_STARTED.md)：选择本机 Python、启用 hooks、核对完整性，并区分代码更新与运行环境恢复。

今后采用**本地分支开发 → 本地测试/验收通过 → 上传 GitHub 分支并创建 PR → 用户允许合并**的流程。通过门禁后可直接上传日常分支；助手不自行合并或启用自动合并，`main` 由已获用户批准的 PR 更新。步骤和首次空仓基线边界见[日常维护](docs/MAINTENANCE.md)。

换机器补模型与 LoRA，从[下载来源清单](docs/MODEL_SOURCES.md)逐项查看网址、版本、上游原文件名与现行 `current_path`；按[分类命名规则](docs/MODEL_NAMING.md)放入加载器目录内的家族／用途子目录。[模型维护](docs/MODELS.md)说明怎样核验及以后补记录。网上资源按确切版本重新获取并使用规范本地名，自训资源另备份原权重。

2026-10-07 的[最终全流程验收](docs/receipts/final_workflow_acceptance_20261007.json)区分结构／回归、真实运行和画质：本轮修复已按 27 文件部署，仍保留 Krea2 运行状态、扩图接缝及旧 SAM 编辑 UI 等限制，不能将取得仓库视作全项画质通过。

随后完成[未通过项核验](docs/receipts/workflow_failure_verification_20261007.json)：Krea2 三组显存对照及原顺序复跑未复现黑图，显存溢出根因仍未证实；手误动脚定位为检测器误检，脸眼正例局部效果通过。扩图接缝、旧 SAM 编辑器及区域有命中画质仍未通过或未覆盖；正式工作流、模板与资料保持。

## 日常只看四个入口

| 要做什么 | 从哪里开始 |
|---|---|
| 看当前提交、未提交改动和本地版本标签 | [维护入口](scripts/maintain.py)：运行下面的 `status` |
| 找一项功能的代码、测试与技术说明 | [功能地图](docs/technical/README.md) |
| 修改、检查、提交和按范围部署 | [日常维护](docs/MAINTENANCE.md) |
| 回退、换机器与补齐外部资源 | [恢复方法](docs/RESTORE.md) |

在本仓目录运行；先按[开始使用](docs/GETTING_STARTED.md)选择并核验本机 Python 3.10+，将完整解释器路径保存在当前终端的 `$comfyPython`：

```powershell
# 快速看现在；不扫描整库、不访问在线服务
& $comfyPython -X utf8 -B scripts\maintain.py status

# 只看我们自己的主线，不展开旧组件的全部历史
& $comfyPython -X utf8 -B scripts\maintain.py history

# 精确 git add 本次文件后，检查真正暂存的字节
& $comfyPython -X utf8 -B scripts\maintain.py check-staged
```

首次 clone 要按开始使用页启用 hooks；这些本仓设置不会从原机器继承。普通开发不会自动加版本、打标签或部署；正式发布按 [版本规则](docs/VERSIONING.md) 执行。状态命令区分“有本地标签”“有未提交修改”和“运行状态未实测”，不把任一项当成全部完成。

备份状态由本机登记的仓外回执索引提供，登记方法见 [日常维护](docs/MAINTENANCE.md)。快速查询核验回执链及文件存在/大小，不读取私密配置正文、不重算大型有效载荷哈希；历史备份与当前提交/未提交修改的覆盖情况分别显示。

## 保持三个边界

- **主仓**：源码在 `snapshot/runtime/`，结构与迁移在 `database/`，受审查资料导出在 `snapshot/library/`。真实提示词、收藏、备注与历史可保留，不手工改资料分片。
- **运行区**：部署代码、环境、模型及应用最新数据。旧 Git 已退休，不能继续从运行插件目录开发或一键拉取覆盖；旧 SQL 检查点不能覆盖更新的在线库。
- **仓外资料**：密钥、模型、预览原图、训练集、原始 Git 和回滚材料。路径引用不是备份，同盘归档不是异盘灾备；当前备份保留规则不执行自动清理。

详细归属见 [工作区](docs/WORKSPACE.md) 和 [外部状态](docs/EXTERNAL_STATE.md)。用户模型、预览与缓存只有清单/格式及标注样例；上游源码自带的界面图片和示例媒体另有许可边界。clone 本仓不等于装好了完整运行环境；现有功能限制见 [已知问题](docs/KNOWN_ISSUES.md)。

18 项功能均在 [技术目录](docs/technical/catalog.json) 登记独立说明、示例入口和日期式维护记录；提交门禁检查这些文件实际存在于待提交内容。五站网页提示词桥接的安装/更新与验收边界见 [网页接入工作台](docs/technical/runtime/browser-import.md)。再次核验唯一 Git、现行实例组合与公开边界的结果见 [2026-10-06 复核](docs/receipts/reassurance_20261006.json)。

首次上传内容复核补齐了 900 份遗漏插件源码／支持文件、Gallery 独立词典 SQL、两份随机模板及旧选择器正文／编辑历史检查点。核心六份资料文件与三库原本完整；运行 DB 的页面体积、SQL 导出大小与 Git 压缩传输大小不同。精确保留范围、现行全文索引不一致及隔离重建边界见 [2026-10-07 内容复核](docs/receipts/github_content_reconciliation_20261007.json)；补齐保存在本地功能分支，首次上传与合并仍等用户核对。

## 历史需要时再看

[旧 Git 迁移](docs/history/README.md)和 [445 份技术原件](docs/technical/archive/README.md)保留追溯，不是另一套开发入口。日常更新对应功能的现行说明及短记录，不为每次小改动复制一套文档；历史脚本不可直接重跑。

[技术覆盖复核](docs/ACCEPTANCE_TECHNICAL.md)保留建仓时的历史基线；后续支持文件补齐见[源码覆盖验收](docs/receipts/source_coverage_20261005.json)。当前代码、最后本地版本和未提交改动以 `maintain.py status` 为准。交付包是否覆盖该版本、是否通过隔离还原，须核对[恢复方法](docs/RESTORE.md)说明的随包交付回执，不能由标签或旧包推断。

正式分发必须通过[安全与许可检查](docs/SECURITY.md)，不能公开复制本机 `.git`、运行根或私密档案。已创建 [GitHub 私有仓](https://github.com/wangtianbao19971204-spec/comfyui-aki-v3)；2026-10-07 当前阶段为空仓，尚未首次上传，本地也尚未配置在线远端。流程约定不等于远端保护已经生效。
