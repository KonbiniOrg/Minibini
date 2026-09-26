import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0056_task_money_fields'),
    ]

    operations = [
        migrations.RenameField(
            model_name='task',
            old_name='rate_scheme',
            new_name='source_scheme',
        ),
        migrations.AlterField(
            model_name='task',
            name='source_scheme',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='stamped_tasks', to='jobs.ratescheme',
            ),
        ),
    ]
