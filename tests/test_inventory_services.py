"""Tests for inventory app service methods (service-mediated saves)."""
from decimal import Decimal
from django.test import TestCase
from apps.core.models import AccountingCategory
from apps.inventory.models import PriceListItem
from apps.inventory.services import InventoryService
from apps.core.services import NotFoundError


class InventoryServiceTest(TestCase):
    """Tests for InventoryService create/update methods."""

    def setUp(self):
        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]

    def test_create_item(self):
        """Create a new PriceListItem via service."""
        pli = InventoryService.create_item(
            code='MAT-001', description='Steel plate', units='sheets',
            purchase_price=Decimal('50.00'), selling_price=Decimal('75.00'),
            accounting_category=self.category,
        )
        self.assertEqual(pli.code, 'MAT-001')
        self.assertEqual(pli.description, 'Steel plate')
        self.assertEqual(pli.units, 'sheets')
        self.assertEqual(pli.purchase_price, Decimal('50.00'))
        self.assertEqual(pli.selling_price, Decimal('75.00'))
        self.assertIsNotNone(pli.pk)

    def test_create_item_with_defaults(self):
        """Create with minimal args — defaults should apply."""
        pli = InventoryService.create_item(code='MAT-002', description='Bolts', accounting_category=self.category)
        self.assertEqual(pli.purchase_price, Decimal('0.00'))
        self.assertEqual(pli.selling_price, Decimal('0.00'))
        self.assertEqual(pli.qty_on_hand, Decimal('0.00'))
        self.assertTrue(pli.is_active)
        self.assertFalse(pli.is_inventoried)

    def test_create_item_inventoried(self):
        """Create an inventoried item with initial stock."""
        pli = InventoryService.create_item(
            code='INV-001', description='Lumber', units='bd ft',
            is_inventoried=True, qty_on_hand=Decimal('100.00'),
            accounting_category=self.category,
        )
        self.assertTrue(pli.is_inventoried)
        self.assertEqual(pli.qty_on_hand, Decimal('100.00'))

    def test_update_item(self):
        """Update an existing PriceListItem by PK."""
        pli = PriceListItem.objects.create(
            code='MAT-001', description='Steel', units='sheets',
            accounting_category=self.category,
        )
        updated = InventoryService.update_item(
            pli.pk, description='Stainless steel', selling_price=Decimal('80.00'),
        )
        self.assertEqual(updated.description, 'Stainless steel')
        self.assertEqual(updated.selling_price, Decimal('80.00'))
        self.assertEqual(updated.code, 'MAT-001')  # unchanged

    def test_update_item_persists(self):
        """Update should be persisted to database."""
        pli = PriceListItem.objects.create(code='MAT-001', description='Steel', accounting_category=self.category)
        InventoryService.update_item(pli.pk, description='Aluminum')
        refreshed = PriceListItem.objects.get(pk=pli.pk)
        self.assertEqual(refreshed.description, 'Aluminum')

    def test_update_item_not_found(self):
        """Updating a nonexistent PK raises NotFoundError."""
        with self.assertRaises(NotFoundError):
            InventoryService.update_item(99999, description='Nope')


class AssignPlanTaskServiceTest(TestCase):
    """Tests for InventoryService.assign_plan_task — moves PlanMaterial across PlanTasks."""

    def setUp(self):
        from apps.contacts.models import Contact
        from apps.jobs.models import Job, PlanTask, RateScheme
        from apps.estimates.models import EstWorksheet
        from apps.inventory.models import PlanMaterial
        self.cat = AccountingCategory.objects.get_or_create(
            code='APT-CAT', defaults={'name': 'apt', 'taxable': False},
        )[0]
        self.contact = Contact.objects.create(first_name='Apt', last_name='User')
        self.job = Job.objects.create(job_number='APT-JOB', contact=self.contact)
        self.worksheet = EstWorksheet.objects.create(job=self.job)
        self.scheme = RateScheme.objects.create(
            name='apt-scheme', algorithm=RateScheme.FLAT_FEE,
            rate=Decimal('1'), unit_label='ea', accounting_category=self.cat,
        )
        self.task_a = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='A',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.task_b = PlanTask.objects.create(
            est_worksheet=self.worksheet, name='B',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        # A second worksheet w/ its own PlanTask, for cross-worksheet rejection.
        self.other_ws = EstWorksheet.objects.create(job=self.job)
        self.other_task = PlanTask.objects.create(
            est_worksheet=self.other_ws, name='Other',
            rate_scheme=self.scheme, est_qty=Decimal('1'),
        )
        self.mat = PlanMaterial.objects.create(
            est_worksheet=self.worksheet, plan_task=self.task_a,
            description='m', quantity=Decimal('1'),
        )

    def test_assign_plan_task_moves_fk(self):
        InventoryService.assign_plan_task(self.mat, self.task_b)
        self.mat.refresh_from_db()
        self.assertEqual(self.mat.plan_task_id, self.task_b.pk)

    def test_assign_plan_task_none_makes_taskless(self):
        InventoryService.assign_plan_task(self.mat, None)
        self.mat.refresh_from_db()
        self.assertIsNone(self.mat.plan_task_id)

    def test_assign_plan_task_cross_worksheet_rejected(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            InventoryService.assign_plan_task(self.mat, self.other_task)
        self.mat.refresh_from_db()
        self.assertEqual(self.mat.plan_task_id, self.task_a.pk)
