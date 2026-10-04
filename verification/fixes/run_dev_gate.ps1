param(
    [switch]$IncludeLocalSmoke
)

chcp 65001 > $null
$env:PYTHONUTF8="1"
$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$scriptPath = Join-Path $PSScriptRoot "run_dev_gate.py"

if (Test-Path $venvPython) {
    $python = $venvPython
    $argsList = @($scriptPath)
} else {
    $python = "py"
    $argsList = @("-3", $scriptPath)
}

if ($IncludeLocalSmoke) {
    $argsList += "--include-local-smoke"
}

Write-Host "RUN: $python $($argsList -join ' ')"
& $python @argsList
exit $LASTEXITCODE
