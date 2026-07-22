"""QBOItemMintService: lazy mirroring of catalog entities into QBO Items.

Mocks the python-quickbooks Item class at its import site; the client is a
plain MagicMock (minting never touches QBOService.get_client itself — the
caller hands the client in).
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.core.models import AccountingCategory
from apps.estimates.models import ServiceItem
from apps.inventory.models import InventoryItem
from apps.jobs.models import RateScheme
from apps.qbo.services import QBOItemMintService


def _mock_item_class(save_id='901', save_raises=None, filter_result=None):
    """A stand-in for quickbooks.objects.item.Item.

    Returns (ItemClass, created_instances). Instantiating the class yields a
    MagicMock whose save() stamps Id=save_id (or raises save_raises).
    ItemClass.get returns a generic item carrying an IncomeAccountRef;
    ItemClass.filter returns filter_result.
    """
    created = []
    generic = MagicMock()
    generic.IncomeAccountRef = MagicMock(name='IncomeAccountRef')

    item_cls = MagicMock()

    def construct():
        inst = MagicMock()
        if save_raises is not None:
            inst.save.side_effect = save_raises
        else:
            def _save(qb=None):
                inst.Id = save_id
            inst.save.side_effect = _save
        created.append(inst)
        return inst

    item_cls.side_effect = construct
    item_cls.get.return_value = generic
    item_cls.filter.return_value = filter_result or []
    return item_cls, created, generic


class QBOItemMintTests(TestCase):
    def setUp(self):
        self.cat = AccountingCategory.objects.create(
            code='MAT', name='Material', taxable=True, qbo_item_id='55',
        )
        self.inv = InventoryItem.objects.create(
            code='PLY', description='Plywood', accounting_category=self.cat,
        )
        self.scheme = RateScheme.objects.create(
            name='Per-cut', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10.00'), unit_label='ea',
            accounting_category=self.cat,
        )
        self.svc = ServiceItem.objects.create(
            template_name='CNC Cutting', is_active=True,
            rate_scheme=self.scheme,
        )

    def test_short_circuits_on_existing_qbo_id(self):
        self.inv.qbo_id = '42'
        self.inv.save(update_fields=['qbo_id'])
        client = MagicMock()
        with patch('quickbooks.objects.item.Item') as item_cls:
            result = QBOItemMintService.ensure_item(self.inv, client)
        self.assertEqual(result, '42')
        item_cls.get.assert_not_called()

    def test_mints_noninventory_item_for_inventory_item(self):
        item_cls, created, generic = _mock_item_class(save_id='901')
        with patch('quickbooks.objects.item.Item', item_cls):
            result = QBOItemMintService.ensure_item(self.inv, MagicMock())
        self.assertEqual(result, '901')
        item_cls.get.assert_called_once()
        self.assertEqual(item_cls.get.call_args.args[0], '55')
        self.assertEqual(len(created), 1)
        minted = created[0]
        self.assertEqual(minted.Name, 'PLY')
        self.assertEqual(minted.Type, 'NonInventory')
        self.assertIs(minted.IncomeAccountRef, generic.IncomeAccountRef)
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.qbo_id, '901')

    def test_mints_service_item_with_service_type_and_template_name(self):
        item_cls, created, generic = _mock_item_class(save_id='902')
        with patch('quickbooks.objects.item.Item', item_cls):
            result = QBOItemMintService.ensure_item(self.svc, MagicMock())
        self.assertEqual(result, '902')
        minted = created[0]
        self.assertEqual(minted.Name, 'CNC Cutting')
        self.assertEqual(minted.Type, 'Service')
        self.svc.refresh_from_db()
        self.assertEqual(self.svc.qbo_id, '902')

    def test_duplicate_name_adopts_existing(self):
        existing = MagicMock()
        existing.Id = '333'
        item_cls, created, generic = _mock_item_class(
            save_raises=Exception(
                'Duplicate Name Exists Error: The name supplied already '
                'exists. : Another item is already using this name.'
            ),
            filter_result=[existing],
        )
        with patch('quickbooks.objects.item.Item', item_cls):
            result = QBOItemMintService.ensure_item(self.inv, MagicMock())
        self.assertEqual(result, '333')
        item_cls.filter.assert_called_once()
        self.assertEqual(item_cls.filter.call_args.kwargs.get('Name'), 'PLY')
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.qbo_id, '333')

    def test_non_duplicate_error_reraises(self):
        item_cls, created, generic = _mock_item_class(
            save_raises=Exception('ValidationFault: something else'),
        )
        with patch('quickbooks.objects.item.Item', item_cls):
            with self.assertRaises(Exception):
                QBOItemMintService.ensure_item(self.inv, MagicMock())
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.qbo_id, '')

    def test_unmapped_category_returns_empty_and_mints_nothing(self):
        self.cat.qbo_item_id = ''
        self.cat.save()
        with patch('quickbooks.objects.item.Item') as item_cls:
            result = QBOItemMintService.ensure_item(self.inv, MagicMock())
        self.assertEqual(result, '')
        item_cls.get.assert_not_called()
        self.inv.refresh_from_db()
        self.assertEqual(self.inv.qbo_id, '')
