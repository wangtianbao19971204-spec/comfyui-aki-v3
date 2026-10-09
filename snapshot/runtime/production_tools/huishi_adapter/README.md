# 绘世原界面适配

让现有绘世 2.9.2 继续显示真实 ComfyUI 版本，并从原图形界面启动现行生产配置。开发来源仍只有 `maintenance/comfyui`，运行目录不重建 `.git`。

本机已部署精确 7 文件，原 GUI 启动和实际工作台载入通过验收；原停止按钮另有隔离验证。显存、设备、预览及自动打开浏览器选项保留；源码更新、依赖安装转主仓维护，启动时不自动重写依赖。使用方法、支持的管理操作及验收限制见[技术说明](../../../../docs/technical/runtime/huishi-launcher.md)。

| 文件 | 用途 |
|---|---|
| `Entry.cs` | 无控制台入口，调用保存的原版启动器，并设置本次子进程环境 |
| `StartupHook.cs` | 原 GUI 的版本读取映射、Git 与源码写入保护 |
| `NativeGuards.cs`、`ProcessPolicy.cs` | 原生文件／进程调用保护及允许的调用范围 |
| `runtime_start.py` | 在原 GUI 的 Python 子进程中应用现行生产插件清单 |
| `build_*.ps1` | 编译到全新仓外目录，保存源码、依赖及产物摘要 |
| `prepare.py` | 只读计划，或显式生成私有候选／回滚包；不部署 |
| `*Tests.cs`、`ProbeRunner.cs` | 无模型隔离测试与研究探针，不作为日常入口 |

Git 只保存自有源码。原版绘世 EXE／DLL、生成的 Hook／入口 EXE、依赖 DLL、本机设置和日志都在仓外或运行环境中，不能当作公开载荷上传。
