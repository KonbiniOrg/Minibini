from django.db import migrations


def forwards(apps, schema_editor):
    from apps.estimates.line_kind_backfill import (
        backfill_change_order_line_item_kind,
        backfill_estimate_line_item_kind,
    )
    EstimateLineItem = apps.get_model('estimates', 'EstimateLineItem')
    ChangeOrderLineItem = apps.get_model('estimates', 'ChangeOrderLineItem')
    EstimateLineItemSource = apps.get_model('estimates', 'EstimateLineItemSource')
    ChangeOrderLineItemSource = apps.get_model('estimates', 'ChangeOrderLineItemSource')
    backfill_estimate_line_item_kind(EstimateLineItem, EstimateLineItemSource)
    backfill_change_order_line_item_kind(ChangeOrderLineItem, ChangeOrderLineItemSource)


class Migration(migrations.Migration):

    dependencies = [
        ('estimates', '0045_changeorderlineitem_freeform_kind_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
