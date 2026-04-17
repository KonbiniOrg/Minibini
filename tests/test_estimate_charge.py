from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import RateScheme, PlanCharge, PlanTask, Job
from apps.estimates.models import EstWorksheet, EstimateLineItem
from apps.estimates.services import EstimateGenerationService
from apps.core.models import AccountingCategory
from apps.contacts.models import Contact


class EstimateFromPlanChargeTest(TestCase):

    def setUp(self):
        self.category = AccountingCategory.objects.create(
            code='LAB', name='Labor', taxable=False,
        )
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='test@test.com',
        )
        self.job = Job.objects.create(
            name='Test Job', job_number='TEST-001', status='draft',
            contact=self.contact,
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job, status='draft',
        )
        self.scheme = RateScheme.objects.create(
            name='CNC Router Test',
            algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('4.00'),
            unit_label='minute',
            modifiers=[
                {'key': 'messy', 'label': 'Messy', 'percent': 10},
            ],
            accounting_category=self.category,
        )
        self.plan_task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='CNC cut panels',
            mapping_strategy='direct',
            units='hours',
            rate=Decimal('99.00'),  # old value — should be overridden by PlanCharge
            est_qty=Decimal('99.00'),  # old value
            accounting_category=self.category,
        )

    def test_line_item_uses_plan_charge_when_present(self):
        PlanCharge.objects.create(
            plan_task=self.plan_task,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            estimated_billable_qty=Decimal('30.00'),
        )

        service = EstimateGenerationService()
        line_item = service._create_direct_line_item(self.plan_task, None)

        # Should use PlanCharge: qty=30, price=4.40 (4.00 * 1.10), units='minute'
        self.assertEqual(line_item.qty, Decimal('30.00'))
        self.assertEqual(line_item.price, Decimal('4.40'))
        self.assertEqual(line_item.units, 'minute')

    def test_line_item_falls_back_without_plan_charge(self):
        # No PlanCharge — should use PlanTask's old fields
        service = EstimateGenerationService()
        line_item = service._create_direct_line_item(self.plan_task, None)

        self.assertEqual(line_item.qty, Decimal('99.00'))
        self.assertEqual(line_item.price, Decimal('99.00'))
        self.assertEqual(line_item.units, 'hours')

    def test_bundle_uses_plan_charge_when_present(self):
        from apps.jobs.models import PlanBundle
        bundle = PlanBundle.objects.create(
            est_worksheet=self.worksheet,
            name='Bundle Test',
            accounting_category=self.category,
        )
        self.plan_task.mapping_strategy = 'bundle'
        self.plan_task.bundle = bundle
        self.plan_task.save()

        PlanCharge.objects.create(
            plan_task=self.plan_task,
            rate_scheme=self.scheme,
            active_modifiers=['messy'],
            estimated_billable_qty=Decimal('30.00'),
        )

        service = EstimateGenerationService()
        line_item = service._create_bundle_line_item(
            [self.plan_task], bundle, None
        )

        # 30 * 4.40 = 132.00
        self.assertEqual(line_item.price, Decimal('132.00'))
