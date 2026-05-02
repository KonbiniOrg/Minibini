from django.db import migrations


def copy_forward(apps, schema_editor):
    PlanCharge = apps.get_model('jobs', 'PlanCharge')
    for pc in PlanCharge.objects.all():
        pt = pc.plan_task
        pt.rate_scheme_id = pc.rate_scheme_id
        pt.active_modifiers = pc.active_modifiers
        pt.estimated_billable_qty = pc.estimated_billable_qty
        pt.save(update_fields=['rate_scheme', 'active_modifiers', 'estimated_billable_qty'])


def copy_back(apps, schema_editor):
    # Reverse: clear fields on PlanTask. PlanCharge rows are untouched.
    PlanTask = apps.get_model('jobs', 'PlanTask')
    PlanTask.objects.update(
        rate_scheme=None, active_modifiers=[], estimated_billable_qty=None,
    )


class Migration(migrations.Migration):
    dependencies = [('jobs', '0019_plantask_active_modifiers_and_more')]
    operations = [migrations.RunPython(copy_forward, copy_back)]
