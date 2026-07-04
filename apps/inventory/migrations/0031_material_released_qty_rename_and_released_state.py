# Hand-adjusted: makemigrations emitted RemoveField+AddField for the
# restocked_qty → released_qty rename, which would drop the data. RenameField
# preserves it (quantity + released_qty must keep reconstructing the original
# purchase for the expense-void reversal).

from decimal import Decimal
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0030_remove_material_source_plan_material_and_more'),
    ]

    operations = [
        migrations.RenameField(
            model_name='material',
            old_name='restocked_qty',
            new_name='released_qty',
        ),
        migrations.AlterField(
            model_name='material',
            name='released_qty',
            field=models.DecimalField(decimal_places=2, default=Decimal('0.00'), help_text='Quantity restocked/released back out of the plan. quantity + released_qty = originally planned.', max_digits=10),
        ),
        migrations.AlterField(
            model_name='material',
            name='consumption_state',
            field=models.CharField(choices=[('pending', 'Pending'), ('consumed', 'Consumed'), ('released', 'Released')], default='pending', max_length=20),
        ),
    ]
