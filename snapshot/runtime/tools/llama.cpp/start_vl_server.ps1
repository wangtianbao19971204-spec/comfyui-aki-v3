# 启动本地 Qwen VL（GGUF + mmproj）作为 llama-server，供批处理判图调用。
# 用法： pwsh -File start_vl_server.ps1 [-Port 8081] [-Ctx 8192] [-GpuLayers 99]
#        pwsh -File start_vl_server.ps1 -Preset qwen38-27b-q8 -Port 8082 -Ctx 8192
param(
    [int]$Port = 8081,
    [int]$Ctx = 8192,
    [int]$GpuLayers = 99,
    [int]$Parallel = 2,
    [string]$Preset = "qwen3vl-8b-abliterated",
    [string]$Model,
    [string]$Mmproj
)

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$models = "G:\ComfyUI-aki-v3\ComfyUI\models\LLM"

$presets = @{
    "qwen3vl-8b-abliterated" = @{
        model  = "Qwen3-VL-8B-Instruct-abliterated-v2.0.Q6_K.gguf"
        mmproj = "Qwen3-VL-8B-Instruct-abliterated-v2.0.mmproj-f16.gguf"
    }
    "qwen38-27b-q8" = @{
        model  = "Huihui-Qwen3.8-27B-abliterated-Q8_0.gguf"
        mmproj = "mmproj-model-bf16.gguf"
        ctx    = 4096
    }
}

if (-not $Model -or -not $Mmproj) {
    if (-not $presets.ContainsKey($Preset)) {
        throw "未知预设：$Preset（可选：$($presets.Keys -join ', ')）"
    }
    $p = $presets[$Preset]
    if (-not $Model) { $Model = Join-Path $models $p.model }
    if (-not $Mmproj) { $Mmproj = Join-Path $models $p.mmproj }
    if ($p.ContainsKey("ctx") -and $Ctx -eq 8192) { $Ctx = $p.ctx }
}

foreach ($path in @($Model, $Mmproj)) {
    if (-not (Test-Path $path)) { throw "缺少模型文件: $path" }
}

$exe = Join-Path $here "llama-server.exe"
$arguments = @(
    "-m", $Model,
    "--mmproj", $Mmproj,
    "-ngl", "$GpuLayers",
    "-c", "$Ctx",
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--no-webui",
    "-np", "$Parallel",
    "-fa", "on",
    "--image-min-tokens", "1024",
    "--jinja"
)

$process = Start-Process -FilePath $exe -ArgumentList $arguments -WorkingDirectory $here `
    -RedirectStandardOutput (Join-Path $here "server.out.log") `
    -RedirectStandardError (Join-Path $here "server.err.log") `
    -WindowStyle Hidden -PassThru

"pid=$($process.Id) port=$Port ctx=$Ctx ngl=$GpuLayers np=$Parallel"
