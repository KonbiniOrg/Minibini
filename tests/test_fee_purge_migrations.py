"""estimates/0045 + invoicing/0024 fee-purge data migrations.

The one data transform between the fee-removal branch and the dev DB's
legacy rows: prove each migration's drop_fee_sources() deletes exactly the
source_type='fee' rows in its app's source tables and spares every other
claim. Fresh test DBs migrate an empty schema, so nothing else exercises
the purge against populated tables. Direct-call precedent for invoking a
migration's function against the live apps registry:
tests/test_singular_units_migration.py.

The 'fee' literal is planted directly — choices are not enforced on
.objects.create(), which is exactly how the legacy rows exist in the dev
DB (written before the choice narrowing).
"""
import importlib
from decimal import Decimal

from django.apps import apps as django_apps
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource,
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.invoicing.models import (
    Invoice, InvoiceLineItem, InvoiceLineItemSource,
)
from apps.jobs.models import Job

# Module names start with digits, so importlib handles the dotted strings.
_est_migration = importlib.import_module(
    'apps.estimates.migrations.0045_alter_changeorderlineitem_is_material_and_more')
_inv_migration = importlib.import_module(
    'apps.invoicing.migrations.0024_alter_invoicelineitemsource_source_type')


class FeePurgeMigrationTest(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(
            name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0')
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001')
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001',
            status=Estimate.STATUS_ACCEPTED)
        self.line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='claimed line',
            qty=Decimal('1'), price=Decimal('100.00'),
            accounting_category=self.cat)

    def test_purges_fee_rows_and_spares_other_claims(self):
        # Estimate lens: one legacy fee claim + one surviving material claim.
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line, source_type='fee', source_pk=101)
        est_keep = EstimateLineItemSource.objects.create(
            estimate_line_item=self.line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL, source_pk=201)

        # CO lens: same pair on a CO add line.
        co = ChangeOrder.objects.create(
            job=self.job, estimate=self.estimate,
            change_order_number='CO-2026-0001')
        co_line = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            line_number=1, description='co line', qty=Decimal('1'),
            price=Decimal('50.00'), accounting_category=self.cat)
        ChangeOrderLineItemSource.objects.create(
            change_order_line_item=co_line, source_type='fee', source_pk=102)
        co_keep = ChangeOrderLineItemSource.objects.create(
            change_order_line_item=co_line,
            source_type=ChangeOrderLineItemSource.SOURCE_TASK, source_pk=202)

        # Invoice lens: same pair on an invoice line.
        invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-2026-0001')
        inv_line = InvoiceLineItem.objects.create(
            invoice=invoice, description='inv line', qty=Decimal('1'),
            price=Decimal('25.00'), accounting_category=self.cat)
        InvoiceLineItemSource.objects.create(
            invoice_line_item=inv_line, source_type='fee', source_pk=103)
        inv_keep = InvoiceLineItemSource.objects.create(
            invoice_line_item=inv_line,
            source_type=InvoiceLineItemSource.SOURCE_TASK, source_pk=203)

        _est_migration.drop_fee_sources(django_apps, None)
        _inv_migration.drop_fee_sources(django_apps, None)

        self.assertEqual(
            EstimateLineItemSource.objects.filter(source_type='fee').count(), 0)
        self.assertEqual(
            ChangeOrderLineItemSource.objects.filter(source_type='fee').count(), 0)
        self.assertEqual(
            InvoiceLineItemSource.objects.filter(source_type='fee').count(), 0)

        # Every non-fee claim survives untouched.
        self.assertTrue(
            EstimateLineItemSource.objects.filter(pk=est_keep.pk).exists())
        self.assertTrue(
            ChangeOrderLineItemSource.objects.filter(pk=co_keep.pk).exists())
        self.assertTrue(
            InvoiceLineItemSource.objects.filter(pk=inv_keep.pk).exists())
