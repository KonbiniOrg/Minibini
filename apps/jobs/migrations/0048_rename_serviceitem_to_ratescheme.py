from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0047_rename_serviceprice_to_serviceitem'),
        # Cross-app FK holders that reference jobs.serviceitem — must be present
        # before we rename so Django can resolve the content type correctly.
        ('estimates', '0029_alter_estimatelineitem_adjustment_service'),
        ('invoicing', '0016_alter_invoicelineitem_adjustment_service'),
    ]

    operations = [
        migrations.RenameModel(old_name='ServiceItem', new_name='RateScheme'),
        migrations.AlterModelTable(name='ratescheme', table='rate_schemes'),
        migrations.RenameField(model_name='ratescheme', old_name='service_item_id', new_name='rate_scheme_id'),
        migrations.RenameField(model_name='task', old_name='service_item', new_name='rate_scheme'),
        migrations.RenameField(model_name='plantask', old_name='service_item', new_name='rate_scheme'),
    ]
