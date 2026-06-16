"""B4 — hide-on-spend lifecycle.

A finished transient lot (not catalog, QOH 0, no earmarks) is filtered from the
active inventory list and allocation pickers, but reachable via
?include_finished=true for management (merge/write-off). Catalog items always
survive at QOH 0. Nothing is physically deleted (line items PROTECT-reference
items).
"""
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from apps.core.models import AccountingCategory, User
from apps.contacts.models import Contact, Business
from apps.jobs.models import Job
from apps.inventory.models import InventoryItem, Earmark


class IsFinishedLotPropertyTest(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.contact = Contact.objects.create(first_name='A', last_name='B')
        self.job = Job.objects.create(job_number='J-HOS-1', contact=self.contact)

    def _item(self, **kw):
        defaults = dict(code=kw.pop('code'), accounting_category=self.cat)
        defaults.update(kw)
        return InventoryItem.objects.create(**defaults)

    def test_spent_lot_is_finished(self):
        lot = self._item(code='L1', is_catalog=False, qty_on_hand=Decimal('0.00'))
        self.assertTrue(lot.is_finished_lot)

    def test_catalog_at_zero_is_not_finished(self):
        cat = self._item(code='C1', is_catalog=True, qty_on_hand=Decimal('0.00'))
        self.assertFalse(cat.is_finished_lot)

    def test_lot_with_stock_is_not_finished(self):
        lot = self._item(code='L2', is_catalog=False, qty_on_hand=Decimal('3.00'))
        self.assertFalse(lot.is_finished_lot)

    def test_lot_with_earmark_is_not_finished(self):
        lot = self._item(code='L3', is_catalog=False, qty_on_hand=Decimal('0.00'))
        Earmark.objects.create(price_list_item=lot, job=self.job, quantity=Decimal('2'))
        self.assertFalse(lot.is_finished_lot)


class HideOnSpendListTest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create(username='hos_user', is_superuser=True)
        self.client.force_authenticate(user=self.user)
        self.cat = AccountingCategory.objects.get_or_create(
            code='SVC', defaults={'name': 'Service', 'taxable': False})[0]
        self.contact = Contact.objects.create(first_name='A', last_name='B')
        self.job = Job.objects.create(job_number='J-HOS-2', contact=self.contact)
        self.catalog = InventoryItem.objects.create(
            code='CAT', is_catalog=True, qty_on_hand=Decimal('0.00'),
            accounting_category=self.cat)
        self.live_lot = InventoryItem.objects.create(
            code='LIVE', is_catalog=False, qty_on_hand=Decimal('5.00'),
            accounting_category=self.cat)
        self.earmarked_lot = InventoryItem.objects.create(
            code='EARM', is_catalog=False, qty_on_hand=Decimal('0.00'),
            accounting_category=self.cat)
        Earmark.objects.create(
            price_list_item=self.earmarked_lot, job=self.job, quantity=Decimal('2'))
        self.finished_lot = InventoryItem.objects.create(
            code='DONE', is_catalog=False, qty_on_hand=Decimal('0.00'),
            accounting_category=self.cat)

    def _codes(self, params=''):
        resp = self.client.get(f'/api/inventory/{params}')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        rows = data['results'] if isinstance(data, dict) and 'results' in data else data
        return {r['code'] for r in rows}

    def test_default_list_hides_finished_lot(self):
        codes = self._codes()
        self.assertIn('CAT', codes)        # catalog survives at QOH 0
        self.assertIn('LIVE', codes)       # lot with stock
        self.assertIn('EARM', codes)       # lot with an earmark
        self.assertNotIn('DONE', codes)    # finished lot hidden

    def test_include_finished_shows_finished_lot(self):
        codes = self._codes('?include_finished=true')
        self.assertIn('DONE', codes)
        self.assertIn('CAT', codes)

    def test_finished_lot_is_reachable_by_pk(self):
        """A hidden finished lot must still be retrievable by pk — get_object()
        must not be scoped by the list's hide-on-spend filter."""
        resp = self.client.get(f'/api/inventory/{self.finished_lot.pk}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['code'], 'DONE')

    def test_finished_lot_can_be_re_promoted_to_catalog(self):
        """The bug: PATCHing a hidden finished lot 404'd because get_object went
        through the list filter. It must succeed (e.g. to re-promote it)."""
        resp = self.client.patch(
            f'/api/inventory/{self.finished_lot.pk}/',
            {'is_catalog': True}, format='json')
        self.assertEqual(resp.status_code, 200, resp.content)
        self.finished_lot.refresh_from_db()
        self.assertTrue(self.finished_lot.is_catalog)
