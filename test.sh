#!/bin/bash
# Run the frontend (Vitest) and backend (Django) test suites — peer of dev.sh.
#
#   ./test.sh              both suites (frontend, then backend)
#   ./test.sh frontend     frontend only          (alias: fe)
#   ./test.sh backend ...   backend only; extra args pass through to manage.py test
#                          (alias: be) e.g. ./test.sh backend tests.test_fee_model
#
# Runs both suites even if the first fails, prints a summary, and exits
# non-zero if either suite failed. Backend tests are NOT piped, so the exit
# code is Django's real result, not a pipe's.

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"

run_frontend=1
run_backend=1
backend_args=()

case "$1" in
    frontend|fe) run_backend=0; shift ;;
    backend|be)  run_frontend=0; shift; backend_args=("$@") ;;
    "") ;;
    *) backend_args=("$@") ;;   # bare extra args → forwarded to the backend suite
esac

FRONTEND_RC=0
BACKEND_RC=0

if [ "$run_frontend" -eq 1 ]; then
    echo "=== Frontend tests (Vitest) ==="
    cd "$FRONTEND_DIR" && npm run test:run
    FRONTEND_RC=$?
    echo ""
fi

if [ "$run_backend" -eq 1 ]; then
    echo "=== Backend tests (Django) ==="
    cd "$PROJECT_DIR" && "$PYTHON" manage.py test "${backend_args[@]}"
    BACKEND_RC=$?
    echo ""
fi

echo "=== Summary ==="
[ "$run_frontend" -eq 1 ] && { [ "$FRONTEND_RC" -eq 0 ] && echo "  frontend: PASS" || echo "  frontend: FAIL ($FRONTEND_RC)"; }
[ "$run_backend"  -eq 1 ] && { [ "$BACKEND_RC"  -eq 0 ] && echo "  backend:  PASS" || echo "  backend:  FAIL ($BACKEND_RC)"; }

[ "$FRONTEND_RC" -eq 0 ] && [ "$BACKEND_RC" -eq 0 ] && exit 0
exit 1
