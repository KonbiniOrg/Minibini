# CO amend-in-place plan (docs/plans/2026-08-09-co-amend-in-place-plan),
# Task 4: one-time historical backfill of Task.descoped_by /
# Material.descoped_by from legacy accepted-CO data.
#
# The current acceptance service (apps/estimates/co_acceptance.py) only
# stamps descoped_by on REMOVE lines, walking the accepted-CO replace chain
# to find each target's *current* atom. Legacy data predates that split:
# under the old semantics a REPLACE line also retired the target's atom, so
# this backfill stamps both remove AND replace lines' targets, reading each
# target's *own* EstimateLineItemSource rows directly (no CO-chain walk —
# this is a flat historical pass, not a re-run of the live algorithm).
#
# Depends on estimates/0046 (ChangeOrderLineItem.adjustment_* — irrelevant
# here but the latest schema state) and, explicitly, on the three schema
# migrations that added the fields this backfill writes/reads via
# historical models: jobs/0063 (Task.descoped_by) and inventory/0035
# (Material.descoped_by).
#
# Reverse is a noop: the stamp is derived, re-derivable by re-running this
# function, and not something any other migration depends on unwinding.

from django.db import migrations


def stamp_descoped_atoms(apps, schema_editor):
    """Stamp descoped_by on the atoms behind every accepted CO's legacy
    remove/replace targets.

    For each ACCEPTED ChangeOrder (oldest closed_date first, so a later CO's
    stamp overwrites an earlier one when several target the same estimate
    line — 'later-accepted CO wins'), walk its remove and replace lines'
    target_line_item, read that line's EstimateLineItemSource rows, and
    stamp the referenced Task or Material's descoped_by = co. A source row
    whose atom no longer exists (already hard-deleted) is skipped silently.

    Historical models carry no custom save()/delete() side effects, so
    QuerySet.update() here is the standard, correct tool — this is not the
    live-model case the house no-QuerySet.update rule guards against.
    """
    ChangeOrder = apps.get_model('estimates', 'ChangeOrder')
    Task = apps.get_model('jobs', 'Task')
    Material = apps.get_model('inventory', 'Material')

    ACTION_REMOVE = 'remove'
    ACTION_REPLACE = 'replace'
    SOURCE_TASK = 'task'
    SOURCE_MATERIAL = 'material'

    cos = (ChangeOrder.objects
           .filter(status='accepted')
           .order_by('closed_date', 'change_order_id'))

    for co in cos:
        lines = co.changeorderlineitem_set.filter(
            action__in=(ACTION_REMOVE, ACTION_REPLACE),
            target_line_item__isnull=False,
        )
        for line in lines:
            for src in line.target_line_item.sources.all():
                if src.source_type == SOURCE_TASK:
                    Task.objects.filter(pk=src.source_pk).update(descoped_by=co)
                elif src.source_type == SOURCE_MATERIAL:
                    Material.objects.filter(pk=src.source_pk).update(descoped_by=co)
                # Any other/unknown source_type or a dangling pk: no rows
                # match, .update() is a silent no-op — exactly "skip".


class Migration(migrations.Migration):

    dependencies = [
        ('estimates', '0046_changeorderlineitem_adjustment_percent_and_more'),
        ('jobs', '0063_task_descoped_by'),
        ('inventory', '0035_material_descoped_by'),
    ]

    operations = [
        migrations.RunPython(stamp_descoped_atoms, migrations.RunPython.noop),
    ]
