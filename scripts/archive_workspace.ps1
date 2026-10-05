<#
Recoverable same-volume archival of an explicit reviewed path list. No deletion,
no recursive glob moves, no runtime-root moves, and no overwrite of destinations.
Plan schema: {workspace, archive_root, protected_paths:[], items:[{source,target,reason}]}.
Source and target are relative to the two respective roots. Plan defaults to
content SHA-256. Explicit Metadata mode records path/size/mtime, not content;
PreserveReparsePoints only records links without traversing targets. Apply binds
the exact assurance mode and requires the review receipt's SHA-256.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Plan,
    [Parameter(Mandatory)][string]$Receipt,
    [ValidateSet('Plan','Apply')][string]$Mode = 'Plan',
    [ValidateSet('Content','Metadata')][string]$InventoryMode = 'Content',
    [switch]$PreserveReparsePoints,
    [string]$ReviewSha256
)
$ErrorActionPreference = 'Stop'

function Assert-PlainPath([string]$Value) {
    $absolute = [IO.Path]::GetFullPath($Value)
    $cursor = $absolute
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            $item = Get-Item -LiteralPath $cursor -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked/reparse path is not permitted' }
        }
        $parent = [IO.Path]::GetDirectoryName($cursor)
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
    return $absolute
}
function Resolve-Child([string]$Root, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or [IO.Path]::IsPathRooted($Relative) -or $Relative -match '[:*?"<>|\x00-\x1f]') { throw 'Unsafe relative path' }
    foreach ($part in ($Relative -split '[\\/]')) {
        if (-not $part -or $part -in @('.','..') -or $part -ne $part.TrimEnd(' ','.') -or $part -match '^(?i:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)') { throw 'Unsafe Windows path segment' }
    }
    $candidate = Assert-PlainPath (Join-Path $Root $Relative)
    if (-not $candidate.StartsWith($Root.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path escaped root' }
    return $candidate
}
function Get-TreeInventory([string]$Path) {
    $rootItem = Get-Item -LiteralPath $Path -Force
    $rows = [Collections.Generic.List[object]]::new()
    $pending = [Collections.Generic.Stack[object]]::new()
    $pending.Push($rootItem)
    while ($pending.Count) {
        $item = $pending.Pop()
        $relative = if ($rootItem.PSIsContainer -and $item.FullName -ne $Path) { $item.FullName.Substring($Path.Length + 1) } else { '.' }
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            if (-not $PreserveReparsePoints) { throw 'Linked tree requires explicit metadata-only preservation review' }
            $rows.Add([ordered]@{path=$relative; type='reparse'; link_type=$item.LinkType; target=@($item.Target); verification='link_metadata_only_target_not_followed'})
            continue
        }
        if ($item.PSIsContainer) {
            foreach ($child in (Get-ChildItem -LiteralPath $item.FullName -Force)) { $pending.Push($child) }
            continue
        }
        if ($item.Name -in @('index.lock','packed-refs.lock','run.lock')) { throw 'Lock file requires separate owner review; refused' }
        if ($InventoryMode -eq 'Content') {
            $rows.Add([ordered]@{path=$relative; bytes=$item.Length; sha256=(Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash.ToLowerInvariant()})
        } else {
            $rows.Add([ordered]@{path=$relative; bytes=$item.Length; mtime_utc_ticks=$item.LastWriteTimeUtc.Ticks; verification='path_size_mtime_only'})
        }
    }
    return @($rows | Sort-Object { $_.path })
}
function Inventory-Hash($Rows) {
    $bytes = [Text.Encoding]::UTF8.GetBytes((ConvertTo-Json -InputObject @($Rows) -Depth 10 -Compress))
    return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

$planFile = Assert-PlainPath $Plan
$receiptFile = Assert-PlainPath $Receipt
if ($PreserveReparsePoints -and $InventoryMode -ne 'Metadata') { throw 'Linked trees require explicit Metadata mode; no target content is hashed or followed' }
$spec = Get-Content -LiteralPath $planFile -Raw | ConvertFrom-Json
$workspacePath = Assert-PlainPath $spec.workspace
$archivePath = Assert-PlainPath $spec.archive_root
if ($workspacePath -eq [IO.Path]::GetPathRoot($workspacePath) -or $archivePath -eq [IO.Path]::GetPathRoot($archivePath)) { throw 'Broad roots are forbidden' }
if ([IO.Path]::GetPathRoot($workspacePath) -ne [IO.Path]::GetPathRoot($archivePath)) { throw 'Only recoverable same-volume moves are supported' }
if ($archivePath.StartsWith($workspacePath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or $archivePath -eq $workspacePath) { throw 'Archive must be outside workspace' }
if (-not $receiptFile.StartsWith($archivePath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Private receipts must be outside workspace in archive root' }
$planHash = (Get-FileHash -LiteralPath $planFile -Algorithm SHA256).Hash.ToLowerInvariant()
$allowedChildren = if ($spec.allowed_protected_sources) { @($spec.allowed_protected_sources | ForEach-Object { Resolve-Child $workspacePath $_ }) } else { @() }
$resolved = @()
foreach ($entry in $spec.items) {
    $source = Resolve-Child $workspacePath $entry.source
    $target = Resolve-Child $archivePath $entry.target
    foreach ($protected in $spec.protected_paths) {
        $p = Resolve-Child $workspacePath $protected
        if ($p -eq $source -or $p.StartsWith($source + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Move contains a protected root' }
        if ($source.StartsWith($p + '\', [StringComparison]::OrdinalIgnoreCase) -and $source -notin $allowedChildren) { throw 'Move is inside a protected root without an exact reviewed exception' }
    }
    if (-not (Test-Path -LiteralPath $source)) { throw 'Source is missing' }
    if (Test-Path -LiteralPath $target) { throw 'Destination exists; no overwrite permitted' }
    foreach ($other in $resolved) {
        if ($source -eq $other.source -or $source.StartsWith($other.source + '\', [StringComparison]::OrdinalIgnoreCase) -or $other.source.StartsWith($source + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Overlapping sources' }
        if ($target -eq $other.target -or $target.StartsWith($other.target + '\', [StringComparison]::OrdinalIgnoreCase) -or $other.target.StartsWith($target + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Overlapping destinations' }
    }
    $files = @(Get-TreeInventory $source)
    $resolved += [ordered]@{source=$source; target=$target; reason=$entry.reason; files=$files; inventory_sha256=(Inventory-Hash $files)}
}
if ($Mode -eq 'Plan') {
    if (Test-Path -LiteralPath $receiptFile) { throw 'Receipt exists' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $receiptFile) -Force | Out-Null
    [ordered]@{schema=1; mode='REVIEW'; inventory_mode=$InventoryMode; preserve_reparse_points=[bool]$PreserveReparsePoints; plan_sha256=$planHash; moves=$resolved; deleted_files=0} | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $receiptFile -Encoding utf8
    [ordered]@{items=$resolved.Count; review_sha256=(Get-FileHash -LiteralPath $receiptFile -Algorithm SHA256).Hash.ToLowerInvariant(); receipt=$receiptFile} | ConvertTo-Json
    exit 0
}
if (-not $ReviewSha256 -or (Get-FileHash -LiteralPath $receiptFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $ReviewSha256) { throw 'Missing or stale review SHA' }
$review = Get-Content -LiteralPath $receiptFile -Raw | ConvertFrom-Json
if ([bool]$review.preserve_reparse_points -ne [bool]$PreserveReparsePoints) { throw 'Link preservation mode changed since review' }
if ($review.inventory_mode -and $review.inventory_mode -ne $InventoryMode) { throw 'Inventory assurance changed since review' }
if (-not $review.inventory_mode -and $InventoryMode -ne 'Content') { throw 'Legacy review only permits content verification' }
if ($review.plan_sha256 -ne $planHash -or $review.moves.Count -ne $resolved.Count) { throw 'Plan changed since review' }
for ($i=0; $i -lt $resolved.Count; $i++) {
    if ($resolved[$i].inventory_sha256 -ne $review.moves[$i].inventory_sha256 -or $resolved[$i].source -ne $review.moves[$i].source -or $resolved[$i].target -ne $review.moves[$i].target) { throw 'Sources changed since review' }
}
$journal = $receiptFile + '.applied.jsonl'
if (Test-Path -LiteralPath $journal) { throw 'Apply journal exists; inspect previous partial run' }
foreach ($move in $resolved) {
    $source = Assert-PlainPath $move.source
    $target = Assert-PlainPath $move.target
    if (Test-Path -LiteralPath $target) { throw 'Target appeared during apply' }
    if ((Inventory-Hash @(Get-TreeInventory $source)) -ne $move.inventory_sha256) { throw 'Source changed immediately before move' }
    New-Item -ItemType Directory -Path (Split-Path -Parent $target) -Force | Out-Null
    Move-Item -LiteralPath $source -Destination $target
    $verified = (Inventory-Hash @(Get-TreeInventory $target)) -eq $move.inventory_sha256
    [ordered]@{source=$source; target=$target; verified=$verified; inventory_mode=$InventoryMode; preserve_reparse_points=[bool]$PreserveReparsePoints; inventory_sha256=$move.inventory_sha256; recoverable=$true} | ConvertTo-Json -Compress | Add-Content -LiteralPath $journal -Encoding utf8
    if (-not $verified) { throw 'Post-move verification failed; archive retained for inspection' }
}
[ordered]@{moved=$resolved.Count; deleted_files=0; verified=$true; journal=$journal} | ConvertTo-Json
