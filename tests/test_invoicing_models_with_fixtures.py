from django.test import TestCase
from decimal import Decimal
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.inventory.models import PriceListItem
from apps.estimates.models import EstimateLineItem
from apps.purchasing.models import PurchaseOrderLineItem, BillLineItem
from apps.jobs.models import Job, Task
from apps.estimates.models import Estimate
from .base import FixtureTestCase



class PriceListItemModelFixtureTest(FixtureTestCase):
    """
    Test PriceListItem model using fixture data
    """
    
    def test_price_list_items_exist_from_fixture(self):
        """Test that price list items from fixture data exist and have correct properties"""
        screw_item = PriceListItem.objects.get(code="SCREW001")
        self.assertEqual(screw_item.description, "Stainless steel screws 2.5 inch")
        self.assertEqual(screw_item.purchase_price, Decimal('0.25'))
        self.assertEqual(screw_item.selling_price, Decimal('0.50'))
        self.assertEqual(screw_item.qty_on_hand, Decimal('1000.00'))
        self.assertEqual(screw_item.qty_sold, Decimal('150.00'))
        self.assertEqual(screw_item.qty_wasted, Decimal('5.00'))
        
        labor_item = PriceListItem.objects.get(code="LABOR001")
        self.assertEqual(labor_item.description, "Skilled labor hourly rate")
        self.assertEqual(labor_item.purchase_price, Decimal('0.00'))
        self.assertEqual(labor_item.selling_price, Decimal('75.00'))
        self.assertEqual(labor_item.qty_on_hand, Decimal('0.00'))
        self.assertEqual(labor_item.qty_sold, Decimal('240.00'))
        
    def test_price_list_item_str_method_with_fixture_data(self):
        """Test price list item string representation with fixture data"""
        item = PriceListItem.objects.get(code="SCREW001")
        expected_str = "SCREW001 - Stainless steel screws 2.5 inch"
        self.assertEqual(str(item), expected_str)
        
        
    def test_create_new_price_list_item(self):
        """Test creating a new price list item"""
        new_item = PriceListItem.objects.create(
            code="WOOD001",
            units="bd ft",
            description="Oak lumber 1x6",
            purchase_price=Decimal('3.50'),
            selling_price=Decimal('5.25')
        )
        self.assertEqual(new_item.code, "WOOD001")
        self.assertEqual(PriceListItem.objects.count(), 3)  # 2 from fixture + 1 new


class InvoiceModelFixtureTest(FixtureTestCase):
    """
    Test Invoice model using fixture data
    """
    
    def test_invoices_exist_from_fixture(self):
        """Test that invoices from fixture data exist and have correct properties"""
        invoice1 = Invoice.objects.get(invoice_number="INV-2024-0001")
        self.assertEqual(invoice1.status, "active")
        self.assertEqual(invoice1.job.job_number, "JOB-2024-0001")
        
        invoice2 = Invoice.objects.get(invoice_number="INV-2024-0002")
        self.assertEqual(invoice2.status, "active")
        self.assertEqual(invoice2.job.job_number, "JOB-2024-0002")
        
    def test_invoice_str_method_with_fixture_data(self):
        """Test invoice string representation with fixture data"""
        invoice = Invoice.objects.get(invoice_number="INV-2024-0001")
        self.assertEqual(str(invoice), "Invoice INV-2024-0001")
        
    def test_invoice_job_relationships(self):
        """Test that invoices are properly linked to jobs"""
        invoice = Invoice.objects.get(invoice_number="INV-2024-0001")
        job = Job.objects.get(job_number="JOB-2024-0001")
        self.assertEqual(invoice.job, job)
        
    def test_invoice_status_update(self):
        """Test updating invoice status using fixture data"""
        invoice = Invoice.objects.get(invoice_number="INV-2024-0001")
        self.assertEqual(invoice.status, "active")
        
        invoice.status = Invoice.STATUS_CANCELLED
        invoice.save()
        
        updated_invoice = Invoice.objects.get(invoice_number="INV-2024-0001")
        self.assertEqual(updated_invoice.status, Invoice.STATUS_CANCELLED)
        
    def test_create_new_invoice_for_existing_job(self):
        """Test creating a new invoice for existing job from fixtures"""
        job = Job.objects.get(job_number="JOB-2024-0001")
        new_invoice = Invoice.objects.create(
            job=job,
            invoice_number="INV-2024-0003",
            status="active"
        )
        self.assertEqual(new_invoice.job, job)
        self.assertEqual(Invoice.objects.count(), 3)  # 2 from fixture + 1 new


class LineItemModelFixtureTest(FixtureTestCase):
    """
    Test LineItem submodels using fixture data
    """
    
    def test_estimate_line_items_exist_from_fixture(self):
        """Test that estimate line items from fixture data exist and have correct properties"""
        estimate_item1 = EstimateLineItem.objects.get(line_number=1)
        self.assertEqual(estimate_item1.qty, Decimal('50.00'))
        self.assertEqual(estimate_item1.units, "ea")
        self.assertEqual(estimate_item1.description, "Screws for kitchen cabinet installation")
        self.assertEqual(estimate_item1.price, Decimal('25.00'))
        self.assertEqual(estimate_item1.estimate.estimate_number, "EST-2024-0001")
        self.assertIsNone(estimate_item1.task)
        self.assertEqual(estimate_item1.price_list_item.code, "SCREW001")
        
        estimate_item2 = EstimateLineItem.objects.get(line_number=2)
        self.assertEqual(estimate_item2.qty, Decimal('8.00'))
        self.assertEqual(estimate_item2.units, "hours")
        self.assertEqual(estimate_item2.description, "Electrical rough-in labor")
        self.assertEqual(estimate_item2.price, Decimal('600.00'))
        # Post-split: fixture ELI task is null (ELI.task targets PlanTask, fixture has none)
        self.assertIsNone(estimate_item2.task)
        self.assertIsNone(estimate_item2.price_list_item)
        
    def test_invoice_line_items_exist_from_fixture(self):
        """Test that invoice line items from fixture data exist and have correct properties"""
        invoice_item1 = InvoiceLineItem.objects.get(line_number=1)
        self.assertEqual(invoice_item1.qty, Decimal('50.00'))
        self.assertEqual(invoice_item1.units, "ea")
        self.assertEqual(invoice_item1.description, "Screws for kitchen cabinet installation")
        self.assertEqual(invoice_item1.price, Decimal('25.00'))
        self.assertEqual(invoice_item1.invoice.invoice_number, "INV-2024-0001")
        self.assertIsNone(invoice_item1.task)
        self.assertEqual(invoice_item1.price_list_item.code, "SCREW001")
        
        invoice_item2 = InvoiceLineItem.objects.get(line_number=2)
        self.assertEqual(invoice_item2.qty, Decimal('8.00'))
        self.assertEqual(invoice_item2.units, "hours")
        self.assertEqual(invoice_item2.description, "Electrical rough-in labor")
        self.assertEqual(invoice_item2.price, Decimal('600.00'))
        self.assertEqual(invoice_item2.invoice.invoice_number, "INV-2024-0001")
        # InvoiceLineItem.task targets WO Task; fixture task #2 is "Electrical rough-in"
        self.assertEqual(invoice_item2.task.name, "Electrical rough-in")
        self.assertIsNone(invoice_item2.price_list_item)
        # CLI002 has task but no price_list_item
        
    def test_purchase_order_line_items_exist_from_fixture(self):
        """Test that purchase order line items from fixture data exist and have correct properties"""
        po_item = PurchaseOrderLineItem.objects.get(line_number=3)
        self.assertEqual(po_item.qty, Decimal('100.00'))
        self.assertEqual(po_item.units, "ea")
        self.assertEqual(po_item.description, "Screws for purchase order")
        self.assertEqual(po_item.price, Decimal('25.00'))
        self.assertEqual(po_item.purchase_order.po_number, "PO-2024-0001")
        self.assertIsNone(po_item.task)
        self.assertEqual(po_item.price_list_item.code, "SCREW001")
        
    def test_bill_line_items_exist_from_fixture(self):
        """Test that bill line items from fixture data exist and have correct properties"""
        bill_item = BillLineItem.objects.get(line_number=4)
        self.assertEqual(bill_item.qty, Decimal('100.00'))
        self.assertEqual(bill_item.units, "ea")
        self.assertEqual(bill_item.description, "Screws received on bill")
        self.assertEqual(bill_item.price, Decimal('25.00'))
        self.assertEqual(bill_item.bill.bill_id, 1)
        self.assertIsNone(bill_item.task)
        self.assertEqual(bill_item.price_list_item.code, "SCREW001")
        
    def test_line_item_str_method_with_fixture_data(self):
        """Test line item string representation with fixture data"""
        estimate_item = EstimateLineItem.objects.get(line_number=1)
        expected_str = f"Estimate Line Item {estimate_item.line_item_id} for {estimate_item.estimate.estimate_number}"
        self.assertEqual(str(estimate_item), expected_str)
        
        invoice_item = InvoiceLineItem.objects.get(line_number=1)
        expected_str = f"Invoice Line Item {invoice_item.line_item_id} for {invoice_item.invoice.invoice_number}"
        self.assertEqual(str(invoice_item), expected_str)
        
    def test_line_item_relationships(self):
        """Test that line items are properly linked to related models"""
        # Test estimate line item relationships
        estimate_item = EstimateLineItem.objects.get(line_number=1)
        estimate = estimate_item.estimate
        self.assertEqual(estimate.estimate_number, "EST-2024-0001")
        
        # Test invoice line item relationships
        invoice_item = InvoiceLineItem.objects.get(line_number=1)
        invoice = invoice_item.invoice
        self.assertEqual(invoice.invoice_number, "INV-2024-0001")
        
        # Post-split: ELI.task targets PlanTask, InvoiceLineItem.task targets WO Task
        # (different model types). The fixture's line_number=2 items have null tasks
        # since the fixture only has WO Tasks, not PlanTasks on this worksheet.
        estimate_item2 = EstimateLineItem.objects.get(line_number=2)
        invoice_item2 = InvoiceLineItem.objects.get(line_number=2)
        # Post-split: ELI.task targets PlanTask (fixture has none)
        self.assertIsNone(estimate_item2.task)
        # InvoiceLineItem.task targets WO Task; fixture points to #2 "Electrical rough-in"
        self.assertIsNotNone(invoice_item2.task)

        # Test price list item relationship for items that have price list items
        price_item = PriceListItem.objects.get(code="SCREW001")
        self.assertEqual(estimate_item.price_list_item, price_item)
        self.assertEqual(invoice_item.price_list_item, price_item)

        # Verify items without price list items
        self.assertIsNone(estimate_item2.price_list_item)
        self.assertIsNone(invoice_item2.price_list_item)
        
    def test_line_item_calculations(self):
        """Test line item calculations using fixture data"""
        estimate_item1 = EstimateLineItem.objects.get(line_number=1)
        # 50 screws at $0.50 each = $25.00 total
        expected_total = estimate_item1.qty * estimate_item1.price_list_item.selling_price
        self.assertEqual(estimate_item1.price, expected_total)
        
        # Note: CLI002 has task but no price_list_item, so we can't calculate from selling_price
        estimate_item2 = EstimateLineItem.objects.get(line_number=2)
        # This is custom labor pricing, not based on price list item
        self.assertEqual(estimate_item2.price, Decimal('600.00'))
        
        invoice_item1 = InvoiceLineItem.objects.get(line_number=1)
        # Same calculations for invoice items with price list items
        expected_total = invoice_item1.qty * invoice_item1.price_list_item.selling_price
        self.assertEqual(invoice_item1.price, expected_total)
        
        # CLI002 has task but no price_list_item
        invoice_item2 = InvoiceLineItem.objects.get(line_number=2)
        self.assertEqual(invoice_item2.price, Decimal('600.00'))
        
    def test_create_new_line_items_with_existing_relationships(self):
        """Test creating new line items with existing related objects from fixtures.
        Post-split: ELI.task targets PlanTask; InvoiceLineItem.task targets WO Task."""
        from apps.jobs.models import Task, PlanTask
        from apps.estimates.models import Estimate, EstWorksheet

        estimate = Estimate.objects.get(estimate_number="EST-2024-0001")
        invoice = Invoice.objects.get(invoice_number="INV-2024-0001")
        wo_task = Task.objects.get(name="Kitchen demolition")
        # Create a worksheet + plan task for ELI
        worksheet = EstWorksheet.objects.create(job=estimate.job)
        plan_task = PlanTask.objects.create(
            est_worksheet=worksheet, name="Cleanup plan task",
        )
        price_item = PriceListItem.objects.get(code="LABOR001")

        new_estimate_item = EstimateLineItem.objects.create(
            estimate=estimate,
            task=plan_task,
            price_list_item=None,
            line_number=5,
            qty=Decimal('2.00'),
            units="hours",
            description="Cleanup labor estimate",
            price=Decimal('150.00')
        )

        new_invoice_item = InvoiceLineItem.objects.create(
            invoice=invoice,
            task=wo_task,
            price_list_item=None,
            line_number=6,
            qty=Decimal('2.00'),
            units="hours",
            description="Cleanup labor invoice",
            price=Decimal('150.00')
        )

        self.assertEqual(new_estimate_item.estimate, estimate)
        self.assertEqual(new_estimate_item.task, plan_task)
        self.assertEqual(new_invoice_item.invoice, invoice)
        self.assertEqual(new_invoice_item.task, wo_task)
        self.assertEqual(EstimateLineItem.objects.count(), 3)  # 2 from fixture + 1 new
        self.assertEqual(InvoiceLineItem.objects.count(), 3)  # 2 from fixture + 1 new