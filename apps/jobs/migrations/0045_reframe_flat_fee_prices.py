from django.db import migrations


def forwards(apps, schema_editor):
    from apps.jobs.flat_fee_reframe import reframe_flat_fee_prices
    ServicePrice = apps.get_model('jobs', 'ServicePrice')
    Task = apps.get_model('jobs', 'Task')
    PlanTask = apps.get_model('jobs', 'PlanTask')
    TaskTemplate = apps.get_model('estimates', 'TaskTemplate')
    worklist = reframe_flat_fee_prices(ServicePrice, Task, PlanTask, TaskTemplate)
    for kind, pk, reason in worklist:
        print(f'[flat_fee_reframe] UNRESOLVED {kind} pk={pk}: {reason}')


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0044_rename_ratescheme_to_serviceprice'),
        ('estimates', '0026_rename_tasktemplate_rate_scheme'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
