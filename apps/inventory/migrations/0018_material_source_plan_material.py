# Generated manually 2026-04-20

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0017_material_po_line_item'),
    ]

    operations = [
        migrations.AddField(
            model_name='material',
            name='source_plan_material',
            field=models.OneToOneField(
                blank=True,
                help_text='PlanMaterial this material was carried over from (carry-over idempotency)',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='carried_material',
                to='inventory.planmaterial',
            ),
        ),
    ]
