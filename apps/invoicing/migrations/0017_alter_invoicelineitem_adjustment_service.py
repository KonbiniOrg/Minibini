import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoicing', '0016_alter_invoicelineitem_adjustment_service'),
        ('jobs', '0048_rename_serviceitem_to_ratescheme'),
    ]

    operations = [
        migrations.AlterField(
            model_name='invoicelineitem',
            name='adjustment_service',
            field=models.ForeignKey(
                blank=True,
                help_text='Set when this line is a percentage adjustment (rush/discount).',
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='+',
                to='jobs.ratescheme',
            ),
        ),
    ]
