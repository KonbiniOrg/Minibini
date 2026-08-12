"""ItemRef resolution for the per-line QBO invoice push.

_catalog_entity_for_line: which single catalog entity (InventoryItem or
ServiceItem) an invoice line sells, via its direct inventory_item FK or its
source atoms. _resolve_item_ref: that entity's (minted) QBO Item id, else the
category fallback Item, else None.
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.models import ServiceItem
from apps.inventory.models import InventoryItem, Material
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.jobs.models import Job, RateScheme, Task
from apps.qbo.services import QBOInvoiceSyncService


class ItemRefResolutionTests(TestCase):
    def setUp(self):
        self.contact = Contact.objects.create(
            first_name='Jane', last_name='Doe',
            email='jane@example.com', mobile_number='555-0000',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001',
        )
        self.category = AccountingCategory.objects.create(
            code='SVC', name='Service', taxable=True, qbo_item_id='55',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly-res', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('25.00'), unit_label='hour',
            accounting_category=self.category,
        )
        self.svc_a = ServiceItem.objects.create(
            template_name='CNC Cutting', is_active=True, rate_scheme=self.scheme,
        )
        self.svc_b = ServiceItem.objects.create(
            template_name='Finishing', is_active=True, rate_scheme=self.scheme,
        )
        self.pli = InventoryItem.objects.create(
            code='PLY', description='Plywood', accounting_category=self.category,
        )
        self.invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-RES-1',
        )

    def _line(self, **kwargs):
        defaults = dict(
            invoice=self.invoice, description='line', qty=Decimal('1'),
            price=Decimal('10.00'), accounting_category=self.category,
        )
        defaults.update(kwargs)
        return InvoiceLineItem.objects.create(**defaults)

    def _task(self, service_item=None, name='T'):
        task = Task(
            job=self.job, name=name,
            service_item=service_item,
        )
        task.stamp_from_scheme(self.scheme)
        task.save()
        return task

    def _source(self, line, atom):
        if isinstance(atom, Task):
            stype = InvoiceLineItemSource.SOURCE_TASK
        else:
            stype = InvoiceLineItemSource.SOURCE_MATERIAL
        return InvoiceLineItemSource.objects.create(
            invoice_line_item=line, source_type=stype, source_pk=atom.pk,
        )

    # --- _catalog_entity_for_line ---

    def test_direct_inventory_item_fk_wins(self):
        line = self._line(inventory_item=self.pli)
        entity = QBOInvoiceSyncService._catalog_entity_for_line(line)
        self.assertEqual(entity, self.pli)

    def test_single_task_source_with_service_item(self):
        line = self._line()
        self._source(line, self._task(service_item=self.svc_a))
        entity = QBOInvoiceSyncService._catalog_entity_for_line(line)
        self.assertEqual(entity, self.svc_a)

    def test_two_task_sources_same_service_item(self):
        line = self._line()
        self._source(line, self._task(service_item=self.svc_a, name='T1'))
        self._source(line, self._task(service_item=self.svc_a, name='T2'))
        entity = QBOInvoiceSyncService._catalog_entity_for_line(line)
        self.assertEqual(entity, self.svc_a)

    def test_two_task_sources_different_service_items(self):
        line = self._line()
        self._source(line, self._task(service_item=self.svc_a, name='T1'))
        self._source(line, self._task(service_item=self.svc_b, name='T2'))
        self.assertIsNone(QBOInvoiceSyncService._catalog_entity_for_line(line))

    def test_task_source_without_service_item(self):
        line = self._line()
        self._source(line, self._task(service_item=None))
        self.assertIsNone(QBOInvoiceSyncService._catalog_entity_for_line(line))

    def test_material_source_with_inventory_item(self):
        line = self._line()
        material = Material.objects.create(
            job=self.job, description='Ply', quantity=Decimal('1'),
            sell_price=Decimal('25.00'), inventory_item=self.pli,
            accounting_category=self.category,
        )
        self._source(line, material)
        entity = QBOInvoiceSyncService._catalog_entity_for_line(line)
        self.assertEqual(entity, self.pli)

    def test_provisional_material_source(self):
        line = self._line()
        material = Material.objects.create(
            job=self.job, description='Custom resin', quantity=Decimal('1'),
            sell_price=Decimal('40.00'), inventory_item=None,
            accounting_category=self.category,
        )
        self._source(line, material)
        self.assertIsNone(QBOInvoiceSyncService._catalog_entity_for_line(line))

    def test_adjustment_line_has_no_entity(self):
        line = self._line(adjustment_service=self.scheme)
        self.assertIsNone(QBOInvoiceSyncService._catalog_entity_for_line(line))

    def test_sourceless_hand_line_has_no_entity(self):
        line = self._line()
        self.assertIsNone(QBOInvoiceSyncService._catalog_entity_for_line(line))

    # --- _resolve_item_ref ---

    def test_resolves_entity_via_mint(self):
        line = self._line(inventory_item=self.pli)
        with patch('apps.qbo.services.QBOItemMintService.ensure_item',
                   return_value='901') as mock_mint:
            result = QBOInvoiceSyncService._resolve_item_ref(line, MagicMock())
        self.assertEqual(result, '901')
        self.assertEqual(mock_mint.call_args.args[0], self.pli)

    def test_mint_returning_empty_falls_back_to_category(self):
        line = self._line(inventory_item=self.pli)
        with patch('apps.qbo.services.QBOItemMintService.ensure_item',
                   return_value=''):
            result = QBOInvoiceSyncService._resolve_item_ref(line, MagicMock())
        self.assertEqual(result, '55')

    def test_no_entity_uses_category_fallback(self):
        line = self._line()
        result = QBOInvoiceSyncService._resolve_item_ref(line, MagicMock())
        self.assertEqual(result, '55')

    def test_unmapped_category_returns_none(self):
        bare_cat = AccountingCategory.objects.create(
            code='MISC', name='Misc', taxable=False, qbo_item_id='',
        )
        line = self._line(accounting_category=bare_cat)
        self.assertIsNone(
            QBOInvoiceSyncService._resolve_item_ref(line, MagicMock()))

    def test_null_category_with_no_entity_raises_clear_error(self):
        """A sourceless hand line (no catalog entity) with a null AC — the
        entity path can't resolve an ItemRef and there's no category to
        fall back to, so this must raise a clear ValidationError naming
        the line rather than an AttributeError on a None category."""
        from django.core.exceptions import ValidationError
        line = self._line(accounting_category=None)
        with self.assertRaises(ValidationError) as ctx:
            QBOInvoiceSyncService._resolve_item_ref(line, MagicMock())
        msg = str(ctx.exception)
        self.assertIn(str(line.line_number), msg)
        self.assertIn('fallback_accounting_category', msg)
