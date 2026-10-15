# tests/test_vendor_history.py
"""GET /api/inventory/{id}/vendor-history/ (spec 2026-10-14 §4.1): vendors
from non-draft, non-cancelled PO lines newest first; earmarks by job with
?exclude_job; every open draft (vendor-less included) for client-side
filtering."""
from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from apps.contacts.models import Business, Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.inventory.models import Earmark, InventoryItem
from apps.inventory.services import InventoryService
from apps.jobs.models import Job
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLineItem
from apps.purchasing.services import PurchaseOrderService


def _vendor(name):
    c = Contact.objects.create(first_name=name, last_name='Sales',
                               email=f'{name.lower()}@vendor.example',
                               phones=[{'number': '5', 'label': 'work'}])
    b = Business.objects.create(business_name=name, default_contact=c)
    c.business = b
    c.save()
    return b, c


class _Base(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='po_number_sequence', defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='po_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='Materials', code='MATVH')
        self.item = InventoryItem.objects.create(
            code='BB34P', description='ply', accounting_category=self.cat,
            purchase_price=Decimal('60.00'), units='sheet')
        self.rugby, self.rugby_contact = _vendor('Rugby')
        self.royal, self.royal_contact = _vendor('Royal')
        self.now = timezone.now()

    def _po(self, business, contact=None, status=PurchaseOrder.STATUS_ISSUED, days_ago=0):
        po = PurchaseOrder.objects.create(business=business, contact=contact)
        if status != PurchaseOrder.STATUS_DRAFT:
            PurchaseOrder.objects.filter(pk=po.pk).update(
                status=status, issued_date=self.now - timedelta(days=days_ago))
            po.refresh_from_db()
        return po

    def _line(self, po, price=Decimal('60.00'), sku=''):
        return PurchaseOrderLineItem.objects.create(
            purchase_order=po, inventory_item=self.item, description='ply',
            qty=1, price=price, vendor_sku=sku)


class VendorHistoryServiceTests(_Base):
    def test_vendors_newest_first_with_newest_line_details(self):
        old = self._po(self.rugby, self.rugby_contact, days_ago=10)
        self._line(old, Decimal('58.00'), 'R-OLD')
        mid = self._po(self.rugby, None, days_ago=5)
        self._line(mid, Decimal('60.00'), 'R-NEW')
        new = self._po(self.royal, self.royal_contact,
                       status=PurchaseOrder.STATUS_RECEIVED_IN_FULL, days_ago=2)
        self._line(new, Decimal('62.40'), 'BB34P-48')

        data = InventoryService.vendor_history(self.item)
        self.assertEqual([v['business_name'] for v in data['vendors']], ['Royal', 'Rugby'])
        royal, rugby = data['vendors']
        self.assertEqual(royal['contact_id'], self.royal_contact.pk)
        self.assertEqual(royal['last_price'], '62.40')
        self.assertEqual(royal['vendor_sku'], 'BB34P-48')
        self.assertEqual(royal['po_number'], new.po_number)
        self.assertEqual(royal['last_ordered'], (self.now - timedelta(days=2)).date().isoformat())
        self.assertEqual(royal['times'], 1)
        self.assertEqual(rugby['vendor_sku'], 'R-NEW')
        self.assertIsNone(rugby['contact_id'])
        self.assertEqual(rugby['po_number'], mid.po_number)
        self.assertEqual(rugby['times'], 2)

    def test_drafts_and_cancelled_excluded_from_vendors(self):
        self._line(self._po(self.rugby, status=PurchaseOrder.STATUS_DRAFT))
        self._line(self._po(self.royal, status=PurchaseOrder.STATUS_CANCELLED, days_ago=1))
        self.assertEqual(InventoryService.vendor_history(self.item)['vendors'], [])

    def test_lot_item_has_no_vendors_but_sees_open_drafts(self):
        lot = InventoryItem.objects.create(
            code='LOT-9', description='lot', accounting_category=self.cat)
        draft = self._po(self.rugby, status=PurchaseOrder.STATUS_DRAFT)
        data = InventoryService.vendor_history(lot)
        self.assertEqual(data['vendors'], [])
        self.assertEqual([d['po_id'] for d in data['open_drafts']], [draft.pk])

    def test_open_drafts_include_vendorless_with_line_count(self):
        vendored = self._po(self.rugby, status=PurchaseOrder.STATUS_DRAFT)
        self._line(vendored)
        self._line(vendored)
        bare = PurchaseOrderService.create_po()
        issued = self._po(self.royal, days_ago=1)
        self._line(issued)
        rows = {d['po_id']: d for d in InventoryService.vendor_history(self.item)['open_drafts']}
        self.assertEqual(set(rows), {vendored.pk, bare.pk})
        self.assertEqual(rows[vendored.pk]['line_count'], 2)
        self.assertEqual(rows[vendored.pk]['business_name'], 'Rugby')
        self.assertIsNone(rows[bare.pk]['business_id'])
        self.assertIsNone(rows[bare.pk]['business_name'])

    def test_earmarks_by_job_with_exclude_job(self):
        cust = Contact.objects.create(first_name='C', last_name='C',
                                      email='c@cust.example',
                                      phones=[{'number': '1', 'label': 'work'}])
        job_a = Job.objects.create(job_number='08157', contact=cust, description='a')
        job_b = Job.objects.create(job_number='08149', contact=cust, description='b')
        Earmark.objects.create(inventory_item=self.item, job=job_a, quantity=Decimal('4'))
        Earmark.objects.create(inventory_item=self.item, job=job_b, quantity=Decimal('3'))
        all_rows = InventoryService.vendor_history(self.item)['earmarks']
        self.assertEqual({(e['job_number'], e['quantity']) for e in all_rows},
                         {('08157', '4.00'), ('08149', '3.00')})
        others = InventoryService.vendor_history(self.item, exclude_job=job_a.pk)['earmarks']
        self.assertEqual([e['job_id'] for e in others], [job_b.pk])


class VendorHistoryApiTests(_Base):
    def setUp(self):
        super().setUp()
        self.worker = User.objects.create_user('vh_worker', password='p')
        self.client = APIClient()

    def test_any_authenticated_user_can_read(self):
        self._line(self._po(self.rugby, days_ago=1), sku='R-1')
        self.client.force_authenticate(self.worker)
        r = self.client.get(f'/api/inventory/{self.item.pk}/vendor-history/')
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()['vendors'][0]['vendor_sku'], 'R-1')
        self.assertEqual(set(r.json()), {'vendors', 'earmarks', 'open_drafts'})

    def test_anonymous_rejected(self):
        r = self.client.get(f'/api/inventory/{self.item.pk}/vendor-history/')
        self.assertIn(r.status_code, (401, 403))

    def test_exclude_job_must_be_integer(self):
        self.client.force_authenticate(self.worker)
        r = self.client.get(f'/api/inventory/{self.item.pk}/vendor-history/?exclude_job=abc')
        self.assertEqual(r.status_code, 400)
        self.assertIn('exclude_job', r.json())
