from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.inventory.models import Material, Earmark, PriceListItem
from apps.inventory.services import InventoryService, MaterialService
from apps.core.models import AccountingCategory


class ConsumeTest(TestCase):
    def setUp(self):
        cat = AccountingCategory.objects.create(name='c')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='c@test.com'
        )
        self.job = Job.objects.create(job_number='JOB-C-1', contact=self.contact)
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_consume_inventoried_updates_qoh_sold_earmark_state(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('4'),
            price_list_item=self.pli,
        )
        MaterialService.consume(m)
        m.refresh_from_db()
        self.pli.refresh_from_db()
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_CONSUMED)
        self.assertEqual(self.pli.qty_on_hand, Decimal('6'))
        self.assertEqual(self.pli.qty_sold, Decimal('4'))
        self.assertFalse(
            Earmark.objects.filter(price_list_item=self.pli, job=self.job).exists()
        )

    def test_consume_requires_pending(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('2'),
            price_list_item=self.pli,
        )
        MaterialService.consume(m)
        with self.assertRaises(ValidationError):
            MaterialService.consume(m)

    def test_consume_uses_effective_qty(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None,
            description='x', quantity=Decimal('5'),
            price_list_item=self.pli,
        )
        MaterialService.restock(m, Decimal('2'))
        MaterialService.consume(m)
        self.pli.refresh_from_db()
        self.assertEqual(self.pli.qty_sold, Decimal('3'))


class RestockTest(TestCase):
    def setUp(self):
        cat = AccountingCategory.objects.create(name='c')
        self.contact = Contact.objects.create(
            first_name='Test', last_name='Contact', email='r@test.com'
        )
        self.job = Job.objects.create(job_number='JOB-R-1', contact=self.contact)
        self.pli = PriceListItem.objects.create(
            code='I', accounting_category=cat, is_inventoried=True,
            qty_on_hand=Decimal('10'),
        )

    def test_partial_restock_shrinks_earmark_and_bumps_restocked_qty(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), price_list_item=self.pli,
        )
        MaterialService.restock(m, Decimal('2'))
        m.refresh_from_db()
        self.assertEqual(m.restocked_qty, Decimal('2'))
        self.assertEqual(m.consumption_state, Material.CONSUMPTION_STATE_PENDING)
        e = Earmark.objects.get(price_list_item=self.pli, job=self.job)
        self.assertEqual(e.quantity, Decimal('3'))

    def test_full_restock_manual_add_deletes_material(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('5'), price_list_item=self.pli,
        )
        mid = m.pk
        MaterialService.restock(m, Decimal('5'))
        self.assertFalse(Material.objects.filter(pk=mid).exists())
        self.assertFalse(Earmark.objects.filter(
            price_list_item=self.pli, job=self.job).exists())

    def test_restock_validates_positive_and_leq_effective(self):
        m = MaterialService.create_on_job(
            job=self.job, task=None, description='x',
            quantity=Decimal('2'), price_list_item=self.pli,
        )
        with self.assertRaises(ValidationError):
            MaterialService.restock(m, Decimal('0'))
        with self.assertRaises(ValidationError):
            MaterialService.restock(m, Decimal('3'))
