from datetime import timedelta
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import (
    ChangeOrder,
    ChangeOrderLineItem,
    ChangeOrderLineItemSource,
    Estimate,
    EstimateLineItem,
    EstimateLineItemSource,
)
from apps.estimates.services import EstimateService
from apps.jobs.models import Job, Task, RateScheme


class PerUnitFieldsTest(TestCase):
    """Model-level fields for per-unit lines (per-unit-lines spec Task 1).

    Atoms always store whole-job totals (spec §2); the per-unit snapshot
    lives only on claim source rows.
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
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('95'),
            unit_label='hour', accounting_category=self.cat,
        )
        self.task = Task(job=self.job, name='Setup', est_qty=Decimal('1'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        self.change_order = ChangeOrder.objects.create(
            job=self.job, estimate=self.estimate, status=ChangeOrder.STATUS_DRAFT,
        )

    def test_line_item_per_unit_defaults_false(self):
        est_li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('95'), description='', accounting_category=self.cat,
        )
        self.assertFalse(est_li.per_unit)

        co_li = ChangeOrderLineItem.objects.create(
            change_order=self.change_order, action=ChangeOrderLineItem.ACTION_ADD,
            qty=Decimal('1'), units='each', price=Decimal('95'),
            description='', accounting_category=self.cat,
        )
        self.assertFalse(co_li.per_unit)

    def test_source_per_unit_fields_default_null(self):
        est_li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('95'), description='', accounting_category=self.cat,
        )
        est_src = EstimateLineItemSource.objects.create(
            estimate_line_item=est_li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self.assertIsNone(est_src.per_unit_qty)
        self.assertIsNone(est_src.per_unit_worker_time)

        co_li = ChangeOrderLineItem.objects.create(
            change_order=self.change_order, action=ChangeOrderLineItem.ACTION_ADD,
            qty=Decimal('1'), units='each', price=Decimal('95'),
            description='', accounting_category=self.cat,
        )
        co_src = ChangeOrderLineItemSource.objects.create(
            change_order_line_item=co_li,
            source_type=ChangeOrderLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self.assertIsNone(co_src.per_unit_qty)
        self.assertIsNone(co_src.per_unit_worker_time)

    def test_revise_estimate_copies_per_unit_flag(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('95'), description='Per-unit line',
            accounting_category=self.cat, per_unit=True,
        )
        EstimateService.update_status(self.estimate.pk, Estimate.STATUS_OPEN)
        new_est = EstimateService.revise_estimate(self.estimate.pk)

        new_li = EstimateLineItem.objects.get(estimate=new_est)
        self.assertTrue(new_li.per_unit)
        self.assertNotEqual(new_li.pk, li.pk)

    def test_revise_estimate_moves_per_unit_qty_with_source_rows(self):
        li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('3'), units='each',
            price=Decimal('95'), description='Per-unit line',
            accounting_category=self.cat, per_unit=True,
        )
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=li,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
            per_unit_qty=Decimal('0.75'),
            per_unit_worker_time=timedelta(minutes=30),
        )
        EstimateService.update_status(self.estimate.pk, Estimate.STATUS_OPEN)
        EstimateService.revise_estimate(self.estimate.pk)

        src.refresh_from_db()
        self.assertNotEqual(src.estimate_line_item_id, li.pk)
        self.assertEqual(src.per_unit_qty, Decimal('0.75'))
        self.assertEqual(src.per_unit_worker_time, timedelta(minutes=30))
