"""Paths 3+4 receipt: an explicit, recorded QOH bump in job context (spec §Path 3/4)."""
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, Configuration, InventoryHistory
from apps.inventory.services import MaterialService
from apps.jobs.models import Job


class MarkOnHandTests(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='default_material_markup_percent', value='25')
        self.cat = AccountingCategory.objects.create(
            name='Materials', is_active=True, code='MOH')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='5')
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-1001')

    def test_mark_on_hand_bumps_lot_and_records_history(self):
        m = MaterialService.create_on_job(
            job=self.job, description='steel', quantity=Decimal('3'),
            unit_cost=Decimal('10.00'), accounting_category=self.cat, units='ea')
        MaterialService.mark_on_hand(m, Decimal('3'))
        m.refresh_from_db()
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('3'))
        entry = InventoryHistory.objects.filter(
            object_type='inventoryitem', object_id=m.inventory_item_id).latest('pk')
        self.assertEqual(entry.changes.get('_action'), 'Marked on-hand')
        MaterialService.consume(m)   # arrival satisfied the gate

    def test_customer_delivery_action_label_and_partial(self):
        m = MaterialService.create_on_job(
            job=self.job, description='panels', quantity=Decimal('12'),
            accounting_category=self.cat, units='ea', customer_supplied=True)
        MaterialService.mark_on_hand(m, Decimal('8'))
        m.refresh_from_db()
        self.assertEqual(m.inventory_item.qty_on_hand, Decimal('8'))
        entry = InventoryHistory.objects.filter(
            object_type='inventoryitem', object_id=m.inventory_item_id).latest('pk')
        self.assertEqual(entry.changes.get('_action'), 'Customer delivery')
        with self.assertRaises(ValidationError):
            MaterialService.consume(m)          # 8 < 12 still blocks

    def test_refuses_provisional_and_nonpositive(self):
        prov = MaterialService.create_on_job(
            job=self.job, description='?', quantity=Decimal('1'),
            accounting_category=self.cat, units='ea')
        with self.assertRaises(ValidationError):
            MaterialService.mark_on_hand(prov, Decimal('1'))
        m = MaterialService.create_on_job(
            job=self.job, description='established', quantity=Decimal('1'),
            unit_cost=Decimal('5.00'), accounting_category=self.cat, units='ea')
        with self.assertRaises(ValidationError):
            MaterialService.mark_on_hand(m, Decimal('0'))
