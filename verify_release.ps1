param(
    [string]$PythonExecutable = ""
)

chcp 65001 > $null
$env:PYTHONUTF8 = "1"
$ErrorActionPreference = "Stop"

function Fail-AndExit {
    param(
        [string]$Message,
        [int]$Code = 1
    )
    Write-Host "FAIL: $Message"
    exit $Code
}

$repoRoot = Resolve-Path $PSScriptRoot
$venvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
$pythonPrefix = @()

if (-not [string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $python = $PythonExecutable
} elseif (Test-Path $venvPython) {
    $python = $venvPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $python = "py"
    $pythonPrefix = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $python = "python"
} else {
    Fail-AndExit "no Python interpreter found; create .venv or pass -PythonExecutable"
}

function Invoke-ProjectPython {
    param(
        [string]$Step,
        [string]$Display,
        [string[]]$Arguments,
        [string]$Failure
    )
    $commandArgs = @($script:pythonPrefix) + @($Arguments)
    Write-Host "RUN: $Step) $script:python $Display"
    & $script:python @commandArgs
    if ($LASTEXITCODE -ne 0) {
        Fail-AndExit "$Failure (exit code: $LASTEXITCODE)" $LASTEXITCODE
    }
}

Write-Host "=== PRE-RELEASE HEALTH CHECK ==="
Write-Host ("Timestamp: {0}" -f (Get-Date -Format o))
Write-Host ("Python: {0} {1}" -f $python, ($pythonPrefix -join " "))

Push-Location $repoRoot
try {
    $porcelain = git status --porcelain
    if ($LASTEXITCODE -ne 0) {
        Fail-AndExit "git status --porcelain failed (exit code: $LASTEXITCODE)"
    }
    if (-not [string]::IsNullOrWhiteSpace($porcelain)) {
        Write-Host "FAIL: git working tree is not clean."
        Write-Host $porcelain
        exit 1
    }

    foreach ($requiredPath in @("requirements.txt", "pyproject.toml", "docs\k12_platform_execution_plan.md")) {
        if (-not (Test-Path $requiredPath)) {
            Fail-AndExit "$requiredPath not found"
        }
    }

    Invoke-ProjectPython `
        -Step "a" `
        -Display "run.py --help" `
        -Arguments @("run.py", "--help") `
        -Failure "scheduler CLI help check failed"

    Invoke-ProjectPython `
        -Step "b" `
        -Display "verification/fixes/run_dev_gate.py" `
        -Arguments @("verification/fixes/run_dev_gate.py") `
        -Failure "development gate failed"

    Invoke-ProjectPython `
        -Step "c" `
        -Display "verification/fixes/ai_or_acceptance_audit.py" `
        -Arguments @("verification/fixes/ai_or_acceptance_audit.py") `
        -Failure "generic AI OR framework acceptance audit failed"

    Invoke-ProjectPython `
        -Step "d" `
        -Display "verification/fixes/commercial_acceptance_audit.py --strict-release" `
        -Arguments @("verification/fixes/commercial_acceptance_audit.py", "--strict-release") `
        -Failure "strict commercial acceptance audit failed"

    Write-Host "NOTE: use Get-Content outputs/meta/explain_summary_latest.md -Encoding UTF8 -TotalCount 60 on Windows PowerShell 5.1"
    Write-Host "PROJECT HEALTH: PASS"
} catch {
    Fail-AndExit ("unhandled error: " + $_.Exception.Message) 1
} finally {
    Pop-Location
}
