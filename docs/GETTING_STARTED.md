# 首次取得主仓与后续更新

本页面向 Windows PowerShell。准备 Git for Windows、带 `sqlite3` 的 Python 3.10+，以及较短、可写的本地路径，例如 `C:\c\comfyui`。这些工具足以检查与物化主仓；启动所需的 Torch/CUDA、插件依赖、模型和配置另见[恢复与迁移](RESTORE.md)。

## 1. 取得主仓

当前未配置在线远端，也没有已发布的 GitHub 地址。取得真实、已审查的主仓 URL 后，在父目录执行；占位值必须先替换，目标目录必须全新：

```powershell
$comfyRepositoryUrl = '<实际已审查的主仓URL>'
git clone -c core.longpaths=true -- $comfyRepositoryUrl .\comfyui
if ($LASTEXITCODE -ne 0) { throw 'Clone failed; retain the partial directory for inspection' }
Set-Location -LiteralPath .\comfyui
```

2026-10-06 的完整克隆实测约 633 MiB Git 对象包，加上 1.46 GiB 检出文件；建议先留至少 3 GiB 空间，物化运行树与外部模型/图片另算。大小来自源码、资料分片和保留历史，未包含用户模型或 LoRA 权重；后续大小随内容增长。

Windows 长路径选项须在第一次检出前传给 clone。别人的机器可以把这份克隆作为该机唯一开发来源；同一台机器的主仓仍只有一个。仅用于本机验收的副本放到仓外 validation，不在其中开发；下面采用独立对象复制：

```powershell
$comfyLocalSource = '<本机唯一主仓的绝对路径>'
$comfyValidationClone = '<全新的仓外validation目录>'
git clone --no-local -c core.longpaths=true -- $comfyLocalSource $comfyValidationClone
if ($LASTEXITCODE -ne 0) { throw 'Validation clone failed' }
```

收到离线 bundle 时，先按[随包回执与 SHA 校验流程](RESTORE.md)核验再克隆到新目录；包名或标签不能证明它覆盖最新提交。bundle 克隆的 origin 是本地包路径，不是在线更新地址。

## 2. 选择 Python，启用提交检查

以下在克隆后的仓根执行。选择实际安装的解释器；原机器也可明确指定 `G:\ComfyUI-aki-v3\python\python.exe`，其他机器使用自己的路径：

```powershell
$comfyPython = (Get-Command python -CommandType Application -ErrorAction Stop).Source
# 若 python 不在 PATH，改用自己的完整路径，例如：
# $comfyPython = 'C:\Python311\python.exe'
& $comfyPython -c "import sys, sqlite3; assert sys.version_info >= (3, 10); print(sys.executable, sys.version.split()[0], sqlite3.sqlite_version)"
if ($LASTEXITCODE -ne 0) { throw 'A working Python 3.10+ with sqlite3 is required' }
$env:COMFYUI_MAINTENANCE_PYTHON = $comfyPython
git config --local core.hooksPath .githooks
git config --local core.longpaths true
```

`COMFYUI_MAINTENANCE_PYTHON` 只接受单个解释器 exe 路径，不能填 `py -3` 等带参数的命令串。变量只在当前终端会话生效，新终端需重新选择。hooks 未获指定时依次尝试 `../../python/python.exe`、`python3`、`python`。

新克隆不继承原仓的 repo-local hooks 设置、维护作者身份或备份索引。需要提交时配置自己的本仓作者，不修改全局身份：

```powershell
git config --local user.name '<你的维护姓名>'
git config --local user.email '<你的提交邮箱>'
```

## 3. 检查仓库，再恢复运行环境

```powershell
& $comfyPython -X utf8 -B scripts\maintain.py status
if ($LASTEXITCODE -ne 0) { throw 'Status check failed' }
& $comfyPython -X utf8 -B scripts\technical_catalog.py check --require-tracked
if ($LASTEXITCODE -ne 0) { throw 'Feature catalogue check failed' }
& $comfyPython -X utf8 -B scripts\model_sources.py check
if ($LASTEXITCODE -ne 0) { throw 'Model source catalogue check failed' }
# 读取快照内容并核对哈希，比前两项耗时更长：
& $comfyPython -X utf8 -B scripts\snapshot.py verify
if ($LASTEXITCODE -ne 0) { throw 'Snapshot verification failed' }
```

新机器显示“备份未登记”或“运行状态未实测”是正常边界，不表示克隆损坏。检查失败时保留输出和当前提交，核对检出是否完整，不用 `seal` 重新认可损坏字节。公开或打包还须通过[全历史安全与许可检查](SECURITY.md)。

不要直接运行 `snapshot/runtime/ComfyUI/main.py` 或快照中的启动脚本：库资料仍在 `snapshot/library/` 分片，模型与本机配置也未随克隆提供。先按[恢复方法](RESTORE.md)物化到全新运行目录，再补齐资源、依赖和配置，用独立端口及隔离数据验收。正式运行目录只接收明确范围的部署。

模型与 LoRA 的补齐入口是[下载来源清单](MODEL_SOURCES.md)，优先查看正式 UAP v2 所需资源，再按自己的工作分支补齐其他资源。记录包含本地相对路径、来源版本和原文件名；网站改名或一个版本提供多种精度时，按文件 ID／声明摘要选择，不能只下载同名最新版本。自训、来源待补和目录配套的处理见[模型维护](MODELS.md)。

## 4. 后续取得主仓更新

仅在该机唯一主仓执行，先确认 origin 是实际已审查的在线主仓。若仍是本地 bundle 或验证源，使用新的已验收 bundle 与回执在新目录校验，不把它冒充在线更新。

有本地修改时，先按[日常维护](MAINTENANCE.md)精确暂存、检查并提交本次范围，或单独保存改动和未跟踪文件；不自动 stash 或 hard reset。干净 `main` 的在线更新如下：

```powershell
$comfyBranch = git branch --show-current
if ($LASTEXITCODE -ne 0 -or $comfyBranch -ne 'main') { throw 'Update requires the reviewed main branch' }
$comfyPendingChanges = git status --porcelain --untracked-files=normal
if ($LASTEXITCODE -ne 0 -or $comfyPendingChanges) { throw 'Preserve local changes before updating' }
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'Fetch failed; review the remote and connection' }
git log --oneline --max-count=20 HEAD..origin/main
git merge --ff-only origin/main
if ($LASTEXITCODE -ne 0) { throw 'Branches diverged or update failed; review both histories' }
```

完成后重跑第 3 节检查。分叉时保留两边提交并单独评审，不强制覆盖。主仓更新不自动部署；插件上游更新也先导入主仓评审，不在运行插件目录另行 clone/pull。

## 5. 换机器与常见问题

| 遇到的问题 | 下一步 |
|---|---|
| `python` 不存在、跳转 Microsoft Store 或缺 `sqlite3` | 改用已安装 Python 的完整 exe 路径，重新执行解释器检查并设置 hooks 环境变量 |
| `Filename too long` | 用短父目录与初次 clone 的 `core.longpaths=true`；保留失败目录，在另一新目录重试 |
| hooks 找不到解释器，或提示 Git 作者身份缺失 | 按第 2 节设置当前终端变量和 repo-local 身份，先运行 `maintain.py check-staged` |
| 缺模型、预览、配置或前端/插件依赖 | 按[资源样例](EXTERNAL_ASSETS.md)、[外部状态](EXTERNAL_STATE.md)与[恢复方法](RESTORE.md)补齐；清单不是资源副本 |
| 换运行根后 adopt 报 `Different runtime root` | 当前要求 candidate 与现有 manifest 的 `source_root` 相同；`--purpose recovery-migration` 也不豁免。保留候选另行评审迁移，不手改 manifest 绕过 |

另一台机器可在自己的主仓修改源码、`seal` 并用显式 `deploy-plan --runtime <实际运行根>` 比较；不同运行根的现场 capture/adopt 目前没有自动迁移入口。离线物化、源码维护、线上部署与完整环境迁移分别验收，详见[工作区边界](WORKSPACE.md)。

## 更新记录

- 2026-10-06：补首次克隆、Python/hooks、快慢检查与后续更新步骤；区分主仓和验证副本，说明新包回执、仓外资源及跨运行根 capture/adopt 的现行限制。未配置远端、下载模型、安装依赖或启动服务。
