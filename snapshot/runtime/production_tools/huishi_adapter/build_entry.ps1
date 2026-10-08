param([Parameter(Mandatory=$true)][string]$OutputDirectory)
# Compile only our transparent entry. Vendor binaries are never distributed by Git.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$outputPath = [IO.Path]::GetFullPath($OutputDirectory)
$repoPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
if ($outputPath.StartsWith($repoPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or (Test-Path -LiteralPath $outputPath)) { throw 'Choose a new build directory outside the main Git.' }
$compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
if (-not (Test-Path -LiteralPath $compiler)) { throw 'Existing .NET Framework compiler not found.' }
$null = New-Item -ItemType Directory -Path $outputPath
$executable = Join-Path $outputPath '绘世启动器.exe'
$originalSource = Join-Path $PSScriptRoot 'Entry.cs'
$sourceBytes = [IO.File]::ReadAllBytes($originalSource)
$sourceHasher = [Security.Cryptography.SHA256]::Create()
try { $sourceHash = ([BitConverter]::ToString($sourceHasher.ComputeHash($sourceBytes))).Replace('-', '').ToLowerInvariant() } finally { $sourceHasher.Dispose() }
$cachedSource = Join-Path $outputPath 'Entry.cs'
[IO.File]::WriteAllBytes($cachedSource, $sourceBytes)
& $compiler /nologo /target:winexe /platform:x64 /reference:System.Web.Extensions.dll /reference:System.Windows.Forms.dll "/out:$executable" $cachedSource
if ($LASTEXITCODE -ne 0) { throw 'Entry compilation failed.' }
if ((Get-FileHash -LiteralPath $originalSource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHash) { throw 'Entry source changed during compilation.' }
$receipt = [pscustomobject]@{
    executable = $executable
    source_sha256 = [ordered]@{ 'Entry.cs' = $sourceHash }
    executable_sha256 = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash.ToLowerInvariant()
    compiler_sha256 = (Get-FileHash -LiteralPath $compiler -Algorithm SHA256).Hash.ToLowerInvariant()
    runtime_target = 'net48'
    deployed = $false
}
$receiptJson = $receipt | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText((Join-Path $outputPath 'build.receipt.json'), $receiptJson, [Text.UTF8Encoding]::new($false))
$receiptJson
