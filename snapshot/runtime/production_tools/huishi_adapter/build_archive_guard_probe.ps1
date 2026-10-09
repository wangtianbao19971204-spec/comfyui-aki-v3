param(
    [Parameter(Mandatory=$true)][string]$Net6References,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$outputPath = [IO.Path]::GetFullPath($OutputDirectory)
$repositoryPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
if ($outputPath.StartsWith($repositoryPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    (Test-Path -LiteralPath $outputPath)) { throw 'Choose a new build directory outside the repository.' }
$referencePath = (Resolve-Path -LiteralPath $Net6References).Path
$references = @(Get-ChildItem -LiteralPath $referencePath -Filter '*.dll' -File | ForEach-Object FullName)
if ($references.Count -lt 100) { throw 'A complete .NET 6 reference set is required.' }
$null = [Reflection.Assembly]::LoadFrom((Join-Path $PSHOME 'Microsoft.CodeAnalysis.dll'))
$null = [Reflection.Assembly]::LoadFrom((Join-Path $PSHOME 'Microsoft.CodeAnalysis.CSharp.dll'))
$syntax = [Microsoft.CodeAnalysis.SyntaxTree[]]@([Microsoft.CodeAnalysis.CSharp.SyntaxFactory]::ParseSyntaxTree(
    [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'ArchiveGuardProbe.cs'))))
$metadata = [Microsoft.CodeAnalysis.MetadataReference[]]@($references | ForEach-Object {
    [Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile($_)
})
$options = [Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new([Microsoft.CodeAnalysis.OutputKind]::DynamicallyLinkedLibrary)
$compilation = [Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create('Huishi.ArchiveGuard.Probe', $syntax, $metadata, $options)
$null = New-Item -ItemType Directory -Path $outputPath
$assembly = Join-Path $outputPath 'Huishi.ArchiveGuard.Probe.dll'
$stream = [IO.File]::Open($assembly, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $result = $compilation.Emit($stream) } finally { $stream.Dispose() }
if (-not $result.Success) {
    throw ('Compilation failed: ' + ((@($result.Diagnostics | Where-Object Severity -eq 'Error' | ForEach-Object ToString)) -join [Environment]::NewLine))
}
[pscustomobject]@{ assembly = $assembly; runtime_target = 'net6.0'; deployed = $false } | ConvertTo-Json
