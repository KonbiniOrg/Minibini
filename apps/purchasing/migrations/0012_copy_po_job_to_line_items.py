"""Data migration: copy PurchaseOrder.job to all its line items."""
from django.db import migrations


def copy_po_job_to_line_items(apps, schema_editor):
    PurchaseOrder = apps.get_model('purchasing', 'PurchaseOrder')
    PurchaseOrderLineItem = apps.get_model('purchasing', 'PurchaseOrderLineItem')

    for po in PurchaseOrder.objects.filter(job__isnull=False):
        PurchaseOrderLineItem.objects.filter(
            purchase_order=po,
            job__isnull=True,
        ).update(job=po.job)


def reverse_copy(apps, schema_editor):
    # No reverse needed — the PO.job field will still exist during reversal
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('purchasing', '0011_purchaseorderlineitem_inventory_item_and_more'),
    ]

    operations = [
        migrations.RunPython(copy_po_job_to_line_items, reverse_copy),
    ]
