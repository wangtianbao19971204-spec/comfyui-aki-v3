[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$RuntimeRoot,
    [string]$ServiceUrl = 'http://127.0.0.1:8188',
    [switch]$Apply
)

# One reviewed cleanup request, bound to its published path/hash receipt.
# Preview is the default; deletion mode was used for this reviewed cleanup.
$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$receiptPath = Join-Path $repoRoot 'docs/receipts/model_checkpoint_cleanup_20261007.json'
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
$root = [IO.Path]::GetFullPath($RuntimeRoot).TrimEnd('\')
function Get-Utf8Sha256([string]$value) {
    $hasher = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($value)))).Replace('-', '').ToLowerInvariant() }
    finally { $hasher.Dispose() }
}
$targetBinding = (@($receipt.targets | ForEach-Object { $_.role + "`t" + $_.path + "`t" + [string]$_.bytes + "`t" + $_.sha256 }) -join "`n")
$keepBinding = (@($receipt.preserved | ForEach-Object { $_.path + "`t" + [string]$_.bytes + "`t" + $_.sha256 }) -join "`n")
# These constants bind exact path/role/size/hash identities, not a mutable count.
$expectedTargetBinding = 'f031ec43a1251dc05caf5144013a3657f80dd5f46d465a2c22c423fb2bab6629'
$expectedKeepBinding = '90b6b2ed0f810bada1e529889b69a2e99b2db01c745d147527f22ff4d1ed8373'
if ((Get-Utf8Sha256 $targetBinding) -ne $expectedTargetBinding -or
    (Get-Utf8Sha256 $keepBinding) -ne $expectedKeepBinding) {
    throw 'The exact reviewed deletion or preservation identities changed.'
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'ComfyUI/models/loras'))) {
    throw 'Runtime model root is missing.'
}
if ($receipt.receipt_id -ne 'model-checkpoint-cleanup-20261007-01' -or
    $receipt.targets.Count -ne 51 -or $receipt.preserved.Count -ne 8) {
    throw 'This is not the reviewed cleanup receipt.'
}

function Resolve-ReviewedPath([string]$relativePath) {
    if ([IO.Path]::IsPathRooted($relativePath) -or
        $relativePath.Contains('\') -or $relativePath.Contains(':') -or
        @($relativePath.Split('/') | Where-Object { $_ -eq '..' -or $_ -eq '.' -or $_ -eq '' }).Count) {
        throw 'Invalid relative target path.'
    }
    $absolute = [IO.Path]::GetFullPath((Join-Path $root $relativePath))
    if (-not $absolute.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw 'Target is outside the selected runtime root.'
    }
    $ancestorPath = $absolute
    while ($ancestorPath -and $ancestorPath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) {
        if (Test-Path -LiteralPath $ancestorPath) {
            $item = Get-Item -LiteralPath $ancestorPath -Force
            if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
                throw 'Linked files or directories cannot be removed.'
            }
        }
        if ($ancestorPath -eq $root) { break }
        $ancestorPath = Split-Path -Parent $ancestorPath
    }
    return $absolute
}

$keep = @{}
foreach ($asset in $receipt.preserved) {
    $path = Resolve-ReviewedPath $asset.path
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'A finished weight is missing.' }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.sha256) {
        throw 'Finished-weight content differs from the reviewed version.'
    }
    $keep[$path.ToLowerInvariant()] = $true
}

$seen = @{}
$pending = @()
$alreadyAbsent = @()
foreach ($asset in $receipt.targets) {
    $path = Resolve-ReviewedPath $asset.path
    $key = $path.ToLowerInvariant()
    if ($seen.ContainsKey($key) -or $keep.ContainsKey($key)) { throw 'Duplicate or protected deletion path.' }
    $seen[$key] = $true
    $allowed = switch ($asset.role) {
        'runtime_evaluation' { $asset.path.StartsWith('ComfyUI/models/loras/anima/自训评估/') -and $asset.path.EndsWith('.safetensors') }
        'evaluation_metadata' { $asset.path.StartsWith('ComfyUI/models/loras/anima/自训评估/') -and $asset.path.EndsWith('.metadata.json') }
        'training_evaluation' { $asset.path.StartsWith('anima_lora_forge/runs/') -and $asset.path.Contains('/weights/') -and $asset.path.EndsWith('.safetensors') }
        'training_checkpoint_final_alias' { $asset.path.StartsWith('anima_lora_forge/runs/') -and $asset.path.Contains('/weights/') -and $asset.path.EndsWith('.safetensors') }
        'retired_evaluation_fallback_alias' { $asset.path.StartsWith('anima_lora_forge/releases/') -and ([IO.Path]::GetFileName($path) -in @('fallback_step0125.safetensors', 'fallback_step0200.safetensors')) }
        default { $false }
    }
    if (-not $allowed) { throw 'Unreviewed target role or directory.' }
    if (-not (Test-Path -LiteralPath $path)) {
        $alreadyAbsent += $asset.path
        continue
    }
    $item = Get-Item -LiteralPath $path -Force
    if ($item.PSIsContainer -or $item.Length -ne $asset.bytes) { throw 'Target type or size changed.' }
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.sha256) {
        throw 'Target content changed; no files have been deleted.'
    }
    $pending += [pscustomobject]@{ Path = $path; RelativePath = $asset.path; Role = $asset.role; Bytes = $asset.bytes; Sha256 = $asset.sha256 }
}

if (-not $Apply) {
    [pscustomobject]@{ mode = 'preview'; pending_files = $pending.Count; already_absent = $alreadyAbsent.Count; preserved_versions = 4 } | ConvertTo-Json
    return
}

$service = [Uri]$ServiceUrl
if ($service.Scheme -ne 'http' -or $service.Host -notin @('127.0.0.1', 'localhost', '[::1]', '::1') -or $service.UserInfo) {
    throw 'Use a local ComfyUI service URL without authentication.'
}
$queue = Invoke-RestMethod -Uri ($ServiceUrl.TrimEnd('/') + '/queue') -TimeoutSec 8
if (@($queue.queue_running).Count -or @($queue.queue_pending).Count) {
    throw 'The ComfyUI queue must be empty before this cleanup.'
}
$active = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -match 'train_network\.py'
})
if ($active.Count) { throw 'A training process is active; inspect it before removing checkpoints.' }

$recordDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'ComfyUI-maintenance/receipts'
[IO.Directory]::CreateDirectory($recordDirectory) | Out-Null
$journalPath = Join-Path $recordDirectory ('eval-cleanup-' + [Guid]::NewGuid().ToString() + '.jsonl')
foreach ($asset in $pending) {
    $currentPath = Resolve-ReviewedPath $asset.RelativePath
    if ($currentPath -ne $asset.Path -or $keep.ContainsKey($currentPath.ToLowerInvariant())) {
        throw 'The reviewed deletion path changed or became protected.'
    }
    $currentItem = Get-Item -LiteralPath $currentPath -Force
    if ($currentItem.PSIsContainer -or $currentItem.Length -ne $asset.Bytes -or
        (Get-FileHash -LiteralPath $currentPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.Sha256) {
        throw 'Target identity changed immediately before removal.'
    }
    Remove-Item -LiteralPath $currentPath -Force
    if (Test-Path -LiteralPath $currentPath) { throw 'A target remained after removal.' }
    [pscustomobject]@{ path = $asset.RelativePath; role = $asset.Role; removed_at = [DateTimeOffset]::UtcNow.ToString('o') } |
        ConvertTo-Json -Compress | Add-Content -LiteralPath $journalPath -Encoding utf8
}
foreach ($asset in $receipt.preserved) {
    $path = Resolve-ReviewedPath $asset.path
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() -ne $asset.sha256) {
        throw 'Post-cleanup finished-weight verification failed.'
    }
}
[pscustomobject]@{
    mode = 'applied'; removed_files = $pending.Count; already_absent = $alreadyAbsent.Count
    preserved_versions = 4; journal = $journalPath
    source_catalogue_updated = $false
} | ConvertTo-Json
