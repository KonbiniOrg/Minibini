#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VARIANT="${1:-lite}"
FRONTEND_DIR="$PROJECT_DIR/frontend/$VARIANT"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"

if [ ! -d "$FRONTEND_DIR" ]; then
    echo "Error: frontend variant '$VARIANT' not found at $FRONTEND_DIR"
    exit 1
fi

echo "=== Building frontend ($VARIANT) ==="
cd "$FRONTEND_DIR"
npx vite build
echo "=== Build complete ==="
echo ""

cleanup() {
    echo ""
    echo "=== Shutting down ==="
    kill $DJANGO_PID $VITE_PID 2>/dev/null
    pkill -P $DJANGO_PID 2>/dev/null
    pkill -P $VITE_PID 2>/dev/null
    lsof -ti :8000,:9000 2>/dev/null | xargs kill 2>/dev/null
    wait 2>/dev/null
    exit 0
}
trap cleanup INT TERM

echo "=== Starting Django on :8000 ==="
cd "$PROJECT_DIR"
$PYTHON manage.py runserver &
DJANGO_PID=$!

echo "=== Starting Vite on :9000 ==="
cd "$FRONTEND_DIR"
npx vite &
VITE_PID=$!

echo ""
echo "=== Both servers running ($VARIANT). Ctrl+C to stop. ==="
echo ""

wait
