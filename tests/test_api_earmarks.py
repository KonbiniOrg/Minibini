from decimal import Decimal
from rest_framework.test import APIClient
from tests.base import BaseTestCase
from apps.core.models import User, AccountingCategory, AppState, Configuration
from apps.contacts.models import Contact
from apps.jobs.models import Job
from apps.inventory.models import Earmark, InventoryItem
from apps.inventory.services import InventoryService


class EarmarkAPITest(BaseTestCase):
    def setUp(self):
        super().setUp()
        Configuration.objects.update_or_create(
            key='po_number_sequence',
            defaults={'value': 'PO-{year}-{counter:04d}'})
        AppState.objects.update_or_create(
            key='po_counter', defaults={'value': '0'})
        self.client = APIClient()
        self.client.force_authenticate(user=User.objects.get(username='admin'))
        cat = AccountingCategory.objects.get(pk=901)
        contact = Contact.objects.create(
            first_name='E', last_name='M', email='e@test.com')
        self.job = Job.objects.create(
            job_number='JOB-EM-1', contact=contact,
            status=Job.STATUS_APPROVED)
        self.item = InventoryItem.objects.create(
            code='EM-1', description='earmark item',
            accounting_category=cat, qty_on_hand=Decimal('1'))
        self.earmark = Earmark.objects.create(
            inventory_item=self.item, job=self.job, quantity=Decimal('4'))

    def _rows(self, resp):
        # Unpaginated: plain list, not {results: [...]}.
        self.assertIsInstance(resp.data, list)
        return resp.data

    def test_list_returns_item_and_job_fields(self):
        resp = self.client.get('/api/earmarks/')
        self.assertEqual(resp.status_code, 200)
        rows = self._rows(resp)
        row = next(r for r in rows if r['earmark_id'] == self.earmark.pk)
        self.assertEqual(row['item_code'], 'EM-1')
        self.assertEqual(row['job_number'], 'JOB-EM-1')
        self.assertEqual(Decimal(row['quantity']), Decimal('4'))
        self.assertEqual(Decimal(row['qty_on_hand']), Decimal('1'))
        self.assertEqual(Decimal(row['qty_earmarked_total']), Decimal('4'))
        self.assertEqual(row['pos'], [])

    def test_pos_lists_outstanding_pos_only(self):
        po, li = InventoryService.order_stock(self.item, Decimal('3'))
        resp = self.client.get('/api/earmarks/')
        row = next(r for r in self._rows(resp)
                   if r['earmark_id'] == self.earmark.pk)
        self.assertEqual(row['pos'], [{'po_id': po.pk, 'po_number': po.po_number}])
        self.assertEqual(Decimal(row['qty_on_order']), Decimal('3'))
        # Fully received → the PO is history, drops out of pos.
        li.qty_received = li.qty
        li.save()
        resp = self.client.get('/api/earmarks/')
        row = next(r for r in self._rows(resp)
                   if r['earmark_id'] == self.earmark.pk)
        self.assertEqual(row['pos'], [])

    def test_write_methods_rejected(self):
        resp = self.client.post('/api/earmarks/', {}, format='json')
        self.assertEqual(resp.status_code, 405)
        resp = self.client.delete(f'/api/earmarks/{self.earmark.pk}/')
        self.assertEqual(resp.status_code, 405)
