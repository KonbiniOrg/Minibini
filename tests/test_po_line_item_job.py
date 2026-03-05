"""
Tests for Phase 3: PO line item-level job FK.
Validates that job association has moved from PurchaseOrder to PurchaseOrderLineItem.
"""
from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.inventory.models import InventoryItem
from apps.core.models import Configuration


class POLineItemJobTest(TestCase):
    """Tests for the job FK on PurchaseOrderLineItem."""

    def setUp(self):
        Configuration.objects.get_or_create(
            key='po_number_sequence',
            defaults={'value': 'PO-{year}-{counter:05d}'}
        )
        Configuration.objects.get_or_create(
            key='po_counter',
            defaults={'value': '0'}
        )

        self.contact = Contact.objects.create(
            first_name='Test', last_name='Vendor',
            email='vendor@example.com', work_number='555-0100',
        )
        self.business = Business.objects.create(
            business_name='Test Vendor',
            default_contact=self.contact,
        )
        self.contact.business = self.business
        self.contact.save()

        self.job_a = Job.objects.create(
            job_number='J-PO-001', contact=self.contact, description='Job A',
        )
        self.job_b = Job.objects.create(
            job_number='J-PO-002', contact=self.contact, description='Job B',
        )

        self.inventory_item = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Plywood',
            units='sheet',
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
        )

    def test_line_item_has_job_fk(self):
        """PurchaseOrderLineItem can be linked to a job."""
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-TEST-001',
        )
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=po,
            description='Plywood for Job A',
            qty=Decimal('10.00'),
            price=Decimal('45.00'),
            job=self.job_a,
        )
        self.assertEqual(li.job, self.job_a)

    def test_line_item_has_inventory_item_fk(self):
        """PurchaseOrderLineItem can be linked to an inventory item."""
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-TEST-002',
        )
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=po,
            description='Plywood',
            qty=Decimal('5.00'),
            price=Decimal('45.00'),
            inventory_item=self.inventory_item,
        )
        self.assertEqual(li.inventory_item, self.inventory_item)

    def test_line_items_different_jobs_same_po(self):
        """A single PO can have line items for different jobs."""
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-TEST-003',
        )
        li_a = PurchaseOrderLineItem.objects.create(
            purchase_order=po,
            description='Plywood for Job A',
            qty=Decimal('10.00'),
            price=Decimal('45.00'),
            job=self.job_a,
        )
        li_b = PurchaseOrderLineItem.objects.create(
            purchase_order=po,
            description='Plywood for Job B',
            qty=Decimal('5.00'),
            price=Decimal('45.00'),
            job=self.job_b,
        )
        self.assertEqual(li_a.job, self.job_a)
        self.assertEqual(li_b.job, self.job_b)

    def test_line_item_job_is_optional(self):
        """Line items can exist without a job (general stock purchase)."""
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-TEST-004',
        )
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=po,
            description='General stock',
            qty=Decimal('20.00'),
            price=Decimal('45.00'),
        )
        self.assertIsNone(li.job)

    def test_line_item_inventory_item_is_optional(self):
        """Line items can exist without an inventory item."""
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-TEST-005',
        )
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=po,
            description='Custom order item',
            qty=Decimal('1.00'),
            price=Decimal('100.00'),
        )
        self.assertIsNone(li.inventory_item)

    def test_derive_po_jobs_from_line_items(self):
        """Can derive the set of jobs associated with a PO from its line items."""
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-TEST-006',
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item 1',
            qty=Decimal('10.00'), price=Decimal('45.00'),
            job=self.job_a,
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item 2',
            qty=Decimal('5.00'), price=Decimal('45.00'),
            job=self.job_b,
        )
        PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='General stock',
            qty=Decimal('20.00'), price=Decimal('45.00'),
        )

        # Get unique jobs from line items
        job_ids = po.purchaseorderlineitem_set.exclude(
            job__isnull=True
        ).values_list('job', flat=True).distinct()
        jobs = Job.objects.filter(job_id__in=job_ids)
        self.assertEqual(jobs.count(), 2)
        self.assertIn(self.job_a, jobs)
        self.assertIn(self.job_b, jobs)

    def test_job_set_null_on_delete(self):
        """Line item job FK set to null when job is deleted."""
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-TEST-007',
        )
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item',
            qty=Decimal('1.00'), price=Decimal('10.00'),
            job=self.job_a,
        )
        self.job_a.delete()
        li.refresh_from_db()
        self.assertIsNone(li.job)

    def test_inventory_item_set_null_on_delete(self):
        """Line item inventory_item FK set to null when inventory item is deleted."""
        po = PurchaseOrder.objects.create(
            business=self.business, po_number='PO-TEST-008',
        )
        li = PurchaseOrderLineItem.objects.create(
            purchase_order=po, description='Item',
            qty=Decimal('1.00'), price=Decimal('10.00'),
            inventory_item=self.inventory_item,
        )
        self.inventory_item.delete()
        li.refresh_from_db()
        self.assertIsNone(li.inventory_item)
