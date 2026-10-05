# comfyui

本机 ComfyUI 项目的维护仓库。覆盖**本体源码、生产插件与统一工作台、已保存工作流及子图、提示词资料库、模型依赖清单和维护工具**。

这是本地私人维护基线，不是 Comfy-Org 官方仓库，也不是已经安装好模型的整机镜像。没有配置远端、没有上传 GitHub。原运行目录和原有嵌套 Git 历史均未替换。

## 从这里开始

- [项目地图](docs/PROJECT_MAP.md)：每类文件的归属、作用和实际源路径。
- [日常维护](docs/MAINTENANCE.md)：检查、捕获、比较、接纳新版本、提交与打包。
- [恢复与迁移](docs/RESTORE.md)：Git bundle 克隆、离线还原、外部资源和凭证补齐。
- [模型管理](docs/MODELS.md)：本体、编码器、VAE、LoRA、检测器与超分依赖。
- [已知限制](docs/KNOWN_ISSUES.md)：已验收边界和仍未修复的问题。
- [安全与授权](docs/SECURITY.md)：哪些内容不能进 Git、何时不能公开仓库。

## 内容结构

```text
comfyui/
├─ README.md / AGENTS.md / CHANGELOG.md
├─ docs/                      维护、恢复、安全与项目地图
├─ scripts/snapshot.py        只读采集、哈希校验、离线物化
├─ scripts/repository.py      差异审查、接纳快照、Git bundle
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
git status --short
```

详细交付数量、提交和 bundle 位置见 [首版验收](docs/ACCEPTANCE.md)。后续不要直接执行 snapshot 中写死旧日期、旧 PID 的历史发布/回滚脚本。
