param(
    [string]$Server = "http://127.0.0.1:8188"
)

$body = @{
    unload_models = $true
    free_memory = $true
} | ConvertTo-Json

Invoke-RestMethod `
    -Method Post `
    -Uri "$Server/free" `
    -ContentType "application/json" `
    -Body $body | Out-Null

Start-Sleep -Seconds 3
$gpu = nvidia-smi `
    --query-gpu=name,memory.used,memory.free,utilization.gpu `
    --format=csv,noheader,nounits

Write-Host "ComfyUI models unloaded. GPU state: $gpu"
