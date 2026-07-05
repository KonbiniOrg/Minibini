"""Path 4: customer-supplied = established at a deliberate, locked $0 (spec §Path 4)."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job


class CustomerSuppliedTests(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='default_material_markup_percent', value='25')
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MATCS')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='5')
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0002')

    def _customer_material(self, qty=Decimal('12')):
        return MaterialService.create_on_job(
            job=self.job, description='museum panels', quantity=qty,
            accounting_category=self.cat, units='ea', customer_supplied=True)

    def test_born_established_at_locked_zero(self):
        m = self._customer_material()
        self.assertIsNotNone(m.inventory_item_id)
        self.assertEqual(m.unit_cost, Decimal('0.00'))
        self.assertEqual(m.sell_price, Decimal('0.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_CUSTOMER)
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('0.00'))
        self.assertEqual(m.inventory_item.selling_price, Decimal('0.00'))
        em = Earmark.objects.get(inventory_item=m.inventory_item, job=self.job)
        self.assertEqual(em.quantity, Decimal('12'))

    def test_pricing_is_locked(self):
        m = self._customer_material()
        with self.assertRaises(ValidationError):
            MaterialService.update_fields(m, unit_cost=Decimal('5.00'))
        with self.assertRaises(ValidationError):
            MaterialService.update_fields(m, sell_price=Decimal('5.00'))

    def test_consume_blocks_until_received(self):
        m = self._customer_material()
        with self.assertRaises(ValidationError):
            MaterialService.consume(m)

    def test_rejects_inventory_item_or_nonzero_cost(self):
        item = InventoryItem.objects.create(
            code='I-CS1', accounting_category=self.cat, qty_on_hand=Decimal('5'))
        with self.assertRaises(ValidationError):
            MaterialService.create_on_job(
                job=self.job, description='x', quantity=Decimal('1'),
                accounting_category=self.cat, units='ea',
                inventory_item=item, customer_supplied=True)
        with self.assertRaises(ValidationError):
            MaterialService.create_on_job(
                job=self.job, description='x', quantity=Decimal('1'),
                accounting_category=self.cat, units='ea',
                unit_cost=Decimal('9.00'), customer_supplied=True)
