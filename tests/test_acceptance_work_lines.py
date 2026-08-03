"""Acceptance crystallizes bare freeform_kind='work' hand-lines into flat
Tasks (task-owned-money Phase 2, Task 3) — the explicit third branch
alongside 'material' (test_acceptance_provisional_material.py) and
'fee'/NULL (test_acceptance_fees.py). Mirrors those modules for the estimate
side, and test_change_order_acceptance.py's ChangeOrderAcceptanceBase
scaffolding for the CO side.

A flat work Task is entered-qty, has no RateScheme provenance
(source_scheme=None) and no ServiceItem (service_item_id=None) — the
discriminator CO acceptance's _retire uses to tell it apart from a
service-backed Task (which cancels, preserving bleps): an un-invoiced flat
work Task is deleted outright on CO remove/replace, same as a Fee, subject
to the same bleps/in-progress/complete guards TaskService.delete_task
enforces.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration, User
from apps.deliverables.models import Deliverable
from apps.estimates.acceptance import EstimateAcceptanceService
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.co_acceptance import ChangeOrderAcceptanceService
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, ChangeOrderLineItemSource,
    Estimate, EstimateLineItem, EstimateLineItemSource,
)
from apps.inventory.models import Material
from apps.jobs.models import Blep, Fee, Job, RateScheme, Task


# ---------------------------------------------------------------------------
# Estimate acceptance
# ---------------------------------------------------------------------------

class EstimateAcceptanceWorkLineTest(TestCase):
    """Bare freeform_kind='work' hand-lines crystallize into flat Tasks at
    estimate acceptance, source-linked with source_type='task', counted
    under work_tasks_created; fee/material lines are unaffected."""

    def setUp(self):
        Configuration.objects.create(key='estimate_number_sequence', value='EST-{year}-{counter:04d}')
        Configuration.objects.create(key='estimate_counter', value='0')
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001', status=Estimate.STATUS_OPEN,
        )

    def _work_line(self, **kw):
        defaults = dict(
            estimate=self.estimate, line_number=1, description='Custom fitting',
            qty=Decimal('3'), price=Decimal('50.00'), units='ea',
            accounting_category=self.cat, freeform_kind=EstimateLineItem.KIND_WORK,
        )
        defaults.update(kw)
        return EstimateLineItem.objects.create(**defaults)

    def test_work_line_becomes_a_flat_task(self):
        line = self._work_line()

        result = EstimateAcceptanceService.on_accept(self.estimate)

        task = Task.objects.get(job=self.job, name='Custom fitting')
        self.assertEqual(task.description, 'Custom fitting')
        self.assertEqual(task.qty_source, Task.QTY_ENTERED)
        self.assertEqual(task.est_qty, Decimal('3'))
        self.assertEqual(task.rate, Decimal('50.00'))
        self.assertEqual(task.unit_label, 'ea')
        self.assertEqual(task.accounting_category, self.cat)
        self.assertIsNone(task.source_scheme)          # no RateScheme provenance
        self.assertIsNone(task.service_item_id)         # not catalog/service-backed
        self.assertEqual(result['work_tasks_created'], 1)
        self.assertEqual(result['fees_created'], 0)
        self.assertEqual(result['materials_created'], 0)
        # It did NOT become a Fee.
        self.assertFalse(Fee.objects.filter(job=self.job).exists())
        # Source-linked as a Task.
        src = EstimateLineItemSource.objects.get(estimate_line_item=line)
        self.assertEqual(src.source_type, EstimateLineItemSource.SOURCE_TASK)
        self.assertEqual(src.source_pk, task.pk)

    def test_work_task_falls_back_to_description_for_name_when_blank(self):
        self._work_line(description='')
        EstimateAcceptanceService.on_accept(self.estimate)
        self.assertTrue(Task.objects.filter(job=self.job, name='Work').exists())

    def test_work_task_appears_in_job_task_list(self):
        self._work_line()
        EstimateAcceptanceService.on_accept(self.estimate)
        names = list(Task.objects.filter(job=self.job).values_list('name', flat=True))
        self.assertIn('Custom fitting', names)

    def test_negative_price_work_line_raises_validation_error(self):
        self._work_line(price=Decimal('-10.00'))
        with self.assertRaises(ValidationError):
            EstimateAcceptanceService.on_accept(self.estimate)
        # No Task was minted from the rejected line.
        self.assertFalse(Task.objects.filter(job=self.job).exists())

    def test_fee_and_material_lines_unaffected_by_work_branch(self):
        Configuration.objects.create(key='default_material_markup_percent', value='25')
        EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=2, description='Rush handling',
            qty=Decimal('1'), price=Decimal('25.00'), accounting_category=self.cat,
        )
        EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=3, description='Raw stock',
            qty=Decimal('2'), price=Decimal('40.00'), units='ft',
            accounting_category=self.cat, freeform_kind=EstimateLineItem.KIND_MATERIAL,
        )

        result = EstimateAcceptanceService.on_accept(self.estimate)

        self.assertEqual(result['fees_created'], 1)
        self.assertEqual(result['materials_created'], 1)
        self.assertEqual(result['work_tasks_created'], 0)
        self.assertTrue(Fee.objects.filter(job=self.job, description='Rush handling').exists())
        self.assertTrue(Material.objects.filter(job=self.job, description='Raw stock').exists())


# ---------------------------------------------------------------------------
# Change order acceptance
# ---------------------------------------------------------------------------

class ChangeOrderWorkLineTestBase(TestCase):
    """Shared scaffolding: an approved job with an accepted estimate, put on
    hold so a CO can be authored, sent, and accepted. Mirrors
    ChangeOrderAcceptanceBase in tests/test_change_order_acceptance.py."""

    def setUp(self):
        Configuration.objects.update_or_create(key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.update_or_create(key='job_counter', defaults={'value': '0'})

        self.cat = AccountingCategory.objects.create(name='Labor', is_active=True, code='LAB')
        self.contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555-0',
        )
        self.job = Job.objects.create(
            contact=self.contact, status=Job.STATUS_APPROVED, job_number='JOB-2026-0001',
        )
        self.estimate = Estimate.objects.create(
            job=self.job, estimate_number='EST-2026-0001',
            status=Estimate.STATUS_ACCEPTED,
        )
        Deliverable.objects.create(
            job=self.job, description='Widget', qty_ordered=Decimal('1'),
            units='ea', sort_order=10,
        )

    def _make_co(self):
        self.job.refresh_from_db()
        self.job.on_hold = True
        self.job.hold_reason = 'CO editing'
        self.job.save()
        return ChangeOrderService.create(job_id=self.job.pk)

    def _accept(self, co):
        ChangeOrderService.mark_open(co.pk)
        co = ChangeOrderService.update_status(co.pk, ChangeOrder.STATUS_ACCEPTED)
        self.job.refresh_from_db()
        return co

    def _work_task_backed_line(self, line_number=1, est_qty=Decimal('3'), price=Decimal('50.00')):
        """An estimate line already crystallized (as estimate acceptance
        would) into a flat work Task — the CO's starting state."""
        task = Task(
            job=self.job, name='Custom fitting', description='Custom fitting',
            qty_source=Task.QTY_ENTERED, est_qty=est_qty, rate=price,
            unit_label='ea', accounting_category=self.cat, source_scheme=None,
        )
        task.save()
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=line_number, description='Custom fitting',
            qty=est_qty, price=price, units='ea', accounting_category=self.cat,
            freeform_kind=EstimateLineItem.KIND_WORK,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        return line, task


class COAddWorkLineTest(ChangeOrderWorkLineTestBase):
    def test_bare_add_work_line_crystallizes_flat_task(self):
        co = self._make_co()
        li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra fitting', qty=Decimal('2'), price=Decimal('60.00'),
            units='ea', accounting_category=self.cat,
            freeform_kind=ChangeOrderLineItem.KIND_WORK,
        )
        self._accept(co)

        task = Task.objects.get(job=self.job, name='Extra fitting')
        self.assertEqual(task.est_qty, Decimal('2'))
        self.assertEqual(task.rate, Decimal('60.00'))
        self.assertEqual(task.unit_label, 'ea')
        self.assertEqual(task.accounting_category, self.cat)
        self.assertIsNone(task.source_scheme)
        self.assertIsNone(task.service_item_id)
        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_TASK)
        self.assertEqual(src.source_pk, task.pk)

    def test_negative_price_work_add_line_raises(self):
        co = self._make_co()
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Bad line', qty=Decimal('1'), price=Decimal('-5.00'),
            accounting_category=self.cat, freeform_kind=ChangeOrderLineItem.KIND_WORK,
        )
        with self.assertRaises(ValidationError):
            self._accept(co)
        self.assertFalse(Task.objects.filter(job=self.job, description='Bad line').exists())

    def test_on_accept_counts_work_tasks_created(self):
        # on_accept is driven by the status-transition signal in production
        # but is callable directly in tests (mirrors
        # OnAcceptCrystallizesServiceTest in test_deferred_service_crystallization.py) —
        # it does not itself require any particular co.status.
        co = self._make_co()
        ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_ADD,
            description='Extra fitting', qty=Decimal('2'), price=Decimal('60.00'),
            units='ea', accounting_category=self.cat,
            freeform_kind=ChangeOrderLineItem.KIND_WORK,
        )
        self.job.on_hold = False
        self.job.save()

        result = ChangeOrderAcceptanceService.on_accept(co)
        self.assertEqual(result['work_tasks_created'], 1)


class COReplaceWorkLineTest(ChangeOrderWorkLineTestBase):
    def test_replace_work_line_retires_old_and_creates_new(self):
        line, old_task = self._work_task_backed_line()
        co = self._make_co()
        li = ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_REPLACE, target_line_item=line.pk,
            description='Custom fitting (bigger)', qty=Decimal('5'), price=Decimal('50.00'),
            units='ea',
        )
        self._accept(co)

        # Old task deleted outright (not cancelled) — un-invoiced flat work task.
        self.assertFalse(Task.objects.filter(pk=old_task.pk).exists())
        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_TASK)
        new_task = Task.objects.get(pk=src.source_pk)
        self.assertEqual(new_task.est_qty, Decimal('5'))
        self.assertEqual(new_task.description, 'Custom fitting (bigger)')
        self.assertIsNone(new_task.service_item_id)

    def test_replace_of_document_only_target_with_work_descriptor_crystallizes(self):
        """A REPLACE line with an explicit freeform_kind='work' descriptor
        must crystallize even when its target has no current atom to mirror
        (e.g. an adjustment line, which never had a source row) — the
        has_descriptor gate in on_accept must treat 'work' like 'material',
        not like an unmarked bare line (which correctly stays document-only
        here since there's nothing to replace)."""
        adj_scheme = RateScheme.objects.create(
            name='Rush 10%', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10'), unit_label='none', accounting_category=self.cat,
        )
        line = EstimateLineItem.objects.create(
            estimate=self.estimate, line_number=1, description='Rush surcharge',
            qty=Decimal('1'), price=Decimal('50.00'), accounting_category=self.cat,
            adjustment_service=adj_scheme,
        )
        co = self._make_co()
        li = ChangeOrderLineItem.objects.create(
            change_order=co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=line, description='Fabricated part',
            qty=Decimal('1'), price=Decimal('75.00'), units='ea',
            accounting_category=self.cat, freeform_kind=ChangeOrderLineItem.KIND_WORK,
        )
        self._accept(co)

        src = ChangeOrderLineItemSource.objects.get(change_order_line_item=li)
        self.assertEqual(src.source_type, ChangeOrderLineItemSource.SOURCE_TASK)
        task = Task.objects.get(pk=src.source_pk)
        self.assertEqual(task.rate, Decimal('75.00'))
        self.assertIsNone(task.service_item_id)


class CORemoveWorkLineTest(ChangeOrderWorkLineTestBase):
    def _remove_line(self, co, target):
        return ChangeOrderService.add_line_item(
            co.pk, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=target.pk,
        )

    def test_remove_work_line_deletes_task(self):
        line, task = self._work_task_backed_line()
        co = self._make_co()
        self._remove_line(co, line)
        self._accept(co)

        self.assertFalse(Task.objects.filter(pk=task.pk).exists())
        self.assertFalse(line.sources.exists())

    def test_remove_work_task_with_bleps_refuses(self):
        line, task = self._work_task_backed_line()
        worker = User.objects.create(username='worker')
        now = timezone.now()
        Blep.objects.create(user=worker, task=task, start_time=now, end_time=now)
        co = self._make_co()
        self._remove_line(co, line)

        with self.assertRaises(ValidationError):
            self._accept(co)

        # Refused: the task and its blep both survive.
        self.assertTrue(Task.objects.filter(pk=task.pk).exists())
        self.assertTrue(Blep.objects.filter(task=task).exists())

    def test_remove_in_progress_work_task_refuses(self):
        line, task = self._work_task_backed_line()
        Task.objects.filter(pk=task.pk).update(status=Task.STATUS_IN_PROGRESS)
        co = self._make_co()
        self._remove_line(co, line)

        with self.assertRaises(ValidationError):
            self._accept(co)

        self.assertTrue(Task.objects.filter(pk=task.pk).exists())

    def test_remove_invoiced_work_task_is_left_alone(self):
        from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
        line, task = self._work_task_backed_line()
        invoice = Invoice.objects.create(
            job=self.job, invoice_number='INV-2026-0001')
        inv_li = InvoiceLineItem.objects.create(
            invoice=invoice, description='Custom fitting',
            qty=Decimal('3'), price=Decimal('50.00'),
            accounting_category=self.cat,
        )
        InvoiceLineItemSource.objects.create(
            invoice_line_item=inv_li,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=task.pk,
        )
        co = self._make_co()
        self._remove_line(co, line)
        self._accept(co)

        self.assertTrue(Task.objects.filter(pk=task.pk).exists())
