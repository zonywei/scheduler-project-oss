param(
    [switch]$Dev,
    [switch]$PipCheck,
    [switch]$SkipEntrypoint
)

chcp 65001 > $null
$env:PYTHONUTF8 = "1"
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$scriptPath = Join-Path $repoRoot "verification\fixes\verify_environment.py"

if (Test-Path $venvPython) {
    $python = $venvPython
    $argsList = @($scriptPath)
} else {
    $python = "py"
    $argsList = @("-3", $scriptPath)
}

if ($Dev) {
    $argsList += "--dev"
}
if ($PipCheck) {
    $argsList += "--pip-check"
}
if ($SkipEntrypoint) {
    $argsList += "--skip-entrypoint"
}

Write-Host "RUN: $python $($argsList -join ' ')"
& $python @argsList
exit $LASTEXITCODE
