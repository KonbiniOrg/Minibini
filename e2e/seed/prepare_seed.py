#!/usr/bin/env python3
"""Rebase the E2E seed fixture so its data stays within reach of the clock.

Reads the committed fixtures/playwright/seed.json (never modified) and
writes the rebased copy to fixtures/playwright/rebased.json (gitignored,
regenerated every run — reset_db.sh loads it). Design:
docs/plans/2026-07-07-e2e-test-platform.md §4.1.

- Anchors on the newest `core.jobhistory` timestamp: job history is
  written at action time, so it can never postdate the dump and is always
  very recent in a fresh export. Deadline-style values (estimate
  expirations, job due dates) and session expiry legitimately sit in the
  dataset's future and must not anchor the "present".
- Computes the exact whole-day delta that lands that anchor on yesterday
  (yesterday, not today, so a rebased afternoon timestamp can't land in
  the test run's future), then shifts every date/datetime string in the
  dataset by that same delta — causal ordering, minute alignment,
  time-of-day patterns, and relative gaps are all preserved.
- Overwrites every core.user password with the hash of "e2e_password" so
  every persona has a known login.

Shifting matches by string shape, not by a per-field list: whole-string
ISO datetimes and whole-string bare dates. Document numbers
("JOB-2025-0001") and dates embedded in prose match neither and are never
touched. If a model ever stores a *string* shaped exactly like a bare ISO
date that must not shift, note it here and exclude it.

Pure stdlib — no Django, so it can run before any Django env exists.
"""
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

SEED_PATH = Path(__file__).resolve().parents[2] / 'fixtures' / 'playwright' / 'seed.json'
OUT_PATH = SEED_PATH.with_name('rebased.json')

# django.contrib.auth.hashers.make_password('e2e_password'), precomputed so
# this script needs no Django. Regenerate if PASSWORD_HASHERS ever changes.
E2E_PASSWORD_HASH = (
    'pbkdf2_sha256$1000000$42I72SfWa6efqoOXPeIP6b$'
    '+vhkQ310Xkguci9QQ7dG/lpEGNrfzvw2z7WaXwCOxyA='
)

ANCHOR_MODEL = 'core.jobhistory'

DATETIME_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2})T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$')
BARE_DATE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})$')


def shift_string(value, delta_days):
    """Shift value's date part by delta_days if it is date-shaped; else return it unchanged."""
    match = DATETIME_RE.match(value) or BARE_DATE_RE.match(value)
    if not match:
        return value
    shifted = date.fromisoformat(match.group(1)) + timedelta(days=delta_days)
    return shifted.isoformat() + value[10:]


def _iter_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_strings(v)


def _shift_values(obj, delta_days):
    if isinstance(obj, str):
        return shift_string(obj, delta_days)
    if isinstance(obj, dict):
        return {k: _shift_values(v, delta_days) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_shift_values(v, delta_days) for v in obj]
    return obj


def compute_delta_days(records, today):
    """Exact whole-day delta landing the newest job-history timestamp on yesterday."""
    anchor = None
    for record in records:
        if record['model'] != ANCHOR_MODEL:
            continue
        for value in _iter_strings(record['fields']):
            match = DATETIME_RE.match(value)
            if match:
                candidate = date.fromisoformat(match.group(1))
                if anchor is None or candidate > anchor:
                    anchor = candidate
    if anchor is None:
        raise ValueError(
            f'no {ANCHOR_MODEL} timestamp found to anchor the rebase')
    return (today - timedelta(days=1) - anchor).days


def rebase(records, today):
    """Return (rebased records, delta_days): dates shifted, persona passwords set."""
    delta = compute_delta_days(records, today)
    rebased = _shift_values(records, delta)
    for record in rebased:
        if record['model'] == 'core.user':
            record['fields']['password'] = E2E_PASSWORD_HASH
    return rebased, delta


def dumps_fixture(records):
    """Serialize in `manage.py dumpdata --indent 2` style."""
    return '[\n' + ',\n'.join(json.dumps(r, indent=2) for r in records) + '\n]\n'


def main(path=SEED_PATH, out_path=OUT_PATH, today=None):
    if today is None:
        today = date.today()
    records = json.loads(path.read_text())
    rebased, delta = rebase(records, today)
    out_path.write_text(dumps_fixture(rebased))
    users = sum(1 for r in rebased if r['model'] == 'core.user')
    print(f'{path.name} → {out_path.name}: shifted dates by {delta:+d} days; '
          f'set {users} user passwords to e2e_password')


if __name__ == '__main__':
    sys.exit(main())
