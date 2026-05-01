# Generated manually 2026-04-20

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0016_add_job_in_progress_state'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='source_plan_charge',
            field=models.OneToOneField(
                blank=True,
                help_text='PlanCharge this task was carried over from (carry-over idempotency)',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='carried_task',
                to='jobs.plancharge',
            ),
        ),
    ]
