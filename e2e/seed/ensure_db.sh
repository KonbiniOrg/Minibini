#!/usr/bin/env bash
# Create this checkout's e2e database if it doesn't exist yet. Run by the
# Django webServer command in playwright.config.js: Playwright starts the
# web servers *before* globalSetup's reset_db.sh, and Django won't start
# against a missing database (first run of a new MINIBINI_SLOT).
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/db_guard.sh"
mysql -u "${DATABASE_USER:-minibini_user}" -p"${DATABASE_PASSWORD:-dev_password}" \
  -h "${DATABASE_HOST:-localhost}" \
  -e "CREATE DATABASE IF NOT EXISTS $DATABASE_NAME CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
