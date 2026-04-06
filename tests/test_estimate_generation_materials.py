"""
Tests that EstimateGenerationService correctly handles materials on tasks.

Phase 2: Materials produce their own line items on estimates.
- Direct tasks: labor line item + N material line items
- Pass-through tasks (no rate): material line items only, no labor line item
- Bundled tasks: material costs included in bundle price
- Excluded tasks: materials also excluded
- Backward compatibility: no materials = same behavior as before
"""
from decimal import Decimal
from django.test import TestCase
from apps.jobs.models import PlanTask, PlanBundle, Job
from apps.estimates.models import EstWorksheet, EstimateLineItem
from apps.inventory.models import Material, PlanMaterial
from apps.estimates.services import EstimateGenerationService
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.inventory.models import PriceListItem


class EstimateGenerationMaterialsTest(TestCase):
    """Tests for material line item generation in estimates."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='estimate_number_sequence',
            defaults={'value': 'EST-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='estimate_counter',
            defaults={'value': '0'}
        )

        self.contact = Contact.objects.create(first_name="Test", last_name="User")
        self.job = Job.objects.create(job_number="J-EGM-001", contact=self.contact)
        self.lit_labor, _ = AccountingCategory.objects.get_or_create(
            code="LBR", defaults={"name": "Labor"}
        )
        self.lit_material, _ = AccountingCategory.objects.get_or_create(
            code="MAT", defaults={"name": "Material"}
        )
        # PLI with accounting_category for testing type propagation
        self.pli_plywood = PriceListItem.objects.create(
            code='PLY.75', description='Plywood',
            purchase_price=Decimal('45.00'), selling_price=Decimal('90.00'),
            accounting_category=self.lit_material,
        )

    def test_direct_task_with_materials(self):
        """Direct task with materials produces labor + material line items."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=worksheet, name="Install shelving",
            rate=Decimal('50.00'), est_qty=Decimal('4.00'), units='hours',
            mapping_strategy='direct',
        )
        PlanMaterial.objects.create(plan_task=task, description='Plywood',
            quantity=Decimal('3.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        PlanMaterial.objects.create(plan_task=task, description='Screws',
            quantity=Decimal('100.00'), unit_cost=Decimal('0.10'),
            sell_price=Decimal('0.20'),
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # 1 labor + 2 material = 3 line items
        self.assertEqual(estimate.estimatelineitem_set.count(), 3)

        line_items = list(estimate.estimatelineitem_set.order_by('line_number'))

        # Labor line item
        labor_li = line_items[0]
        self.assertEqual(labor_li.description, 'Install shelving')
        self.assertEqual(labor_li.price, Decimal('50.00'))
        self.assertEqual(labor_li.qty, Decimal('4.00'))
        self.assertIsNone(labor_li.material)

        # Material line items
        plywood_li = line_items[1]
        self.assertEqual(plywood_li.description, 'Plywood')
        self.assertEqual(plywood_li.qty, Decimal('3.00'))
        self.assertEqual(plywood_li.price, Decimal('90.00'))
        self.assertIsNotNone(plywood_li.accounting_category)
        self.assertIsNotNone(plywood_li.material)

        screws_li = line_items[2]
        self.assertEqual(screws_li.description, 'Screws')
        self.assertEqual(screws_li.qty, Decimal('100.00'))
        self.assertEqual(screws_li.price, Decimal('0.20'))

    def test_pass_through_task_materials_only(self):
        """PlanTask with no rate (pass-through) produces material line items only, no labor."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=worksheet, name="Materials pass-through",
            rate=None, est_qty=None,
            mapping_strategy='direct',
        )
        PlanMaterial.objects.create(plan_task=task, description='Special order hardware',
            quantity=Decimal('1.00'), unit_cost=Decimal('50.00'),
            sell_price=Decimal('100.00'),
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Only material line item, no labor
        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        li = estimate.estimatelineitem_set.first()
        self.assertEqual(li.description, 'Special order hardware')
        self.assertEqual(li.price, Decimal('100.00'))
        self.assertIsNotNone(li.accounting_category)

    def test_pass_through_task_zero_rate(self):
        """PlanTask with rate=0 is also pass-through — no labor line item."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=worksheet, name="Pass-through task",
            rate=Decimal('0.00'), est_qty=Decimal('1.00'),
            mapping_strategy='direct',
        )
        PlanMaterial.objects.create(plan_task=task, description='Widget',
            quantity=Decimal('2.00'), unit_cost=Decimal('25.00'),
            sell_price=Decimal('50.00'),
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        li = estimate.estimatelineitem_set.first()
        self.assertEqual(li.description, 'Widget')

    def test_bundled_tasks_include_material_costs(self):
        """Bundled tasks include material total_sell in the bundle price."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        bundle = PlanBundle.objects.create(
            est_worksheet=worksheet, name="Cabinet Build",
            accounting_category=self.lit_labor, sort_order=1,
        )
        task1 = PlanTask.objects.create(
            est_worksheet=worksheet, name="Cut parts",
            rate=Decimal('50.00'), est_qty=Decimal('2.00'),
            mapping_strategy='bundle', bundle=bundle,
        )
        task2 = PlanTask.objects.create(
            est_worksheet=worksheet, name="Assemble",
            rate=Decimal('50.00'), est_qty=Decimal('3.00'),
            mapping_strategy='bundle', bundle=bundle,
        )
        # Materials on bundled tasks
        PlanMaterial.objects.create(plan_task=task1, description='Plywood',
            quantity=Decimal('2.00'), unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        PlanMaterial.objects.create(plan_task=task2, description='Screws',
            quantity=Decimal('50.00'), unit_cost=Decimal('0.05'),
            sell_price=Decimal('0.10'),
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Still 1 bundle line item
        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        li = estimate.estimatelineitem_set.first()
        self.assertEqual(li.description, 'Cabinet Build')

        # Bundle price = labor (2*50 + 3*50 = 250) + materials (2*90 + 50*0.10 = 185)
        expected_price = Decimal('250.00') + Decimal('180.00') + Decimal('5.00')
        self.assertEqual(li.price, expected_price)

    def test_excluded_task_materials_also_excluded(self):
        """Materials on excluded tasks are not on the estimate."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=worksheet, name="Internal prep",
            rate=Decimal('25.00'), est_qty=Decimal('1.00'),
            mapping_strategy='exclude',
        )
        PlanMaterial.objects.create(plan_task=task, description='Should not appear',
            quantity=Decimal('1.00'), unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
        )
        # Add a visible task so the estimate isn't empty
        PlanTask.objects.create(
            est_worksheet=worksheet, name="Visible task",
            rate=Decimal('50.00'), est_qty=Decimal('1.00'),
            mapping_strategy='direct',
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        # Only 1 line item (the visible task), no material line items
        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        self.assertEqual(
            estimate.estimatelineitem_set.first().description, 'Visible task'
        )

    def test_backward_compatibility_no_materials(self):
        """Tasks with no materials still work exactly as before."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        PlanTask.objects.create(
            est_worksheet=worksheet, name="Simple task",
            rate=Decimal('100.00'), est_qty=Decimal('2.00'), units='hours',
            mapping_strategy='direct',
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        self.assertEqual(estimate.estimatelineitem_set.count(), 1)
        li = estimate.estimatelineitem_set.first()
        self.assertEqual(li.description, 'Simple task')
        self.assertEqual(li.price, Decimal('100.00'))
        self.assertEqual(li.qty, Decimal('2.00'))

    def test_material_line_item_has_material_fk(self):
        """Material line items have the material FK set for traceability."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=worksheet, name="PlanTask",
            rate=Decimal('50.00'), est_qty=Decimal('1.00'),
            mapping_strategy='direct',
        )
        material = PlanMaterial.objects.create(plan_task=task, description='Bracket',
            quantity=Decimal('4.00'), unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        material_li = estimate.estimatelineitem_set.filter(
            material__isnull=False
        ).first()
        self.assertIsNotNone(material_li)
        self.assertEqual(material_li.material, material)

    def test_material_accounting_category_from_pli(self):
        """Material line items get their accounting_category from the PLI."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=worksheet, name="PlanTask",
            rate=Decimal('50.00'), est_qty=Decimal('1.00'),
            mapping_strategy='direct',
        )
        PlanMaterial.objects.create(plan_task=task, price_list_item=self.pli_plywood,
            quantity=Decimal('4.00'),
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        material_li = estimate.estimatelineitem_set.filter(
            material__isnull=False
        ).first()
        self.assertEqual(material_li.accounting_category, self.lit_material)

    def test_freeform_material_uses_own_accounting_category(self):
        """Freeform materials (no PLI) use their own accounting_category."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=worksheet, name="PlanTask",
            rate=Decimal('50.00'), est_qty=Decimal('1.00'),
            mapping_strategy='direct',
        )
        PlanMaterial.objects.create(plan_task=task, description='Custom bracket',
            quantity=Decimal('4.00'), unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
            accounting_category=self.lit_material,
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        material_li = estimate.estimatelineitem_set.filter(
            material__isnull=False
        ).first()
        self.assertEqual(material_li.accounting_category, self.lit_material)

    def test_freeform_material_no_type_gets_fallback(self):
        """Freeform materials with no accounting_category get fallback."""
        worksheet = EstWorksheet.objects.create(job=self.job)
        task = PlanTask.objects.create(
            est_worksheet=worksheet, name="PlanTask",
            rate=Decimal('50.00'), est_qty=Decimal('1.00'),
            mapping_strategy='direct',
        )
        PlanMaterial.objects.create(plan_task=task, description='Mystery part',
            quantity=Decimal('1.00'), unit_cost=Decimal('5.00'),
            sell_price=Decimal('10.00'),
        )

        service = EstimateGenerationService()
        estimate = service.generate_estimate_from_worksheet(worksheet)

        material_li = estimate.estimatelineitem_set.filter(
            material__isnull=False
        ).first()
        # Should get some type (first active), not None
        self.assertIsNotNone(material_li.accounting_category)
