"""Per-unit-lines spec (2026-09-19 RM decision) — "un-stamp on removal".

Bundling a per-unit line stamps atoms up to whole-job totals (task
`est_qty`/`est_worker_time`, material `quantity`) and snapshots the raw
one-unit values on the claim row (`per_unit_qty`/`per_unit_worker_time`).
Removing a claim (`remove_atoms_from_line_item`, or whole-line deletion via
`LineItemService.delete_line_item_with_renumber`) used to delete the claim
row without touching the atom — the atom kept its multiplied total and the
snapshot was destroyed, so re-bundling one-unit would multiply AGAIN.

This module covers the fix: removal restores each atom field independently
from the claim snapshot, but ONLY when that field currently sits at its
exact expected stamped value (undrifted) — a drifted (hand-edited) field is
left untouched.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.core.services import LineItemService
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.models import ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem
from apps.estimates.services import ChangeOrderWizardService, EstimateService, EstimateWizardService
from apps.inventory.models import Material
from apps.invoicing.models import Invoice
from apps.invoicing.services import InvoiceService
from apps.jobs.models import Job, RateScheme, Task


class PerUnitUnstampTestBase(TestCase):
    def setUp(self):
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})
        Configuration.objects.update_or_create(
            key='estimate_number_sequence', defaults={'value': 'EST-{year}-{counter:04d}'})
        Configuration.objects.update_or_create(key='estimate_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(
            name='Labor', is_active=True, code='LAB-PUU')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@unstamp.com', mobile_number='555-9',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_DRAFT, job_number='JOB-2026-8001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-8001',
        )
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ELAPSED_TIME, rate=Decimal('60'),
            unit_label='hour', accounting_category=self.cat,
        )

    def _task(self, est_qty=None, est_worker_time=None, name='Setup'):
        t = Task(job=self.job, name=name)
        t.stamp_from_scheme(self.scheme)
        t.est_qty = est_qty
        t.est_worker_time = est_worker_time
        t.save()
        return t

    def _material(self, quantity):
        return Material.objects.create(
            job=self.job, description='Steel', quantity=quantity,
            sell_price=Decimal('2.50'), accounting_category=self.cat,
        )

    def _bundle(self, atoms, qty=Decimal('10'), description='Bundle'):
        overrides = {
            'description': description, 'qty': qty, 'units': 'each', 'price': Decimal('99.00'),
        }
        return EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, atoms, overrides=overrides, per_unit=True)


# ---------------------------------------------------------------------------
# 1/2/3/4/9 — remove_atoms_from_line_item restore behavior.
# ---------------------------------------------------------------------------

class RemoveAtomsRestoresPerUnitClaimTest(PerUnitUnstampTestBase):
    def test_task_qty_restored_to_one_unit_on_removal(self):
        task = self._task(Decimal('2'), None)
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('20.00'))
        source_id = li.sources.get(source_type='task', source_pk=task.pk).source_id

        result = EstimateWizardService.remove_atoms_from_line_item(li, [source_id])

        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('2'))
        self.assertTrue(result['line_item_deleted'])
        self.assertFalse(EstimateLineItem.objects.filter(pk=li.pk).exists())

    def test_task_worker_time_restored_to_one_unit_on_removal(self):
        task = self._task(Decimal('1'), timedelta(minutes=45))
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        task.refresh_from_db()
        self.assertEqual(task.est_worker_time, timedelta(hours=7, minutes=30))
        source_id = li.sources.get(source_type='task', source_pk=task.pk).source_id

        EstimateWizardService.remove_atoms_from_line_item(li, [source_id])

        task.refresh_from_db()
        self.assertEqual(task.est_worker_time, timedelta(minutes=45))

    def test_drifted_qty_untouched_but_undrifted_worker_time_restored(self):
        # Per-field independence: a task whose qty was hand-edited since
        # stamping keeps that hand-edit; its untouched worker_time IS
        # restored on removal.
        task = self._task(Decimal('2'), timedelta(minutes=45))
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('20.00'))
        self.assertEqual(task.est_worker_time, timedelta(hours=7, minutes=30))

        # Hand-edit est_qty after stamping — drift.
        task.est_qty = Decimal('25')
        task.save()

        source_id = task_src_id = None
        source_row = li.sources.get(source_type='task', source_pk=task.pk)
        EstimateWizardService.remove_atoms_from_line_item(li, [source_row.source_id])

        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('25'))  # untouched — drifted
        self.assertEqual(task.est_worker_time, timedelta(minutes=45))  # restored

    def test_material_quantity_restored_to_one_unit_on_removal(self):
        material = self._material(Decimal('4'))
        li = self._bundle([{'type': 'material', 'id': material.pk}], qty=Decimal('10'))
        material.refresh_from_db()
        self.assertEqual(material.quantity, Decimal('40.00'))
        source_id = li.sources.get(source_type='material', source_pk=material.pk).source_id

        EstimateWizardService.remove_atoms_from_line_item(li, [source_id])

        material.refresh_from_db()
        self.assertEqual(material.quantity, Decimal('4'))

    def test_snapshot_null_worker_time_no_write(self):
        # A task with no est_worker_time at bundle time snapshots
        # per_unit_worker_time=None — removal must not touch
        # est_worker_time at all (it stays None, no spurious write/attempt).
        task = self._task(Decimal('1'), None)
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('5'))
        task.refresh_from_db()
        self.assertIsNone(task.est_worker_time)
        source_id = li.sources.get(source_type='task', source_pk=task.pk).source_id

        EstimateWizardService.remove_atoms_from_line_item(li, [source_id])

        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('1'))
        self.assertIsNone(task.est_worker_time)

    def test_partial_removal_resyncs_line_without_removed_atom(self):
        # Removing one of two claims: the removed atom restores, the line
        # survives (resynced), the remaining atom is untouched.
        task = self._task(Decimal('2'), None)
        task2 = self._task(Decimal('3'), None, name='Second')
        li = self._bundle(
            [{'type': 'task', 'id': task.pk}, {'type': 'task', 'id': task2.pk}],
            qty=Decimal('10'))
        task.refresh_from_db()
        task2.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('20.00'))
        self.assertEqual(task2.est_qty, Decimal('30.00'))
        source_id = li.sources.get(source_type='task', source_pk=task.pk).source_id

        result = EstimateWizardService.remove_atoms_from_line_item(li, [source_id])

        self.assertFalse(result['line_item_deleted'])
        task.refresh_from_db()
        task2.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('2'))  # restored
        self.assertEqual(task2.est_qty, Decimal('30.00'))  # untouched, still claimed


# ---------------------------------------------------------------------------
# 6/7 — whole-line deletion pre-pass (delete_line_item_with_renumber).
# ---------------------------------------------------------------------------

class DeleteLineItemRestoresPerUnitClaimsTest(PerUnitUnstampTestBase):
    def test_direct_delete_of_per_unit_line_restores_all_claims(self):
        task = self._task(Decimal('2'), timedelta(minutes=45))
        material = self._material(Decimal('4'))
        li = self._bundle(
            [{'type': 'task', 'id': task.pk}, {'type': 'material', 'id': material.pk}],
            qty=Decimal('10'))
        task.refresh_from_db()
        material.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('20.00'))
        self.assertEqual(material.quantity, Decimal('40.00'))

        EstimateService.delete_line_item(li.pk)

        task.refresh_from_db()
        material.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('2'))
        self.assertEqual(task.est_worker_time, timedelta(minutes=45))
        self.assertEqual(material.quantity, Decimal('4'))
        self.assertFalse(EstimateLineItem.objects.filter(pk=li.pk).exists())

    def test_direct_delete_leaves_drifted_field_untouched(self):
        task = self._task(Decimal('2'), None)
        li = self._bundle([{'type': 'task', 'id': task.pk}], qty=Decimal('10'))
        task.refresh_from_db()
        task.est_qty = Decimal('99')
        task.save()

        EstimateService.delete_line_item(li.pk)

        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('99'))

    def test_non_per_unit_line_removal_leaves_atoms_untouched(self):
        # Regression: a plain (per_unit=False) bundle's atoms are never
        # touched by remove_atoms_from_line_item.
        task = self._task(Decimal('2'), None)
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': task.pk}])
        self.assertFalse(li.per_unit)
        source_id = li.sources.get(source_type='task', source_pk=task.pk).source_id

        EstimateWizardService.remove_atoms_from_line_item(li, [source_id])

        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('2'))

    def test_non_per_unit_line_direct_delete_leaves_atoms_untouched(self):
        task = self._task(Decimal('2'), None)
        li = EstimateWizardService.add_atoms_to_new_line_item(
            self.estimate, [{'type': 'task', 'id': task.pk}])
        self.assertFalse(li.per_unit)

        EstimateService.delete_line_item(li.pk)

        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('2'))

    def test_invoice_line_item_delete_unaffected_by_getattr_guard(self):
        # InvoiceLineItem carries no `per_unit` attribute at all — the
        # getattr(line_item, 'per_unit', False) guard in
        # delete_line_item_with_renumber must short-circuit before ever
        # touching `.sources`, so a plain invoice line deletes exactly as
        # before (no AttributeError, no restore attempted).
        Configuration.objects.create(key='invoice_number_sequence', value='INV-{counter:04d}')
        AppState.objects.update_or_create(key='invoice_counter', defaults={'value': '0'})
        job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-8099')
        invoice = Invoice.objects.create(job=job, status=Invoice.STATUS_DRAFT)
        li = InvoiceService.add_line_item(
            invoice.pk, description='Freeform', qty=Decimal('1'), units='each',
            price=Decimal('10.00'), accounting_category=self.cat.id,
        )
        self.assertFalse(hasattr(li, 'per_unit'))

        LineItemService.delete_line_item_with_renumber(li)

        from apps.invoicing.models import InvoiceLineItem
        self.assertFalse(InvoiceLineItem.objects.filter(pk=li.pk).exists())


# ---------------------------------------------------------------------------
# 8 — CO lens: the base-class path applies unchanged to ChangeOrderLineItem.
# ---------------------------------------------------------------------------

class ChangeOrderRemoveAtomsRestoresPerUnitClaimTest(PerUnitUnstampTestBase):
    def setUp(self):
        super().setUp()
        # A fresh approved job + accepted estimate (status transitions are
        # validated on save() — flip directly after building draft, same
        # idiom as tests/test_per_unit_drift.py's COReplaceQtyChangeBase).
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-8010',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, status=Estimate.STATUS_DRAFT, estimate_number='EST-2026-8010',
        )
        Estimate.objects.filter(pk=self.estimate.pk).update(status=Estimate.STATUS_ACCEPTED)
        self.estimate.refresh_from_db()
        self.job.on_hold = True
        self.job.hold_reason = 'CO editing'
        self.job.save()
        self.co = ChangeOrderService.create(job_id=self.job.pk)

    def test_co_add_line_remove_atoms_restores_task(self):
        task = self._task(Decimal('2'), None)
        overrides = {
            'description': 'CO bundle', 'qty': Decimal('10'),
            'units': 'each', 'price': Decimal('55.00'),
        }
        li = ChangeOrderWizardService.add_atoms_to_new_line_item(
            self.co, [{'type': 'task', 'id': task.pk}], overrides=overrides, per_unit=True)
        self.assertEqual(li.action, ChangeOrderLineItem.ACTION_ADD)
        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('20.00'))
        source_id = li.sources.get(source_type='task', source_pk=task.pk).source_id

        result = ChangeOrderWizardService.remove_atoms_from_line_item(li, [source_id])

        task.refresh_from_db()
        self.assertEqual(task.est_qty, Decimal('2'))
        self.assertTrue(result['line_item_deleted'])
