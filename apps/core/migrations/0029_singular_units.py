import json
from django.db import migrations

UNIT_RENAMES = {'hours': 'hour', 'sheets': 'sheet', 'lbs': 'lb', 'pcs': 'pc'}

# (app_label, model, field) for every stored unit string.
UNIT_FIELDS = [
    ('estimates', 'EstimateLineItem', 'units'),
    ('estimates', 'ChangeOrderLineItem', 'units'),
    ('purchasing', 'PurchaseOrderLineItem', 'units'),
    ('purchasing', 'BillLineItem', 'units'),      # schema stub; rows may exist
    ('invoicing', 'InvoiceLineItem', 'units'),
    ('inventory', 'InventoryItem', 'units'),
    ('inventory', 'Material', 'units'),
    ('deliverables', 'Deliverable', 'units'),
    ('deliverables', 'DeliverableSnapshot', 'units'),
    ('jobs', 'RateScheme', 'unit_label'),
]


def forwards(apps, schema_editor):
    Configuration = apps.get_model('core', 'Configuration')
    try:
        cfg = Configuration.objects.get(key='units_list')
    except Configuration.DoesNotExist:
        cfg = None
    if cfg is not None:
        try:
            units = json.loads(cfg.value)
        except ValueError:
            units = None
        if isinstance(units, list):
            units = [UNIT_RENAMES.get(u, u) for u in units]
            if 'hour' not in units:
                units.append('hour')
            cfg.value = json.dumps(units)
            cfg.save(update_fields=['value'])

    # QuerySet.update() is correct here despite the house rule: historical
    # models carry no custom save(), and none of these fields are
    # save-normalized.
    for app_label, model_name, field in UNIT_FIELDS:
        Model = apps.get_model(app_label, model_name)
        for old, new in UNIT_RENAMES.items():
            Model.objects.filter(**{field: old}).update(**{field: new})

    # elapsed_time schemes were always billed in hours whatever their label
    # said; correct the label (fixes a lie, not a price).
    RateScheme = apps.get_model('jobs', 'RateScheme')
    RateScheme.objects.filter(algorithm='elapsed_time') \
        .exclude(unit_label='hour').update(unit_label='hour')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0028_accountingcategory_is_deposit'),
        # Routed through a single sequential anchor chain (rather than
        # depending on estimates/purchasing/invoicing/inventory/deliverables/
        # jobs directly here as six siblings) so a fresh build walks all of
        # them in a known-safe order instead of MigrationGraph's reverse-
        # alphabetical sibling DFS order, which walks straight into several
        # existing renames' ordering hazards (PriceListItem -> InventoryItem;
        # RateScheme -> ServicePrice -> ServiceItem -> RateScheme). See
        # apps/purchasing/migrations/0018_anchor_expenses_before_pricelistitem_rename.py
        # through 0024_anchor_deliverables_latest.py for the full "why" and
        # the per-link reasoning. This also transitively satisfies the
        # 'estimates' and 'purchasing' dependencies UNIT_FIELDS needs below.
        ('purchasing', '0024_anchor_deliverables_latest'),
    ]
    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
