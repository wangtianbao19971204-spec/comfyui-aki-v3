# 拉起 ComfyUI（与原有启动参数一致），供批处理任务出图使用。
$ErrorActionPreference = "Continue"
$root = "G:\ComfyUI-aki-v3"
$python = Join-Path $root "python\python.exe"
$main = Join-Path $root "ComfyUI\main.py"
$log = Join-Path $root "tools\comfyui.out.log"
$err = Join-Path $root "tools\comfyui.err.log"

$process = Start-Process -FilePath $python `
    -ArgumentList @($main, "--auto-launch", "--preview-method", "auto",
                    "--cuda-malloc", "--reserve-vram", "4") `
    -WorkingDirectory (Join-Path $root "ComfyUI") `
    -RedirectStandardOutput $log -RedirectStandardError $err `
    -WindowStyle Hidden -PassThru

"comfyui pid=$($process.Id) log=$log"
