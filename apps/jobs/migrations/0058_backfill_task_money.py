from django.db import migrations


def forwards(apps, schema_editor):
    from apps.jobs.task_money_backfill import backfill_task_money
    Task = apps.get_model('jobs', 'Task')
    RateScheme = apps.get_model('jobs', 'RateScheme')
    backfill_task_money(Task, RateScheme)


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0057_task_source_scheme'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
