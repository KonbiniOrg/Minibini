from django.db import migrations


class Migration(migrations.Migration):

    # Pass B of the Phase-0 rename: the saved-work-item TaskTemplate -> ServiceItem.
    # Depends on jobs/0048 (which renamed the rate card's table service_items ->
    # rate_schemes), so the `service_items` table name is free for this model to claim.
    dependencies = [
        ('estimates', '0030_rename_tasktemplate_rate_scheme_alter_adj_service'),
        ('jobs', '0048_rename_serviceitem_to_ratescheme'),
    ]

    operations = [
        migrations.RenameModel(old_name='TaskTemplate', new_name='ServiceItem'),
        migrations.AlterModelTable(name='serviceitem', table='service_items'),
        migrations.RenameField(
            model_name='templatetaskassociation',
            old_name='task_template',
            new_name='service_item',
        ),
    ]
