"""'Struck from agreement' badge derivation (RM decision 2026-07-20).

An accepted CO's remove stamps stored descope provenance
(Task.descoped_by / Material.descoped_by = the accepted ChangeOrder) on the
atom(s) it retires-or-leaves-alone, before retirement runs (CO amend-in-place
Task 3). The invoice wizard pool reads that stamp — never a derived query —
to badge the atom so the biller chooses consciously. A replace never stamps:
it moves the target's claim rows onto the replacement CO line without
touching the underlying atom at all (backing inheritance), so a replaced
atom is never flagged. No hold/status lifecycle changes — see
estimates-and-prices §14.11 decision record.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory
from apps.estimates.change_order_service import ChangeOrderService
from apps.estimates.co_acceptance import ChangeOrderAcceptanceService
from apps.estimates.models import (
    ChangeOrder, ChangeOrderLineItem, Estimate, EstimateLineItem,
    EstimateLineItemSource,
)
from apps.invoicing.services import InvoiceWizardService
from apps.jobs.models import Job, RateScheme, Task


class DescopedByPoolBadgeTests(TestCase):
    """Task-atom coverage: a remove line's stamp shows up in the pool."""

    def setUp(self):
        from apps.core.models import AppState, Configuration
        Configuration.objects.update_or_create(
            key='invoice_number_sequence',
            defaults={'value': 'INV-{year}-{counter:04d}'})
        AppState.objects.get_or_create(
            key='invoice_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='sb', code='SB')
        self.scheme = RateScheme.objects.create(
            name='S-sb', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.cat)
        contact = Contact.objects.create(
            first_name='S', last_name='B', email='sb@test.com')
        self.job = Job.objects.create(
            job_number='JOB-SB-1', contact=contact,
            status=Job.STATUS_IN_PROGRESS)
        self.task = Task(
            job=self.job, name='Struck work',
            status=Task.STATUS_COMPLETE, actual_qty=Decimal('2'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        self.other_task = Task(
            job=self.job, name='Untouched work',
            status=Task.STATUS_COMPLETE, actual_qty=Decimal('1'))
        self.other_task.stamp_from_scheme(self.scheme)
        self.other_task.save()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SB-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        self.line = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='Struck line',
            qty=Decimal('2'), price=Decimal('10'),
            accounting_category=self.cat)
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk)
        # ACCEPTED via raw ORM (mirrors the old fixture) — on_accept is run
        # explicitly per-test so tests can choose whether acceptance actually
        # happened.
        self.co = ChangeOrder.objects.create(
            job=self.job, estimate=self.est, change_order_number='CO-SB-1',
            status=ChangeOrder.STATUS_ACCEPTED)
        ChangeOrderLineItem.objects.create(
            change_order=self.co, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=self.line, line_number=1)

    def _pool_task_atoms(self):
        from apps.invoicing.models import Invoice
        invoice = Invoice.objects.create(job=self.job)
        pool = InvoiceWizardService.get_source_pool(invoice)
        return {a['id']: a for g in pool['tasks'] for a in g['atoms']
                if a['type'] == 'task'}

    def test_on_accept_stamps_descoped_by_on_target_atom(self):
        ChangeOrderAcceptanceService.on_accept(self.co)
        self.task.refresh_from_db()
        self.other_task.refresh_from_db()
        self.assertEqual(self.task.descoped_by_id, self.co.pk)
        self.assertIsNone(self.other_task.descoped_by_id)

    def test_pool_flags_struck_task(self):
        ChangeOrderAcceptanceService.on_accept(self.co)
        atoms = self._pool_task_atoms()
        self.assertEqual(
            atoms[self.task.pk]['descoped_by_co_number'], 'CO-SB-1')
        self.assertTrue(atoms[self.task.pk]['struck_from_agreement'])
        self.assertIsNone(atoms[self.other_task.pk]['descoped_by_co_number'])
        self.assertFalse(atoms[self.other_task.pk]['struck_from_agreement'])

    def test_pool_suppresses_struck_flag_on_cancelled_task_but_keeps_co_number(self):
        # test_remove_complete_task_is_left_alone_but_stamped in
        # test_change_order_acceptance.py covers COMPLETE (the retire-side
        # left-alone case); this covers the cancelled-suppression rule on
        # the badge itself, independent of retirement.
        ChangeOrderAcceptanceService.on_accept(self.co)
        Task.objects.filter(pk=self.task.pk).update(
            status=Task.STATUS_CANCELLED)
        atoms = self._pool_task_atoms()
        atom = atoms[self.task.pk]
        self.assertTrue(atom['task_cancelled'])
        self.assertEqual(atom['descoped_by_co_number'], 'CO-SB-1')
        self.assertFalse(atom['struck_from_agreement'])

    def test_unaccepted_co_never_stamps_and_pool_does_not_flag(self):
        # on_accept is only ever invoked from ChangeOrderService._handle_accepted
        # (i.e. a real acceptance transition) — a CO that never went through
        # that path never stamps anything, whatever its stored status says.
        atoms = self._pool_task_atoms()
        self.assertIsNone(atoms[self.task.pk]['descoped_by_co_number'])
        self.assertFalse(atoms[self.task.pk]['struck_from_agreement'])

    def test_replace_never_stamps_target(self):
        # Backing inheritance: replace moves the claim row, it never touches
        # descoped_by. A second, independent CO replaces (rather than
        # removes) the same estimate line — the atom must stay unflagged.
        replace_co = ChangeOrder.objects.create(
            job=self.job, estimate=self.est, change_order_number='CO-SB-2',
            status=ChangeOrder.STATUS_ACCEPTED)
        replace_li = ChangeOrderLineItem.objects.create(
            change_order=replace_co, action=ChangeOrderLineItem.ACTION_REPLACE,
            target_line_item=self.line, line_number=1,
            description='Struck line v2', qty=Decimal('2'), price=Decimal('12'),
            accounting_category=self.cat,
        )
        ChangeOrderAcceptanceService.on_accept(replace_co)

        self.task.refresh_from_db()
        self.assertIsNone(self.task.descoped_by_id)
        atoms = self._pool_task_atoms()
        self.assertIsNone(atoms[self.task.pk]['descoped_by_co_number'])
        self.assertFalse(atoms[self.task.pk]['struck_from_agreement'])
        # The claim moved onto the replace line, same as elsewhere.
        self.assertTrue(replace_li.sources.exists())


class DraftCOTargetsDoNotCountTests(TestCase):
    """The public-API counterpart of the old struck_atom_keys draft-exclusion
    test: ChangeOrderService.update_status only calls on_accept on a real
    ACCEPTED transition, so a CO that stays draft/open never stamps its
    targets, regardless of what a remove line on it points at."""

    def setUp(self):
        from apps.core.models import AppState, Configuration
        Configuration.objects.update_or_create(
            key='invoice_number_sequence',
            defaults={'value': 'INV-{year}-{counter:04d}'})
        AppState.objects.get_or_create(
            key='invoice_counter', defaults={'value': '0'})
        Configuration.objects.update_or_create(
            key='job_number_sequence', defaults={'value': 'JOB-{year}-{counter:04d}'})
        AppState.objects.get_or_create(key='job_counter', defaults={'value': '0'})
        self.cat = AccountingCategory.objects.create(name='draft', code='DFT')
        self.scheme = RateScheme.objects.create(
            name='S-draft', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('10'), unit_label='ea', accounting_category=self.cat)
        contact = Contact.objects.create(
            first_name='D', last_name='F', email='df@test.com')
        self.job = Job.objects.create(
            job_number='JOB-DFT-1', contact=contact,
            status=Job.STATUS_APPROVED, on_hold=True, hold_reason='CO editing')
        self.task = Task(
            job=self.job, name='Draft-targeted work',
            status=Task.STATUS_COMPLETE, actual_qty=Decimal('1'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()
        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-DFT-1', version=1,
            status=Estimate.STATUS_ACCEPTED)
        self.line = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, description='Draft-targeted line',
            qty=Decimal('1'), price=Decimal('10'), accounting_category=self.cat)
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk)
        self.co = ChangeOrderService.create(job_id=self.job.pk)
        ChangeOrderService.add_line_item(
            self.co.pk, action=ChangeOrderLineItem.ACTION_REMOVE,
            target_line_item=self.line.pk,
        )

    def test_draft_co_never_stamps_target(self):
        self.task.refresh_from_db()
        self.assertIsNone(self.task.descoped_by_id)

    def test_open_co_never_stamps_target(self):
        ChangeOrderService.mark_open(self.co.pk)
        self.task.refresh_from_db()
        self.assertIsNone(self.task.descoped_by_id)
