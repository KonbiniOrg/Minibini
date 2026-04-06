# Part 2 of the Task/Bundle/Material split refactor: move worksheet-side
# Task/TaskBundle/Material rows into the new PlanTask/PlanBundle/PlanMaterial
# tables, retarget EstimateLineItem.task_id values, then drop the old
# dual-FK columns on jobs.Task and delete the jobs.TaskBundle model.
#
# Depends on inventory/0006 so PlanMaterial (with plan_task FK) already
# exists before the data move runs.
#
# See docs/plans/2026-04-05-task-split-plan1-model-refactor.md.

import django.db.models.deletion
from django.db import migrations, models


def split_all(apps, schema_editor):
    """Copy worksheet-side data to plan_* tables and clean up the old rows."""
    Task = apps.get_model('jobs', 'Task')
    PlanTask = apps.get_model('jobs', 'PlanTask')
    TaskBundle = apps.get_model('jobs', 'TaskBundle')
    PlanBundle = apps.get_model('jobs', 'PlanBundle')
    Material = apps.get_model('inventory', 'Material')
    PlanMaterial = apps.get_model('inventory', 'PlanMaterial')
    EstimateLineItem = apps.get_model('estimates', 'EstimateLineItem')

    # --- Copy worksheet-side TaskBundles to PlanBundles ---
    bundle_id_map = {}
    for tb in TaskBundle.objects.filter(est_worksheet__isnull=False):
        pb = PlanBundle.objects.create(
            est_worksheet_id=tb.est_worksheet_id,
            name=tb.name,
            description=tb.description,
            accounting_category_id=tb.accounting_category_id,
            sort_order=tb.sort_order,
            source_template_bundle_id=tb.source_template_bundle_id,
        )
        bundle_id_map[tb.pk] = pb.pk

    # --- Copy worksheet-side Tasks to PlanTasks ---
    task_id_map = {}
    for t in Task.objects.filter(est_worksheet__isnull=False).order_by('pk'):
        pt = PlanTask.objects.create(
            est_worksheet_id=t.est_worksheet_id,
            name=t.name,
            description=t.description,
            sort_order=t.sort_order,
            units=t.units,
            rate=t.rate,
            est_qty=t.est_qty,
            accounting_category_id=t.accounting_category_id,
            mapping_strategy=t.mapping_strategy,
            bundle_id=bundle_id_map.get(t.bundle_id) if t.bundle_id else None,
        )
        task_id_map[t.pk] = pt.pk

    # --- Copy Materials on worksheet-side tasks to PlanMaterials ---
    worksheet_task_pks = set(task_id_map.keys())
    materials_to_delete = []
    for m in Material.objects.filter(task_id__in=worksheet_task_pks):
        PlanMaterial.objects.create(
            plan_task_id=task_id_map[m.task_id],
            description=m.description,
            quantity=m.quantity,
            unit_cost=m.unit_cost,
            sell_price=m.sell_price,
            price_list_item_id=m.price_list_item_id,
            accounting_category_id=m.accounting_category_id,
        )
        materials_to_delete.append(m.pk)
    Material.objects.filter(pk__in=materials_to_delete).delete()

    # --- Retarget EstimateLineItem.task_id values from old Task PKs to new
    # PlanTask PKs. The old FK constraint still references jobs.Task, so
    # we temporarily disable FOREIGN_KEY_CHECKS (MySQL) for the update.
    # The subsequent estimates/0006 migration's AlterField will drop the
    # old constraint and recreate it against jobs.PlanTask; by that point
    # the data is already consistent with the new target.
    connection = schema_editor.connection
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == 'mysql':
            cursor.execute('SET FOREIGN_KEY_CHECKS=0')
        try:
            for li_pk, old_task_id in list(
                EstimateLineItem.objects.filter(
                    task_id__in=worksheet_task_pks
                ).values_list('pk', 'task_id')
            ):
                EstimateLineItem.objects.filter(pk=li_pk).update(
                    task_id=task_id_map[old_task_id]
                )
            # Null out any EstimateLineItem.task that points at a WO-side
            # Task row; those would violate the new FK target. Shouldn't
            # exist in practice but guard for correctness.
            wo_task_pks = list(Task.objects.filter(
                est_worksheet__isnull=True
            ).values_list('pk', flat=True))
            if wo_task_pks:
                EstimateLineItem.objects.filter(
                    task_id__in=wo_task_pks
                ).update(task_id=None)
        finally:
            if vendor == 'mysql':
                cursor.execute('SET FOREIGN_KEY_CHECKS=1')

    # --- Delete worksheet-side Task rows ---
    Task.objects.filter(est_worksheet__isnull=False).delete()

    # --- Delete any remaining TaskBundle rows before DeleteModel runs ---
    TaskBundle.objects.all().delete()


def reverse_split(apps, schema_editor):
    raise RuntimeError(
        "The Task/Bundle/Material split migration cannot be reversed automatically."
    )


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0006_planmaterial_plan_task_planmaterial_price_list_item'),
        ('jobs', '0008_task_bundle_material_split'),
    ]

    operations = [
        migrations.RunPython(split_all, reverse_split),
        migrations.RemoveField(
            model_name='task',
            name='bundle',
        ),
        migrations.RemoveField(
            model_name='task',
            name='est_worksheet',
        ),
        migrations.RemoveField(
            model_name='task',
            name='mapping_strategy',
        ),
        migrations.DeleteModel(
            name='TaskBundle',
        ),
        migrations.AlterField(
            model_name='task',
            name='work_order',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tasks', to='jobs.workorder'),
        ),
    ]
