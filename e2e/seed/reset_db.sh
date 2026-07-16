#!/usr/bin/env bash
# Drop and rebuild the dedicated E2E database from current migrations, then
# load the rebased seed (docs/plans/2026-07-07-e2e-test-platform.md §4.3).
# Invoked by global-setup.js on every `npx playwright test` run unless
# PW_KEEP_DB is set; safe to run by hand from any working directory:
#   DATABASE_NAME=minibini_e2e bash e2e/seed/reset_db.sh
set -euo pipefail

# Refuse to run against anything but the e2e schema — belt & braces.
[ "${DATABASE_NAME:-}" = "minibini_e2e" ] || { echo "DATABASE_NAME must be minibini_e2e" >&2; exit 1; }
export DATABASE_NAME  # the guard passes even for an unexported shell var; Django must see it

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PYTHON="${PYTHON:-$REPO_ROOT/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python

# Credentials: env vars, falling back to the settings.py defaults. Django also
# reads .env; the mysql CLI does not — export DATABASE_* if your creds live there.
mysql -u "${DATABASE_USER:-minibini_user}" -p"${DATABASE_PASSWORD:-dev_password}" \
  -h "${DATABASE_HOST:-localhost}" \
  -e "DROP DATABASE IF EXISTS minibini_e2e; CREATE DATABASE minibini_e2e CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

"$PYTHON" "$REPO_ROOT/manage.py" migrate --no-input
"$PYTHON" "$SCRIPT_DIR/prepare_seed.py"
"$PYTHON" "$REPO_ROOT/manage.py" loaddata "$REPO_ROOT/fixtures/playwright/rebased.json"

echo "minibini_e2e reset complete"
