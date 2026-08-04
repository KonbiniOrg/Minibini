# apps/jobs/subtask_scale_backfill.py
#
# HISTORICAL MIGRATION HELPER — invoked by data migration
# jobs/0062_task_qty_scales_with_parent, immediately after it adds the
# `qty_scales_with_parent` column (DB default `True`). The `Task` arg the
# migration passes is its HISTORICAL model (via apps.get_model), frozen at
# this exact point in schema history — always call this with that model,
# never the live one.
#
# Controller-verified (2026-08-04, read-only dev-DB SELECT — see the final
# fix wave's report): 26 real dev-DB subtask rows have `est_qty` values that
# were authored as plain per-batch TOTALS — no `qty_scales_with_parent`
# multiplier existed yet when they were created. The blanket `AddField`
# default of `True` would silently start MULTIPLYING those historical totals
# by their parent's `est_qty` the moment `expected_qty()` /
# `expected_worker_time()` / `derived_unit_price()` read them — a real money
# distortion, not a display quirk. Every row that already had a
# `parent_task_id` set BEFORE this migration ran is such a row (the flag
# didn't exist for it to have been authored against), so this backfill sets
# `qty_scales_with_parent=False` for ALL of them, preserving their original
# "raw number is the whole batch" meaning. Any subtask created AFTER this
# migration runs goes through TaskService.create_direct's own unit-keyed
# default instead (True iff the parent's unit_label == 'ea') — this
# migration only ever touches rows that predate the flag.
#
# DO NOT sweep this file's field names (`parent_task_id`,
# `qty_scales_with_parent`) forward when a later phase renames them again —
# see apps/jobs/task_money_backfill.py's header for why a blanket rename
# once broke `migrate` on a fresh database the same way: the historical
# model at THIS migration's position in history only has the fields as they
# existed then, regardless of what the live model looks like today.
def backfill_subtask_qty_scales_with_parent(Task):
    """Set qty_scales_with_parent=False for every existing subtask row
    (parent_task_id IS NOT NULL) at this point in migration history.

    A single bulk update — no per-row derivation needed (every qualifying
    row gets the same value), and the historical Task model has no custom
    save() side effects for this field to bypass. Returns the number of
    rows touched so the migration can report it.
    """
    return Task.objects.filter(parent_task_id__isnull=False).update(
        qty_scales_with_parent=False)
