from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('estimates', '0027_estimatelineitem_adjustment_service_and_more'),
        ('jobs', '0047_rename_serviceprice_to_serviceitem'),
    ]

    operations = [
        migrations.RenameField(model_name='tasktemplate', old_name='service_price', new_name='service_item'),
    ]
