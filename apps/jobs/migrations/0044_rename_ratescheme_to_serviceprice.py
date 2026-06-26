from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0043_job_project_manager'),
    ]

    operations = [
        migrations.RenameModel(old_name='RateScheme', new_name='ServicePrice'),
        migrations.AlterModelTable(name='serviceprice', table='service_prices'),
        migrations.RenameField(
            model_name='serviceprice',
            old_name='rate_scheme_id',
            new_name='service_price_id',
        ),
        migrations.RenameField(
            model_name='task', old_name='rate_scheme', new_name='service_price',
        ),
        migrations.RenameField(
            model_name='plantask', old_name='rate_scheme', new_name='service_price',
        ),
    ]
