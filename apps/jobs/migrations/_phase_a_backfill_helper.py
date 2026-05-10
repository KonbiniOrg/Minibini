"""Helper used by the Phase A data migration AND by tests.

Pulled into a module so the migration's RunPython callable can import it
and the test suite can verify the backfill logic against live ORM models.
The migration uses historical models via apps.get_model; the test uses live
ORM. The helper takes both Task and TaskCharge classes as arguments so it
works in both worlds.
"""
from decimal import Decimal, InvalidOperation


def run(Task, TaskCharge):
    """Copy rate_scheme, active_modifiers, actuals.qty from TaskCharge → Task.

    Idempotent. If Task already has rate_scheme set (from a previous run), it
    is left alone. Tasks without a TaskCharge are left alone.
    """
    for charge in TaskCharge.objects.select_related('rate_scheme').all():
        task = charge.task
        # Idempotency: skip if already backfilled.
        if task.rate_scheme_id and task.active_modifiers:
            continue
        task.rate_scheme_id = charge.rate_scheme_id
        task.active_modifiers = list(charge.active_modifiers or [])
        raw_qty = charge.actuals.get('qty') if charge.actuals else None
        if raw_qty not in (None, ''):
            try:
                task.actual_qty = Decimal(str(raw_qty))
            except (InvalidOperation, ValueError):
                task.actual_qty = None
        task.save(update_fields=['rate_scheme', 'active_modifiers', 'actual_qty'])
