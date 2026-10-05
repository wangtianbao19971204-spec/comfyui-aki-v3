param(
    [ValidateSet("doctor", "prepare", "command", "dashboard", "submit", "train", "status")]
    [string]$Action = "doctor",
    [string]$Profile = "profiles\rosasha.json",
    [string]$RunId = "",
    [switch]$VerifyModelHash
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot "..\python\python.exe"
$EntryPoint = Join-Path $ProjectRoot "anima_lora.py"

if (-not (Test-Path -LiteralPath $PythonExe)) {
    throw "找不到绘世 Python: $PythonExe"
}

$Arguments = @($EntryPoint, "--profile", $Profile, $Action)
if ($RunId) {
    $Arguments += @("--run-id", $RunId)
}
if ($VerifyModelHash -and $Action -eq "doctor") {
    $Arguments += "--verify-model-hash"
}

Push-Location $ProjectRoot
try {
    & $PythonExe @Arguments
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
