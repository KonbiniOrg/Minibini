from django.db import migrations


def backfill(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    PlanMaterial = apps.get_model('inventory', 'PlanMaterial')
    Task = apps.get_model('jobs', 'Task')

    for m in Material.objects.all():
        dirty = False
        if m.job_id is None and m.task_id:
            m.job_id = m.task.job_id
            dirty = True
        if m.price_list_item_id:
            pli = m.price_list_item
            if pli.is_inventoried and m.consumption_state == 'na':
                if m.task_id and getattr(m.task, 'status', None) == 'complete':
                    m.consumption_state = 'consumed'
                else:
                    m.consumption_state = 'pending'
                dirty = True
        if dirty:
            m.save()

    for pm in PlanMaterial.objects.all():
        if pm.est_worksheet_id is None and pm.plan_task_id:
            pm.est_worksheet_id = pm.plan_task.est_worksheet_id
            pm.save()

    # Placeholder "Materials" task cleanup
    for t in Task.objects.filter(name='Materials'):
        # blep reverse accessor may be blep_set or bleps; check both
        has_bleps = False
        for rel in ('blep_set', 'bleps'):
            if hasattr(t, rel):
                has_bleps = getattr(t, rel).exists()
                break
        mats = list(t.materials.all())
        if not mats:
            continue
        all_expense_bound = all(m.expenses.exists() for m in mats)
        if not has_bleps and all_expense_bound:
            for m in mats:
                m.task = None
                m.save()
            t.delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0012_plan_material_plan_task_nullable'),
    ]
    operations = [
        migrations.RunPython(backfill, noop_reverse),
    ]
