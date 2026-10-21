# Sourced by reset_db.sh and ensure_db.sh. Refuses anything but an e2e
# schema — belt & braces that keeps these scripts off the dev database.
# Valid: minibini_e2e, or minibini_e2e_s1..s9 for a MINIBINI_SLOT checkout
# (e2e/lib/slot.js). The name is interpolated into SQL, so this is also
# what keeps injected SQL out.
[[ "${DATABASE_NAME:-}" =~ ^minibini_e2e(_s[1-9])?$ ]] || { echo "DATABASE_NAME must be minibini_e2e or minibini_e2e_s<1-9>" >&2; exit 1; }
export DATABASE_NAME  # the guard passes even for an unexported shell var; Django must see it
