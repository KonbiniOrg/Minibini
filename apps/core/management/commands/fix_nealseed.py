"""
Management command that rewrites fixtures/large_datasets/nealseed.json into
a loadable nealseed_fixed.json by:
  1. Remapping legacy core.historyentry records to the correct concrete subclass.
  2. Dropping records whose model no longer exists.
  3. Stripping fields that no longer exist on any model.
"""
import json
from django.apps import apps as django_apps
from django.core.management.base import BaseCommand


DROP_MODELS = {
    'inventory.inventoryadjustment',
}

HISTORY_OBJECT_TYPE_MAP = {
    'job': 'core.jobhistory', 'task': 'core.jobhistory',
    'estimate': 'core.jobhistory', 'changeorder': 'core.jobhistory',
    'invoice': 'core.jobhistory', 'material': 'core.jobhistory',
    'deliverable': 'core.jobhistory', 'shipment': 'core.jobhistory',
    'contact': 'core.crmhistory', 'business': 'core.crmhistory',
    'purchaseorder': 'core.purchasinghistory', 'bill': 'core.purchasinghistory',
    'inventoryitem': 'core.inventoryhistory',
    'expense': 'core.expenseshistory', 'reimbursement': 'core.expenseshistory',
}


def known_fields(model_label):
    try:
        app_label, model_name = model_label.split('.')
        model = django_apps.get_model(app_label, model_name)
    except LookupError:
        return None
    names = set()
    for f in model._meta.get_fields():
        names.add(f.name)
        if hasattr(f, 'attname'):
            names.add(f.attname)
    return names


class Command(BaseCommand):
    help = 'Transform nealseed.json into a loadable nealseed_fixed.json'

    def handle(self, *args, **options):
        src = 'fixtures/large_datasets/nealseed.json'
        dst = 'fixtures/large_datasets/nealseed_fixed.json'

        self.stdout.write(f'Reading {src}...')
        with open(src) as f:
            data = json.load(f)

        remapped = dropped = field_stripped = skipped_history = 0
        field_drop_log = {}
        out = []

        for record in data:
            model = record.get('model')

            if model in DROP_MODELS:
                dropped += 1
                continue

            if model == 'core.historyentry':
                object_type = record['fields'].get('object_type', '')
                new_model = HISTORY_OBJECT_TYPE_MAP.get(object_type)
                if new_model is None:
                    skipped_history += 1
                    continue
                record = dict(record, model=new_model)
                model = new_model
                remapped += 1

            fields = known_fields(model)
            if fields is not None:
                bad = [k for k in record['fields'] if k not in fields]
                if bad:
                    record = dict(record, fields={k: v for k, v in record['fields'].items() if k in fields})
                    field_stripped += 1
                    field_drop_log.setdefault(model, set()).update(bad)

            out.append(record)

        self.stdout.write(f'Remapped {remapped} history records.')
        self.stdout.write(f'Dropped {dropped} records for obsolete models.')
        self.stdout.write(f'Stripped stale fields from {field_stripped} records.')
        if skipped_history:
            self.stdout.write(self.style.WARNING(
                f'Skipped {skipped_history} core.historyentry records with unknown object_type.'
            ))
        if field_drop_log:
            self.stdout.write('Fields removed per model:')
            for m, fs in sorted(field_drop_log.items()):
                self.stdout.write(f'  {m}: {sorted(fs)}')

        self.stdout.write(f'\nWriting {dst}...')
        with open(dst, 'w') as f:
            json.dump(out, f, indent=2)

        self.stdout.write(self.style.SUCCESS(
            f'Done. Run: python manage.py loaddata fixtures/large_datasets/nealseed_fixed.json'
        ))
