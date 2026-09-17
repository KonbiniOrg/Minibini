from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.estimates.services import EstimateWizardService
from apps.inventory.models import Material
from apps.jobs.models import Job, RateScheme, Task


class PerUnitDerivationTest(TestCase):
    """Per-unit-lines spec Task 2: the derivation/sync branch for per_unit
    lines. A per_unit line's price is compared against the raw Σ of
    per_unit_qty × atom-rate over its claimed sources — NO division by
    qty — whereas a whole-line (per_unit=False) line keeps today's
    price == round(sum/qty, 2) rule unchanged.
    """

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='j@example.com', mobile_number='555-0001',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('60'),
            unit_label='hour', accounting_category=self.cat,
        )
        self.task = Task(job=self.job, name='Setup', est_qty=Decimal('1'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        self.material = Material.objects.create(
            job=self.job, description='Steel', quantity=Decimal('1'),
            sell_price=Decimal('2.50'), accounting_category=self.cat,
        )

    def _make_per_unit_line(self, price):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('10'), units='each',
            price=price, description='', accounting_category=self.cat,
            per_unit=True,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
            per_unit_qty=Decimal('0.75'),
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=self.material.pk,
            per_unit_qty=Decimal('4'),
        )
        return li

    def test_per_unit_sum_tasks_and_materials(self):
        # task claim: 0.75 * $60/h = $45.00; material claim: 4 * $2.50 = $10.00
        # -> Σ = $55.00, with NO division by qty (qty=10).
        li = self._make_per_unit_line(Decimal('55.00'))
        self.assertEqual(EstimateWizardService._line_sum(li), Decimal('55.00'))

    def test_per_unit_in_sync_is_price_equals_sum(self):
        li = self._make_per_unit_line(Decimal('55.00'))
        sum_value = EstimateWizardService._line_sum(li)
        self.assertTrue(EstimateWizardService._is_in_sync(li, sum_value))

        # The whole-line reading (price == sum * qty) must NOT pass either —
        # a per-unit line is never judged against sum/qty or sum*qty.
        li.price = Decimal('550.00')
        li.save()
        self.assertFalse(EstimateWizardService._is_in_sync(li, sum_value))

    def test_whole_line_sync_rule_unchanged(self):
        # Regression pin: per_unit=False keeps price == round(sum/qty, 2).
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('2'), units='each',
            price=Decimal('100.00'), description='', accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        # task.compute_estimate_amount(): est_qty=1 * rate=60 = $60.00 (whole-job total)
        second_task = Task(job=self.job, name='Second', est_qty=Decimal('1'))
        second_task.stamp_from_scheme(self.scheme)
        second_task.save()
        EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=second_task.pk,
        )
        # sum = $120.00, qty = 2 -> expected per-unit price = $60.00, not $100.00
        sum_value = EstimateWizardService._line_sum(li)
        self.assertEqual(sum_value, Decimal('120.00'))
        self.assertFalse(EstimateWizardService._is_in_sync(li, sum_value))

        li.price = Decimal('60.00')
        li.save()
        self.assertTrue(EstimateWizardService._is_in_sync(li, sum_value))

    def test_per_unit_backing_chip_in_sync(self):
        # Proves the serializer's backing derivation calls the per_unit-aware
        # dispatcher rather than _sum_sources directly: an out-of-sync
        # whole-line sum ($55 != round($55/10, 2) = $5.50) would otherwise
        # misclassify this in-sync per-unit line as 'edited_work'.
        from apps.api.estimates.serializers import derive_estimate_backing

        li = self._make_per_unit_line(Decimal('55.00'))
        self.assertEqual(derive_estimate_backing(li), 'planned_work')

    def test_resync_per_unit_recomputes_price_as_per_unit_sum(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('10'), units='each',
            price=Decimal('45.00'), description='', accounting_category=self.cat,
            per_unit=True,
        )
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
            per_unit_qty=Decimal('0.75'),
        )
        # Bump the claim's per-unit qty post-creation (e.g. a modal edit) —
        # resync must recompute price = the new per-unit sum (1.00 * $60 =
        # $60.00), NOT sum/qty ($6.00), and must leave qty untouched (a
        # per-unit line's price is independent of qty, unlike the uniform
        # money-bundle resummarization whole-line lines get).
        src.per_unit_qty = Decimal('1.00')
        src.save()

        EstimateWizardService._resync_in_sync_line_item(li)
        li.refresh_from_db()
        self.assertEqual(li.price, Decimal('60.00'))
        self.assertEqual(li.qty, Decimal('10'))
