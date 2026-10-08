param(
    [Parameter(Mandatory=$true)][string]$Net6References,
    [Parameter(Mandatory=$true)][string]$HarmonyDll,
    [Parameter(Mandatory=$true)][string]$LibGit2SharpDll,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidateSet('StartupHook.cs', 'ProbeRunner.cs', 'AdapterTests.cs')][string]$SourceName = 'StartupHook.cs'
)

# Compile against .NET 6 reference assemblies, not PowerShell's own runtime.
# Vendor executables and generated assemblies stay outside the public repository.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$sourceFile = Join-Path $PSScriptRoot $SourceName
$sourceFiles = @($sourceFile)
if ($SourceName -eq 'StartupHook.cs') {
    $sourceFiles += Join-Path $PSScriptRoot 'NativeGuards.cs'
    $sourceFiles += Join-Path $PSScriptRoot 'ProcessPolicy.cs'
}
$outputPath = [IO.Path]::GetFullPath($OutputDirectory)
$repositoryPath = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../../..'))
if ($outputPath.StartsWith($repositoryPath.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Build output must stay outside the maintenance repository.'
}
if (Test-Path -LiteralPath $outputPath) {
    throw 'Choose a new output directory; existing builds are preserved.'
}
$referencePath = (Resolve-Path -LiteralPath $Net6References).Path
$harmonyPath = (Resolve-Path -LiteralPath $HarmonyDll).Path
$gitLibraryPath = (Resolve-Path -LiteralPath $LibGit2SharpDll).Path
$references = @(Get-ChildItem -LiteralPath $referencePath -Filter '*.dll' -File | ForEach-Object FullName)
if ($references.Count -lt 100 -or -not (Test-Path -LiteralPath (Join-Path $referencePath 'System.Runtime.dll'))) {
    throw 'A complete .NET 6 reference assembly set is required.'
}
$references += @($harmonyPath, $gitLibraryPath)
$sourceHashes = [ordered]@{}
$sourceTexts = [ordered]@{}
foreach ($compiledSource in $sourceFiles) {
    $sourceNameKey = [IO.Path]::GetFileName($compiledSource)
    $sourceBytes = [IO.File]::ReadAllBytes($compiledSource)
    $sourceHasher = [Security.Cryptography.SHA256]::Create()
    try { $sourceHashes[$sourceNameKey] = ([BitConverter]::ToString($sourceHasher.ComputeHash($sourceBytes))).Replace('-', '').ToLowerInvariant() } finally { $sourceHasher.Dispose() }
    # Parse the same cached bytes whose identity is recorded in the receipt.
    $sourceTexts[$sourceNameKey] = [Text.Encoding]::UTF8.GetString($sourceBytes).TrimStart([char]0xfeff)
}
$dependencyHashes = [ordered]@{}
foreach ($dependencyFile in $references) {
    $dependencyName = [IO.Path]::GetFileName($dependencyFile)
    if ($dependencyHashes.Contains($dependencyName)) { throw 'Ambiguous assembly reference name.' }
    $dependencyHashes[$dependencyName] = (Get-FileHash -LiteralPath $dependencyFile -Algorithm SHA256).Hash.ToLowerInvariant()
}
$null = New-Item -ItemType Directory -Path $outputPath
$assemblyName = if ($SourceName -eq 'StartupHook.cs') { 'Huishi.SingleGit.StartupHook' } elseif ($SourceName -eq 'AdapterTests.cs') { 'Huishi.Adapter.Tests' } else { 'Huishi.Adapter.Probe' }
$assembly = Join-Path $outputPath ($assemblyName + '.dll')
# Add-Type injects PowerShell's own framework references. Explicit Roslyn
# references keep the output loadable by the vendor's .NET 6 GUI.
$null = [Reflection.Assembly]::LoadFrom((Join-Path $PSHOME 'Microsoft.CodeAnalysis.dll'))
$null = [Reflection.Assembly]::LoadFrom((Join-Path $PSHOME 'Microsoft.CodeAnalysis.CSharp.dll'))
$syntax = [Microsoft.CodeAnalysis.SyntaxTree[]]@($sourceFiles | ForEach-Object {
    [Microsoft.CodeAnalysis.CSharp.SyntaxFactory]::ParseSyntaxTree($sourceTexts[[IO.Path]::GetFileName($_)])
})
$metadata = [Microsoft.CodeAnalysis.MetadataReference[]]@($references | ForEach-Object {
    [Microsoft.CodeAnalysis.MetadataReference]::CreateFromFile($_)
})
$kind = if ($SourceName -eq 'StartupHook.cs') { [Microsoft.CodeAnalysis.OutputKind]::DynamicallyLinkedLibrary } elseif ($SourceName -eq 'AdapterTests.cs') { [Microsoft.CodeAnalysis.OutputKind]::ConsoleApplication } else { [Microsoft.CodeAnalysis.OutputKind]::WindowsApplication }
$options = [Microsoft.CodeAnalysis.CSharp.CSharpCompilationOptions]::new($kind)
$compilation = [Microsoft.CodeAnalysis.CSharp.CSharpCompilation]::Create($assemblyName, [Microsoft.CodeAnalysis.SyntaxTree[]]$syntax, $metadata, $options)
$stream = [IO.File]::Open($assembly, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try { $result = $compilation.Emit($stream) } finally { $stream.Dispose() }
if (-not $result.Success) {
    $errors = @($result.Diagnostics | Where-Object Severity -eq 'Error' | ForEach-Object ToString)
    throw ('Compilation failed: ' + ($errors -join [Environment]::NewLine))
}
Copy-Item -LiteralPath $harmonyPath -Destination (Join-Path $outputPath '0Harmony.dll')
if ($SourceName -ne 'StartupHook.cs') {
    [IO.File]::WriteAllText((Join-Path $outputPath ($assemblyName + '.runtimeconfig.json')),
        '{"runtimeOptions":{"tfm":"net6.0","framework":{"name":"Microsoft.NETCore.App","version":"6.0.0"}}}', [Text.UTF8Encoding]::new($false))
}
# Stop if another owner changed a source or reference during the build. A receipt
# must identify every compiled source and dependency, rather than the first file.
foreach ($compiledSource in $sourceFiles) {
    if ((Get-FileHash -LiteralPath $compiledSource -Algorithm SHA256).Hash.ToLowerInvariant() -ne $sourceHashes[[IO.Path]::GetFileName($compiledSource)]) { throw 'Source changed during compilation.' }
}
foreach ($dependencyFile in $references) {
    if ((Get-FileHash -LiteralPath $dependencyFile -Algorithm SHA256).Hash.ToLowerInvariant() -ne $dependencyHashes[[IO.Path]::GetFileName($dependencyFile)]) { throw 'Reference changed during compilation.' }
}
$receipt = [pscustomobject]@{
    assembly = $assembly
    source_sha256 = $sourceHashes
    dependency_sha256 = $dependencyHashes
    assembly_sha256 = (Get-FileHash -LiteralPath $assembly -Algorithm SHA256).Hash.ToLowerInvariant()
    runtime_target = 'net6.0'
    deployed = $false
}
$receiptJson = $receipt | ConvertTo-Json -Depth 5
[IO.File]::WriteAllText((Join-Path $outputPath 'build.receipt.json'), $receiptJson, [Text.UTF8Encoding]::new($false))
$receiptJson
