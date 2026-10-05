# comfyui

本机 ComfyUI 项目的维护仓库。覆盖**本体源码、生产插件与统一工作台、已保存工作流及子图、提示词资料库、模型依赖清单和维护工具**。

这是今后 **ComfyUI 相关修改的唯一主 Git**，不是 Comfy-Org 官方仓库，也不是装好全部模型的整机镜像。日常开发直接改本仓 `snapshot/runtime/` 对应源码；运行目录只作部署目标。数据库结构、迁移、工作流和提示词资料维护也在本仓登记。

按用户最新决定保留真实提示词库、收藏、备注和历史；公开准备的重点是移除密钥、登录配置及插件缓存。所有发现的工作 Git 的本地可得提交历史已接入主仓；原始含凭证图另作私有档案。**没有配置在线远端、没有上传 GitHub。** 本轮只部署了 9 份凭证外置/安全示例文件及运行根维护路由，没有重启、生图或覆盖数据库；不表示完成了全部功能的冷启动验收。

## 从这里开始

- [项目地图](docs/PROJECT_MAP.md)：每类文件的归属、作用和实际源路径。
- [工作区与唯一来源](docs/WORKSPACE.md)：主 Git、仓外私密/资源、实际运行目录的关系及清理恢复。
- [外部状态组合](docs/EXTERNAL_STATE.md)：私密配置、在线库和大资源的显式引用与隔离组合。
- [日常维护](docs/MAINTENANCE.md)：主仓开发、封装清单、隔离验收、授权部署与打包。
- [历史迁移](docs/history/README.md)：完整图、reflog 补迁、脱敏映射与私有原件。
- [数据库契约](docs/DATABASE.md)：三库结构、虚构测试资料、未来有序迁移入口。
- [外部资源](docs/EXTERNAL_ASSETS.md)：模型/预览放置路径与小型格式样例。
- [恢复与迁移](docs/RESTORE.md)：Git bundle 克隆、离线还原、外部资源和凭证补齐。
- [模型管理](docs/MODELS.md)：本体、编码器、VAE、LoRA、检测器与超分依赖。
- [已知限制](docs/KNOWN_ISSUES.md)：已验收边界和仍未修复的问题。
- [安全与发布](docs/SECURITY.md)：凭证门禁、GitHub 发布前检查与禁止上传项。

## 内容结构

```text
comfyui/
├─ README.md / AGENTS.md / CHANGELOG.md
├─ docs/                      维护、恢复、安全与项目地图
├─ scripts/snapshot.py        只读采集、哈希校验、离线物化
├─ scripts/repository.py      差异审查、接纳快照、Git bundle
├─ scripts/project.py         主仓源码封装与只读部署计划
├─ scripts/security_guard.py  index / 全可达历史凭证与资源门禁
├─ database/                  结构契约、迁移登记与隔离测试资料
├─ examples/external-assets/  一个中性视觉样例、格式与放置表
├─ governance/                运行根 AGENTS 路由的版本化原件
├─ .githooks/ / .github/       本地提交/推送保护与 CI
├─ tests/                     快照工具测试
└─ snapshot/
   ├─ manifest.json          逐文件来源、哈希、分片顺序、服务基线
   ├─ runtime/               保留原相对目录的源码/工作流/生产工具
   ├─ library/json/          提示词库 JSON 的逐字节可逆分片
   ├─ library/sql/           一致 SQLite 备份产生的逻辑 SQL 分片
   ├─ inventory/             模型、预览、依赖、上游与排除项清单
   └─ evidence/              当前 UI、工作流发布与真实推理验收记录
```

模型权重、约 23 GB 的提示词预览媒体、Python/CUDA 二进制、日志、生成图和密钥**不包含在 Git 中**。权重及预览清单不等于文件备份，换机器必须另行保存这些原目录。

提示词正文、分类、ID、收藏、备注、关联与历史数据库是本轮快照的实质内容，不是只列清单。JSON 分片合并后可恢复原始字节；SQLite 从在线备份导出，恢复后校验表行数与完整逻辑 SQL 哈希，不直接拷贝运行中的 WAL 数据库。

## 快速检查

在仓库目录执行（下面的 Python 路径适用于当前安装位置）：

```powershell
& ..\..\python\python.exe -X utf8 -B scripts\snapshot.py verify
& ..\..\python\python.exe -X utf8 -B -m unittest discover -s tests -v
& ..\..\python\python.exe -X utf8 -B database\tools\contract.py check --against-snapshot
& ..\..\python\python.exe -X utf8 -B scripts\security_guard.py --all-history
git config --local core.hooksPath .githooks
git config --local core.longpaths true
git status --short
```

首次 clone 后需自己启用 hooks（Git 不会自动执行仓库脚本）。最新整理见 [工作区整理验收](docs/ACCEPTANCE_WORKSPACE.md)；[统一主仓 v2](docs/ACCEPTANCE_V2.md) 与 [首版验收](docs/ACCEPTANCE.md)保留为历史证据，旧 `comfyui.bundle` 不可公开。不要执行快照中写死旧日期、旧 PID 的历史发布/回滚脚本；也不要整目录上传运行根、仓外根、`maintenance` 或复制本机 `.git` 公开。
