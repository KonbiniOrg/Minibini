from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0046_alter_serviceprice_algorithm'),
    ]

    operations = [
        migrations.RenameModel(old_name='ServicePrice', new_name='ServiceItem'),
        migrations.AlterModelTable(name='serviceitem', table='service_items'),
        migrations.RenameField(model_name='serviceitem', old_name='service_price_id', new_name='service_item_id'),
        migrations.RenameField(model_name='task', old_name='service_price', new_name='service_item'),
        migrations.RenameField(model_name='plantask', old_name='service_price', new_name='service_item'),
    ]
