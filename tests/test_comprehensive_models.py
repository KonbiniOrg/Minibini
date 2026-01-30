from django.test import TestCase, TransactionTestCase
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.contrib.auth.models import Group
from decimal import Decimal
from datetime import timedelta
from apps.contacts.models import Contact, Business, PaymentTerms
from apps.core.models import User, Configuration
from apps.jobs.models import Job, Estimate, WorkOrder, Task, Blep, TaskMapping, TaskTemplate
from apps.invoicing.models import Invoice, InvoiceLineItem, PriceListItem
from apps.jobs.models import EstimateLineItem
from apps.purchasing.models import PurchaseOrderLineItem, BillLineItem
from apps.purchasing.models import PurchaseOrder, Bill


class ComprehensiveModelIntegrationTest(TestCase):
    def setUp(self):
        # Create Configuration for number generation
        Configuration.objects.create(key='bill_number_sequence', value='BILL-{year}-{counter:04d}')
        Configuration.objects.create(key='bill_counter', value='0')

        self.group = Group.objects.create(name="Manager")
        self.user = User.objects.create_user(username="testuser", email="test@example.com")
        self.user.groups.add(self.group)
        self.payment_terms = PaymentTerms.objects.create()
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(
            business_name="Test Business",
            terms=self.payment_terms,
            default_contact=self.default_contact
        )
        self.contact = Contact.objects.create(
            first_name='Test Contact',
            last_name='',
            email="contact@example.com",
            addr1="123 Main St",
            city="Test City",
            municipality="TS",
            postal_code="12345",
            business=self.business
        )

    def test_complete_job_workflow(self):
        job = Job.objects.create(
            job_number="JOB001",
            status='draft',
            contact=self.contact,
            description="Test job description"
        )

        estimate = Estimate.objects.create(
            job=job,
            estimate_number="EST001",
            version=1,
            status='open'
        )

        work_order = WorkOrder.objects.create(
            job=job,
            status='incomplete'
        )

        task = Task.objects.create(
            assignee=self.user,
            work_order=work_order,
            name="Test Task",
        )

        blep = Blep.objects.create(
            user=self.user,
            task=task,
            start_time=timezone.now()
        )

        self.assertEqual(job.status, 'draft')
        self.assertEqual(estimate.job, job)
        self.assertEqual(work_order.job, job)
        self.assertEqual(task.work_order, work_order)
        self.assertEqual(blep.task, task)

    def test_invoice_line_item_workflow(self):
        job = Job.objects.create(
            job_number="JOB002",
            contact=self.contact
        )

        estimate = Estimate.objects.create(
            job=job,
            estimate_number="EST002"
        )

        invoice = Invoice.objects.create(
            job=job,
            invoice_number="INV001"
        )

        price_list_item = PriceListItem.objects.create(
            code="ITEM001",
            description="Test item",
            purchase_price=Decimal('10.00'),
            selling_price=Decimal('15.00')
        )

        # Test creating both estimate and invoice line items
        estimate_line_item = EstimateLineItem.objects.create(
            estimate=estimate,
            price_list_item=price_list_item,
            qty=Decimal('5.00'),
            description="Test estimate line item",
            price_currency=Decimal('75.00')
        )

        invoice_line_item = InvoiceLineItem.objects.create(
            invoice=invoice,
            price_list_item=price_list_item,
            qty=Decimal('5.00'),
            description="Test invoice line item",
            price_currency=Decimal('75.00')
        )

        self.assertEqual(estimate_line_item.estimate, estimate)
        self.assertEqual(estimate_line_item.price_list_item, price_list_item)
        self.assertEqual(estimate_line_item.qty, Decimal('5.00'))

        self.assertEqual(invoice_line_item.invoice, invoice)
        self.assertEqual(invoice_line_item.price_list_item, price_list_item)
        self.assertEqual(invoice_line_item.qty, Decimal('5.00'))

    def test_purchase_order_workflow(self):
        job = Job.objects.create(
            job_number="JOB003",
            contact=self.contact
        )

        purchase_order = PurchaseOrder.objects.create(
            business=self.business,
            job=job,
            po_number="PO001",
            status='draft'
        )
        purchase_order.status = 'issued'
        purchase_order.save()

        bill = Bill.objects.create(
            bill_number="BILL-TEST-001",
            purchase_order=purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number="VENDOR001"
        )

        # Test creating both purchase order and bill line items
        # Create price list item for testing
        price_item = PriceListItem.objects.create(
            code="TEST001",
            selling_price=Decimal('25.00')
        )

        po_line_item = PurchaseOrderLineItem.objects.create(
            purchase_order=purchase_order,
            price_list_item=price_item,
            qty=Decimal('2.00'),
            description="Purchase order item",
            price_currency=Decimal('50.00')
        )

        bill_line_item = BillLineItem.objects.create(
            bill=bill,
            price_list_item=price_item,
            qty=Decimal('2.00'),
            description="Bill item",
            price_currency=Decimal('50.00')
        )

        self.assertEqual(bill.purchase_order, purchase_order)
        self.assertEqual(po_line_item.purchase_order, purchase_order)
        self.assertEqual(bill_line_item.bill, bill)

    def test_estimate_superseding(self):
        job = Job.objects.create(
            job_number="JOB004",
            contact=self.contact
        )

        original_estimate = Estimate.objects.create(
            job=job,
            estimate_number="EST003",
            version=1,
            status='open'
        )

        superseding_estimate = Estimate.objects.create(
            job=job,
            estimate_number="EST003",
            version=2,
            status='open',
            parent=original_estimate
        )

        original_estimate.status = 'superseded'
        original_estimate.save()  # closed_date is set automatically by model.save()

        original_estimate.refresh_from_db()
        self.assertEqual(original_estimate.status, 'superseded')
        self.assertEqual(superseding_estimate.parent, original_estimate)
        self.assertIsNotNone(original_estimate.closed_date)

    def test_task_workflow(self):
        job = Job.objects.create(
            job_number="JOB005",
            contact=self.contact
        )

        work_order = WorkOrder.objects.create(job=job)

        task = Task.objects.create(
            work_order=work_order,
            name="Planning Task",
        )

        task_mapping = TaskMapping.objects.create(
            step_type="labor",
            mapping_strategy="direct",
            task_type_id="PLAN001",
            breakdown_of_task="Break down the planning requirements"
        )

        task_template = TaskTemplate.objects.create(
            template_name="Planning Task Template",
            task_mapping=task_mapping
        )

        # Update task to use template
        task.template = task_template
        task.save()

        self.assertEqual(task.work_order, work_order)
        self.assertEqual(task.template.task_mapping, task_mapping)

    def test_configuration_number_sequences(self):
        # Create configuration entries for number sequences
        job_seq = Configuration.objects.create(
            key="job_number_sequence",
            value="JOB-{year}-{counter:05d}"
        )
        estimate_seq = Configuration.objects.create(
            key="estimate_number_sequence",
            value="EST-{year}-{counter:05d}"
        )
        invoice_seq = Configuration.objects.create(
            key="invoice_number_sequence",
            value="INV-{year}-{counter:05d}"
        )
        po_seq = Configuration.objects.create(
            key="po_number_sequence",
            value="PO-{year}-{counter:05d}"
        )

        self.assertIn("{year}", job_seq.value)
        self.assertIn("{counter:", job_seq.value)
        self.assertIn("{year}", estimate_seq.value)
        self.assertIn("{year}", invoice_seq.value)
        self.assertIn("{year}", po_seq.value)

    def test_model_cascade_deletions(self):
        job = Job.objects.create(
            job_number="JOB006",
            contact=self.contact
        )

        work_order = WorkOrder.objects.create(job=job)
        task = Task.objects.create(work_order=work_order, name="Test Task")

        initial_task_count = Task.objects.count()

        work_order.delete()

        self.assertEqual(Task.objects.count(), initial_task_count - 1)

    def test_user_group_relationship(self):
        group_count_before = Group.objects.count()
        user_count_before = User.objects.count()

        new_group = Group.objects.create(name="Developer")
        developer_user = User.objects.create_user(
            username="developer"
        )
        developer_user.groups.add(new_group)

        self.assertEqual(Group.objects.count(), group_count_before + 1)
        self.assertEqual(User.objects.count(), user_count_before + 1)
        self.assertIn(new_group, developer_user.groups.all())

        new_group.delete()
        developer_user.refresh_from_db()
        self.assertNotIn(new_group, developer_user.groups.all())

    def test_price_calculation_accuracy(self):
        price_list_item = PriceListItem.objects.create(
            code="BOLT001",
            purchase_price=Decimal('1.50'),
            selling_price=Decimal('2.25'),
            qty_on_hand=Decimal('100.00')
        )

        # Create an invoice for testing
        job = Job.objects.create(job_number="CALC_TEST", contact=self.contact)
        invoice = Invoice.objects.create(job=job, invoice_number="INV_CALC")

        line_item = InvoiceLineItem.objects.create(
            invoice=invoice,
            price_list_item=price_list_item,
            qty=Decimal('10.00'),
            price_currency=Decimal('22.50')
        )

        expected_total = line_item.qty * price_list_item.selling_price
        self.assertEqual(line_item.price_currency, expected_total)

    def test_unique_constraints(self):
        job = Job.objects.create(job_number="UNIQUE001", contact=self.contact)

        with self.assertRaises(ValidationError):
            with transaction.atomic():
                Job.objects.create(job_number="UNIQUE001", contact=self.contact)

        invoice = Invoice.objects.create(
            job=job,
            invoice_number="INV_UNIQUE001"
        )

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Invoice.objects.create(
                    job=job,
                    invoice_number="INV_UNIQUE001"
                )

    def test_model_str_representations(self):
        job = Job.objects.create(job_number="STR_TEST", contact=self.contact)
        estimate = Estimate.objects.create(job=job, estimate_number="EST_STR")
        invoice = Invoice.objects.create(job=job, invoice_number="INV_STR")
        po = PurchaseOrder.objects.create(business=self.business, po_number="PO_STR")

        self.assertEqual(str(job), "STR_TEST")
        self.assertEqual(str(estimate), "Estimate EST_STR")
        self.assertEqual(str(invoice), "Invoice INV_STR")
        self.assertEqual(str(po), "PO PO_STR")
        self.assertEqual(str(self.group), "Manager")
        self.assertEqual(str(self.contact), "Test Contact")


class LineItemValidationTest(TestCase):
    """Test LineItem validation across all submodel types"""

    def setUp(self):
        self.default_contact = Contact.objects.create(first_name='Default Contact', last_name='', email='default.contact@test.com')
        self.business = Business.objects.create(business_name="Test Business", default_contact=self.default_contact)
        self.contact = Contact.objects.create(first_name='Test Customer', last_name='', email='test.customer@test.com', business=self.business)
        self.job = Job.objects.create(
            job_number="VALID_JOB001",
            contact=self.contact,
            description="Test job for validation"
        )

        # Create related objects
        self.estimate = Estimate.objects.create(
            job=self.job,
            estimate_number="EST_VALID001"
        )
        self.invoice = Invoice.objects.create(
            job=self.job,
            invoice_number="INV_VALID001"
        )
        self.purchase_order = PurchaseOrder.objects.create(
            business=self.business,
            job=self.job,
            po_number="PO_VALID001",
            status='draft'
        )
        self.purchase_order.status = 'issued'
        self.purchase_order.save()

        self.bill = Bill.objects.create(
            bill_number="BILL-TEST-002",
            purchase_order=self.purchase_order,
            business=self.business,
            contact=self.contact,
            vendor_invoice_number="VIN_VALID001"
        )
        self.work_order = WorkOrder.objects.create(job=self.job)
        self.task = Task.objects.create(
            work_order=self.work_order,
            name="Test Task",
        )

        # Create price list item
        self.price_list_item = PriceListItem.objects.create(
            code="TEST001",
            selling_price=Decimal('25.00')
        )

    def test_estimate_line_item_validation_both_null_allowed(self):
        """Test EstimateLineItem allows both task and price_list_item to be null"""
        line_item = EstimateLineItem.objects.create(
            estimate=self.estimate,
            task=None,
            price_list_item=None,
            description="No task or price item"
        )
        line_item.full_clean()  # Should not raise
        self.assertIsNone(line_item.task)
        self.assertIsNone(line_item.price_list_item)

    def test_estimate_line_item_validation_cannot_have_both(self):
        """Test EstimateLineItem cannot have both task and price_list_item"""
        line_item = EstimateLineItem(
            estimate=self.estimate,
            task=self.task,
            price_list_item=self.price_list_item,
            description="Invalid - has both"
        )
        with self.assertRaises(ValidationError) as context:
            line_item.full_clean()
        self.assertIn("cannot have both task and price_list_item", str(context.exception))

    def test_purchase_order_line_item_validation_both_null_allowed(self):
        """Test PurchaseOrderLineItem allows both task and price_list_item to be null"""
        line_item = PurchaseOrderLineItem.objects.create(
            purchase_order=self.purchase_order,
            task=None,
            price_list_item=None,
            description="No task or price item"
        )
        line_item.full_clean()  # Should not raise
        self.assertIsNone(line_item.task)
        self.assertIsNone(line_item.price_list_item)

    def test_purchase_order_line_item_validation_cannot_have_both(self):
        """Test PurchaseOrderLineItem cannot have both task and price_list_item"""
        line_item = PurchaseOrderLineItem(
            purchase_order=self.purchase_order,
            task=self.task,
            price_list_item=self.price_list_item,
            description="Invalid - has both"
        )
        with self.assertRaises(ValidationError) as context:
            line_item.full_clean()
        self.assertIn("cannot have both task and price_list_item", str(context.exception))

    def test_bill_line_item_validation_both_null_allowed(self):
        """Test BillLineItem allows both task and price_list_item to be null"""
        line_item = BillLineItem.objects.create(
            bill=self.bill,
            task=None,
            price_list_item=None,
            description="No task or price item"
        )
        line_item.full_clean()  # Should not raise
        self.assertIsNone(line_item.task)
        self.assertIsNone(line_item.price_list_item)

    def test_bill_line_item_validation_cannot_have_both(self):
        """Test BillLineItem cannot have both task and price_list_item"""
        line_item = BillLineItem(
            bill=self.bill,
            task=self.task,
            price_list_item=self.price_list_item,
            description="Invalid - has both"
        )
        with self.assertRaises(ValidationError) as context:
            line_item.full_clean()
        self.assertIn("cannot have both task and price_list_item", str(context.exception))
