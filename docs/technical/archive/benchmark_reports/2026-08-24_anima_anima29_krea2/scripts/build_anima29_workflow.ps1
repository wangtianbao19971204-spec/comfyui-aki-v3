param(
    [string]$Source = "G:\ComfyUI-aki-v3\ComfyUI\user\default\workflows\Anima_推荐版_细化可选_手动候选_K2预览外显_无LoRA.json",
    [string]$Destination = "G:\ComfyUI-aki-v3\ComfyUI\user\default\workflows\Anima_推荐版_官方2.9B_BF16_发布页骨架版_细化可选_K2预览外显_无LoRA.json"
)

$ErrorActionPreference = "Stop"

$workflow = [IO.File]::ReadAllText($Source) | ConvertFrom-Json
$workflow.id = [guid]::NewGuid().ToString()
$workflow.revision = 0

$sampler = $workflow.nodes | Where-Object { $_.id -eq 10 -and $_.type -eq "KSampler" }
if ($null -eq $sampler) {
    throw "Expected KSampler node 10 was not found."
}
$sampler.title = "[06B] Anima 2.9B 采样"
$sampler.widgets_values[2] = 50
$sampler.widgets_values[3] = 3.5
$sampler.widgets_values[4] = "euler"
$sampler.widgets_values[5] = "sgm_uniform"
$sampler.widgets_values[6] = 1.0

$samplingNote = $workflow.nodes | Where-Object { $_.id -eq 11 -and $_.type -eq "MarkdownNote" }
if ($null -ne $samplingNote) {
    $samplingNote.widgets_values = @"
# 06 Anima 2.9B Sampler / Output
## 发布者推荐起步值

- steps: 28-50 (最高质量推荐 50)
- cfg: 3.5-5 (本工作流默认 3.5)
- sampler: euler
- scheduler: sgm_uniform
- denoise: 1.0

提示词建议包含 highres、absurdres、年份标签、角色/作品锚点与明确背景；不依赖 score 标签。
"@
}

$modelSubgraph = $workflow.definitions.subgraphs | Where-Object { $_.id -eq "173da526-e230-4aaa-b442-2b3f561be267" }
if ($null -eq $modelSubgraph) {
    throw "Expected model subgraph was not found."
}
$modelSubgraph.name = "[02] Anima 2.9B 模型与 LoRA"

$unetLoader = $modelSubgraph.nodes | Where-Object { $_.id -eq 580 -and $_.type -eq "UNETLoader" }
if ($null -eq $unetLoader) {
    throw "Expected UNETLoader node 580 was not found."
}
$unetLoader.title = "[02B] Anima 2.9B BF16 底模"
$unetLoader.widgets_values[0] = "Anima-2.9B\anima29B_v10_bf16.safetensors"
$unetLoader.properties.label = "Anima 2.9B preview v1 BF16 完整权重。文件位于 ComfyUI/models/diffusion_models/Anima-2.9B/。"

$clipLoader = $modelSubgraph.nodes | Where-Object { $_.id -eq 579 -and $_.type -eq "CLIPLoader" }
if ($null -eq $clipLoader -or $clipLoader.widgets_values[0] -ne "anima_baseV10_txt.safetensors") {
    throw "The shared Anima Qwen3 0.6B text encoder was not found."
}
$clipLoader.title = "[02A] Anima 2.9B 文本编码器"
$clipLoader.properties.label = "Anima 2.9B 沿用原 Anima Qwen3 0.6B 文本编码器，type 使用 stable_diffusion。"

$json = $workflow | ConvertTo-Json -Depth 100 -Compress
[IO.File]::WriteAllText($Destination, $json, [Text.UTF8Encoding]::new($false))

[pscustomobject]@{
    Destination = $Destination
    WorkflowId = $workflow.id
    UNet = $unetLoader.widgets_values[0]
    CLIP = $clipLoader.widgets_values[0]
    Sampler = $sampler.widgets_values[4]
    Scheduler = $sampler.widgets_values[5]
    Steps = $sampler.widgets_values[2]
    CFG = $sampler.widgets_values[3]
} | Format-List
