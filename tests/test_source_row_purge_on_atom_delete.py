"""No estimate/CO source row may outlive its atom.

Regression for the /api/estimates/ 500: shipment pickup completed a job,
JobService.release_loose_materials restocked a loose pending material to zero,
MaterialService.restock deleted the Material row — and the accepted estimate's
EstimateLineItemSource kept pointing at the deleted pk, crashing
EstimateLineItemSourceSerializer.get_description (unguarded resolve()).

The invariant lives on the atom itself: Material.delete() / Fee.delete() /
Task.delete() purge EstimateLineItemSource and ChangeOrderLineItemSource rows
referencing the atom, so every deletion path (restock-to-zero, sever, fee
delete, task delete, CO retirement) is covered. The serializer additionally
tolerates a pre-existing dangling row (renders null) instead of 500ing.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource,
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.inventory.models import InventoryItem, Material
from apps.inventory.services import MaterialService
from apps.jobs.models import Fee, Job, RateScheme, Task


class AtomDeletePurgeBase(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(
            name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED,
            job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001',
            status=Estimate.STATUS_ACCEPTED,
        )
        self.line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='claimed line',
            qty=Decimal('1'), price=Decimal('100.00'),
            accounting_category=self.cat,
        )

    def _claim(self, source_type, pk):
        return EstimateLineItemSource.objects.create(
            estimate_line_item=self.line,
            source_type=source_type,
            source_pk=pk,
        )


class MaterialDeletePurgesSourceRowsTest(AtomDeletePurgeBase):

    def _make_material(self):
        return MaterialService.create_on_job(
            job=self.job, description='acrylic', quantity=Decimal('1'),
            sell_price=Decimal('50.00'), accounting_category=self.cat,
            units='ea',
        )

    def test_direct_delete_purges_estimate_source_row(self):
        material = self._make_material()
        self._claim(EstimateLineItemSource.SOURCE_MATERIAL, material.pk)
        material.delete()
        self.assertFalse(self.line.sources.exists())

    def test_restock_to_zero_of_claimed_material_releases_instead(self):
        # The path that originally motivated the purge (release_loose_materials
        # → restock-to-zero → row deleted under a live claim) no longer deletes
        # at all: a claimed material is *released* and the claim keeps
        # resolving. The purge remains the backstop for unreferenced deletes
        # (test_direct_delete_purges_estimate_source_row above).
        material = self._make_material()
        row = self._claim(EstimateLineItemSource.SOURCE_MATERIAL, material.pk)
        MaterialService.restock(material, material.quantity)
        material.refresh_from_db()
        self.assertEqual(
            material.consumption_state, Material.CONSUMPTION_STATE_RELEASED)
        self.assertEqual(row.resolve().pk, material.pk)

    def test_delete_purges_co_source_row(self):
        material = self._make_material()
        co = ChangeOrder.objects.create(job=self.job, estimate=self.estimate)
        co_line = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            description='co material', qty=Decimal('1'), price=Decimal('50.00'),
            accounting_category=self.cat,
        )
        ChangeOrderLineItemSource.objects.create(
            change_order_line_item=co_line,
            source_type=ChangeOrderLineItemSource.SOURCE_MATERIAL,
            source_pk=material.pk,
        )
        material.delete()
        self.assertFalse(co_line.sources.exists())

    def test_delete_leaves_other_atoms_rows_alone(self):
        material = self._make_material()
        other = self._make_material()
        self._claim(EstimateLineItemSource.SOURCE_MATERIAL, material.pk)
        other_row = EstimateLineItemSource.objects.create(
            estimate_line_item=EstimateLineItem.objects.create(
                estimate=self.estimate, line_number=2, description='other',
                qty=Decimal('1'), price=Decimal('10.00'),
                accounting_category=self.cat,
            ),
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=other.pk,
        )
        material.delete()
        self.assertTrue(
            EstimateLineItemSource.objects.filter(pk=other_row.pk).exists())


class FeeDeletePurgesSourceRowsTest(AtomDeletePurgeBase):

    def test_delete_purges_estimate_source_row(self):
        fee = Fee.objects.create(
            job=self.job, description='fee', quantity=Decimal('1'),
            unit_rate=Decimal('25.00'), accounting_category=self.cat,
        )
        self._claim(EstimateLineItemSource.SOURCE_FEE, fee.pk)
        fee.delete()
        self.assertFalse(self.line.sources.exists())

    def test_delete_purges_invoice_source_row(self):
        # FeeService.delete has no invoiced-guard, so the invoice lens must be
        # purged too — same invariant, third table.
        from apps.invoicing.models import (
            Invoice, InvoiceLineItem, InvoiceLineItemSource,
        )
        fee = Fee.objects.create(
            job=self.job, description='fee', quantity=Decimal('1'),
            unit_rate=Decimal('25.00'), accounting_category=self.cat,
        )
        invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-2026-0001')
        inv_li = InvoiceLineItem.objects.create(
            invoice=invoice, description='fee', qty=Decimal('1'),
            price=Decimal('25.00'), accounting_category=self.cat,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=inv_li,
            source_type=InvoiceLineItemSource.SOURCE_FEE,
            source_pk=fee.pk,
        )
        fee.delete()
        self.assertFalse(inv_li.sources.exists())


class TaskDeletePurgesSourceRowsTest(AtomDeletePurgeBase):

    def test_delete_purges_estimate_source_row(self):
        scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat,
        )
        task = Task(
            job=self.job, name='Cutting',
            est_qty=Decimal('2'),
        )
        task.stamp_from_scheme(scheme)
        task.save()
        self._claim(EstimateLineItemSource.SOURCE_TASK, task.pk)
        task.delete()
        self.assertFalse(self.line.sources.exists())


class DanglingSourceRowSerializationTest(AtomDeletePurgeBase):
    """Pre-existing dangling rows (bad data) must render as null, not 500."""

    def test_serializer_tolerates_dangling_material_row(self):
        from apps.api.estimates.serializers import EstimateLineItemSourceSerializer
        dangling = self._claim(EstimateLineItemSource.SOURCE_MATERIAL, 999999)
        data = EstimateLineItemSourceSerializer(dangling).data
        self.assertIsNone(data['description'])
        self.assertIsNone(data['computed_amount'])

    def test_estimate_list_endpoint_returns_200_with_dangling_row(self):
        from rest_framework.test import APIClient
        from apps.core.models import User
        self._claim(EstimateLineItemSource.SOURCE_MATERIAL, 999999)
        client = APIClient()
        client.force_authenticate(
            user=User.objects.create_user(username='viewer', password='x'))
        resp = client.get(f'/api/estimates/?job={self.job.pk}')
        self.assertEqual(resp.status_code, 200)

    def test_invoice_source_serializer_tolerates_dangling_row(self):
        from apps.api.invoicing.serializers import InvoiceLineItemSourceSerializer
        from apps.invoicing.models import (
            Invoice, InvoiceLineItem, InvoiceLineItemSource,
        )
        invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-2026-0002')
        inv_li = InvoiceLineItem.objects.create(
            invoice=invoice, description='x', qty=Decimal('1'),
            price=Decimal('10.00'), accounting_category=self.cat,
        )
        dangling = InvoiceLineItemSource.objects.create(
            invoice_line_item=inv_li,
            source_type=InvoiceLineItemSource.SOURCE_MATERIAL,
            source_pk=999999,
        )
        data = InvoiceLineItemSourceSerializer(dangling).data
        self.assertIsNone(data['description'])
        self.assertIsNone(data['computed_amount'])
