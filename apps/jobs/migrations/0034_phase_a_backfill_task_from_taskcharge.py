from django.db import migrations


def forwards(apps, schema_editor):
    Task = apps.get_model('jobs', 'Task')
    TaskCharge = apps.get_model('jobs', 'TaskCharge')
    from apps.jobs.migrations._phase_a_backfill_helper import run
    run(Task, TaskCharge)


def backwards(apps, schema_editor):
    # Reverse leaves the backfilled Task fields populated. The TaskCharge
    # rows still exist (Phase A doesn't drop them). Re-running forwards
    # would be a no-op because of the idempotency check.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0033_phase_a_add_task_billing_fields'),
    ]
    operations = [
        migrations.RunPython(forwards, backwards),
    ]
