"""QBOSnapshotService: one-sweep fetch of QBO setup data into Configuration."""
import json
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.core.models import Configuration
from apps.qbo.import_services import QBOSnapshotService


def _obj(**attrs):
    o = MagicMock()
    for k, v in attrs.items():
        setattr(o, k, v)
    return o


def _ref(value, name=''):
    r = MagicMock()
    r.value = value
    r.name = name
    return r


def _items_page_one():
    return [
        _obj(Id='11', Name='CNC Cutting', Type='Service',
             UnitPrice=95.0, Description='Hourly cutting',
             IncomeAccountRef=_ref('4000', 'Service Income'),
             ExpenseAccountRef=None, PurchaseCost=0, Taxable=True),
        _obj(Id='12', Name='Baltic Birch', Type='NonInventory',
             UnitPrice=85.0, Description='4x8 sheet',
             IncomeAccountRef=_ref('4100', 'Sales of Product'),
             ExpenseAccountRef=_ref('5000', 'COGS'), PurchaseCost=52.5,
             Taxable=True),
        _obj(Id='13', Name='Legacy stock', Type='Inventory',
             UnitPrice=10.0, Description='',
             IncomeAccountRef=_ref('4100', 'Sales of Product'),
             ExpenseAccountRef=None, PurchaseCost=4.0, Taxable=False),
        _obj(Id='14', Name='Grouping node', Type='Category',
             UnitPrice=None, Description='', IncomeAccountRef=None,
             ExpenseAccountRef=None, PurchaseCost=None, Taxable=None),
    ]


class SnapshotPullTest(TestCase):
    def _run_pull(self, items_pages=None):
        items_pages = items_pages if items_pages is not None else [_items_page_one(), []]
        income = [_obj(Id='4000', Name='Service Income', AccountType='Income')]
        expense = [_obj(Id='5000', Name='COGS', AccountType='Cost of Goods Sold',
                        AccountSubType='SuppliesMaterials')]
        customers = [_obj(Id='71', DisplayName='Acme Corp', CompanyName='Acme Corp',
                          GivenName='Jo', FamilyName='Acme',
                          PrimaryEmailAddr=_obj(Address='jo@acme.com'),
                          PrimaryPhone=_obj(FreeFormNumber='555-1000'),
                          SalesTermRef=_ref('3'))]
        vendors = [_obj(Id='81', DisplayName='Moore Newton', CompanyName='Moore Newton',
                        PrimaryEmailAddr=None, PrimaryPhone=None)]
        terms = [_obj(Id='3', Name='Net 30', DueDays=30)]

        def paged(pages):
            state = {'i': 0}
            def _filter(order_by='', start_position='', max_results='', qb=None, **kw):
                page = pages[state['i']] if state['i'] < len(pages) else []
                state['i'] += 1
                return page
            return _filter

        with patch('quickbooks.objects.item.Item.filter',
                   side_effect=paged(items_pages)), \
             patch('quickbooks.objects.account.Account.filter',
                   side_effect=lambda **kw: (
                       income if kw.get('AccountType') == 'Income'
                       else expense if kw.get('AccountType') in ('Expense', 'Cost of Goods Sold')
                       else [])), \
             patch('quickbooks.objects.customer.Customer.filter',
                   side_effect=paged([customers, []])), \
             patch('quickbooks.objects.vendor.Vendor.filter',
                   side_effect=paged([vendors, []])), \
             patch('quickbooks.objects.term.Term.filter',
                   side_effect=paged([terms, []])):
            return QBOSnapshotService.pull(MagicMock())

    def test_pull_stores_and_returns_snapshot(self):
        snap = self._run_pull()
        self.assertEqual(snap['version'], 1)
        self.assertTrue(snap['fetched_at'])
        stored = json.loads(
            Configuration.objects.get(key=QBOSnapshotService.KEY).value)
        self.assertEqual(stored['fetched_at'], snap['fetched_at'])

    def test_item_mapping(self):
        snap = self._run_pull()
        by_id = {i['qbo_id']: i for i in snap['items']}
        # Category-type rows are excluded entirely.
        self.assertEqual(set(by_id), {'11', '12', '13'})
        svc = by_id['11']
        self.assertEqual(svc['type'], 'Service')
        self.assertEqual(svc['unit_price'], '95.0')
        self.assertEqual(svc['income_account_id'], '4000')
        self.assertEqual(svc['income_account_name'], 'Service Income')
        self.assertEqual(svc['expense_account_id'], '')
        self.assertTrue(svc['taxable'])
        two_sided = by_id['12']
        self.assertEqual(two_sided['expense_account_id'], '5000')
        self.assertEqual(two_sided['purchase_cost'], '52.5')
        self.assertFalse(by_id['13']['taxable'])

    def test_account_customer_vendor_term_mapping(self):
        snap = self._run_pull()
        self.assertEqual(snap['income_accounts'],
                         [{'qbo_id': '4000', 'name': 'Service Income',
                           'type': 'Income'}])
        self.assertEqual(snap['expense_accounts'][0]['qbo_id'], '5000')
        cust = snap['customers'][0]
        self.assertEqual(cust['qbo_id'], '71')
        self.assertEqual(cust['company_name'], 'Acme Corp')
        self.assertEqual(cust['email'], 'jo@acme.com')
        self.assertEqual(cust['term_qbo_id'], '3')
        self.assertEqual(snap['vendors'][0]['display_name'], 'Moore Newton')
        self.assertEqual(snap['terms'][0],
                         {'qbo_id': '3', 'name': 'Net 30', 'due_days': 30})

    def test_pagination_loops_until_short_page(self):
        page1 = _items_page_one()  # 4 rows == patched page size → full page
        page2 = [_obj(Id='15', Name='Extra', Type='Service', UnitPrice=1.0,
                      Description='', IncomeAccountRef=_ref('4000', 'Service Income'),
                      ExpenseAccountRef=None, PurchaseCost=0, Taxable=True)]
        with patch('apps.qbo.import_services._PAGE', len(page1)):
            snap = self._run_pull(items_pages=[page1, page2, []])
        self.assertIn('15', {i['qbo_id'] for i in snap['items']})

    def test_load_none_when_absent_and_roundtrip(self):
        self.assertIsNone(QBOSnapshotService.load())
        self._run_pull()
        self.assertEqual(QBOSnapshotService.load()['version'], 1)
