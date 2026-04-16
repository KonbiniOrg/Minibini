"""
Tests for QOH Automatic Updates via InventoryService.
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory
from apps.jobs.models import Job, PlanTask, Task
from apps.estimates.models import EstWorksheet
from apps.inventory.models import PlanMaterial, Material
from apps.inventory.models import PriceListItem
from apps.inventory.models import Earmark, InventoryAdjustment
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.inventory.services import InventoryService, MaterialService


class ReceivePOLineItemTest(TestCase):
    """Tests for InventoryService.receive_po_line_item()."""

    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact',
            email='test@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Supplier',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('10.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )

        self.job = Job.objects.create(
            job_number='J-QOH-001', contact=self.contact, description='Test Job',
        )

        self.po = PurchaseOrder.objects.create(
            business=self.business,
            po_number='PO-QOH-001',
        )

    def test_receive_increases_qoh(self):
        """Receiving a PO line item with inventoried price_list_item increases QOH."""
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            price_list_item=self.plywood,
            description='Plywood',
            qty=Decimal('5.00'),
            price=Decimal('45.00'),
        )
        InventoryService.receive_po_line_item(li)
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('15.00'))

    def test_receive_creates_earmark_if_job_linked(self):
        """Receiving a job-linked PO line item creates an earmark."""
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            price_list_item=self.plywood,
            job=self.job,
            description='Plywood for job',
            qty=Decimal('5.00'),
            price=Decimal('45.00'),
        )
        InventoryService.receive_po_line_item(li)
        earmark = Earmark.objects.get(price_list_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('5.00'))

    def test_receive_updates_existing_earmark(self):
        """Receiving more of the same item+job updates existing earmark."""
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job, quantity=Decimal('3.00'),
        )
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            price_list_item=self.plywood,
            job=self.job,
            description='More plywood',
            qty=Decimal('5.00'),
            price=Decimal('45.00'),
        )
        InventoryService.receive_po_line_item(li)
        earmark = Earmark.objects.get(price_list_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('8.00'))

    def test_receive_no_price_list_item_is_noop(self):
        """Receiving a PO line item without price_list_item does nothing to inventory."""
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            description='Generic supplies',
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
        )
        InventoryService.receive_po_line_item(li)
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('10.00'))

    def test_receive_non_inventoried_is_noop(self):
        """Receiving a PO line item with non-inventoried PLI does nothing."""
        non_inv = PriceListItem.objects.create(
            code='NONINV', description='Not tracked', is_inventoried=False,
            accounting_category=self.category,
        )
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            price_list_item=non_inv,
            description='Not tracked',
            qty=Decimal('5.00'),
            price=Decimal('10.00'),
        )
        InventoryService.receive_po_line_item(li)
        non_inv.refresh_from_db()
        self.assertEqual(non_inv.qty_on_hand, Decimal('0.00'))

    def test_receive_no_job_no_earmark(self):
        """Receiving without a job increases QOH but creates no earmark."""
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            price_list_item=self.plywood,
            description='Stock plywood',
            qty=Decimal('5.00'),
            price=Decimal('45.00'),
        )
        InventoryService.receive_po_line_item(li)
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('15.00'))
        self.assertEqual(Earmark.objects.count(), 0)


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
        from apps.jobs.models import Task
        self.task = Task.objects.create(
            job=self.job,
            name='Install plywood',
            description='Install plywood',
            sort_order=1,
        )

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )

    def test_consume_decreases_qoh(self):
        """Consuming material decreases QOH."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            price_list_item=self.plywood,
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
            price_list_item=self.plywood,
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
            price_list_item=self.plywood, job=self.job, quantity=Decimal('10.00'),
        )
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            price_list_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        MaterialService.consume(material)
        earmark = Earmark.objects.get(price_list_item=self.plywood, job=self.job)
        self.assertEqual(earmark.quantity, Decimal('5.00'))

    def test_consume_clears_earmark_when_fully_consumed(self):
        """Consuming all earmarked material deletes the earmark."""
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job, quantity=Decimal('5.00'),
        )
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            price_list_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        MaterialService.consume(material)
        self.assertEqual(
            Earmark.objects.filter(price_list_item=self.plywood, job=self.job).count(), 0
        )

    def test_consume_no_price_list_item_is_noop(self):
        """Consuming a material without price_list_item does nothing."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            description='Custom brackets',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
        )
        MaterialService.consume(material)
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
        self.task = Task.objects.create(
            job=self.job,
            name='Install plywood',
            description='Install plywood',
            sort_order=1,
        )

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('15.00'),
            qty_sold=Decimal('5.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )

    def test_actual_less_than_estimated_returns_excess(self):
        """If actual < estimated, excess is returned to stock."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            price_list_item=self.plywood,
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
            price_list_item=self.plywood,
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
            price_list_item=self.plywood,
            description='Plywood',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('45.00'),
            sell_price=Decimal('90.00'),
        )
        InventoryService.complete_task_adjustment(material, actual_qty=Decimal('5.00'))
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('15.00'))
        self.assertEqual(self.plywood.qty_sold, Decimal('5.00'))

    def test_no_price_list_item_is_noop(self):
        """Adjustment on material without price_list_item does nothing."""
        material = Material.objects.create(
            job=self.job,
            task=self.task,
            description='Custom brackets',
            quantity=Decimal('5.00'),
            unit_cost=Decimal('10.00'),
            sell_price=Decimal('20.00'),
        )
        InventoryService.complete_task_adjustment(material, actual_qty=Decimal('3.00'))
        self.plywood.refresh_from_db()
        self.assertEqual(self.plywood.qty_on_hand, Decimal('15.00'))


class ManualAdjustmentTest(TestCase):
    """Tests for InventoryService.manual_adjustment()."""

    def setUp(self):
        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = PriceListItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_inventoried=True,
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
        """Manual adjustment creates an InventoryAdjustment record."""
        InventoryService.manual_adjustment(
            self.plywood, Decimal('-2.00'), 'Waste',
        )
        adj = InventoryAdjustment.objects.get(price_list_item=self.plywood)
        self.assertEqual(adj.quantity_change, Decimal('-2.00'))
        self.assertEqual(adj.reason, 'Waste')

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
