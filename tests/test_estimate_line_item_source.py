from decimal import Decimal
from django.db import IntegrityError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, AppState
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import Material
from apps.jobs.models import Job, Task, RateScheme


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
        self.estimate = Estimate.objects.create(job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-0001')
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('95'),
            unit_label='hour', accounting_category=self.cat,
        )
        self.task = Task.objects.create(
            job=self.job, name='Setup',
            rate_scheme=self.scheme,
            est_qty=Decimal('1'),
        )
        self.material = Material.objects.create(
            job=self.job, description='steel', quantity=Decimal('2'),
            sell_price=Decimal('5'), accounting_category=self.cat,
        )
        self.line_item = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('95'), description='', accounting_category=self.cat,
        )

    def test_create_source_for_task(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self.assertEqual(src.estimate_line_item, self.line_item)

    def test_create_source_for_material(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=self.material.pk,
        )
        self.assertEqual(src.source_pk, self.material.pk)

    def test_unique_constraint_blocks_double_claim(self):
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        other_li = EstimateLineItem.objects.create(
            estimate=self.estimate, qty=Decimal('1'), units='each',
            price=Decimal('1'), description='', accounting_category=self.cat,
        )
        with self.assertRaises(IntegrityError):
            EstimateLineItemSource.objects.create(
                estimate_line_item=other_li,
                source_type=EstimateLineItemSource.SOURCE_TASK,
                source_pk=self.task.pk,
            )

    def test_resolve_returns_task(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        self.assertEqual(src.resolve(), self.task)

    def test_resolve_returns_material(self):
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=self.material.pk,
        )
        self.assertEqual(src.resolve(), self.material)

    def test_serializer_computed_amount_uses_est_qty_for_task_not_actuals(self):
        """An estimate Task source's computed_amount must reflect the est_qty
        quote (compute_estimate_amount), NOT the task's actuals. A freshly-added
        task with no bleps/actual_qty bills $0 via compute_amount(), which would
        read as '$0.00 / out of sync' against its est_qty-priced line."""
        from apps.api.estimates.serializers import EstimateLineItemSourceSerializer
        # Guard: actuals are 0 (no bleps), est_qty quote is 95 (1 × $95).
        self.assertEqual(self.task.compute_amount(), Decimal('0.00'))
        self.assertEqual(self.task.compute_estimate_amount(), Decimal('95.00'))
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        data = EstimateLineItemSourceSerializer(src).data
        self.assertEqual(data['computed_amount'], '95.00')

    def test_serializer_computed_amount_for_material_uses_compute_amount(self):
        """Material has no est/actual split — computed_amount stays quantity ×
        sell_price (2 × $5 = $10.00) via the compute_amount() fallback."""
        from apps.api.estimates.serializers import EstimateLineItemSourceSerializer
        src = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=self.material.pk,
        )
        data = EstimateLineItemSourceSerializer(src).data
        self.assertEqual(data['computed_amount'], '10.00')

    def test_cascade_on_line_item_delete(self):
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line_item,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        li_pk = self.line_item.pk
        self.line_item.delete()
        self.assertFalse(EstimateLineItemSource.objects.filter(estimate_line_item_id=li_pk).exists())
