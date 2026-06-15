from decimal import Decimal
from django.test import TestCase
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, InventoryItem
from apps.inventory.services import InventoryService
from apps.core.models import AccountingCategory


class MutateEarmarkTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(name='c')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(job_number='JOB-E-1', contact=self.contact)
        self.pli = InventoryItem.objects.create(
            code='A', accounting_category=self.cat, is_catalog=True,
        )
        self.noninv = InventoryItem.objects.create(
            code='B', accounting_category=self.cat, is_catalog=False,
        )

    def test_positive_delta_creates_earmark(self):
        InventoryService._mutate_earmark(self.pli, self.job, Decimal('3'))
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('3'))

    def test_positive_delta_increments_existing(self):
        Earmark.objects.create(price_list_item=self.pli, job=self.job, quantity=Decimal('2'))
        InventoryService._mutate_earmark(self.pli, self.job, Decimal('3'))
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('5'))

    def test_negative_delta_shrinks(self):
        Earmark.objects.create(price_list_item=self.pli, job=self.job, quantity=Decimal('5'))
        InventoryService._mutate_earmark(self.pli, self.job, Decimal('-2'))
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('3'))

    def test_negative_delta_to_zero_deletes(self):
        Earmark.objects.create(price_list_item=self.pli, job=self.job, quantity=Decimal('2'))
        InventoryService._mutate_earmark(self.pli, self.job, Decimal('-2'))
        self.assertFalse(
            Earmark.objects.filter(price_list_item=self.pli, job=self.job).exists()
        )

    def test_lot_item_gets_earmark(self):
        """Universal tracking: a non-catalog lot earmarks like any item
        (only a None item is a no-op — see test_noop_for_none_pli)."""
        InventoryService._mutate_earmark(self.noninv, self.job, Decimal('3'))
        self.assertTrue(Earmark.objects.filter(
            price_list_item=self.noninv, job=self.job).exists())

    def test_noop_for_none_pli(self):
        InventoryService._mutate_earmark(None, self.job, Decimal('3'))
        self.assertFalse(Earmark.objects.exists())
