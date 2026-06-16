"""
Tests for Earmark model and inventory availability.
"""
from decimal import Decimal
from django.test import TestCase
from django.db import IntegrityError
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory
from apps.jobs.models import Job
from apps.inventory.models import InventoryItem
from apps.inventory.models import Earmark
from apps.inventory.services import InventoryService
from apps.core.models import InventoryHistory


class EarmarkModelTest(TestCase):
    """Tests for the Earmark model."""

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

        self.job_a = Job.objects.create(
            job_number='J-EAR-001', contact=self.contact, description='Job A',
        )
        self.job_b = Job.objects.create(
            job_number='J-EAR-002', contact=self.contact, description='Job B',
        )

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_catalog=True,
            accounting_category=self.category,
        )
        self.screws = InventoryItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='ea',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            is_catalog=True,
            accounting_category=self.category,
        )

    def test_create_earmark(self):
        """Can create an earmark linking price list item to job."""
        earmark = Earmark.objects.create(
            inventory_item=self.plywood,
            job=self.job_a,
            quantity=Decimal('5.00'),
        )
        self.assertEqual(earmark.inventory_item, self.plywood)
        self.assertEqual(earmark.job, self.job_a)
        self.assertEqual(earmark.quantity, Decimal('5.00'))
        self.assertIsNotNone(earmark.created_date)

    def test_earmark_with_notes(self):
        """Earmark can have notes."""
        earmark = Earmark.objects.create(
            inventory_item=self.plywood,
            job=self.job_a,
            quantity=Decimal('10.00'),
            notes='Reserved for kitchen cabinets',
        )
        self.assertEqual(earmark.notes, 'Reserved for kitchen cabinets')

    def test_unique_together_item_job(self):
        """Only one earmark per inventory_item + job combination."""
        Earmark.objects.create(
            inventory_item=self.plywood,
            job=self.job_a,
            quantity=Decimal('5.00'),
        )
        with self.assertRaises(IntegrityError):
            Earmark.objects.create(
                inventory_item=self.plywood,
                job=self.job_a,
                quantity=Decimal('3.00'),
            )

    def test_same_item_different_jobs(self):
        """Same item can be earmarked for different jobs."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job_b, quantity=Decimal('3.00'),
        )
        self.assertEqual(Earmark.objects.filter(inventory_item=self.plywood).count(), 2)

    def test_cascade_on_item_delete(self):
        """Earmarks deleted when price list item is deleted."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        self.plywood.delete()
        self.assertEqual(Earmark.objects.count(), 0)

    def test_cascade_on_job_delete(self):
        """Earmarks deleted when job is deleted."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        self.job_a.delete()
        self.assertEqual(Earmark.objects.count(), 0)

    def test_str_representation(self):
        """Earmark has a useful string representation."""
        earmark = Earmark.objects.create(
            inventory_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        self.assertIn('PLY.75', str(earmark))
        self.assertIn('J-EAR-001', str(earmark))


class InventoryItemAvailabilityTest(TestCase):
    """Tests for qty_earmarked and qty_available properties on InventoryItem."""

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

        self.job_a = Job.objects.create(
            job_number='J-AVL-001', contact=self.contact, description='Job A',
        )
        self.job_b = Job.objects.create(
            job_number='J-AVL-002', contact=self.contact, description='Job B',
        )

        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_catalog=True,
            accounting_category=self.category,
        )

    def test_no_earmarks_all_available(self):
        """With no earmarks, all QOH is available."""
        self.assertEqual(self.plywood.qty_earmarked, Decimal('0.00'))
        self.assertEqual(self.plywood.qty_available, Decimal('20.00'))

    def test_earmarked_reduces_available(self):
        """Earmarked quantity reduces available quantity."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job_a, quantity=Decimal('8.00'),
        )
        self.assertEqual(self.plywood.qty_earmarked, Decimal('8.00'))
        self.assertEqual(self.plywood.qty_available, Decimal('12.00'))

    def test_multiple_earmarks_sum(self):
        """Multiple earmarks sum up for total earmarked."""
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        Earmark.objects.create(
            inventory_item=self.plywood, job=self.job_b, quantity=Decimal('3.00'),
        )
        self.assertEqual(self.plywood.qty_earmarked, Decimal('8.00'))
        self.assertEqual(self.plywood.qty_available, Decimal('12.00'))


class InventoryHistoryRecordTest(TestCase):
    """Inventory QOH events record durable InventoryHistory action entries
    (the retired InventoryAdjustment's replacement)."""

    def setUp(self):
        self.category = AccountingCategory.objects.get_or_create(code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.plywood = InventoryItem.objects.create(
            code='PLY.75',
            description='3/4" Baltic Birch Plywood',
            units='sheets',
            qty_on_hand=Decimal('20.00'),
            purchase_price=Decimal('45.00'),
            selling_price=Decimal('90.00'),
            is_catalog=True,
            accounting_category=self.category,
        )

    def _entries(self, item=None):
        item = item or self.plywood
        return InventoryHistory.objects.filter(
            object_type='inventoryitem', object_id=item.pk, entry_type='action')

    def test_manual_adjustment_records_entry(self):
        InventoryService.manual_adjustment(
            self.plywood, Decimal('-2.00'), reason='Damaged in storage')
        entry = self._entries().latest('timestamp')
        self.assertEqual(entry.text, 'Damaged in storage')
        self.assertEqual(entry.changes['qty_change'], '-2.00')
        self.assertEqual(entry.changes['code'], 'PLY.75')
        self.assertEqual(entry.changes['qty_on_hand'], '18.00')

    def test_entry_snapshots_identity(self):
        InventoryService.manual_adjustment(
            self.plywood, Decimal('5.00'), reason='Stock count correction')
        entry = self._entries().latest('timestamp')
        self.assertEqual(entry.changes['description'], '3/4" Baltic Birch Plywood')

    def test_history_survives_item_deletion(self):
        """The whole point of the loose ref: history outlives the item."""
        pk = self.plywood.pk
        InventoryService.manual_adjustment(
            self.plywood, Decimal('-1.00'), reason='Waste')
        self.plywood.delete()
        survivors = InventoryHistory.objects.filter(
            object_type='inventoryitem', object_id=pk, entry_type='action')
        self.assertEqual(survivors.count(), 1)
        self.assertEqual(survivors.first().changes['code'], 'PLY.75')
