# Generated manually to update line item fields

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('invoicing', '0011_pricelistitem_is_active_and_more'),
        ('jobs', '0019_alter_blep_user'),
        ('purchasing', '0007_add_business_contact_and_status_fields'),
    ]

    operations = [
        # Update task foreign key to PROTECT for BillLineItem
        migrations.AlterField(
            model_name='billlineitem',
            name='task',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='jobs.task',
                null=True,
                blank=True
            ),
        ),
        # Update task foreign key to PROTECT for PurchaseOrderLineItem
        migrations.AlterField(
            model_name='purchaseorderlineitem',
            name='task',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='jobs.task',
                null=True,
                blank=True
            ),
        ),
        # Update price_list_item foreign key to PROTECT for BillLineItem
        migrations.AlterField(
            model_name='billlineitem',
            name='price_list_item',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='invoicing.pricelistitem',
                null=True,
                blank=True
            ),
        ),
        # Update price_list_item foreign key to PROTECT for PurchaseOrderLineItem
        migrations.AlterField(
            model_name='purchaseorderlineitem',
            name='price_list_item',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='invoicing.pricelistitem',
                null=True,
                blank=True
            ),
        ),
    ]
