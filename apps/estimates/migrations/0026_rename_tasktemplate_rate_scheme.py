from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('estimates', '0025_rename_price_list_item_changeorderlineitem_inventory_item_and_more'),
        ('jobs', '0044_rename_ratescheme_to_serviceprice'),
    ]

    operations = [
        migrations.RenameField(
            model_name='tasktemplate',
            old_name='rate_scheme',
            new_name='service_price',
        ),
    ]
