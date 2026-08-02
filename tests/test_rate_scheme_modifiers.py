"""RateScheme never persists a blank modifier row.

The scheme editor could send `{key: '', label: '', percent: 0}` for an
untouched "add modifier" row; a no-name, no-percent modifier is a no-op and
is dropped on save. A row with a percent but no key is unusable (activation
is by key) and rejects loudly instead of silently losing the percent.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.core.models import AccountingCategory
from apps.jobs.models import RateScheme


class RateSchemeModifierNormalizationTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='mod', code='MOD')

    def _scheme(self, modifiers, name='S-mod'):
        return RateScheme.objects.create(
            name=name, algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea',
            accounting_category=self.cat, modifiers=modifiers,
        )

    def test_blank_row_dropped_on_create(self):
        s = self._scheme([
            {'key': 'rush', 'label': 'Rush', 'percent': 50},
            {'key': '', 'label': '', 'percent': 0},
        ])
        s.refresh_from_db()
        self.assertEqual(len(s.modifiers), 1)
        self.assertEqual(s.modifiers[0]['key'], 'rush')

    def test_blank_row_dropped_on_update(self):
        s = self._scheme([{'key': 'rush', 'label': 'Rush', 'percent': 50}],
                         name='S-mod-upd')
        s.modifiers = [
            {'key': 'rush', 'label': 'Rush', 'percent': 50},
            {'key': '', 'percent': 0},
        ]
        s.save()
        s.refresh_from_db()
        self.assertEqual(len(s.modifiers), 1)

    def test_all_blank_rows_yield_empty_list(self):
        s = self._scheme([{'key': '', 'label': '', 'percent': 0}],
                         name='S-mod-empty')
        s.refresh_from_db()
        self.assertEqual(s.modifiers, [])

    def test_percent_without_key_rejected(self):
        with self.assertRaises(ValidationError):
            self._scheme([{'key': '', 'label': '', 'percent': 25}],
                         name='S-mod-bad').full_clean()

    def test_real_modifiers_untouched(self):
        s = self._scheme([
            {'key': 'rush', 'label': 'Rush', 'percent': 50},
            {'key': 'eco', 'label': 'Eco discount', 'percent': -10},
        ], name='S-mod-real')
        s.refresh_from_db()
        self.assertEqual(len(s.modifiers), 2)


class RateSchemeElapsedUnitTest(TestCase):
    """Time-based (elapsed_time) schemes are always billed in hours."""

    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='elapsed', code='ELP')

    def test_elapsed_scheme_rejects_non_hour_unit(self):
        scheme = RateScheme.objects.create(
            name='S-elapsed', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('50'), unit_label='hour',
            accounting_category=self.cat,
        )
        scheme.unit_label = 'ea'
        with self.assertRaises(ValidationError) as ctx:
            scheme.full_clean()
        self.assertIn('unit_label', ctx.exception.message_dict)
