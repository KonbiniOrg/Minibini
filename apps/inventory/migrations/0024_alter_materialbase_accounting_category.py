from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_retire_can_approve_expenses'),
        ('inventory', '0023_backfill_accounting_category'),
    ]

    operations = [
        migrations.AlterField(
            model_name='material',
            name='accounting_category',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='core.accountingcategory',
            ),
        ),
        migrations.AlterField(
            model_name='planmaterial',
            name='accounting_category',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='core.accountingcategory',
            ),
        ),
    ]
