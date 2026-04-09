# Local Test Runner Script
# Usage:
#   .\run_tests.ps1                    # Run all tests with auto-detected workers
#   .\run_tests.ps1 -Workers 4          # Run with 4 workers
#   .\run_tests.ps1 -Mark "fast"        # Run only fast tests
#   .\run_tests.ps1 -Mark "smoke"       # Run only smoke tests
#   .\run_tests.ps1 -Role "shipper"     # Run shipper tests
#   .\run_tests.ps1 -Coverage           # Run with coverage report

param(
    [int]$Workers = 0,           # 0 = auto-detect, N = specific worker count
    [string]$Mark = "",         # Test marker filter (e.g., "fast", "smoke", "integration")
    [string]$Role = "",         # Role filter (shipper, driver, dispatcher, auth)
    [switch]$Coverage,          # Generate coverage report
    [switch]$Report,            # Generate HTML report
    [string]$Config = "testing" # testing, ci, local
)

$ErrorActionPreference = "Stop"
$BackendDir = Join-Path $PSScriptRoot "backend"

# Detect Python executable
$PythonCmd = if ($IsWindows) { "python" } else { "python3" }

# Ensure dependencies are installed
Write-Host "[1/4] Checking dependencies..." -ForegroundColor Cyan
& $PythonCmd -m pip install -r "$BackendDir/requirements-all.txt" --quiet 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[!] Failed to install dependencies" -ForegroundColor Red
    exit 1
}

# Build pytest command
$PytestArgs = @("-v", "--tb=short")

# Worker count
if ($Workers -gt 0) {
    $PytestArgs += "-n", $Workers
} else {
    $PytestArgs += "-n", "auto"
}

# Markers
if ($Mark) {
    $PytestArgs += "-m", $Mark
    Write-Host "[INFO] Running tests with marker: $Mark" -ForegroundColor Yellow
}

if ($Role) {
    $RoleMap = @{
        "shipper"    = "shipper"
        "driver"     = "driver"
        "dispatcher" = "dispatcher"
        "auth"       = "auth"
    }
    if ($RoleMap.ContainsKey($Role)) {
        $PytestArgs += "-m", $RoleMap[$Role]
        Write-Host "[INFO] Running tests for role: $Role" -ForegroundColor Yellow
    }
}

# Coverage
if ($Coverage) {
    $PytestArgs += "--cov=app", "--cov-report=term-missing", "--cov-report=html"
    Write-Host "[INFO] Coverage report enabled" -ForegroundColor Yellow
}

# HTML Report
if ($Report) {
    $PytestArgs += "--html=pytest_report.html", "--self-contained-html"
    Write-Host "[INFO] HTML report will be generated" -ForegroundColor Yellow
}

# Config-specific settings
switch ($Config) {
    "ci" {
        Write-Host "[INFO] CI mode: verbose output" -ForegroundColor Yellow
        $PytestArgs += "--junitxml=results.xml"
    }
    "testing" {
        Write-Host "[INFO] Testing mode: optimized for speed" -ForegroundColor Yellow
    }
    "local" {
        Write-Host "[INFO] Local mode: detailed output" -ForegroundColor Yellow
        $PytestArgs += "--capture=no"
    }
}

Write-Host "[2/4] Cleaning previous test artifacts..." -ForegroundColor Cyan
$TestDbDir = Join-Path $BackendDir "tests\.test_dbs"
if (Test-Path $TestDbDir) {
    Remove-Item -Path $TestDbDir -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host "[3/4] Running tests..." -ForegroundColor Cyan
Write-Host "Command: pytest $($PytestArgs -join ' ')" -ForegroundColor Gray

# Run pytest
Push-Location $BackendDir
try {
    $StartTime = Get-Date
    
    & python -m pytest @PytestArgs
    
    $ExitCode = $LASTEXITCODE
    $Duration = (Get-Date) - $StartTime
    
    Write-Host "[4/4] Test run completed in $([math]::Round($Duration.TotalSeconds, 2))s" -ForegroundColor Cyan
    
    if ($ExitCode -eq 0) {
        Write-Host "[PASS] All tests passed!" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] Some tests failed (exit code: $ExitCode)" -ForegroundColor Red
    }
    
    # Show coverage report location if generated
    if ($Coverage -and (Test-Path "htmlcov")) {
        Write-Host "`nCoverage report: $BackendDir\htmlcov\index.html" -ForegroundColor Cyan
    }
    
    if ($Report -and (Test-Path "pytest_report.html")) {
        Write-Host "HTML report: $BackendDir\pytest_report.html" -ForegroundColor Cyan
    }
    
    exit $ExitCode
}
finally {
    Pop-Location
}

<#
.SYNOPSIS
    Local test runner with parallel execution support.

.DESCRIPTION
    This script runs pytest with parallel execution (-n auto) and provides
    convenient shortcuts for running specific test categories.

.EXAMPLES
    # Run all tests with auto-detected workers
    .\run_tests.ps1

    # Run with 4 workers
    .\run_tests.ps1 -Workers 4

    # Run only fast tests
    .\run_tests.ps1 -Mark "fast"

    # Run smoke tests
    .\run_tests.ps1 -Mark "smoke"

    # Run only shipper tests
    .\run_tests.ps1 -Role "shipper"

    # Run with coverage
    .\run_tests.ps1 -Coverage

    # Generate HTML report
    .\run_tests.ps1 -Report

    # CI mode
    .\run_tests.ps1 -Config ci
#>
