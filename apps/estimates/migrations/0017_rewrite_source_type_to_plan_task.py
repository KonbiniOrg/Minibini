from django.db import migrations


def rewrite_forward(apps, schema_editor):
    Source = apps.get_model('estimates', 'EstimateLineItemSource')
    PlanCharge = apps.get_model('jobs', 'PlanCharge')
    for src in Source.objects.filter(source_type='plan_charge'):
        try:
            pc = PlanCharge.objects.get(pk=src.source_pk)
        except PlanCharge.DoesNotExist:
            continue
        src.source_type = 'plan_task'
        src.source_pk = pc.plan_task_id
        src.save(update_fields=['source_type', 'source_pk'])


def rewrite_back(apps, schema_editor):
    Source = apps.get_model('estimates', 'EstimateLineItemSource')
    PlanCharge = apps.get_model('jobs', 'PlanCharge')
    for src in Source.objects.filter(source_type='plan_task'):
        pc = PlanCharge.objects.filter(plan_task_id=src.source_pk).first()
        if pc:
            src.source_type = 'plan_charge'
            src.source_pk = pc.pk
            src.save(update_fields=['source_type', 'source_pk'])


class Migration(migrations.Migration):
    dependencies = [
        ('estimates', '0016_alter_estimatelineitemsource_source_type'),
        ('jobs', '0020_copy_plan_charge_to_plan_task'),
    ]
    run_before = [
        ('jobs', '0024_drop_plan_charge_and_source_plan_charge'),
    ]
    operations = [migrations.RunPython(rewrite_forward, rewrite_back)]
