from django.db import migrations


def forwards(apps, schema_editor):
    from apps.jobs.task_money_backfill import backfill_task_money
    Task = apps.get_model('jobs', 'Task')
    RateScheme = apps.get_model('jobs', 'RateScheme')
    skipped = backfill_task_money(Task, RateScheme)
    if skipped:
        print(f'[task_money_backfill] skipped {skipped} task(s) pointing at '
              f'a percentage-algorithm scheme (left unbackfilled)')


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0057_task_source_scheme'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
