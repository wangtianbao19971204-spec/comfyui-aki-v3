$ErrorActionPreference = "Stop"

$oldRoot = "G:\ComfyUI-aki-v3\benchmark_reports\2026-08-24_anima_anima38_krea2"
$newRoot = "G:\ComfyUI-aki-v3\benchmark_reports\2026-08-24_anima_anima29_krea2"
$source = Join-Path $oldRoot "raw\results.jsonl"
$rawDir = Join-Path $newRoot "raw"
$destination = Join-Path $rawDir "results.jsonl"

New-Item -ItemType Directory -Path $rawDir -Force | Out-Null

$kept = [Collections.Generic.List[string]]::new()
foreach ($line in [IO.File]::ReadLines($source)) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    $record = $line | ConvertFrom-Json
    if ($record.model -in @("anima_original", "krea2")) {
        $kept.Add($line)
    }
}

[IO.File]::WriteAllLines($destination, $kept, [Text.UTF8Encoding]::new($false))

$counts = $kept | ForEach-Object { ($_ | ConvertFrom-Json).model } | Group-Object | Sort-Object Name
$counts | Select-Object Name, Count | Format-Table -AutoSize
"Baseline records written: $($kept.Count)"
