#!/bin/bash
# Local Test Runner Script (Linux/macOS)
# Usage:
#   ./run_tests.sh                    # Run all tests with auto-detected workers
#   ./run_tests.sh -w 4               # Run with 4 workers
#   ./run_tests.sh -m "fast"          # Run only fast tests
#   ./run_tests.sh -m "smoke"         # Run only smoke tests
#   ./run_tests.sh -r "shipper"       # Run shipper tests
#   ./run_tests.sh -c                 # Run with coverage report

set -e

BACKEND_DIR="$(cd "$(dirname "$0")" && pwd)"

# Defaults
WORKERS=""
MARK=""
ROLE=""
COVERAGE=false
REPORT=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -w|--workers)
            WORKERS="-n $2"
            shift 2
            ;;
        -m|--mark)
            MARK="-m $2"
            echo "[INFO] Running tests with marker: $2"
            shift 2
            ;;
        -r|--role)
            case $2 in
                shipper) ROLE="-m shipper" ;;
                driver) ROLE="-m driver" ;;
                dispatcher) ROLE="-m dispatcher" ;;
                auth) ROLE="-m auth" ;;
                *) echo "[WARN] Unknown role: $2" ;;
            esac
            echo "[INFO] Running tests for role: $2"
            shift 2
            ;;
        -c|--coverage)
            COVERAGE=true
            shift
            ;;
        --report)
            REPORT=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Auto-detect workers if not specified
if [ -z "$WORKERS" ]; then
    if command -v nproc &> /dev/null; then
        WORKERS="-n $(nproc)"
    elif command -v sysctl &> /dev/null; then
        WORKERS="-n $(sysctl -n hw.ncpu)"
    else
        WORKERS="-n 2"
    fi
fi

# Ensure dependencies are installed
echo "[1/4] Checking dependencies..."
cd "$BACKEND_DIR"
pip install -r requirements-all.txt -q

# Build pytest command
PYTEST_ARGS=("-v" "--tb=short")
PYTEST_ARGS+=($WORKERS)

if [ -n "$MARK" ]; then
    PYTEST_ARGS+=($MARK)
fi

if [ -n "$ROLE" ]; then
    PYTEST_ARGS+=($ROLE)
fi

if [ "$COVERAGE" = true ]; then
    PYTEST_ARGS+=("--cov=app" "--cov-report=term-missing" "--cov-report=html")
    echo "[INFO] Coverage report enabled"
fi

if [ "$REPORT" = true ]; then
    PYTEST_ARGS+=("--html=pytest_report.html" "--self-contained-html")
    echo "[INFO] HTML report will be generated"
fi

echo "[2/4] Cleaning previous test artifacts..."
rm -rf "$BACKEND_DIR/tests/.test_dbs"

echo "[3/4] Running tests..."
echo "Command: pytest ${PYTEST_ARGS[*]}"

START_TIME=$(date +%s)

pytest "${PYTEST_ARGS[@]}"
EXIT_CODE=$?

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo "[4/4] Test run completed in ${DURATION}s"

if [ $EXIT_CODE -eq 0 ]; then
    echo "[PASS] All tests passed!"
else
    echo "[FAIL] Some tests failed (exit code: $EXIT_CODE)"
fi

# Show coverage report location if generated
if [ "$COVERAGE" = true ] && [ -d "htmlcov" ]; then
    echo -e "\nCoverage report: $BACKEND_DIR/htmlcov/index.html"
fi

if [ "$REPORT" = true ] && [ -f "pytest_report.html" ]; then
    echo "HTML report: $BACKEND_DIR/pytest_report.html"
fi

exit $EXIT_CODE
