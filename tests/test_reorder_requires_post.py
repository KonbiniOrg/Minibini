"""Tests for POST requirement on reorder views.

These tests verify that:
1. GET requests to reorder views return 405 Method Not Allowed
2. POST requests to reorder views work correctly
"""
from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from apps.contacts.models import Contact, Business
from apps.core.models import User
from apps.jobs.models import Job, Estimate, EstimateLineItem, WorkOrder, Task, EstWorksheet
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem, Bill, BillLineItem


class ReorderRequiresPostTestBase(TestCase):
    """Base test class with common setup for reorder tests."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.client.login(username='testuser', password='testpass')

        # Create contact and business
        self.contact = Contact.objects.create(
            first_name='Test',
            last_name='Contact',
            email='test@test.com',
            work_number='555-1234'
        )
        self.business = Business.objects.create(
            business_name='Test Business',
            default_contact=self.contact
        )
        self.contact.business = self.business
        self.contact.save()

        # Create job
        self.job = Job.objects.create(
            job_number='JOB-001',
            name='Test Job',
            contact=self.contact,
            status='draft'
        )


class EstimateReorderLineItemTest(ReorderRequiresPostTestBase):
    """Test estimate_reorder_line_item requires POST."""

    def setUp(self):
        super().setUp()
        # Create estimate with line items
        self.estimate = Estimate.objects.create(
            estimate_number='EST-001',
            job=self.job,
            status='draft',
            version=1
        )
        self.line_item1 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Line Item 1',
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            units='hours'
        )
        self.line_item2 = EstimateLineItem.objects.create(
            estimate=self.estimate,
            description='Line Item 2',
            qty=Decimal('2.00'),
            price_currency=Decimal('200.00'),
            units='hours'
        )

    def test_get_returns_405(self):
        """GET request to reorder should return 405 Method Not Allowed."""
        url = reverse('jobs:estimate_reorder_line_item', kwargs={
            'estimate_id': self.estimate.estimate_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_post_reorders_successfully(self):
        """POST request to reorder should work correctly."""
        url = reverse('jobs:estimate_reorder_line_item', kwargs={
            'estimate_id': self.estimate.estimate_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # Verify reordering occurred
        self.line_item1.refresh_from_db()
        self.line_item2.refresh_from_db()
        self.assertEqual(self.line_item1.line_number, 2)
        self.assertEqual(self.line_item2.line_number, 1)


class TaskReorderWorksheetTest(ReorderRequiresPostTestBase):
    """Test task_reorder_worksheet requires POST."""

    def setUp(self):
        super().setUp()
        # Create estimate and worksheet (EstWorksheet requires job from AbstractWorkContainer)
        self.estimate = Estimate.objects.create(
            estimate_number='EST-001',
            job=self.job,
            status='draft',
            version=1
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=self.estimate,
            template=None
        )
        self.task1 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Task 1',
            line_number=1
        )
        self.task2 = Task.objects.create(
            est_worksheet=self.worksheet,
            name='Task 2',
            line_number=2
        )

    def test_get_returns_405(self):
        """GET request to reorder should return 405 Method Not Allowed."""
        url = reverse('jobs:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task1.task_id,
            'direction': 'down'
        })
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_post_reorders_successfully(self):
        """POST request to reorder should work correctly."""
        url = reverse('jobs:task_reorder_worksheet', kwargs={
            'worksheet_id': self.worksheet.est_worksheet_id,
            'task_id': self.task1.task_id,
            'direction': 'down'
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # Verify reordering occurred
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()
        self.assertEqual(self.task1.line_number, 2)
        self.assertEqual(self.task2.line_number, 1)


class TaskReorderWorkOrderTest(ReorderRequiresPostTestBase):
    """Test task_reorder_work_order requires POST."""

    def setUp(self):
        super().setUp()
        # Create estimate, worksheet, and work order (all require job from AbstractWorkContainer)
        self.estimate = Estimate.objects.create(
            estimate_number='EST-001',
            job=self.job,
            status='accepted',
            version=1
        )
        self.worksheet = EstWorksheet.objects.create(
            job=self.job,
            estimate=self.estimate,
            template=None
        )
        self.work_order = WorkOrder.objects.create(
            job=self.job,
            status='draft'
        )
        self.task1 = Task.objects.create(
            work_order=self.work_order,
            name='Task 1',
            line_number=1
        )
        self.task2 = Task.objects.create(
            work_order=self.work_order,
            name='Task 2',
            line_number=2
        )

    def test_get_returns_405(self):
        """GET request to reorder should return 405 Method Not Allowed."""
        url = reverse('jobs:task_reorder_work_order', kwargs={
            'work_order_id': self.work_order.work_order_id,
            'task_id': self.task1.task_id,
            'direction': 'down'
        })
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_post_reorders_successfully(self):
        """POST request to reorder should work correctly."""
        url = reverse('jobs:task_reorder_work_order', kwargs={
            'work_order_id': self.work_order.work_order_id,
            'task_id': self.task1.task_id,
            'direction': 'down'
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # Verify reordering occurred
        self.task1.refresh_from_db()
        self.task2.refresh_from_db()
        self.assertEqual(self.task1.line_number, 2)
        self.assertEqual(self.task2.line_number, 1)


class InvoiceReorderLineItemTest(ReorderRequiresPostTestBase):
    """Test invoice_reorder_line_item requires POST."""

    def setUp(self):
        super().setUp()
        # Create invoice with line items
        self.invoice = Invoice.objects.create(
            invoice_number='INV-001',
            job=self.job,
            status='draft'
        )
        self.line_item1 = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Line Item 1',
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            units='hours'
        )
        self.line_item2 = InvoiceLineItem.objects.create(
            invoice=self.invoice,
            description='Line Item 2',
            qty=Decimal('2.00'),
            price_currency=Decimal('200.00'),
            units='hours'
        )

    def test_get_returns_405(self):
        """GET request to reorder should return 405 Method Not Allowed."""
        url = reverse('invoicing:invoice_reorder_line_item', kwargs={
            'invoice_id': self.invoice.invoice_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_post_reorders_successfully(self):
        """POST request to reorder should work correctly."""
        url = reverse('invoicing:invoice_reorder_line_item', kwargs={
            'invoice_id': self.invoice.invoice_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # Verify reordering occurred
        self.line_item1.refresh_from_db()
        self.line_item2.refresh_from_db()
        self.assertEqual(self.line_item1.line_number, 2)
        self.assertEqual(self.line_item2.line_number, 1)


class PurchaseOrderReorderLineItemTest(ReorderRequiresPostTestBase):
    """Test purchase_order_reorder_line_item requires POST."""

    def setUp(self):
        super().setUp()
        # Create purchase order with line items (requires business, job is optional)
        self.po = PurchaseOrder.objects.create(
            po_number='PO-001',
            business=self.business,
            status='draft'
        )
        self.line_item1 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            description='Line Item 1',
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            units='hours'
        )
        self.line_item2 = PurchaseOrderLineItem.objects.create(
            purchase_order=self.po,
            description='Line Item 2',
            qty=Decimal('2.00'),
            price_currency=Decimal('200.00'),
            units='hours'
        )

    def test_get_returns_405(self):
        """GET request to reorder should return 405 Method Not Allowed."""
        url = reverse('purchasing:purchase_order_reorder_line_item', kwargs={
            'po_id': self.po.po_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_post_reorders_successfully(self):
        """POST request to reorder should work correctly."""
        url = reverse('purchasing:purchase_order_reorder_line_item', kwargs={
            'po_id': self.po.po_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # Verify reordering occurred
        self.line_item1.refresh_from_db()
        self.line_item2.refresh_from_db()
        self.assertEqual(self.line_item1.line_number, 2)
        self.assertEqual(self.line_item2.line_number, 1)


class BillReorderLineItemTest(ReorderRequiresPostTestBase):
    """Test bill_reorder_line_item requires POST."""

    def setUp(self):
        super().setUp()
        # Create bill with line items (requires business, bill_number, vendor_invoice_number)
        self.bill = Bill.objects.create(
            bill_number='BILL-001',
            business=self.business,
            vendor_invoice_number='VINV-001',
            status='draft'
        )
        self.line_item1 = BillLineItem.objects.create(
            bill=self.bill,
            description='Line Item 1',
            qty=Decimal('1.00'),
            price_currency=Decimal('100.00'),
            units='hours'
        )
        self.line_item2 = BillLineItem.objects.create(
            bill=self.bill,
            description='Line Item 2',
            qty=Decimal('2.00'),
            price_currency=Decimal('200.00'),
            units='hours'
        )

    def test_get_returns_405(self):
        """GET request to reorder should return 405 Method Not Allowed."""
        url = reverse('purchasing:bill_reorder_line_item', kwargs={
            'bill_id': self.bill.bill_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)

    def test_post_reorders_successfully(self):
        """POST request to reorder should work correctly."""
        url = reverse('purchasing:bill_reorder_line_item', kwargs={
            'bill_id': self.bill.bill_id,
            'line_item_id': self.line_item1.line_item_id,
            'direction': 'down'
        })
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)

        # Verify reordering occurred
        self.line_item1.refresh_from_db()
        self.line_item2.refresh_from_db()
        self.assertEqual(self.line_item1.line_number, 2)
        self.assertEqual(self.line_item2.line_number, 1)
