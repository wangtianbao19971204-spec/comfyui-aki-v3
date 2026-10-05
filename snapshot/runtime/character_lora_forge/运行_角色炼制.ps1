param(
    [string]$Config = "characters\rosasha\character.json",
    [ValidateSet("doctor", "plan", "generate", "score", "run", "promote")]
    [string]$Action = "doctor",
    [string]$RunId = "",
    [int]$Limit = 0,
    [switch]$NoLLM,
    [switch]$AutoPromote
)

$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = (Resolve-Path (Join-Path $projectRoot "..\python\python.exe")).Path
$forge = Join-Path $projectRoot "forge.py"
$arguments = @($forge, "--config", (Join-Path $projectRoot $Config), $Action)

if ($RunId) {
    $arguments += @("--run-id", $RunId)
}
if ($Limit -gt 0 -and $Action -in @("generate", "score", "run")) {
    $arguments += @("--limit", $Limit)
}
if ($NoLLM -and $Action -in @("score", "run")) {
    $arguments += "--no-llm"
}
if ($AutoPromote -and $Action -in @("score", "run")) {
    $arguments += "--auto-promote"
}

Push-Location $projectRoot
try {
    & $pythonExe @arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
