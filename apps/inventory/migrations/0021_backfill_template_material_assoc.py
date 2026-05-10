from django.db import migrations


def backfill(apps, schema_editor):
    TemplateMaterial = apps.get_model('inventory', 'TemplateMaterial')
    TemplateMaterialAssociation = apps.get_model('inventory', 'TemplateMaterialAssociation')

    # Halt with a clear error if any freeform TemplateMaterials exist —
    # the new design only supports PLI-linked materials at the template level.
    freeforms = TemplateMaterial.objects.filter(price_list_item__isnull=True)
    if freeforms.exists():
        ids = list(freeforms.values_list('template_material_id', flat=True))
        raise RuntimeError(
            f'Cannot migrate: {len(ids)} freeform TemplateMaterial(s) found '
            f'(IDs: {ids}). The new design requires every template-level '
            f'material to link to a PriceListItem. Convert these to PLIs '
            f'(or delete them) before re-running this migration.'
        )

    for tm in TemplateMaterial.objects.all():
        TemplateMaterialAssociation.objects.create(
            work_template_id=tm.work_template_id,
            price_list_item_id=tm.price_list_item_id,
            quantity=tm.quantity,
            sort_order=tm.sort_order,
        )


def reverse_backfill(apps, schema_editor):
    # Best-effort reverse: rebuild TemplateMaterials from associations.
    # Some original fields (description, units, unit_cost, sell_price,
    # accounting_category) get default values since they were never carried
    # forward. This is acceptable since we only reverse pre-production data.
    from decimal import Decimal
    TemplateMaterial = apps.get_model('inventory', 'TemplateMaterial')
    TemplateMaterialAssociation = apps.get_model('inventory', 'TemplateMaterialAssociation')

    for a in TemplateMaterialAssociation.objects.all():
        TemplateMaterial.objects.create(
            work_template_id=a.work_template_id,
            price_list_item_id=a.price_list_item_id,
            quantity=a.quantity,
            sort_order=a.sort_order,
            description='',
            units='none',
            unit_cost=Decimal('0.00'),
            sell_price=Decimal('0.00'),
        )


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0020_templatematerialassociation'),
    ]
    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
