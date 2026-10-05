[CmdletBinding()]
param(
    [ValidateSet('fixture', 'live')]
    [string]$Mode = 'fixture',

    [ValidateSet('danbooru', 'gelbooru', 'yandere', 'civitai')]
    [string[]]$Sites = @('danbooru', 'gelbooru', 'yandere', 'civitai'),

    [ValidateSet('enabled', 'ui-off', 'v2-off')]
    [string]$FeatureProfile = 'enabled',

    [string]$PythonPath = '',
    [string]$NodePath = '',
    [int]$StartupTimeoutSeconds = 90,
    [switch]$SkipUnitTests
)

function Get-SharedFileSha256 {
    param([Parameter(Mandatory = $true)][string]$LiteralPath)
    $stream = [System.IO.File]::Open(
        $LiteralPath,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite -bor [System.IO.FileShare]::Delete
    )
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return ([System.BitConverter]::ToString($sha.ComputeHash($stream))).Replace('-', '')
    } finally {
        $sha.Dispose()
        $stream.Dispose()
    }
}

function New-VerifiedSqliteSnapshot {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExecutable,
        [Parameter(Mandatory = $true)][string]$HelperPath,
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [Parameter(Mandatory = $true)][string]$Purpose
    )
    $snapshotOutput = @(
        & $PythonExecutable -X utf8 $HelperPath --source $Source --destination $Destination 2>&1
    )
    if ($LASTEXITCODE -ne 0) {
        throw "$Purpose failed: $($snapshotOutput -join [Environment]::NewLine)"
    }
    try {
        $snapshot = ($snapshotOutput -join [Environment]::NewLine) | ConvertFrom-Json
    } catch {
        throw "$Purpose returned invalid JSON: $($_.Exception.Message)"
    }
    if ($snapshot.status -ne 'ok' -or $snapshot.quickCheck -ne 'ok') {
        throw "$Purpose did not pass SQLite quick_check"
    }
    if (-not $snapshot.logicalFingerprint -or
        [string]$snapshot.logicalFingerprint.version -ne 'sqlite-logical-v1' -or
        [string]$snapshot.logicalFingerprint.sha256 -notmatch '^[0-9a-f]{64}$') {
        throw "$Purpose did not return a valid logical fingerprint"
    }
    return $snapshot
}

$ErrorActionPreference = 'Stop'
$plugin = [System.IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$customNodes = Split-Path -Parent $plugin
$comfy = Split-Path -Parent $customNodes
$workspace = Split-Path -Parent $comfy
$pluginName = Split-Path -Leaf $plugin

if (-not $PythonPath) { $PythonPath = Join-Path $workspace 'python\python.exe' }
if (-not $NodePath) {
    $bundledNode = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe'
    $NodePath = if (Test-Path -LiteralPath $bundledNode) { $bundledNode } else { 'node' }
}
if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw "Python executable not found: $PythonPath"
}
if ($NodePath -ne 'node' -and -not (Test-Path -LiteralPath $NodePath -PathType Leaf)) {
    throw "Node executable not found: $NodePath"
}
if ($StartupTimeoutSeconds -lt 15 -or $StartupTimeoutSeconds -gt 300) {
    throw 'StartupTimeoutSeconds must be between 15 and 300'
}

$listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
$listener.Start()
$port = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
$listener.Stop()
if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
    throw "Selected test port is already in use: $port"
}

$runId = "$(Get-Date -Format 'yyyyMMdd-HHmmss')-$([guid]::NewGuid().ToString('N').Substring(0, 8))"
$runtimeBase = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '.runtime'))
$runtime = [System.IO.Path]::GetFullPath((Join-Path $runtimeBase $runId))
if (-not $runtime.StartsWith($runtimeBase, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'Runtime path escaped tests/.runtime'
}

$runtimeUser = Join-Path $runtime 'user'
$runtimeTemp = Join-Path $runtime 'temp'
$runtimeOutput = Join-Path $runtime 'output'
$runtimeData = Join-Path $runtime 'plugin-data'
$runtimeLogs = Join-Path $runtimeData 'logs'
$quickPluginLogs = Join-Path $runtimeLogs 'quick-test'
$serverPluginLogs = Join-Path $runtimeLogs 'server'
New-Item -ItemType Directory -Force -Path $runtimeUser, $runtimeTemp, $runtimeOutput, $runtimeData, $runtimeLogs, $quickPluginLogs, $serverPluginLogs | Out-Null

$liveTagDb = [System.IO.Path]::GetFullPath((Join-Path $plugin 'py\shared\data\tags_cache.db'))
$isolatedTagDb = [System.IO.Path]::GetFullPath((Join-Path $runtimeData 'tags_cache.db'))
$liveTagDbBeforeSnapshot = [System.IO.Path]::GetFullPath((Join-Path $runtimeData 'live-tags-before.db'))
$liveTagDbAfterSnapshot = [System.IO.Path]::GetFullPath((Join-Path $runtimeData 'live-tags-after.db'))
$runtimeComfyDb = [System.IO.Path]::GetFullPath((Join-Path $runtime 'comfyui.db'))
$runtimeComfyDbUrl = 'sqlite:///' + ($runtimeComfyDb -replace '\\', '/')
$sqliteSnapshotHelper = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'sqlite_snapshot.py'))
if (-not (Test-Path -LiteralPath $liveTagDb -PathType Leaf)) {
    throw "Live tag database not found: $liveTagDb"
}
if (-not (Test-Path -LiteralPath $sqliteSnapshotHelper -PathType Leaf)) {
    throw "SQLite snapshot helper not found: $sqliteSnapshotHelper"
}

$v2Enabled = $FeatureProfile -ne 'v2-off'
$newUiEnabled = $FeatureProfile -eq 'enabled'
$providersProbed = [object[]]@()
if ($v2Enabled) { $providersProbed = [object[]]$Sites }
$testExpectations = @{
    v2Routes = $v2Enabled
    galleryUi = $newUiEnabled
    providersProbed = $providersProbed
    gelbooruApproxRank = $false
    civitaiCollected = $false
    civitaiPublicFreeText = $false
}
$featureFlags = @{
    v2_routes_enabled = $v2Enabled
    gallery_new_ui_enabled = $newUiEnabled
    provider_danbooru_v2 = $v2Enabled -and ($Sites -contains 'danbooru')
    provider_gelbooru_v2 = $v2Enabled -and ($Sites -contains 'gelbooru')
    provider_yandere_v2 = $v2Enabled -and ($Sites -contains 'yandere')
    provider_civitai_v2 = $v2Enabled -and ($Sites -contains 'civitai')
    gelbooru_approx_rank_enabled = $false
    yandere_html_popular_experimental = $false
    civitai_experimental_web = $false
}
$testConfigPath = Join-Path $runtime 'test-config.json'
$testConfig = @{
    schemaVersion = 1
    mode = $Mode
    featureProfile = $FeatureProfile
    sites = $Sites
    runtimeRoot = $runtime
    isolatedComfyUserRoot = $runtimeUser
    isolatedComfyTempRoot = $runtimeTemp
    isolatedComfyOutputRoot = $runtimeOutput
    isolatedComfyDatabase = $runtimeComfyDb
    isolatedTagDatabase = $isolatedTagDb
    isolatedPluginLogRoots = @($quickPluginLogs, $serverPluginLogs)
    featureFlags = $featureFlags
    expectations = $testExpectations
}
$testConfig | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $testConfigPath -Encoding UTF8

$server = $null
$startedAt = (Get-Date).ToUniversalTime()
$probePath = Join-Path $runtime 'api-probe.json'
$manifestPath = Join-Path $runtime 'manifest.json'
$serverStdout = Join-Path $runtime 'server.stdout.log'
$serverStderr = Join-Path $runtime 'server.stderr.log'
$oldFixtureMode = $env:DANBOORU_GALLERY_TEST_FIXTURES
$oldGalleryLogDir = $env:DANBOORU_GALLERY_LOG_DIR
$oldDeliveryTest = $env:DANBOORU_GALLERY_DELIVERY_TEST
$oldTestConfig = $env:DANBOORU_GALLERY_TEST_CONFIG
$oldTagDbPath = $env:DANBOORU_GALLERY_TAG_DB_PATH
$protectedPaths = @(
    (Join-Path $plugin 'config.json'),
    (Join-Path $plugin 'logs\danbooru_gallery.log')
)
$protectedBefore = @{}
$protectedAfter = @{}
foreach ($protectedPath in $protectedPaths) {
    $protectedBefore[$protectedPath] = if (Test-Path -LiteralPath $protectedPath -PathType Leaf) {
        Get-SharedFileSha256 -LiteralPath $protectedPath
    } else {
        '__ABSENT__'
    }
}
$finalState = 'FAIL'
$failureMessage = $null
$protectedStateUnchanged = $true
$liveTagDbSnapshotBeforeResult = $null
$liveTagDbSnapshotAfterResult = $null
$liveTagDbLogicalBefore = $null
$liveTagDbLogicalAfter = $null
$liveTagDbLogicalUnchanged = $false
$liveTagDbGuardState = 'PENDING'
$liveTagDbGuardFailure = $null

try {
    $liveTagDbSnapshotBeforeResult = New-VerifiedSqliteSnapshot `
        -PythonExecutable $PythonPath -HelperPath $sqliteSnapshotHelper `
        -Source $liveTagDb -Destination $liveTagDbBeforeSnapshot `
        -Purpose 'Live tag database pre-test snapshot'
    $liveTagDbLogicalBefore = $liveTagDbSnapshotBeforeResult.logicalFingerprint

    # Seed the delivery database from the immutable pre-test guard snapshot. This
    # avoids a second read of the live WAL state and gives the server an isolated DB.
    $null = New-VerifiedSqliteSnapshot `
        -PythonExecutable $PythonPath -HelperPath $sqliteSnapshotHelper `
        -Source $liveTagDbBeforeSnapshot -Destination $isolatedTagDb `
        -Purpose 'Isolated delivery tag database snapshot'

    $env:DANBOORU_GALLERY_TEST_FIXTURES = if ($Mode -eq 'fixture') { '1' } else { '0' }
    $env:DANBOORU_GALLERY_DELIVERY_TEST = '1'
    $env:DANBOORU_GALLERY_TEST_CONFIG = $testConfigPath
    $env:DANBOORU_GALLERY_TAG_DB_PATH = $isolatedTagDb
    $env:DANBOORU_GALLERY_LOG_DIR = $quickPluginLogs

    if (-not $SkipUnitTests) {
        # Unit tests intentionally create explicit temporary tag databases.
        # Scope the delivery-only DB override to the ComfyUI processes below;
        # otherwise the fail-closed runtime guard correctly rejects those test
        # databases and turns a safe delivery run into a false failure.
        $env:DANBOORU_GALLERY_DELIVERY_TEST = $oldDeliveryTest
        $env:DANBOORU_GALLERY_TEST_CONFIG = $oldTestConfig
        $env:DANBOORU_GALLERY_TAG_DB_PATH = $oldTagDbPath
        try {
            Push-Location $plugin
            try {
                # -P keeps the plugin's top-level `py` package from shadowing
                # pytest's own dependency while the suite imports v53 in isolation.
                & $PythonPath -P -m pytest -q tests
                if ($LASTEXITCODE -ne 0) { throw 'Python tests failed' }
                $jsTests = @(Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'js') -Filter '*.test.mjs' -File |
                    Sort-Object FullName |
                    ForEach-Object { $_.FullName })
                if ($jsTests.Count -eq 0) { throw 'No JavaScript tests were found' }
                & $NodePath --test @jsTests
                if ($LASTEXITCODE -ne 0) { throw 'JavaScript tests failed' }
            } finally {
                Pop-Location
            }
        } finally {
            $env:DANBOORU_GALLERY_DELIVERY_TEST = '1'
            $env:DANBOORU_GALLERY_TEST_CONFIG = $testConfigPath
            $env:DANBOORU_GALLERY_TAG_DB_PATH = $isolatedTagDb
        }
    }

    Push-Location $comfy
    try {
        $env:DANBOORU_GALLERY_LOG_DIR = $quickPluginLogs
        & $PythonPath -X utf8 (Join-Path $comfy 'main.py') --cpu --quick-test-for-ci `
            --disable-all-custom-nodes --whitelist-custom-nodes $pluginName `
            --user-directory $runtimeUser --temp-directory $runtimeTemp --output-directory $runtimeOutput `
            --database-url $runtimeComfyDbUrl
        if ($LASTEXITCODE -ne 0) { throw 'ComfyUI quick import failed' }

        $env:DANBOORU_GALLERY_LOG_DIR = $serverPluginLogs
        $serverArgs = @(
            '-X', 'utf8',
            (Join-Path $comfy 'main.py'),
            '--listen', '127.0.0.1',
            '--port', [string]$port,
            '--cpu',
            '--disable-all-custom-nodes',
            '--whitelist-custom-nodes', $pluginName,
            '--user-directory', $runtimeUser,
            '--temp-directory', $runtimeTemp,
            '--output-directory', $runtimeOutput,
            '--database-url', $runtimeComfyDbUrl
        )
        $server = Start-Process -FilePath $PythonPath -ArgumentList $serverArgs -WorkingDirectory $comfy `
            -PassThru -WindowStyle Hidden -RedirectStandardOutput $serverStdout -RedirectStandardError $serverStderr
    } finally {
        Pop-Location
        $env:DANBOORU_GALLERY_TEST_FIXTURES = $oldFixtureMode
        $env:DANBOORU_GALLERY_LOG_DIR = $oldGalleryLogDir
        $env:DANBOORU_GALLERY_DELIVERY_TEST = $oldDeliveryTest
        $env:DANBOORU_GALLERY_TEST_CONFIG = $oldTestConfig
        $env:DANBOORU_GALLERY_TAG_DB_PATH = $oldTagDbPath
    }

    $deadline = (Get-Date).AddSeconds($StartupTimeoutSeconds)
    $ready = $false
    while ((Get-Date) -lt $deadline) {
        if ($server.HasExited) { throw "Isolated ComfyUI exited during startup with code $($server.ExitCode)" }
        try {
            $health = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/system_stats" -TimeoutSec 2
            if ($health.StatusCode -eq 200) { $ready = $true; break }
        } catch {
            Start-Sleep -Milliseconds 300
        }
    }
    if (-not $ready) { throw "Isolated ComfyUI did not become ready within $StartupTimeoutSeconds seconds" }

    $owner = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction Stop |
        Where-Object { $_.LocalAddress -eq '127.0.0.1' } |
        Select-Object -First 1 -ExpandProperty OwningProcess
    if ([int]$owner -ne [int]$server.Id) {
        throw "Listener ownership mismatch: expected $($server.Id), found $owner"
    }

    $featureState = Invoke-RestMethod -UseBasicParsing -Uri "http://127.0.0.1:$port/danbooru_gallery/features" -TimeoutSec 5
    if ([bool]$featureState.featureFlags.v2_routes_enabled -ne [bool]$v2Enabled) {
        throw 'Feature endpoint v2_routes_enabled does not match the isolated test config'
    }
    if ([bool]$featureState.featureFlags.gallery_new_ui_enabled -ne [bool]$newUiEnabled) {
        throw 'Feature endpoint gallery_new_ui_enabled does not match the isolated test config'
    }

    if ($v2Enabled) {
        $siteArgument = $Sites -join ','
        & $NodePath (Join-Path $PSScriptRoot 'api_probe.mjs') "http://127.0.0.1:$port" $Mode $siteArgument |
            Set-Content -LiteralPath $probePath -Encoding UTF8
        if ($LASTEXITCODE -ne 0) { throw 'V53 API delivery probe failed' }
    } else {
        $v2Status = $null
        try {
            $unexpectedV2 = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$port/danbooru_gallery/v2/providers" -TimeoutSec 5
            $v2Status = [int]$unexpectedV2.StatusCode
        } catch {
            if ($_.Exception.Response) {
                $v2Status = [int]$_.Exception.Response.StatusCode
            } else {
                throw
            }
        }
        if ($v2Status -ne 404) { throw "V2 rollback drill expected HTTP 404, received $v2Status" }
        @{
            schemaVersion = 1
            mode = $Mode
            featureProfile = $FeatureProfile
            results = @(@{
                site = 'all'
                operation = 'v2_routes_disabled'
                state = 'PASS'
                httpStatus = $v2Status
            })
        } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $probePath -Encoding UTF8
    }

    $probe = Get-Content -LiteralPath $probePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (@($probe.results | Where-Object { $_.state -eq 'FAIL' }).Count -gt 0) {
        throw 'V53 API probe contains failed assertions'
    }
    foreach ($protectedPath in $protectedPaths) {
        $after = if (Test-Path -LiteralPath $protectedPath -PathType Leaf) {
            Get-SharedFileSha256 -LiteralPath $protectedPath
        } else {
            '__ABSENT__'
        }
        $protectedAfter[$protectedPath] = $after
        if ($after -ne $protectedBefore[$protectedPath]) {
            $protectedStateUnchanged = $false
            throw "Delivery test modified protected plugin state: $protectedPath"
        }
    }
    $finalState = 'PASS'
} catch {
    $failureMessage = $_.Exception.Message
    throw
} finally {
    $stoppedOwnServer = $false
    $serverHasExitedAfterCleanup = $null
    $portReleasedByStartedPid = $null
    $listenerOwnersAfterCleanup = @()
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()
    if ($server) {
        try {
            $server.Refresh()
            if (-not $server.HasExited) {
                $owned = Get-CimInstance Win32_Process -Filter "ProcessId = $($server.Id)" -ErrorAction Stop
                if (-not $owned -or $owned.CommandLine -notlike "*$comfy*main.py*") {
                    $cleanupErrors.Add("refused to stop PID $($server.Id) because its command line no longer matches the isolated ComfyUI server")
                } else {
                    Stop-Process -InputObject $server -ErrorAction Stop
                    Wait-Process -InputObject $server -Timeout 15 -ErrorAction Stop
                    $server.Refresh()
                    $stoppedOwnServer = $server.HasExited
                }
            }
        } catch {
            $cleanupErrors.Add("server stop failed: $($_.Exception.Message)")
        }

        try {
            $server.Refresh()
            $serverHasExitedAfterCleanup = [bool]$server.HasExited
            if (-not $serverHasExitedAfterCleanup) {
                $cleanupErrors.Add("isolated ComfyUI PID $($server.Id) is still running after cleanup")
            }
        } catch {
            $serverHasExitedAfterCleanup = $false
            $cleanupErrors.Add("could not refresh isolated ComfyUI PID $($server.Id): $($_.Exception.Message)")
        }

        $listenerQuerySucceeded = $true
        $startedPidStillOwnsPort = $true
        $portReleaseDeadline = (Get-Date).AddSeconds(5)
        do {
            try {
                $listenersAfterCleanup = @(Get-NetTCPConnection -State Listen -ErrorAction Stop |
                    Where-Object { [int]$_.LocalPort -eq [int]$port })
                $listenerOwnersAfterCleanup = @($listenersAfterCleanup |
                    Select-Object -ExpandProperty OwningProcess -Unique)
                $startedPidStillOwnsPort = @($listenersAfterCleanup |
                    Where-Object { [int]$_.OwningProcess -eq [int]$server.Id }).Count -gt 0
            } catch {
                $listenerQuerySucceeded = $false
                $cleanupErrors.Add("listener ownership verification failed: $($_.Exception.Message)")
                break
            }
            if (-not $startedPidStillOwnsPort) { break }
            Start-Sleep -Milliseconds 100
        } while ((Get-Date) -lt $portReleaseDeadline)
        $portReleasedByStartedPid = $listenerQuerySucceeded -and -not $startedPidStillOwnsPort
        if ($listenerQuerySucceeded -and -not $portReleasedByStartedPid) {
            $cleanupErrors.Add("isolated ComfyUI PID $($server.Id) still owns listener port $port after cleanup")
        }
    }
    $env:DANBOORU_GALLERY_TEST_FIXTURES = $oldFixtureMode
    $env:DANBOORU_GALLERY_LOG_DIR = $oldGalleryLogDir
    $env:DANBOORU_GALLERY_DELIVERY_TEST = $oldDeliveryTest
    $env:DANBOORU_GALLERY_TEST_CONFIG = $oldTestConfig
    $env:DANBOORU_GALLERY_TAG_DB_PATH = $oldTagDbPath

    try {
        $liveTagDbSnapshotAfterResult = New-VerifiedSqliteSnapshot `
            -PythonExecutable $PythonPath -HelperPath $sqliteSnapshotHelper `
            -Source $liveTagDb -Destination $liveTagDbAfterSnapshot `
            -Purpose 'Live tag database post-test snapshot'
        $liveTagDbLogicalAfter = $liveTagDbSnapshotAfterResult.logicalFingerprint
        if (-not $liveTagDbLogicalBefore) {
            throw 'pre-test logical fingerprint is unavailable'
        }
        if ($liveTagDbLogicalBefore.sha256 -ne $liveTagDbLogicalAfter.sha256) {
            throw "logical fingerprint changed from $($liveTagDbLogicalBefore.sha256) to $($liveTagDbLogicalAfter.sha256)"
        }
        $liveTagDbLogicalUnchanged = $true
        $liveTagDbGuardState = 'PASS'
    } catch {
        $liveTagDbGuardState = 'FAIL'
        $liveTagDbGuardFailure = "Live tag database protection failed: $($_.Exception.Message)"
        $finalState = 'FAIL'
        $failureMessage = if ($failureMessage) {
            "$failureMessage; $liveTagDbGuardFailure"
        } else {
            $liveTagDbGuardFailure
        }
    }

    foreach ($protectedPath in $protectedPaths) {
        $after = if (Test-Path -LiteralPath $protectedPath -PathType Leaf) {
            Get-SharedFileSha256 -LiteralPath $protectedPath
        } else {
            '__ABSENT__'
        }
        $protectedAfter[$protectedPath] = $after
        if ($after -ne $protectedBefore[$protectedPath]) {
            $protectedStateUnchanged = $false
        }
    }

    if (-not $protectedStateUnchanged -and $finalState -eq 'PASS') {
        $finalState = 'FAIL'
        $failureMessage = 'Delivery cleanup detected modified protected plugin state'
    }
    $cleanupSucceeded = $cleanupErrors.Count -eq 0
    $cleanupFailureMessage = if ($cleanupSucceeded) { $null } else { $cleanupErrors -join '; ' }
    if (-not $cleanupSucceeded) {
        $finalState = 'FAIL'
        $failureMessage = if ($failureMessage) {
            "$failureMessage; cleanup failed: $cleanupFailureMessage"
        } else {
            "Cleanup failed: $cleanupFailureMessage"
        }
    }

    $artifactHashes = @{}
    foreach ($artifact in @(
        $testConfigPath,
        $probePath,
        $serverStdout,
        $serverStderr,
        $isolatedTagDb,
        $liveTagDbBeforeSnapshot,
        $liveTagDbAfterSnapshot,
        $runtimeComfyDb
    )) {
        if (Test-Path -LiteralPath $artifact -PathType Leaf) {
            $artifactHashes[(Split-Path -Leaf $artifact)] = Get-SharedFileSha256 -LiteralPath $artifact
        }
    }
    foreach ($logKind in @('quick-test', 'server')) {
        $pluginLog = Join-Path (Join-Path $runtimeLogs $logKind) 'danbooru_gallery.log'
        if (Test-Path -LiteralPath $pluginLog -PathType Leaf) {
            $artifactHashes["plugin-$logKind.log"] = Get-SharedFileSha256 -LiteralPath $pluginLog
        }
    }
    $manifest = @{
        schemaVersion = 1
        runId = $runId
        mode = $Mode
        featureProfile = $FeatureProfile
        sites = $Sites
        state = $finalState
        failure = $failureMessage
        startedAt = $startedAt.ToString('o')
        finishedAt = (Get-Date).ToUniversalTime().ToString('o')
        origin = "http://127.0.0.1:$port"
        processId = if ($server) { $server.Id } else { $null }
        stoppedOwnServer = $stoppedOwnServer
        cleanupState = if ($cleanupSucceeded) { 'PASS' } else { 'FAIL' }
        cleanupFailure = $cleanupFailureMessage
        serverHasExitedAfterCleanup = $serverHasExitedAfterCleanup
        portReleasedByStartedPid = $portReleasedByStartedPid
        listenerOwnersAfterCleanup = $listenerOwnersAfterCleanup
        expectations = $testExpectations
        featureFlags = $featureFlags
        protectedPluginStateUnchanged = [bool]($protectedStateUnchanged -and $liveTagDbLogicalUnchanged)
        protectedFileStateUnchanged = $protectedStateUnchanged
        protectedFileHashesBefore = $protectedBefore
        protectedFileHashesAfter = $protectedAfter
        liveTagDatabaseProtection = @{
            state = $liveTagDbGuardState
            failure = $liveTagDbGuardFailure
            logicalStateUnchanged = $liveTagDbLogicalUnchanged
            beforeSnapshot = $liveTagDbBeforeSnapshot
            afterSnapshot = $liveTagDbAfterSnapshot
            before = $liveTagDbLogicalBefore
            after = $liveTagDbLogicalAfter
            beforeSnapshotResult = $liveTagDbSnapshotBeforeResult
            afterSnapshotResult = $liveTagDbSnapshotAfterResult
        }
        isolatedTagDatabase = $isolatedTagDb
        isolatedComfyDatabase = $runtimeComfyDb
        artifacts = $artifactHashes
        sanitizerVersion = 'v53-1'
    }
    $manifest | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
}

Write-Output "Delivery run: $runtime"
Write-Output "Manifest: $manifestPath"
if ($finalState -ne 'PASS') { exit 1 }
