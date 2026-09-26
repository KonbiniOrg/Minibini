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


class PerUnitSourceSumQuantizationTest(TestCase):
    """Final-review Finding 4: `_sum_per_unit_sources` must quantize each
    row's `per_unit_qty × rate` to the cent BEFORE summing — matching the
    BundleModal's price-seed math and `_sum_sources` (which sums already-
    per-atom-quantized amounts) — rather than quantizing only the final
    total. Multiple rows landing on a half-cent can otherwise disagree by a
    cent between the two readings and birth a line one cent 'out of sync'.
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
            email='j2@example.com', mobile_number='555-0002',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0002')
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0002')
        # A deliberately cheap rate so 0.5 x $0.05 = $0.025 lands exactly on
        # a half-cent — the case where per-row and final-total quantization
        # genuinely diverge (not a rounding coincidence). ELAPSED_TIME
        # schemes are billed in hours (model-enforced unit_label='hour');
        # the per-unit_qty (0.5) stands in for "half an hour" here, it need
        # not correspond to the line's own 'each' units.
        self.cheap_scheme = RateScheme.objects.create(
            name='Cheap', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('0.05'),
            unit_label='hour', accounting_category=self.cat,
        )

    def _cheap_task(self):
        t = Task(job=self.job, name='Cheap unit')
        t.stamp_from_scheme(self.cheap_scheme)
        t.save()
        return t

    def test_per_row_quantization_matches_modal_seed_math(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('10'), units='each',
            price=Decimal('0.06'), description='', accounting_category=self.cat,
            per_unit=True,
        )
        for _ in range(3):
            task = self._cheap_task()
            EstimateLineItemSource.objects.create(
                estimate_line_item=li,
                source_type=EstimateLineItemSource.SOURCE_TASK,
                source_pk=task.pk,
                per_unit_qty=Decimal('0.5'),
            )
        # Each row: 0.5 x $0.05/each = $0.025 -> quantized per row to $0.02
        # (bankers' rounding: 0.025 ties to the nearest EVEN cent, 2) ->
        # Sigma over 3 rows = $0.06. Quantizing only the FINAL total instead
        # gives 0.075 -> $0.08 (7 is odd, rounds up to the even 8) — a real
        # one-cent disagreement, not luck.
        self.assertEqual(
            EstimateWizardService._sum_per_unit_sources(li), Decimal('0.06'))
        # Regression pin on the bug: summing raw (unquantized) products and
        # quantizing only the total would have produced $0.08.
        self.assertNotEqual(
            EstimateWizardService._sum_per_unit_sources(li), Decimal('0.08'))


class PerUnitSourceSumSkipContractTest(TestCase):
    """Final-review Finding 4 (ledger item, task-2-report.md: 'no direct
    test for _sum_per_unit_sources skip-on-None/dangling contract'): a row
    whose `per_unit_qty` is unset, or whose atom has been deleted out from
    under the claim, is silently skipped rather than raising or
    contributing a bogus amount."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='j3@example.com', mobile_number='555-0003',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0003')
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0003')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('60'),
            unit_label='hour', accounting_category=self.cat,
        )
        self.li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('10'), units='each',
            price=Decimal('45.00'), description='', accounting_category=self.cat,
            per_unit=True,
        )

    def _task(self):
        t = Task(job=self.job, name='Setup')
        t.stamp_from_scheme(self.scheme)
        t.save()
        return t

    def test_row_with_unset_per_unit_qty_is_skipped(self):
        counted_task = self._task()
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=counted_task.pk,
            per_unit_qty=Decimal('0.75'),
        )
        uncounted_task = self._task()
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=uncounted_task.pk,
            per_unit_qty=None,
        )
        # Only the counted row contributes: 0.75 * $60 = $45.00. If the
        # unset row weren't skipped it would raise (None * rate) instead.
        self.assertEqual(
            EstimateWizardService._sum_per_unit_sources(self.li), Decimal('45.00'))

    def test_row_with_dangling_atom_is_skipped(self):
        counted_task = self._task()
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=counted_task.pk,
            per_unit_qty=Decimal('0.75'),
        )
        dangling_task = self._task()
        dangling_src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=dangling_task.pk,
            per_unit_qty=Decimal('1.00'),
        )
        # Bulk-delete bypasses Task.delete()'s own source-row purge
        # (CLAUDE.md's own warning against QuerySet.delete() bypassing a
        # custom delete() — used here deliberately, same pattern as
        # test_api_estimates.py's dangling-source tests, to reproduce a
        # pre-purge dangling claim).
        Task.objects.filter(pk=dangling_task.pk).delete()

        self.assertEqual(
            EstimateWizardService._sum_per_unit_sources(self.li), Decimal('45.00'))
        # The dangling row itself is untouched by the sum (dangling-tolerant,
        # not dangling-deleting) — still there, still per_unit_qty=1.00.
        dangling_src.refresh_from_db()
        self.assertEqual(dangling_src.per_unit_qty, Decimal('1.00'))
