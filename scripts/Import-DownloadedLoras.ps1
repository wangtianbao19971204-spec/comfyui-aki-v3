# 新下载 LoRA 快速整理：默认预览；-Apply 移动新增项并登记工作台。
param(
    [switch]$Apply,
    [string]$Downloads = (Join-Path $env:USERPROFILE 'Downloads')
)
$ErrorActionPreference = 'Stop'
$comfyRepo = Split-Path $PSScriptRoot -Parent
$comfyManifest = Get-Content -LiteralPath (Join-Path $comfyRepo 'snapshot/manifest.json') -Raw | ConvertFrom-Json
$comfyImportPython = Join-Path $comfyManifest.source_root 'python/python.exe'
if (-not (Test-Path -LiteralPath $comfyImportPython -PathType Leaf)) {
    throw '未找到运行区 Python；请按说明直接使用 Python 3.11+ 运行导入器。'
}
$comfyImportArgs = @('-X', 'utf8', '-B', (Join-Path $PSScriptRoot 'import_lora_downloads.py'), '--downloads', $Downloads)
if ($Apply) { $comfyImportArgs += '--apply' }
& $comfyImportPython @comfyImportArgs
if ($LASTEXITCODE -ne 0) { throw '导入未全部完成；请检查仓外收据及提示，原件不会在未核验时移除。' }
