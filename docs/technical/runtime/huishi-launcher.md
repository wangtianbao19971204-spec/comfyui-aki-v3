# 绘世原图形界面与唯一主仓

文档修订：2026-10-09，隔离验收通过，尚未部署。

## 为什么需要适配

绘世通过运行本体的 `.git` 识别 ComfyUI。旧 Git 退休后，它会显示版本信息缺失。适配保留原图形界面、显存／设备／预览选项和管理页面，将版本读取映射到唯一维护仓；不在运行本体新建 Git。

根入口仍叫 `绘世启动器.exe`，由一个无控制台包装器调用同级保存的 `绘世启动器原版.exe`，再进入原绘世 GUI。原版 EXE／DLL 字节不修改。GUI 显示的是保留的 ComfyUI 上游基线 `cc0fc21fea7a6a82f568362b15b7fbd713b419c1`，不能把维护仓 HEAD 解释为上游本体版本。

## 使用与管理范围

| 操作 | 适配后的约定 |
|---|---|
| 原 GUI、高级选项、环境维护、小工具页面 | 保留；参数设置仍由原界面管理 |
| 一键启动 | 原 GUI 管理自己的 Python 子进程；补现行 production 白名单及 `127.0.0.1:8188` |
| 显存、设备、精度、预览等普通参数 | 沿用原 GUI 参数，不改工作流、模型或用户提示词 |
| 自动打开浏览器 | 保留原 GUI 的显式选择；未启用时关闭，启用／关闭冲突时拒绝 |
| 版本查看 | 从主仓保存的真实历史读取；版本列表不表示可直接部署 |
| Git 更新、版本切换、插件源码安装／热修复 | 阻断直接改运行源码，按主仓分支、测试、PR 和精确部署流程维护 |
| 环境包查看 | 仅允许已审查的 bundled Python 执行 pip `--version/list/show/check/freeze`；隔离 pip 配置和继承环境 |
| 启动时自动依赖维护 | 延后使用已有受审查环境；原 Torch 预检保留，缺包不会自动补装 |
| 环境包安装／卸载 | 返回明确限制，转主仓受审查维护；不显示假安装成功 |

端口、数据目录、工作区、前端及 Manager 覆盖参数会在加载 ComfyUI 前拒绝，并给出中文说明。普通 CMD 启动不带适配标记，保持现有路径。此候选不替代 production_tools 的服务身份记录和安全停止工具；真实 GUI 的服务生命周期验收须单独记录。

API 拦截不是进程沙箱。这里保留管理页面和已列明操作，不宣称全部原生组件或模型下载都通过认证。涉及依赖或资源变更先备份、隔离验收，再按维护流程实施。

原绘世启动链每次都会尝试重写 `requirements.txt`。适配在已观察、固定版本的 `LaunchAsync.MoveNext` 调用链中延后整段自动依赖维护，不给源码写入开例外。其它依赖维护入口返回故障任务。调用链或固定组件发生变化时需重新审核；缺失对应栈帧会拒绝继续。

## 唯一实现与数据边界

源码在 [huishi_adapter](../../../snapshot/runtime/production_tools/huishi_adapter/README.md)。[main.py](../../../snapshot/runtime/ComfyUI/main.py)只在收到 `AKI_HUISHI_PROFILE=production` 时先应用 [runtime_start.py](../../../snapshot/runtime/production_tools/huishi_adapter/runtime_start.py)；生产插件取自 [profiles.json](../../../snapshot/runtime/production_tools/profiles.json)。

Startup Hook 只进入原 GUI，进入后清除其继承标记，Python 不加载 .NET Hook。包装器过滤远端配置、继承的实验开关和按名称识别的凭据变量；不改系统或父进程环境。自定义凭据名须另审，不能称任意环境值都被识别。

本机 `entry.local.json` 由准备工具生成，绑定主仓位置、本次产物／源码 SHA 和仓外日志；不入 Git。模型、图库、用户配置与数据库保持各自外置／可变状态，准备工具不读取或覆盖它们。

Managed 进程调用会核验实际工作目录和参数；只读 pip 固定工作目录，清理子进程 `PIP_*`／`PYTHON*`，使用隔离模式和 `PIP_CONFIG_FILE=nul`。不改父环境。Native 调用不信任不透明的环境指针，因此不放行 native pip。生产参数约束依赖包装入口的标记被原 GUI 传给 Python；普通无标记启动保持原行为，这不是防任意进程绕过的安全沙箱。

支持身份固定为现有根启动器 1.11.0.11、内部 GUI 2.9.2 Build 419、.NET 6 与 LibGit2Sharp 0.28。版本漂移会拒绝继续，须先重新审核；不能删除摘要校验强行兼容。

## 构建、候选与回滚

1. 在唯一主仓修改源码并完成相关回归。按[构建示例](../../../examples/huishi-adapter/README.md)将 Hook 和入口编译到全新仓外目录；收据绑定全部编译源码、引用及产物摘要。
2. `prepare.py` 默认只读；显式 `--prepare` 只创建新的私有候选包，包含精确 7 个目标的 before／after、缺失标记、摘要和回滚说明。它不写运行区、不安装依赖、不启动服务。
3. 部署前核对最新目标摘要、队列、服务 PID／启动时间／端口、数据库一致备份与同批回滚。按 [MAINTENANCE](../../MAINTENANCE.md)取得本次部署授权，再只写明确范围。
4. 回退也需核对当前 after 摘要。恢复 before 中原字节，新增文件仅在匹配时按单项移除；不删除整个目录，不回滚用户数据库或后来修改。

本次候选严格包含 7 个运行目标：根 `绘世启动器.exe`、同级 `绘世启动器原版.exe`、`ComfyUI/main.py`，以及 `production_tools/huishi_adapter/` 下的 `runtime_start.py`、`bin/Huishi.SingleGit.StartupHook.dll`、`bin/0Harmony.dll`、`entry.local.json`。原 GUI、LibGit、Python、production 插件及 profiles 是已核对的前置依赖，不复制进本次包。

根 bootstrap 会重新解包内部 runtimeconfig，因此不能只往该配置写 STARTUP_HOOKS。现行包装入口负责向原版子环境传入 Hook，仍保留原 GUI 自己的进程管理链。

依赖来源：[Harmony 2.3.3](https://www.nuget.org/packages/Lib.Harmony/2.3.3)、[.NET 6 参考程序集](https://www.nuget.org/packages/Microsoft.NETCore.App.Ref/6.0.36)。第三方程序集与原版绘世自行从已有合法安装取得，Git 不重新分发其二进制。用 .NET 6 引用直接编译 Hook；PowerShell 自身的框架引用不能代替原 GUI 的目标运行时。

## 验证与更新记录

Python 回归见 [运行参数与环境测试](../../../tests/test_huishi_runtime.py)、[候选包测试](../../../tests/test_huishi_delivery.py)和[快照类型测试](../../../tests/test_snapshot.py)。C# 隔离测试在适配目录中，分别覆盖实际 LibGit2Sharp、原生调用签名和进程参数保护。Windows GUI 页面验收、真实 Python 参数链、解压保护及服务生命周期的结果分别记录，不互相替代。

本轮[公开验收摘要](../../receipts/huishi_launcher_20261009.json)：维护仓 617 项回归通过；最后的浏览器参数变化后，相关 Python 50 项通过；最终 Hook 的 adapter 23 项、进程参数 77 项和 native 签名 24 项通过。实际 7z 回调允许普通文本、拒绝源码写入；它只覆盖该实测格式和路径，不等于所有压缩格式认证。

隔离原 GUI 已打开主页、高级选项、环境维护和小工具页面，显示真实上游版本。一键启动进入原日志面板，真实 Python 收到并消费生产标记，保留 GUI 参数，补齐 25 插件白名单；原停止按钮结束其子进程，界面回到“未运行”。该探针不启动服务、不导入 Torch、不加载模型、不监听端口；原 Torch 缺失警告只在这个空环境中被忽略。生产冷启动、GPU 生图、真实环境维护、所有小工具仍未验收。正式部署后需另记现场结果。

- 2026-10-09：新增原 GUI 的主仓读取适配、生产参数边界、构建身份和精确候选／回滚包；补受控只读 pip、自动依赖维护延后及自动打开浏览器选项。隔离界面与无服务启动／停止链通过，原版二进制未改。未部署或启动生产服务，未重建旧 Git。
