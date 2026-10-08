param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$EntrySettings,
    [Parameter(Mandatory=$true)][string]$AdditionalHook,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [ValidateSet('inspect','extract')][string]$Mode = 'extract'
)

# Only an already prepared empty, vendor-pinned isolation copy is accepted.
# The second hook exits before the GUI Main/UI. It never starts a service.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($Root)
$taskOut = [IO.Path]::GetFullPath($OutputDirectory)
$taskCfg = Get-Content -LiteralPath $EntrySettings -Raw | ConvertFrom-Json
if ((Split-Path -Leaf $taskRoot) -notlike 'archive-gui-*' -or (Test-Path -LiteralPath $taskOut) -or
    (Test-Path -LiteralPath (Join-Path $taskRoot 'python/python.exe')) -or
    (Test-Path -LiteralPath (Join-Path $taskRoot 'python/pythonw.exe'))) { throw 'An empty fresh archive isolation copy is required.' }
$taskGui = Join-Path $taskRoot '.launcher/StableDiffusionWebUILauncher.dll'
if ((Get-FileHash -LiteralPath $taskGui -Algorithm SHA256).Hash.ToLowerInvariant() -ne 'c6b569a1c7f00be362512ed4047a43ff20945baa47d1e2898ccbc052df2bfc2e') { throw 'The pinned vendor GUI is required.' }
if ((Get-FileHash -LiteralPath $taskCfg.hook -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskCfg.hook_sha256) { throw 'Adapter hook differs from the reviewed entry settings.' }
$null = New-Item -ItemType Directory -Path $taskOut
$taskStart = [Diagnostics.ProcessStartInfo]::new((Join-Path $taskRoot '.launcher/StableDiffusionWebUILauncher.exe'))
$taskStart.WorkingDirectory = $taskRoot
$taskStart.UseShellExecute = $false
$taskStart.CreateNoWindow = $true
$taskStart.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
$taskStart.RedirectStandardError = $true
$taskStart.RedirectStandardOutput = $true
foreach ($taskKey in @($taskStart.Environment.Keys)) {
    if ($taskKey -match '(?i)(^HUISHI_|^AKI_HUISHI_|TOKEN$|SECRET$|PASSWORD$|PASSWD$|API_KEY$|ACCESS_KEY$|PRIVATE_KEY$|CREDENTIALS?$|COOKIES?$|JWT$|^DOTNET_STARTUP_HOOKS$|^AUTHORIZATION$|^HTTP_AUTHORIZATION$)') {
        $null = $taskStart.Environment.Remove($taskKey)
    }
}
$taskStart.Environment['DOTNET_STARTUP_HOOKS'] = $taskCfg.hook + ';' + [IO.Path]::GetFullPath($AdditionalHook)
$taskStart.Environment['HUISHI_ADAPTER_ROOT'] = $taskRoot
$taskStart.Environment['HUISHI_MAINTENANCE_REPO'] = $taskCfg.maintenance_repo
$taskStart.Environment['HUISHI_CORE_BASELINE'] = $taskCfg.core_baseline
$taskStart.Environment['HUISHI_ADAPTER_LOG'] = Join-Path $taskOut 'adapter.log'
$taskStart.Environment['HUISHI_ADAPTER_MODE'] = 'isolation'
$taskStart.Environment['HUISHI_ADAPTER_INIT_ORIGINAL_FIRST'] = '1'
$taskStart.Environment['HUISHI_ARCHIVE_TEST_OUT'] = $taskOut
$taskStart.Environment['HUISHI_ARCHIVE_TEST_MODE'] = $Mode
$taskChild = [Diagnostics.Process]::Start($taskStart)
try {
    if (!$taskChild.WaitForExit(20000)) { $taskChild.Kill(); throw 'Own archive probe process timed out.' }
    [IO.File]::WriteAllText((Join-Path $taskOut 'stdout-private.txt'), $taskChild.StandardOutput.ReadToEnd())
    [IO.File]::WriteAllText((Join-Path $taskOut 'stderr-private.txt'), $taskChild.StandardError.ReadToEnd())
    [pscustomobject]@{ exit_code=$taskChild.ExitCode; mode=$Mode; production_deployed=$false } | ConvertTo-Json
    if ($taskChild.ExitCode -ne 0) { throw 'Archive isolation probe failed; inspect the private report.' }
} finally { $taskChild.Dispose() }
Get-Content -LiteralPath (Join-Path $taskOut 'archive-report.json')
