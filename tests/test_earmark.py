"""
Tests for Earmark model and inventory availability.
"""
from decimal import Decimal
from django.test import TestCase
from django.db import IntegrityError
from apps.contacts.models import Contact, Business
from apps.core.models import AccountingCategory
from apps.jobs.models import Job
from apps.inventory.models import PriceListItem
from apps.inventory.models import Earmark, InventoryAdjustment


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
        self.screws = PriceListItem.objects.create(
            code='SCR.100',
            description='Wood Screws Box of 100',
            units='ea',
            qty_on_hand=Decimal('50.00'),
            purchase_price=Decimal('8.00'),
            selling_price=Decimal('12.00'),
            is_inventoried=True,
            accounting_category=self.category,
        )

    def test_create_earmark(self):
        """Can create an earmark linking price list item to job."""
        earmark = Earmark.objects.create(
            price_list_item=self.plywood,
            job=self.job_a,
            quantity=Decimal('5.00'),
        )
        self.assertEqual(earmark.price_list_item, self.plywood)
        self.assertEqual(earmark.job, self.job_a)
        self.assertEqual(earmark.quantity, Decimal('5.00'))
        self.assertIsNotNone(earmark.created_date)

    def test_earmark_with_notes(self):
        """Earmark can have notes."""
        earmark = Earmark.objects.create(
            price_list_item=self.plywood,
            job=self.job_a,
            quantity=Decimal('10.00'),
            notes='Reserved for kitchen cabinets',
        )
        self.assertEqual(earmark.notes, 'Reserved for kitchen cabinets')

    def test_unique_together_item_job(self):
        """Only one earmark per price_list_item + job combination."""
        Earmark.objects.create(
            price_list_item=self.plywood,
            job=self.job_a,
            quantity=Decimal('5.00'),
        )
        with self.assertRaises(IntegrityError):
            Earmark.objects.create(
                price_list_item=self.plywood,
                job=self.job_a,
                quantity=Decimal('3.00'),
            )

    def test_same_item_different_jobs(self):
        """Same item can be earmarked for different jobs."""
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job_b, quantity=Decimal('3.00'),
        )
        self.assertEqual(Earmark.objects.filter(price_list_item=self.plywood).count(), 2)

    def test_cascade_on_item_delete(self):
        """Earmarks deleted when price list item is deleted."""
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        self.plywood.delete()
        self.assertEqual(Earmark.objects.count(), 0)

    def test_cascade_on_job_delete(self):
        """Earmarks deleted when job is deleted."""
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        self.job_a.delete()
        self.assertEqual(Earmark.objects.count(), 0)

    def test_str_representation(self):
        """Earmark has a useful string representation."""
        earmark = Earmark.objects.create(
            price_list_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        self.assertIn('PLY.75', str(earmark))
        self.assertIn('J-EAR-001', str(earmark))


class InventoryItemAvailabilityTest(TestCase):
    """Tests for qty_earmarked and qty_available properties on PriceListItem."""

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

    def test_no_earmarks_all_available(self):
        """With no earmarks, all QOH is available."""
        self.assertEqual(self.plywood.qty_earmarked, Decimal('0.00'))
        self.assertEqual(self.plywood.qty_available, Decimal('20.00'))

    def test_earmarked_reduces_available(self):
        """Earmarked quantity reduces available quantity."""
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job_a, quantity=Decimal('8.00'),
        )
        self.assertEqual(self.plywood.qty_earmarked, Decimal('8.00'))
        self.assertEqual(self.plywood.qty_available, Decimal('12.00'))

    def test_multiple_earmarks_sum(self):
        """Multiple earmarks sum up for total earmarked."""
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job_a, quantity=Decimal('5.00'),
        )
        Earmark.objects.create(
            price_list_item=self.plywood, job=self.job_b, quantity=Decimal('3.00'),
        )
        self.assertEqual(self.plywood.qty_earmarked, Decimal('8.00'))
        self.assertEqual(self.plywood.qty_available, Decimal('12.00'))


class InventoryAdjustmentModelTest(TestCase):
    """Tests for the InventoryAdjustment model."""

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

    def test_create_adjustment(self):
        """Can create an inventory adjustment record."""
        adj = InventoryAdjustment.objects.create(
            price_list_item=self.plywood,
            quantity_change=Decimal('-2.00'),
            reason='Damaged in storage',
        )
        self.assertEqual(adj.price_list_item, self.plywood)
        self.assertEqual(adj.quantity_change, Decimal('-2.00'))
        self.assertEqual(adj.reason, 'Damaged in storage')
        self.assertIsNotNone(adj.created_date)

    def test_positive_adjustment(self):
        """Positive adjustments (stock count correction)."""
        adj = InventoryAdjustment.objects.create(
            price_list_item=self.plywood,
            quantity_change=Decimal('5.00'),
            reason='Stock count correction',
        )
        self.assertEqual(adj.quantity_change, Decimal('5.00'))

    def test_cascade_on_item_delete(self):
        """Adjustments deleted when price list item is deleted."""
        InventoryAdjustment.objects.create(
            price_list_item=self.plywood,
            quantity_change=Decimal('-1.00'),
            reason='Waste',
        )
        self.plywood.delete()
        self.assertEqual(InventoryAdjustment.objects.count(), 0)

    def test_str_representation(self):
        """Adjustment has a useful string representation."""
        adj = InventoryAdjustment.objects.create(
            price_list_item=self.plywood,
            quantity_change=Decimal('-2.00'),
            reason='Damaged',
        )
        self.assertIn('PLY.75', str(adj))
        self.assertIn('-2.00', str(adj))
