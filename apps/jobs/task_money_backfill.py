# apps/jobs/task_money_backfill.py
#
# HISTORICAL MIGRATION HELPER — invoked by data migration
# jobs/0058_backfill_task_money, which runs immediately after jobs/0057
# renames Task.rate_scheme to Task.source_scheme (and makes it nullable,
# on_delete=SET_NULL). The `Task`/`RateScheme` args the migration passes are
# its HISTORICAL models (via apps.get_model), frozen at that exact point in
# schema history — always call this with those, never the live models.
#
# DO NOT sweep this file's field names (`source_scheme`, `active_modifiers`,
# `modifiers`, `algorithm`, `rate`, `unit_label`, `accounting_category`)
# forward when a later phase renames/removes them again — a blanket rename
# once broke `migrate` on a fresh database the same way (see
# apps/jobs/flat_fee_reframe.py's header): the historical model at THIS
# migration's position in history only has the fields as they existed then,
# regardless of what the live model looks like today.
def backfill_task_money(Task, RateScheme):
    """One-shot copy of scheme values onto tasks + key->snapshot modifier resolution.
    Iterates and saves via update() per-row on the historical model (no custom save
    side effects exist for these fields)."""
    for task in Task.objects.select_related('source_scheme').iterator():
        scheme = task.source_scheme
        if scheme is None:
            continue
        keys = task.active_modifiers if isinstance(task.active_modifiers, list) else []
        resolved = [m for m in (scheme.modifiers or []) if m.get('key') in keys]
        Task.objects.filter(pk=task.pk).update(
            qty_source=scheme.algorithm, rate=scheme.rate,
            unit_label=scheme.unit_label,
            accounting_category_id=scheme.accounting_category_id,
            active_modifiers=resolved)
