"""core/0029_singular_units data migration: no test previously exercised its
forwards() body directly. Precedent for calling a migration's logic directly
against the live apps registry (rather than replaying the whole migration
graph): tests/test_setup_defaults_migration.py.

Plants pre-migration legacy state — a units_list containing plural 'hours',
an elapsed_time RateScheme mislabeled with a non-hour unit, and an
InventoryItem stored with plural 'hours' — then calls forwards() and asserts
it all lands singular.
"""
import importlib
import json
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase

from apps.core.models import AccountingCategory, Configuration
from apps.inventory.models import InventoryItem
from apps.jobs.models import RateScheme

# The module name starts with a digit ('0029_...'), so it isn't importable
# via a normal `import` statement — importlib handles the dotted string fine.
_migration = importlib.import_module('apps.core.migrations.0029_singular_units')


class SingularUnitsMigrationTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='SU', code='SU')

    def test_forwards_singularizes_units_list_scheme_and_stored_values(self):
        Configuration.objects.update_or_create(
            key='units_list',
            defaults={'value': json.dumps(['none', 'ea', 'hours', 'sheets'])},
        )

        # An elapsed_time scheme mislabeled with a non-hour unit. Finding 1
        # (this branch) made RateScheme.save() run full_clean() on create,
        # which now rejects an elapsed scheme with any unit_label but
        # 'hour' — so a normal .create() can no longer plant this directly.
        # Create it validly with 'hour', then bypass save()/full_clean via
        # QuerySet.update() to simulate the pre-migration legacy row the
        # real migration exists to fix.
        scheme = RateScheme.objects.create(
            name='Legacy elapsed', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour', accounting_category=self.cat,
        )
        RateScheme.objects.filter(pk=scheme.pk).update(unit_label='min')

        # units is a free-form CharField (no model-level choice validation —
        # only the DRF UnitsField enforces the configured list), so a plain
        # .create() with the legacy plural value is enough to plant it.
        item = InventoryItem.objects.create(
            code='SU-ITEM', units='hours', accounting_category=self.cat,
        )

        _migration.forwards(django_apps, None)

        units = json.loads(Configuration.objects.get(key='units_list').value)
        self.assertNotIn('hours', units)
        self.assertNotIn('sheets', units)
        self.assertIn('hour', units)
        self.assertIn('sheet', units)

        scheme.refresh_from_db()
        self.assertEqual(scheme.unit_label, 'hour')

        item.refresh_from_db()
        self.assertEqual(item.units, 'hour')
