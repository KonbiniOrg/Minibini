# tests/test_units_service_defaults.py
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import Job, PlanTask, PlanBundle
from apps.estimates.models import EstWorksheet, EstimateLineItem
from apps.estimates.services import EstimateGenerationService
from apps.contacts.models import Contact
from apps.core.models import Configuration, AccountingCategory
from apps.inventory.models import Material, PriceListItem, PlanMaterial


class EstimateGenerationUnitsDefaultTest(TestCase):

    def setUp(self):
        Configuration.objects.get_or_create(
            key='estimate_number_sequence',
            defaults={'value': 'EST-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='estimate_counter',
            defaults={'value': '0'}
        )
        self.contact = Contact.objects.create(first_name='Test', last_name='User')
        self.job = Job.objects.create(job_number='J-USD-001', contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.category, _ = AccountingCategory.objects.get_or_create(
            code='LBR', defaults={'name': 'Labor'}
        )

    def test_direct_task_line_item_uses_task_units(self):
        """When a task has explicit units set, the line item should use those units."""
        PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Paint walls',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.00'),
            units='hours',
            mapping_strategy='direct',
        )
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(self.worksheet)
        li = estimate.estimatelineitem_set.first()
        self.assertIsNotNone(li)
        self.assertEqual(li.units, 'hours')

    def test_direct_task_line_item_defaults_to_none(self):
        """When a task has 'none' units (the model default), the line item uses 'none'."""
        # PlanTask model default for units is 'none', so this exercises the normal path
        PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Sand floors',
            rate=Decimal('40.00'),
            est_qty=Decimal('3.00'),
            units='none',
            mapping_strategy='direct',
        )
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(self.worksheet)
        li = estimate.estimatelineitem_set.first()
        self.assertIsNotNone(li)
        self.assertEqual(li.units, 'none')

    def test_material_line_item_uses_none_not_each(self):
        """Material line items should default to 'none', not 'each'."""
        task = PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Install shelving',
            rate=Decimal('50.00'),
            est_qty=Decimal('2.00'),
            units='hours',
            mapping_strategy='direct',
        )
        PlanMaterial.objects.create(est_worksheet=self.worksheet,plan_task=task,
            description='Plywood sheet',
            quantity=Decimal('3.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(self.worksheet)
        # The material line item has no task FK, only a material FK
        material_li = estimate.estimatelineitem_set.filter(material__isnull=False).first()
        self.assertIsNotNone(material_li)
        self.assertEqual(material_li.units, 'none')

    def test_bundle_line_item_uses_none_not_each(self):
        """Bundle line items should default to 'none', not 'each'."""
        bundle = PlanBundle.objects.create(
            name='Prep work',
            est_worksheet=self.worksheet,
            accounting_category=self.category,
        )
        PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Sand',
            rate=Decimal('30.00'),
            est_qty=Decimal('1.00'),
            units='hours',
            mapping_strategy='bundle',
            bundle=bundle,
        )
        PlanTask.objects.create(
            est_worksheet=self.worksheet,
            name='Prime',
            rate=Decimal('40.00'),
            est_qty=Decimal('1.00'),
            units='hours',
            mapping_strategy='bundle',
            bundle=bundle,
        )
        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(self.worksheet)
        bundle_li = estimate.estimatelineitem_set.filter(task__isnull=True, material__isnull=True).first()
        self.assertIsNotNone(bundle_li)
        self.assertEqual(bundle_li.units, 'none')
