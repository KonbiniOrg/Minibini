#!/bin/bash
# PreToolUse guard for Django test runs (see CLAUDE.md > Testing).
# Blocks two whole-session failure modes before they start:
#   1. `manage.py test` without --noinput: a stale test DB (left by any
#      killed run) triggers an interactive delete prompt that hangs
#      non-interactive shells (subagents) forever.
#   2. Parallel Django test runs: they share ONE MySQL test database and
#      deadlock fighting over its creation/destruction.
# Reads the Bash tool call as JSON on stdin; prints a deny decision when
# a rule trips, stays silent otherwise.
c=$(jq -r '.tool_input.command // ""' 2>/dev/null)
case "$c" in
  *"manage.py test"*) ;;
  *) exit 0 ;;
esac
deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"%s"}}\n' "$1"
  exit 0
}
if ! printf '%s' "$c" | grep -q -- '--noinput'; then
  deny "Blocked: manage.py test must include --noinput. A stale test database from any killed run otherwise triggers an interactive delete prompt that hangs non-interactive shells forever. Re-run exactly the same command with --noinput added after: manage.py test"
fi
if pgrep -f 'manage\.py[^ ]* test|manage\.py test' >/dev/null 2>&1; then
  deny "Blocked: another Django test run is already in progress. Parallel runs share one MySQL test database and deadlock. Wait for the running suite to finish (check with: ps aux | grep manage.py), then re-run."
fi
exit 0
