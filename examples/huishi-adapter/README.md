# 绘世适配的构建与准备示例

本例供维护者在主仓拉取源码后构建。先准备合法的原绘世安装、.NET 6 参考程序集与 Harmony；所有路径用本机真实位置替换，输出目录必须尚不存在并位于主仓／运行区之外。

```powershell
$adapterSource = Join-Path (Get-Location) 'snapshot/runtime/production_tools/huishi_adapter'
& "$adapterSource/build_hook.ps1" -Net6References '<完整 net6.0 引用目录>' -HarmonyDll '<0Harmony.dll>' -LibGit2SharpDll '<原绘世 LibGit2Sharp.dll>' -OutputDirectory '<全新仓外 Hook 构建目录>'
if ($LASTEXITCODE -ne 0) { throw 'Hook 构建失败' }
& "$adapterSource/build_entry.ps1" -OutputDirectory '<全新仓外入口构建目录>'
if ($LASTEXITCODE -ne 0) { throw '入口构建失败' }
python -X utf8 -B "$adapterSource/prepare.py" --repository '<唯一主仓绝对路径>' --runtime '<运行根绝对路径>' --hook-build '<本次 Hook 构建目录>' --entry-executable '<本次入口构建目录/绘世启动器.exe>' --output '<全新仓外候选包目录>'
```

最后一条默认只查看计划。审核无误后显式加 `--prepare`，仅在仓外保存候选和回滚字节，仍不部署。生成的 `entry.local.json` 含本机路径，只留私有；不要手抄示例创建它，不要上传候选包中的 EXE／DLL。

部署需要另行授权并核对现场，详见[技术说明](../../docs/technical/runtime/huishi-launcher.md)与[维护流程](../../docs/MAINTENANCE.md)。原 GUI 不是首次搭建 ComfyUI 所必需；普通生产 CMD 入口仍按[启动说明](../../docs/technical/runtime/core.md)使用。
