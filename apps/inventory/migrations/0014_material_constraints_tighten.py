# Generated manually: tighten Material.job and PlanMaterial.est_worksheet to NOT NULL.
# The preceding migration (0013) backfills any NULL values so this is safe.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0013_material_backfill_and_cleanup'),
    ]

    operations = [
        migrations.AlterField(
            model_name='material',
            name='job',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='materials',
                to='jobs.job',
            ),
        ),
        migrations.AlterField(
            model_name='planmaterial',
            name='est_worksheet',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='plan_materials',
                to='estimates.estworksheet',
            ),
        ),
    ]
