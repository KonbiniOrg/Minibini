from decimal import Decimal
from django.db import IntegrityError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource, EstWorksheet
from apps.inventory.models import PlanMaterial
from apps.jobs.models import Job, PlanTask, ServicePrice


class EstimateLineItemSourceTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.create(key='job_number_sequence', value='JOB-{year}-{counter:04d}')
        AppState.objects.create(key='job_counter', value='0')
        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True)
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='j@example.com', mobile_number='555-0001',
        )
        self.job = Job.objects.create(contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-0001')
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.estimate = Estimate.objects.create(job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0001')
        self.scheme = ServicePrice.objects.create(
            name='Hourly', algorithm=ServicePrice.ELAPSED_TIME, rate=Decimal('95'),
            unit_label='hour', accounting_category=self.cat,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='Setup',
            service_price=self.scheme,
            est_qty=Decimal('1'),
        )
        self.plan_material = PlanMaterial.objects.create(
            est_worksheet=self.worksheet, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        self.line_item = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('95'), description='', accounting_category=self.cat,
        )

    def test_create_source_for_plan_task(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
            source_pk=self.plan_task.pk,
        )
        self.assertEqual(src.estimate_line_item, self.line_item)

    def test_create_source_for_plan_material(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_MATERIAL,
            source_pk=self.plan_material.pk,
        )
        self.assertEqual(src.source_pk, self.plan_material.pk)

    def test_unique_constraint_blocks_double_claim(self):
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
            source_pk=self.plan_task.pk,
        )
        other_li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('1'), description='', accounting_category=self.cat,
        )
        with self.assertRaises(IntegrityError):
            EstimateLineItemSource.objects.create(
                estimate_line_item=other_li,
                source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
                source_pk=self.plan_task.pk,
            )

    def test_resolve_returns_plan_task(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
            source_pk=self.plan_task.pk,
        )
        self.assertEqual(src.resolve(), self.plan_task)

    def test_resolve_returns_plan_material(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_MATERIAL,
            source_pk=self.plan_material.pk,
        )
        self.assertEqual(src.resolve(), self.plan_material)

    def test_cascade_on_line_item_delete(self):
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_PLAN_TASK,
            source_pk=self.plan_task.pk,
        )
        li_pk = self.line_item.pk
        self.line_item.delete()
        self.assertFalse(EstimateLineItemSource.objects.filter(estimate_line_item_id=li_pk).exists())

