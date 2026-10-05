# 下载 Huihui-Qwen3.8-27B-abliterated 的 Q8_0 权重 + mmproj（支持断点续传）。
# 注意：本机靠 127.0.0.1:10081 的系统代理出网，curl 不读系统代理设置，必须显式 --proxy。
# 用法： pwsh -File download_qwen38_27b.ps1 [-Proxy http://127.0.0.1:10081]
param([string]$Proxy = "http://127.0.0.1:10081")

$ErrorActionPreference = "Continue"
$dest = "G:\ComfyUI-aki-v3\ComfyUI\models\LLM"
$log  = "G:\ComfyUI-aki-v3\tools\llama.cpp\download_27b.log"
$base = "https://huggingface.co/huihui-ai/Huihui-Qwen3.8-27B-abliterated-GGUF/resolve/main"
$files = @("Huihui-Qwen3.8-27B-abliterated-Q8_0.gguf", "mmproj-model-bf16.gguf")

New-Item -ItemType Directory -Force -Path $dest | Out-Null
foreach ($name in $files) {
    $target = Join-Path $dest $name
    $url = "$base/$name"
    Add-Content -Path $log -Value ("=== start {0} {1} ===" -f $name, (Get-Date).ToString("HH:mm:ss"))
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        & curl.exe -L --fail --retry 3 --retry-delay 5 -C - --proxy $Proxy -o $target $url *>> $log
        if ($LASTEXITCODE -eq 0) { break }
        Add-Content -Path $log -Value ("    attempt {0} exit={1}, retrying" -f $attempt, $LASTEXITCODE)
        Start-Sleep -Seconds 10
    }
    $size = if (Test-Path $target) { [math]::Round((Get-Item $target).Length / 1GB, 2) } else { 0 }
    Add-Content -Path $log -Value ("=== done {0} size={1} GB {2} ===" -f $name, $size, (Get-Date).ToString("HH:mm:ss"))
}
Add-Content -Path $log -Value ("=== all downloads finished {0} ===" -f (Get-Date).ToString("HH:mm:ss"))
