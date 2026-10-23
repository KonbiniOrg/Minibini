#!/bin/bash
# PreToolUse guard for Django test runs (see CLAUDE.md > Testing).
# Blocks two whole-session failure modes before they start:
#   1. `manage.py test` without --noinput: a stale test DB (left by any
#      killed run) triggers an interactive delete prompt that hangs
#      non-interactive shells (subagents) forever.
#   2. Two Django test runs on the SAME test database: they deadlock fighting
#      over its creation/destruction. Runs in checkouts with different
#      MINIBINI_SLOT values use different test DBs and may run side by side
#      (docs/designs/e2e-testing.md §4).
# Reads the Bash tool call as JSON on stdin; prints a deny decision when
# a rule trips, stays silent otherwise.
input=$(cat)
c=$(printf '%s' "$input" | jq -r '.tool_input.command // ""' 2>/dev/null)
# Only an actual `manage.py test` invocation counts: quoted text is dropped
# first, so `pgrep -f "manage.py test"` or `grep "manage.py test"` pass, and
# `test` must be the whole subcommand (not `testserver`). Commands wrapped in
# a quoted `bash -c "..."` are not seen.
unquoted=$(printf '%s' "$c" | sed -E "s/'[^']*'//g; s/\"[^\"]*\"//g")
printf '%s' "$unquoted" | grep -Eq '(^|[[:space:];&|(/])manage\.py[[:space:]]+test([[:space:]]|$)' || exit 0
deny() {
  # Personal hook log (~/.claude/hooks/hook-log.sh), when this machine has it.
  if [ -f "$HOME/.claude/hooks/hook-log.sh" ]; then
    . "$HOME/.claude/hooks/hook-log.sh" && hook_log check-django-test deny "$c"
  fi
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$1"
  exit 0
}
if ! printf '%s' "$c" | grep -q -- '--noinput'; then
  deny "Blocked: manage.py test must include --noinput. A stale test database from any killed run otherwise triggers an interactive delete prompt that hangs non-interactive shells forever. Re-run exactly the same command with --noinput added after: manage.py test"
fi

# A checkout's slot: MINIBINI_SLOT in its .claude/settings.local.json env
# (where per-checkout slots are assigned); empty = the shared default test DB.
checkout_root() { git -C "$1" rev-parse --show-toplevel 2>/dev/null || (cd "$1" 2>/dev/null && jj root --ignore-working-copy 2>/dev/null); }
slot_of() { jq -r '.env.MINIBINI_SLOT // empty' "$1/.claude/settings.local.json" 2>/dev/null; }

cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)
mine=${MINIBINI_SLOT-$(slot_of "$(checkout_root "${cwd:-$PWD}")")}
for pid in $(pgrep -f 'manage\.py[^ ]* test|manage\.py test' 2>/dev/null); do
  their_cwd=$(lsof -a -d cwd -p "$pid" -Fn 2>/dev/null | sed -n 's/^n//p')
  theirs=$(slot_of "$(checkout_root "$their_cwd")")
  if [ "$theirs" = "$mine" ]; then
    deny "Blocked: another Django test run (pid $pid, in ${their_cwd:-unknown dir}) uses the same test database (MINIBINI_SLOT='${mine}'). Two runs on one test DB deadlock. Wait for it to finish (check with: ps aux | grep manage.py), then re-run."
  fi
done
exit 0
