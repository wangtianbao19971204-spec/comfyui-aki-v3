# Aki ComfyUI 工作台

这是一套基于 **ComfyUI 的本地图像生成与提示词管理工作环境**，主要用于动漫图像创作。它把提示词资料库、模型与 LoRA 选择、网页提示词导入，以及生成、编辑和后处理流程放到统一工作台中。

这个仓库保存我们维护的 ComfyUI 本体、插件、工作流、提示词正文和维护工具，供日常开发、换机迁移，以及其他使用者搭建自己的环境。

## 能用它做什么

| 功能 | 用途与详情 |
|---|---|
| 提示词资料管理 | 检索 Tag、翻译和提示词，复用个人资料与随机模板；[资料库说明](docs/technical/library/README.md) |
| 统一绘图工作台 | 编辑正负提示词、选择模型与 LoRA、提交任务和查看结果；[工作台说明](docs/technical/runtime/workbench.md) |
| 生成与图像处理 | Anima、Anima 2.9B、Krea2 生成／编辑，以及裁剪精修、抠图、扩图和超分；[工作流说明](docs/technical/runtime/workflows.md) |
| 网页提示词导入 | 配套油猴脚本从支持的网站提取标签／提示词，发送到工作台待采用区；[安装与使用](docs/technical/runtime/browser-import.md) |
| 角色 LoRA 制作 | 附带角色数据集整理及 Anima LoRA 训练工具；[训练工具说明](docs/technical/training/README.md) |

## 第一次怎么拉取

准备 **Git for Windows** 和带 `sqlite3` 的 **Python 3.10+（建议 3.11 及以上）**。仓库当前私有，先取得访问权限，首次访问时按 Git 的提示登录有权限的 GitHub 账号。

在准备保存项目的父目录打开 PowerShell，路径尽量短，例如 `C:\c`。下面会新建 `comfyui` 目录，该目录须尚不存在：

```powershell
git clone -c core.longpaths=true --branch main -- https://github.com/wangtianbao19971204-spec/comfyui-aki-v3.git .\comfyui
if ($LASTEXITCODE -ne 0) { throw '拉取失败，请检查网络与仓库权限，并保留错误输出' }
Set-Location -LiteralPath .\comfyui
```

首次拉取建议预留至少 **4 GB** 仓库空间；已有网络克隆验收的检出文件约 **1.74 GB**，模型、图片和运行依赖的空间另算。出现 `Repository not found`／404 时，先检查账号权限；不要把令牌写进下载地址。

拉取后，在仓库根目录选择本机 Python 并检查文件是否完整：

```powershell
$comfyPython = (Get-Command python -CommandType Application -ErrorAction Stop).Source
& $comfyPython -X utf8 -B -c "import sys, sqlite3; assert sys.version_info >= (3, 10); print(sys.executable, sys.version.split()[0])"
if ($LASTEXITCODE -ne 0) { throw '请按开始使用指南选择有效的 Python' }
& $comfyPython -X utf8 -B scripts\maintain.py status
if ($LASTEXITCODE -ne 0) { throw '仓库状态检查失败' }
& $comfyPython -X utf8 -B scripts\snapshot.py verify
if ($LASTEXITCODE -ne 0) { throw '文件校验失败，请保留输出检查' }
```

`verify` 返回 `pass: true` 表示清单管理的文件完整。Python 找不到、长路径、提交检查和后续更新的方法见[开始使用](docs/GETTING_STARTED.md)。

## 拉取后怎么运行

**Git 保存源码和文字资料；完整运行实例还需要自己的环境与私有资源。** 模型／LoRA 权重、图片原图、认证配置和 Python／CUDA 环境没有随 Git 上传。

1. 按[恢复指南](docs/RESTORE.md)把源码和提示词资料还原到一个全新的运行目录。`snapshot/runtime/` 是维护副本，不直接在其中启动 ComfyUI。
2. 按[模型来源清单](docs/MODEL_SOURCES.md)补确切版本的底模、LoRA 和配套文件；按[外部资源说明](docs/EXTERNAL_ASSETS.md)补图片与预览。
3. 准备运行依赖和自己的配置，参考[私有状态示例](examples/private-state/README.md)记录资源位置；在独立端口、隔离数据下完成启动与工作流验收后，再切换正式使用。

第一次搭建不需要寻找旧版离线 bundle。详细安装边界、已验证范围与遗留问题见[恢复指南](docs/RESTORE.md)和[已知问题](docs/KNOWN_ISSUES.md)。

## 文件放在哪里

```text
comfyui/
├─ snapshot/
│  ├─ runtime/       ComfyUI、插件、工作流及运行／训练工具源码
│  ├─ library/       提示词、Tag、SQL 分片和随机模板
│  ├─ inventory/     模型来源、环境和媒体登记
│  └─ evidence/      历史验收记录
├─ database/         数据库结构、恢复契约和样例
├─ scripts/          主仓维护与校验工具
├─ tests/            维护工具的隔离测试
├─ examples/         配置、外部资源及标注格式示例
├─ docs/             使用、恢复、维护和技术说明
├─ governance/       版本与保留规则
├─ .githooks/        本地提交和上传检查
├─ .github/          GitHub 检查配置
├─ AGENTS.md         AI 与维护者的共同规则
└─ CHANGELOG.md      更新记录
```

具体源码位置与各目录自述见[项目地图](docs/PROJECT_MAP.md)、[快照说明](docs/SNAPSHOT.md)和[文档导航](docs/README.md)。

## 后续更新与维护

代码、插件、工作流和资料维护都从这个主 Git 开始：本地分支修改 → 测试与检查 → 上传分支并创建 PR → 用户允许合并 → 同步本地 `main`。具体命令见[日常维护](docs/MAINTENANCE.md)；Git 更新与运行目录部署分别处理。

接手开发或交给 AI 维护时，先读 [AGENTS.md](AGENTS.md)，再按[技术目录](docs/technical/README.md)查实现、测试、示例和对应更新记录。公开范围与第三方许可见[安全说明](docs/SECURITY.md)。
