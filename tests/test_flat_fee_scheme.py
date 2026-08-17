"""Flat-fee rate schemes, Task 1: the `flat_fee` algorithm constant and the
scheme-owned interpretation layer.

Load-bearing requirement: RateScheme is the SOLE interpreter of the
polymorphic modifier/config JSON. `RateScheme.resolve_stamp` /
`validate_item_config` / `effective_rate` own that interpretation;
`Task.stamp_from_scheme` becomes a pure delegation to `resolve_stamp`.
Downstream consumers (Task.effective_rate, Task.get_actual_qty,
copy_active_modifiers, TaskSerializer.validate_active_modifiers) must see
zero behavior change for the pre-existing algorithms — the equivalence bar
for this module is byte-identical stamping.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, RateScheme, Task


class FlatFeeSchemeTestBase(TestCase):
    def setUp(self):
        self.ac = AccountingCategory.objects.create(code='X-flatfee', name='X-flatfee')
        self.hourly = RateScheme.objects.create(
            name='Hourly-flatfee', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('95.00'), unit_label='hour',
            modifiers=[
                {'key': 'rush', 'label': 'Rush', 'percent': 20},
                {'key': 'weekend', 'label': 'Weekend', 'percent': 10},
            ],
            accounting_category=self.ac,
        )
        self.elapsed = RateScheme.objects.create(
            name='Elapsed-flatfee', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('60.00'), unit_label='hour',
            accounting_category=self.ac,
        )
        self.pct = RateScheme.objects.create(
            name='Pct-flatfee', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='none',
            accounting_category=self.ac,
        )
        self.flat = RateScheme.objects.create(
            name='Setup fee-flatfee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('0.00'), unit_label='fee',
            modifiers=[], accounting_category=self.ac,
        )
        contact = Contact.objects.create(
            first_name='F', last_name='F', email='f-flatfee@t.test',
        )
        self.job = Job.objects.create(job_number='JOB-flatfee-1', contact=contact)


class AlgorithmConstantTest(TestCase):
    def test_flat_fee_constant_value(self):
        self.assertEqual(RateScheme.FLAT_FEE, 'flat_fee')

    def test_flat_fee_in_algorithm_choices(self):
        self.assertIn(('flat_fee', 'Flat fee'), RateScheme.ALGORITHM_CHOICES)


class ResolveStampExistingAlgorithmsTest(FlatFeeSchemeTestBase):
    def test_entered_qty_resolves_verbatim(self):
        result = self.hourly.resolve_stamp(['rush'])
        self.assertEqual(result['qty_source'], RateScheme.ENTERED_QTY)
        self.assertEqual(result['rate'], Decimal('95.00'))
        self.assertEqual(result['unit_label'], 'hour')
        self.assertEqual(result['accounting_category'], self.ac)
        self.assertEqual(
            result['active_modifiers'], [{'key': 'rush', 'label': 'Rush', 'percent': 20}],
        )

    def test_entered_qty_no_keys_yields_empty_active_modifiers(self):
        result = self.hourly.resolve_stamp(None)
        self.assertEqual(result['active_modifiers'], [])

    def test_entered_qty_unknown_key_ignored(self):
        result = self.hourly.resolve_stamp(['not-a-real-key'])
        self.assertEqual(result['active_modifiers'], [])

    def test_elapsed_time_resolves_verbatim(self):
        result = self.elapsed.resolve_stamp(None)
        self.assertEqual(result['qty_source'], RateScheme.ELAPSED_TIME)
        self.assertEqual(result['rate'], Decimal('60.00'))
        self.assertEqual(result['unit_label'], 'hour')
        self.assertEqual(result['accounting_category'], self.ac)
        self.assertEqual(result['active_modifiers'], [])

    def test_percentage_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.pct.resolve_stamp(None)


class ResolveStampFlatFeeTest(FlatFeeSchemeTestBase):
    def test_flat_fee_resolves_amount_into_rate(self):
        result = self.flat.resolve_stamp([{'amount': '150.00', 'label': 'Setup'}])
        self.assertEqual(result['qty_source'], RateScheme.ENTERED_QTY)
        self.assertEqual(result['rate'], Decimal('150.00'))
        self.assertEqual(result['unit_label'], 'fee')
        self.assertEqual(result['accounting_category'], self.ac)
        self.assertEqual(result['active_modifiers'], [])

    def test_flat_fee_amount_quantized_to_two_places(self):
        result = self.flat.resolve_stamp([{'amount': '150.006'}])
        self.assertEqual(result['rate'], Decimal('150.01'))
        self.assertIsInstance(result['rate'], Decimal)

    def test_flat_fee_no_config_pins_rate_zero(self):
        result = self.flat.resolve_stamp(None)
        self.assertEqual(result['rate'], Decimal('0.00'))
        self.assertEqual(result['qty_source'], RateScheme.ENTERED_QTY)
        self.assertEqual(result['active_modifiers'], [])

    def test_flat_fee_empty_config_pins_rate_zero(self):
        result = self.flat.resolve_stamp([])
        self.assertEqual(result['rate'], Decimal('0.00'))


class ValidateItemConfigPercentStyleTest(FlatFeeSchemeTestBase):
    def test_known_keys_accepted(self):
        self.assertIsNone(self.hourly.validate_item_config(['rush', 'weekend']))

    def test_empty_accepted(self):
        self.assertIsNone(self.hourly.validate_item_config([]))
        self.assertIsNone(self.hourly.validate_item_config(None))

    def test_unknown_key_rejected(self):
        with self.assertRaises(ValidationError):
            self.hourly.validate_item_config(['not-a-real-key'])

    def test_non_string_entry_rejected(self):
        with self.assertRaises(ValidationError):
            self.hourly.validate_item_config([{'amount': 5}])


class ValidateItemConfigFlatFeeTest(FlatFeeSchemeTestBase):
    def test_single_amount_entry_accepted(self):
        self.assertIsNone(
            self.flat.validate_item_config([{'amount': '100.00', 'label': 'Setup'}])
        )

    def test_amount_without_label_accepted(self):
        self.assertIsNone(self.flat.validate_item_config([{'amount': '25.00'}]))

    def test_empty_entries_rejected(self):
        with self.assertRaises(ValidationError):
            self.flat.validate_item_config([])

    def test_none_entries_rejected(self):
        with self.assertRaises(ValidationError):
            self.flat.validate_item_config(None)

    def test_multiple_entries_rejected(self):
        with self.assertRaises(ValidationError):
            self.flat.validate_item_config(
                [{'amount': '10.00'}, {'amount': '20.00'}]
            )

    def test_string_key_entry_rejected(self):
        with self.assertRaises(ValidationError):
            self.flat.validate_item_config(['rush'])

    def test_zero_amount_rejected(self):
        with self.assertRaises(ValidationError):
            self.flat.validate_item_config([{'amount': '0.00'}])

    def test_negative_amount_rejected(self):
        with self.assertRaises(ValidationError):
            self.flat.validate_item_config([{'amount': '-5.00'}])

    def test_missing_amount_rejected(self):
        with self.assertRaises(ValidationError):
            self.flat.validate_item_config([{'label': 'Setup'}])

    def test_percent_key_rejected_no_mixing(self):
        with self.assertRaises(ValidationError):
            self.flat.validate_item_config([{'amount': '10.00', 'percent': 5}])


class CleanFlatFeeTest(FlatFeeSchemeTestBase):
    def test_zero_rate_empty_modifiers_is_valid(self):
        scheme = RateScheme(
            name='Delivery fee-flatfee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('0.00'), unit_label='fee', modifiers=[],
            accounting_category=self.ac,
        )
        scheme.full_clean()  # must not raise

    def test_nonzero_rate_rejected(self):
        scheme = RateScheme(
            name='Bad rate-flatfee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('10.00'), unit_label='fee', modifiers=[],
            accounting_category=self.ac,
        )
        with self.assertRaises(ValidationError) as ctx:
            scheme.full_clean()
        self.assertIn('rate', ctx.exception.message_dict)

    def test_nonempty_modifiers_rejected(self):
        scheme = RateScheme(
            name='Bad modifiers-flatfee', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('0.00'), unit_label='fee',
            modifiers=[{'key': 'rush', 'label': 'Rush', 'percent': 20}],
            accounting_category=self.ac,
        )
        with self.assertRaises(ValidationError) as ctx:
            scheme.full_clean()
        self.assertIn('modifiers', ctx.exception.message_dict)


class EffectiveRateFlatFeeTest(FlatFeeSchemeTestBase):
    def test_effective_rate_reads_amount_from_entries(self):
        rate = self.flat.effective_rate([{'amount': '75.00'}])
        self.assertEqual(rate, Decimal('75.00'))

    def test_effective_rate_quantizes(self):
        rate = self.flat.effective_rate([{'amount': '75.006'}])
        self.assertEqual(rate, Decimal('75.01'))

    def test_effective_rate_no_entries_is_zero(self):
        self.assertEqual(self.flat.effective_rate(None), Decimal('0.00'))
        self.assertEqual(self.flat.effective_rate([]), Decimal('0.00'))

    def test_effective_rate_percentage_still_raises(self):
        with self.assertRaises(ValueError):
            self.pct.effective_rate([])

    def test_effective_rate_other_algorithms_unchanged(self):
        # entered_qty with a rush modifier: unaffected by the flat_fee branch.
        self.assertEqual(self.hourly.effective_rate(['rush']), Decimal('114.00'))


class TaskStampFromSchemeFlatFeeTest(FlatFeeSchemeTestBase):
    def test_stamp_from_scheme_flat_fee_sets_rate_from_config(self):
        task = Task(job=self.job, name='Setup')
        task.stamp_from_scheme(
            self.flat, modifier_keys=[{'amount': '150.00', 'label': 'Setup'}],
        )
        self.assertEqual(task.qty_source, RateScheme.ENTERED_QTY)
        self.assertEqual(task.rate, Decimal('150.00'))
        self.assertEqual(task.unit_label, 'fee')
        self.assertEqual(task.accounting_category, self.ac)
        self.assertEqual(task.source_scheme, self.flat)
        self.assertEqual(task.active_modifiers, [])

    def test_manual_stamp_no_config_pins_rate_zero(self):
        task = Task(job=self.job, name='Manual fee task')
        task.stamp_from_scheme(self.flat)
        self.assertEqual(task.rate, Decimal('0.00'))
        self.assertEqual(task.qty_source, RateScheme.ENTERED_QTY)
        self.assertEqual(task.active_modifiers, [])

    def test_stamped_flat_fee_task_get_actual_qty_uses_entered_qty_path(self):
        # No new branch needed in Task.get_actual_qty: flat_fee stamps
        # qty_source = ENTERED_QTY, so the existing else-branch (actual_qty)
        # already does the right thing.
        task = Task.objects.create(
            job=self.job, name='Setup', accounting_category=self.ac,
        )
        task.stamp_from_scheme(
            self.flat, modifier_keys=[{'amount': '150.00'}],
        )
        task.actual_qty = Decimal('1')
        task.save()
        self.assertEqual(task.get_actual_qty(), Decimal('1'))

    def test_stamp_from_scheme_entered_qty_still_delegates_correctly(self):
        # Equivalence check: existing-algorithm stamping via the new
        # delegation still matches the pre-refactor field set exactly.
        task = Task(job=self.job, name='X')
        task.stamp_from_scheme(self.hourly, modifier_keys=['rush'])
        self.assertEqual(task.qty_source, RateScheme.ENTERED_QTY)
        self.assertEqual(task.rate, Decimal('95.00'))
        self.assertEqual(task.unit_label, 'hour')
        self.assertEqual(task.accounting_category, self.ac)
        self.assertEqual(task.source_scheme, self.hourly)
        self.assertEqual(
            task.active_modifiers, [{'key': 'rush', 'label': 'Rush', 'percent': 20}],
        )

    def test_stamp_from_scheme_percentage_still_raises(self):
        task = Task(job=self.job, name='X')
        with self.assertRaises(ValueError):
            task.stamp_from_scheme(self.pct)
