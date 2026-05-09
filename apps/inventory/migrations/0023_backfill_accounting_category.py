from django.db import migrations


def backfill(apps, schema_editor):
    Material = apps.get_model('inventory', 'Material')
    PlanMaterial = apps.get_model('inventory', 'PlanMaterial')

    # PLI-linked rows: copy the PLI's category.
    for cls in (Material, PlanMaterial):
        rows = cls.objects.filter(
            accounting_category__isnull=True,
            price_list_item__isnull=False,
        ).select_related('price_list_item')
        for row in rows:
            row.accounting_category_id = row.price_list_item.accounting_category_id
            row.save(update_fields=['accounting_category'])

    # Freeform rows: halt with a clear error.
    for cls in (Material, PlanMaterial):
        freeforms = cls.objects.filter(
            accounting_category__isnull=True,
            price_list_item__isnull=True,
        )
        if freeforms.exists():
            ids = list(freeforms.values_list('pk', flat=True))
            raise RuntimeError(
                f'Cannot migrate: {len(ids)} freeform {cls.__name__}(s) without '
                f'accounting_category found (IDs: {ids}). Assign a category '
                f'before re-running this migration.'
            )


def reverse_backfill(apps, schema_editor):
    # No-op: forward migration only fills NULLs from the PLI; reversing
    # would mean re-NULLing those rows, which is destructive and unwanted.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('inventory', '0022_delete_templatematerial'),
    ]
    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]
