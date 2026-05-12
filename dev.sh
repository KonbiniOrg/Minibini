#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"

echo "=== Building frontend ==="
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
$PYTHON manage.py runserver 0.0.0.0:8000 &
DJANGO_PID=$!

echo "=== Starting Vite on :9000 ==="
cd "$FRONTEND_DIR"
npx vite --host 0.0.0.0 &
VITE_PID=$!

echo ""
echo "=== Both servers running. Ctrl+C to stop. ==="
echo ""

wait
