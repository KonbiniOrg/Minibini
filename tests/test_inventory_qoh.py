"""
Tests for QOH Automatic Updates via InventoryService.
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, Task, RateScheme
from apps.inventory.models import Material
from apps.inventory.models import InventoryItem
from apps.inventory.models import Earmark
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.inventory.services import InventoryService, MaterialService


class ConsumeMaterialTest(TestCase):
    """Tests for MaterialService.consume()."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(
            job_number='J-QOH-002', contact=self.contact, description='Test Job',
        )

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.scheme = RateScheme.objects.create(
            name='S-qoh2', algorithm=RateScheme.ENTERED_QTY,
            rate=1, unit_label='ea', accounting_category=self.category,
        )
        self.task = Task.objects.create(
            job=self.job,
            name='Install plywood',
            description='Install plywood',
            sort_order=1,
            rate_scheme=self.scheme,
        )
        self.plywood = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheet',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            accounting_category=self.category,
        )

    def test_consume_decreases_qoh(self):
        """Consuming material decreases QOH."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            inventory_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        MaterialService.consume(material)
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('15.00'))

    def test_consume_increases_qty_sold(self):
        """Consuming material increases qty_sold."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            inventory_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        MaterialService.consume(material)
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_sold, Decimal('5.00'))

    def test_consume_reduces_earmark(self):
        """Consuming material reduces the earmark for that job."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job, quantity=Decimal('10.00'),
        )
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            inventory_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        MaterialService.consume(material)
        earmark = Earmark.objects.get(inventory_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('5.00'))

    def test_consume_clears_earmark_when_fully_consumed(self):
        """Consuming all earmarked material deletes the earmark."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job, quantity=Decimal('5.00'),
        )
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            inventory_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        MaterialService.consume(material)
        self.assertEqual(
            Earmark.objects.filter(inventory_item=self.plywood, job=self.job).count(), 0
        )

    def test_consume_provisional_material_refuses(self):
        """Consuming a provisional (no inventory_item) material now REFUSES
        rather than silently flipping — pricing must be set and the lot received
        first. No QOH side effect, state stays pending."""
        from django.core.exceptions import ValidationError
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            description='Custom brackets',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
            accounting_category=self.category,
        )
        with self.assertRaises(ValidationError):
            MaterialService.consume(material)
        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('20.00'))


class CompleteTaskAdjustmentTest(TestCase):
    """Tests for InventoryService.complete_task_adjustment()."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job = Job.objects.create(
            job_number='J-QOH-003', contact=self.contact, description='Test Job',
        )

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.scheme = RateScheme.objects.create(
            name='S-qoh3', algorithm=RateScheme.ENTERED_QTY,
            rate=1, unit_label='ea', accounting_category=self.category,
        )
        self.task = Task.objects.create(
            job=self.job,
            name='Install plywood',
            description='Install plywood',
            sort_order=1,
            rate_scheme=self.scheme,
        )
        self.plywood = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheet',
            qty_on_hand=Decimal('15.00'),
            qty_sold=Decimal('5.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            accounting_category=self.category,
        )

    def test_actual_less_than_estimated_returns_excess(self):
        """If actual < estimated, excess is returned to stock."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            inventory_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        InventoryService.complete_task_adjustment(material, actual_qty=Decimal('3.00'))
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('17.00'))
        self.assertEqual(self.plywood.qty_sold, Decimal('3.00'))

    def test_actual_more_than_estimated_consumes_more(self):
        """If actual > estimated, additional stock is consumed."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            inventory_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        InventoryService.complete_task_adjustment(material, actual_qty=Decimal('7.00'))
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('13.00'))
        self.assertEqual(self.plywood.qty_sold, Decimal('7.00'))

    def test_actual_equals_estimated_no_change(self):
        """If actual == estimated, no adjustment needed."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            inventory_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        InventoryService.complete_task_adjustment(material, actual_qty=Decimal('5.00'))
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('15.00'))
        self.assertEqual(self.plywood.qty_sold, Decimal('5.00'))

    def test_no_inventory_item_is_noop(self):
        """Adjustment on material without inventory_item does nothing."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            description='Custom brackets',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
            accounting_category=self.category,
        )
        InventoryService.complete_task_adjustment(material, actual_qty=Decimal('3.00'))
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('15.00'))


class ManualAdjustmentTest(TestCase):
    """Tests for InventoryService.manual_adjustment()."""

    def setUp(self):
        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheet',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            accounting_category=self.category,
        )

    def test_negative_adjustment_decreases_qoh(self):
        """Negative manual adjustment decreases QOH."""
        InventoryService.manual_adjustment(
            self.plywood, Decimal('-3.00'), 'Damaged in storage',
        )
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('17.00'))

    def test_positive_adjustment_increases_qoh(self):
        """Positive manual adjustment increases QOH."""
        InventoryService.manual_adjustment(
            self.plywood, Decimal('5.00'), 'Stock count correction',
        )
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('25.00'))

    def test_adjustment_creates_audit_record(self):
        """Manual adjustment records an InventoryHistory action entry."""
        from apps.core.models import InventoryHistory
        InventoryService.manual_adjustment(
            self.plywood, Decimal('-2.00'), 'Waste',
        )
        entry = InventoryHistory.objects.filter(
            object_type='inventoryitem', object_id=self.plywood.pk,
            entry_type='action').latest('timestamp')
        self.assertEqual(entry.changes['qty_change'], '-2.00')
        self.assertEqual(entry.text, 'Waste')

    def test_negative_adjustment_tracks_waste(self):
        """Negative adjustment increases qty_wasted."""
        InventoryService.manual_adjustment(
            self.plywood, Decimal('-3.00'), 'Water damage',
        )
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_wasted, Decimal('3.00'))

    def test_positive_adjustment_no_waste(self):
        """Positive adjustment does not affect qty_wasted."""
        InventoryService.manual_adjustment(
            self.plywood, Decimal('5.00'), 'Found extra stock',
        )
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_wasted, Decimal('0.00'))
