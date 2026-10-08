param(
    [Parameter(Mandatory=$true)][string]$Net6References,
    [Parameter(Mandatory=$true)][string]$HarmonyDll,
    [Parameter(Mandatory=$true)][string]$OutputDirectory
)

# Compile only the independent native guard and fixture; never launch the GUI.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$outputPath = [IO.Path]::GetFullPath($OutputDirectory)
$repositoryPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
if ($outputPath.StartsWith($repositoryPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or
    (Test-Path -LiteralPath $outputPath)) { throw 'Choose a new build directory outside the repository.' }
$referencePath = (Resolve-Path -LiteralPath $Net6References).Path
$harmonyPath = (Resolve-Path -LiteralPath $HarmonyDll).Path
$references = @(Get-ChildItem -LiteralPath $referencePath -Filter '*.dll' -File | ForEach-Object FullName)
if ($references.Count -lt 100) { throw 'A complete .NET 6 reference set is required.' }
$references += $harmonyPath
$null = [Reflection.Assembly]::LoadFrom((Join-Path $PSHOME 'Microsoft.CodeAnalysis.dll'))
$null = [Reflection.Assembly]::LoadFrom((Join-Path $PSHOME 'Microsoft.CodeAnalysis.CSharp.dll'))
$sourceFiles = @('NativeGuards.cs', 'NativeGuardsTests.cs') | ForEach-Object { Join-Path $PSScriptRoot $_ }
$syntax = [Microsoft.CodeAnalysis.SyntaxTree[]]@($sourceFiles | ForEach-Object {
    [Microsoft.CodeAnalysis.CSharp.SyntaxFactory]::ParseSyntaxTree([IO.File]::ReadAllText($_))
})
$metadata = [Microsoft.CodeAnalysis.MetadataReference[]]@($references | ForEach-Object {
    [Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile($_)
})
$options = [Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new([Microsoft.CodeAnalysis.OutputKind]::ConsoleApplication).WithAllowUnsafe($true)
$compilation = [Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create('Huishi.NativeGuards.Tests', $syntax, $metadata, $options)
$null = New-Item -ItemType Directory -Path $outputPath
$assembly = Join-Path $outputPath 'Huishi.NativeGuards.Tests.dll'
$stream = [IO.File]::Open($assembly, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $result = $compilation.Emit($stream) } finally { $stream.Dispose() }
if (-not $result.Success) {
    throw ('Compilation failed: ' + ((@($result.Diagnostics | Where-Object Severity -eq 'Error' | ForEach-Object ToString)) -join [Environment]::NewLine))
}
Copy-Item -LiteralPath $harmonyPath -Destination (Join-Path $outputPath '0Harmony.dll')
[IO.File]::WriteAllText((Join-Path $outputPath 'Huishi.NativeGuards.Tests.runtimeconfig.json'),
    '{"runtimeOptions":{"tfm":"net6.0","framework":{"name":"Microsoft.NETCore.App","version":"6.0.0"}}}', [Text.UTF8Encoding]::new($false))
[pscustomobject]@{ assembly = $assembly; runtime_target = 'net6.0'; deployed = $false } | ConvertTo-Json
