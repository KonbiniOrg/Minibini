from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0046_alter_serviceprice_algorithm'),
        # Must run AFTER the cross-app FKs that target 'jobs.serviceprice'
        # (adjustment_service on estimate/invoice line items). RenameModel below
        # then retargets them to ServiceItem. Without these deps a fresh
        # `migrate` can run this rename first and fail to resolve
        # 'jobs.serviceprice'.
        ('estimates', '0027_estimatelineitem_adjustment_service_and_more'),
        ('invoicing', '0015_invoicelineitem_adjustment_service_and_more'),
    ]

    operations = [
        migrations.RenameModel(old_name='ServicePrice', new_name='ServiceItem'),
        migrations.AlterModelTable(name='serviceitem', table='service_items'),
        migrations.RenameField(model_name='serviceitem', old_name='service_price_id', new_name='service_item_id'),
        migrations.RenameField(model_name='task', old_name='service_price', new_name='service_item'),
        migrations.RenameField(model_name='plantask', old_name='service_price', new_name='service_item'),
    ]
