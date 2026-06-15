from django.db import migrations


class Migration(migrations.Migration):
    """Phase B1: rename PriceListItem -> InventoryItem and its table
    price_list -> inventory_item. Pure rename — no field/behavior changes.
    RenameModel preserves the table + data and updates FK references in state;
    AlterModelTable performs the actual table rename (db_table was explicit, so
    RenameModel alone does not move it)."""

    dependencies = [
        ('inventory', '0025_pricelistitem_price_list_qty_on_hand_non_negative'),
    ]

    operations = [
        migrations.RenameModel(
            old_name='PriceListItem',
            new_name='InventoryItem',
        ),
        migrations.AlterModelTable(
            name='inventoryitem',
            table='inventory_item',
        ),
    ]
