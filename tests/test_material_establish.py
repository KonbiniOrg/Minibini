"""Establishment = pricing mints/attaches the lot (spec §core move)."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration
from apps.inventory.models import Earmark, InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Job


class EstablishBase(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='default_material_markup_percent', value='25')
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MAT')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='5')
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001')

    def _provisional(self, **kw):
        kw.setdefault('quantity', Decimal('4'))
        return MaterialService.create_on_job(
            job=self.job, description='dragon skin',
            accounting_category=self.cat, units='ea', **kw)


class EstablishTests(EstablishBase):
    def test_provisional_birth_no_lot_null_source(self):
        m = self._provisional()
        self.assertIsNone(m.inventory_item_id)
        self.assertIsNone(m.cost_source)
        self.assertFalse(Earmark.objects.filter(job=self.job).exists())

    def test_establish_mints_lot_with_markup_sell_and_earmark(self):
        m = self._provisional()
        MaterialService.establish(m, unit_cost=Decimal('100.00'))
        m.refresh_from_db()
        lot = m.inventory_item
        self.assertIsNotNone(lot)
        self.assertEqual(lot.code, f'LOT-{m.pk}')
        self.assertEqual(lot.qty_on_hand, Decimal('0.00'))
        self.assertEqual(lot.purchase_price, Decimal('100.00'))
        self.assertEqual(lot.selling_price, Decimal('125.00'))  # 25% markup
        self.assertEqual(m.sell_price, Decimal('125.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_ENTERED)
        em = Earmark.objects.get(inventory_item=lot, job=self.job)
        self.assertEqual(em.quantity, Decimal('4'))

    def test_establish_keeps_estimate_locked_sell_price(self):
        m = self._provisional(sell_price=Decimal('400.00'))
        MaterialService.establish(m, unit_cost=Decimal('300.00'))
        m.refresh_from_db()
        self.assertEqual(m.sell_price, Decimal('400.00'))  # locked, not re-derived

    def test_establish_attaches_existing_item(self):
        item = InventoryItem.objects.create(
            code='ACR', accounting_category=self.cat, units='ea',
            purchase_price=Decimal('10.00'), selling_price=Decimal('15.00'))
        m = self._provisional()
        MaterialService.establish(m, inventory_item=item)
        m.refresh_from_db()
        self.assertEqual(m.inventory_item_id, item.pk)
        self.assertEqual(m.unit_cost, Decimal('10.00'))
        self.assertEqual(m.cost_source, Material.COST_SOURCE_ENTERED)

    def test_establish_refuses_established_and_nonpending(self):
        m = self._provisional()
        MaterialService.establish(m, unit_cost=Decimal('1.00'))
        with self.assertRaises(ValidationError):
            MaterialService.establish(m, unit_cost=Decimal('2.00'))

    def test_create_on_job_with_cost_is_born_established(self):
        m = MaterialService.create_on_job(
            job=self.job, description='ply', quantity=Decimal('2'),
            unit_cost=Decimal('50.00'), accounting_category=self.cat, units='ea')
        self.assertIsNotNone(m.inventory_item_id)
        self.assertEqual(m.cost_source, Material.COST_SOURCE_ENTERED)

    def test_update_fields_atomic_failed_patch_rolls_back_establish(self):
        """A PATCH mixing a pricing write (which establishes) with a field the
        now-catalog-backed material refuses must roll back the mint/earmark —
        no half-applied establish behind an HTTP 400."""
        m = self._provisional()
        with self.assertRaises(ValidationError):
            MaterialService.update_fields(
                m, unit_cost=Decimal('7.00'), description='renamed')
        m.refresh_from_db()
        self.assertIsNone(m.inventory_item_id)
        self.assertIsNone(m.cost_source)
        self.assertFalse(
            InventoryItem.objects.filter(code=f'LOT-{m.pk}').exists())
        self.assertFalse(Earmark.objects.filter(job=self.job).exists())

    def test_no_earmark_on_preapproval_job(self):
        # approved→draft is a blocked Job transition, so use a fresh DRAFT job.
        draft_job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT,
            job_number='JOB-2026-0002')
        m = MaterialService.create_on_job(
            job=draft_job, description='dragon skin',
            accounting_category=self.cat, units='ea', quantity=Decimal('4'))
        MaterialService.establish(m, unit_cost=Decimal('10.00'))
        self.assertFalse(Earmark.objects.filter(job=draft_job).exists())
