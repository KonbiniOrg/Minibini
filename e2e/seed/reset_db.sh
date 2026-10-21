#!/usr/bin/env bash
# Drop and rebuild the dedicated E2E database from current migrations, then
# load the rebased seed (docs/designs/e2e-testing.md §3).
# Invoked by global-setup.js on every `npx playwright test` run unless
# PW_KEEP_DB is set; safe to run by hand from any working directory:
#   DATABASE_NAME=minibini_e2e bash e2e/seed/reset_db.sh
# (or minibini_e2e_s<N> for a MINIBINI_SLOT checkout — see e2e/lib/slot.js)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/db_guard.sh"  # refuses anything but an e2e schema
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PYTHON="${PYTHON:-$REPO_ROOT/venv/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python

# Credentials: env vars, falling back to the settings.py defaults. Django also
# reads .env; the mysql CLI does not — export DATABASE_* if your creds live there.
mysql -u "${DATABASE_USER:-minibini_user}" -p"${DATABASE_PASSWORD:-dev_password}" \
  -h "${DATABASE_HOST:-localhost}" \
  -e "DROP DATABASE IF EXISTS $DATABASE_NAME; CREATE DATABASE $DATABASE_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

"$PYTHON" "$REPO_ROOT/manage.py" migrate --no-input
"$PYTHON" "$SCRIPT_DIR/prepare_seed.py"
"$PYTHON" "$REPO_ROOT/manage.py" loaddata "$REPO_ROOT/fixtures/playwright/rebased.json"

echo "$DATABASE_NAME reset complete"
