#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend/full"

echo "=== Building frontend ==="
cd "$FRONTEND_DIR"
npx vite build
echo "=== Build complete ==="
echo ""

cleanup() {
    echo ""
    echo "=== Shutting down ==="
    kill $DJANGO_PID $VITE_PID 2>/dev/null
    wait $DJANGO_PID $VITE_PID 2>/dev/null
    exit 0
}
trap cleanup INT TERM

echo "=== Starting Django on :8000 ==="
cd "$PROJECT_DIR"
python manage.py runserver &
DJANGO_PID=$!

echo "=== Starting Vite on :9000 ==="
cd "$FRONTEND_DIR"
npx vite &
VITE_PID=$!

echo ""
echo "=== Both servers running. Ctrl+C to stop. ==="
echo ""

wait
