"""Post-build reconciliation pass for the Neal's data converter.

Runs after all builders have emitted fixtures into ``c.fixture_data``. Mutates
those already-emitted records in place to enforce cross-model consistency that
the individual builders cannot guarantee on their own (version chains, status
vs. date invariants, task status derived from job status, etc.).

Each pass is a ``_pass_*`` helper. ``reconcile(c)`` runs them in order.
"""
from datetime import date, timedelta

from nealsdata.converter import parsing as P

# est_expire_days configuration default.
_EXPIRE_DAYS = 30

# Terminal job statuses (a completed_date is required for these).
_TERMINAL_JOB_STATUSES = ('completed', 'cancelled', 'rejected')
# Job statuses for which start_date must be set.
_STARTED_JOB_STATUSES = ('approved', 'in_progress', 'work_complete', 'completed')
# Job statuses for which start_date must be null.
# Note: 'cancelled' is intentionally in neither set — a cancelled job keeps whatever start_date it had.
_NO_START_JOB_STATUSES = ('draft', 'submitted', 'rejected')

# Estimate statuses for which sent_date must be set.
_SENT_ESTIMATE_STATUSES = ('open', 'accepted', 'rejected', 'expired', 'superseded')
# Estimate statuses for which closed_date must be set.
_CLOSED_ESTIMATE_STATUSES = ('accepted', 'rejected', 'expired', 'superseded')


def _find(index, model, pk):
    """Return the fixture dict for ``model``+``pk`` via pre-built index, or None."""
    return index.get((model, pk))


def _add_days(date_str, days):
    """Return ``date_str`` ('YYYY-MM-DD') advanced by ``days``, or None."""
    dt = P.to_datetime(date_str)
    if dt is None:
        return None
    return (dt + timedelta(days=days)).strftime('%Y-%m-%d')


def _as_dt_field(date_str):
    """Convert a bare 'YYYY-MM-DD' string to a tz-aware DateTimeField value.

    Returns None if date_str is None or empty. Passes through values that
    already contain a 'T' (i.e. already tz-aware ISO strings).
    """
    if not date_str:
        return None
    if 'T' in date_str:
        return date_str  # already tz-aware
    return f'{date_str}T00:00:00+00:00'


def reconcile(c):
    """Run all reconciliation passes in order, mutating ``c.fixture_data``."""
    index = {(f['model'], f['pk']): f for f in c.fixture_data}
    _pass_estimate_version_chains(c, index)
    _pass_estimate_expiry(c, index)
    _pass_estimate_dates(c, index)
    _pass_job_status_and_dates(c, index)
    _pass_task_status_from_job(c)
    _pass_invoiced_work(c)
    _pass_document_counters(c, index)


def _pass_estimate_version_chains(c, index):
    """Pass 1: every version below the highest is superseded; link parents."""
    today_str = date.today().strftime('%Y-%m-%d')
    for versions in c.estimates.values():
        if len(versions) < 2:
            continue
        ordered = sorted(versions, key=lambda v: v['version'])
        highest = ordered[-1]
        highest_created = highest['created_date'] or today_str

        prev_pk = None
        for entry in ordered:
            fixture = _find(index, 'estimates.estimate', entry['est_pk'])
            if fixture is None:
                prev_pk = entry['est_pk']
                continue
            # Link each non-first version to the previous version.
            if prev_pk is not None:
                fixture['fields']['parent'] = prev_pk
            # Every version except the highest is superseded.
            if entry is not highest:
                fixture['fields']['status'] = 'superseded'
                entry['status'] = 'superseded'
                closed = entry['created_date'] or highest_created
                fixture['fields']['closed_date'] = _as_dt_field(closed)
            prev_pk = entry['est_pk']


def _pass_estimate_expiry(c, index):
    """Pass 2: expire open estimates created more than 30 days ago."""
    cutoff = date.today() - timedelta(days=_EXPIRE_DAYS)
    for base_ref, versions in c.estimates.items():
        if not versions:
            continue
        highest_version = max(v['version'] for v in versions)
        for entry in versions:
            fixture = _find(index, 'estimates.estimate', entry['est_pk'])
            if fixture is None or fixture['fields']['status'] != 'open':
                continue
            created = P.to_datetime(entry['created_date'])
            if created is None or created.date() >= cutoff:
                continue
            fixture['fields']['status'] = 'expired'
            entry['status'] = 'expired'
            fixture['fields']['closed_date'] = _as_dt_field(
                _add_days(entry['created_date'], _EXPIRE_DAYS)
                or entry['created_date']
            )
            # If this is the job's latest estimate, the job is rejected.
            if entry['version'] == highest_version and base_ref in c.job_map:
                job_fixture = _find(index, 'jobs.job', c.job_map[base_ref])
                if job_fixture is not None:
                    job_fixture['fields']['status'] = 'rejected'


def _pass_estimate_dates(c, index):
    """Pass 3: fill in sent/expiration/closed dates consistent with status."""
    for versions in c.estimates.values():
        for entry in versions:
            fixture = _find(index, 'estimates.estimate', entry['est_pk'])
            if fixture is None:
                continue
            fields = fixture['fields']
            status = fields['status']
            # Use the bare date string for arithmetic; fields['created_date'] is
            # tz-aware so extract the date part if needed.
            raw_created = fields['created_date'] or entry['created_date']
            created_bare = entry['created_date'] or raw_created[:10]

            if status == 'draft':
                # Draft estimates keep all lifecycle dates null.
                continue

            # sent_date: set for open-or-later.
            if status in _SENT_ESTIMATE_STATUSES and not fields.get('sent_date'):
                fields['sent_date'] = _as_dt_field(created_bare)
            # expiration_date: set for open-or-later.
            if not fields.get('expiration_date'):
                fields['expiration_date'] = _as_dt_field(
                    _add_days(created_bare, _EXPIRE_DAYS)
                )
            # closed_date: set for terminal statuses.
            if status in _CLOSED_ESTIMATE_STATUSES and not fields.get('closed_date'):
                fields['closed_date'] = _as_dt_field(created_bare)


def _pass_job_status_and_dates(c, index):
    """Pass 4: archived cards complete jobs; reconcile job start/completed dates."""
    for base_ref, job_info in c.jobs.items():
        job_pk = job_info['job_pk']
        job_fixture = _find(index, 'jobs.job', job_pk)
        if job_fixture is None:
            continue
        fields = job_fixture['fields']
        card = job_info.get('card') or {}
        archived_at = (card.get('Archived at') or '').strip()

        # An archived card whose job is still 'approved' is complete.
        if archived_at and fields['status'] == 'approved':
            fields['status'] = 'completed'

        status = fields['status']

        # start_date: required for approved-or-later.
        if status in _STARTED_JOB_STATUSES and not fields.get('start_date'):
            est_list = c.estimates.get(base_ref) or []
            # c.estimates entries store bare 'YYYY-MM-DD' created_date values.
            created_dates = [
                e['created_date'] for e in est_list if e.get('created_date')
            ]
            if created_dates:
                fields['start_date'] = _as_dt_field(min(created_dates))
            else:
                # fields['created_date'] is already tz-aware.
                fields['start_date'] = fields.get('created_date')

        # start_date must be null for draft/submitted/rejected.
        if status in _NO_START_JOB_STATUSES:
            fields['start_date'] = None

        # completed_date: required for terminal statuses, null otherwise.
        if status in _TERMINAL_JOB_STATUSES:
            archived_date = P.format_date(archived_at) if archived_at else None
            fields['completed_date'] = _as_dt_field(
                archived_date or fields.get('created_date', '')[:10]
            )
        else:
            fields['completed_date'] = None


def _pass_task_status_from_job(c):
    """Pass 5: derive task status from the owning job's status."""
    job_status = {
        f['pk']: f['fields']['status']
        for f in c.fixture_data if f['model'] == 'jobs.job'
    }
    for f in c.fixture_data:
        if f['model'] != 'jobs.task':
            continue
        status = job_status.get(f['fields']['job'])
        if status == 'completed':
            f['fields']['status'] = 'complete'
        elif status in ('cancelled', 'rejected'):
            f['fields']['status'] = 'cancelled'
        else:
            f['fields']['status'] = 'pending'


def _pass_invoiced_work(c):
    """Pass 6: jobs invoiced to ~their estimate total have all tasks complete.

    Runs after pass 5; may upgrade pending tasks to complete.
    """
    # Sum qty*price of estimate line items, grouped by estimate pk.
    est_totals = {}
    for f in c.fixture_data:
        if f['model'] != 'estimates.estimatelineitem':
            continue
        fields = f['fields']
        qty = P.parse_decimal(fields.get('qty'))
        price = P.parse_decimal(fields.get('price'))
        est_pk = fields['estimate']
        est_totals[est_pk] = est_totals.get(est_pk, P.parse_decimal('0')) \
            + qty * price

    # Pre-build job status lookup so we can guard on it below.
    job_status_by_pk = {
        f['pk']: f['fields']['status']
        for f in c.fixture_data if f['model'] == 'jobs.job'
    }

    for base_ref, job_info in c.jobs.items():
        job_pk = job_info['job_pk']
        # Skip terminal-negative jobs: marking their tasks complete would be
        # inconsistent with a rejected or cancelled job status.
        if job_status_by_pk.get(job_pk) in ('rejected', 'cancelled'):
            continue
        inv_total = c.invoice_totals.get(base_ref)
        if inv_total is None or inv_total <= 0:
            continue
        est_list = c.estimates.get(base_ref) or []
        if not est_list:
            continue
        latest = max(est_list, key=lambda e: e['version'])
        est_total = est_totals.get(latest['est_pk'])
        if est_total is None or est_total <= 0:
            continue
        if abs(est_total - inv_total) > (max(est_total, inv_total) / 10):
            continue
        # Within 10%: every task on this job is complete.
        for f in c.fixture_data:
            if f['model'] == 'jobs.task' and f['fields']['job'] == job_pk:
                f['fields']['status'] = 'complete'


def _pass_document_counters(c, index):
    """Pass 7: set document-numbering counters to emitted record counts."""
    counts = {
        'job_counter':      'jobs.job',
        'estimate_counter': 'estimates.estimate',
        'invoice_counter':  'invoicing.invoice',
        'po_counter':       'purchasing.purchaseorder',
    }
    for key, model in counts.items():
        n = sum(1 for f in c.fixture_data if f['model'] == model)
        fixture = _find(index, 'core.configuration', key)
        if fixture is not None:
            fixture['fields']['value'] = str(n)
