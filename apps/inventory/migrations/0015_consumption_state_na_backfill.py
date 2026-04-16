from django.db import migrations


TERMINAL_TASK_STATUSES = ('complete', 'cancelled')


def backfill_na(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')

    for m in Material.objects.filter(consumption_state='na'):
        if m.task_id and getattr(m.task, 'status', None) in TERMINAL_TASK_STATUSES:
            m.consumption_state = 'consumed'
        else:
            m.consumption_state = 'pending'
        m.save()


def reverse_backfill(apps, schema_editor):
    # Best-effort reverse: we can't distinguish rows that were originally 'na'
    # from rows that were legitimately set to 'pending'/'consumed' post-migration.
    # No-op is the safe choice.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0014_material_constraints_tighten'),
    ]
    operations = [
        migrations.RunPython(backfill_na, reverse_backfill),
    ]
