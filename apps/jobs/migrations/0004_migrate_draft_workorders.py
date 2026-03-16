from django.db import migrations


def migrate_draft_to_incomplete(apps, schema_editor):
    WorkOrder = apps.get_model('jobs', 'WorkOrder')
    WorkOrder.objects.filter(status='draft').update(status='incomplete')


class Migration(migrations.Migration):
    dependencies = [
        ('jobs', '0003_alter_workorder_status'),
    ]
    operations = [
        migrations.RunPython(migrate_draft_to_incomplete, migrations.RunPython.noop),
    ]
