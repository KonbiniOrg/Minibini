from django.db import migrations


def forwards(apps, schema_editor):
    HistoryEntry = apps.get_model('core', 'HistoryEntry')
    HistoryEntry.objects.filter(object_type='change_order').update(object_type='changeorder')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0018_move_machine_state_to_appstate'),
    ]
    operations = [
        # Reverse is a deliberate no-op — we never want to recreate the split.
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
