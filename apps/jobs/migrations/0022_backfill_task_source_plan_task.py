from django.db import migrations


def backfill_forward(apps, schema_editor):
    Task = apps.get_model('jobs', 'Task')
    for task in Task.objects.exclude(source_plan_charge_id=None).select_related('source_plan_charge'):
        task.source_plan_task_id = task.source_plan_charge.plan_task_id
        task.save(update_fields=['source_plan_task'])


def backfill_back(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [('jobs', '0021_task_source_plan_task')]
    operations = [migrations.RunPython(backfill_forward, backfill_back)]
