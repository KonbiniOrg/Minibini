"""Phase B: tighten Task.rate_scheme to NOT NULL.

The dev DB was backfilled in Phase A so every Task row already has
rate_scheme populated. This migration makes that invariant explicit
at the schema level by dropping the NULL constraint.

It also switches the related_name from '+' (no reverse accessor) to
'task_set' so RateScheme.task_set can be used as a natural reverse manager
in RateScheme.is_referenced() and elsewhere.

The related_name change is a Django ORM change only — it does not alter
the database schema.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        ('jobs', '0034_phase_a_backfill_task_from_taskcharge'),
    ]

    operations = [
        migrations.AlterField(
            model_name='task',
            name='rate_scheme',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='task_set',
                to='jobs.ratescheme',
            ),
        ),
    ]
