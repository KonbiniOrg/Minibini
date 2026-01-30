# Generated manually to add missing fields

import django.db.models.deletion
from django.db import migrations, models
from django.utils import timezone


class Migration(migrations.Migration):

    dependencies = [
        ('contacts', '0002_rename_term_id_business_terms'),
        ('jobs', '0019_alter_blep_user'),
        ('purchasing', '0006_alter_billlineitem_line_number_and_more'),
    ]

    operations = [
        # Add bill_number field to Bill
        migrations.AddField(
            model_name='bill',
            name='bill_number',
            field=models.CharField(max_length=50, unique=True, default='TEMP'),
            preserve_default=False,
        ),
        # Add business field to Bill
        migrations.AddField(
            model_name='bill',
            name='business',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='contacts.business',
                default=1
            ),
            preserve_default=False,
        ),
        # Add status field to Bill
        migrations.AddField(
            model_name='bill',
            name='status',
            field=models.CharField(max_length=20, default='draft'),
        ),
        # Add date fields to Bill
        migrations.AddField(
            model_name='bill',
            name='created_date',
            field=models.DateTimeField(default=timezone.now),
        ),
        migrations.AddField(
            model_name='bill',
            name='due_date',
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='bill',
            name='received_date',
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='bill',
            name='paid_date',
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='bill',
            name='cancelled_date',
            field=models.DateTimeField(null=True, blank=True),
        ),
        # Alter Bill.contact to be nullable
        migrations.AlterField(
            model_name='bill',
            name='contact',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='contacts.contact',
                null=True,
                blank=True
            ),
        ),
        # Alter Bill.purchase_order to be nullable and PROTECT
        migrations.AlterField(
            model_name='bill',
            name='purchase_order',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='purchasing.purchaseorder',
                null=True,
                blank=True
            ),
        ),

        # Add business field to PurchaseOrder
        migrations.AddField(
            model_name='purchaseorder',
            name='business',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='contacts.business',
                default=1
            ),
            preserve_default=False,
        ),
        # Add contact field to PurchaseOrder
        migrations.AddField(
            model_name='purchaseorder',
            name='contact',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                to='contacts.contact',
                null=True,
                blank=True
            ),
        ),
        # Add status field to PurchaseOrder
        migrations.AddField(
            model_name='purchaseorder',
            name='status',
            field=models.CharField(max_length=20, default='draft'),
        ),
        # Add date fields to PurchaseOrder
        migrations.AddField(
            model_name='purchaseorder',
            name='created_date',
            field=models.DateTimeField(default=timezone.now),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='requested_date',
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='issued_date',
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='received_date',
            field=models.DateTimeField(null=True, blank=True),
        ),
        migrations.AddField(
            model_name='purchaseorder',
            name='cancel_date',
            field=models.DateTimeField(null=True, blank=True),
        ),
        # Alter PurchaseOrder.job to be SET_NULL
        migrations.AlterField(
            model_name='purchaseorder',
            name='job',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.SET_NULL,
                to='jobs.job',
                null=True,
                blank=True
            ),
        ),
    ]
