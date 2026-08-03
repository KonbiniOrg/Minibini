"""Cancelling an invoice releases its atom claims.

A cancelled invoice is void: its atoms must be billable again on a fresh
invoice. The claim exclusions everywhere else already treat a cancelled
invoice's sources as dead (InvoiceClaimService._live_sources,
get_source_pool's claims query, depositCredits.js), but the rows themselves
survived cancellation, so a physical re-claim hit the
(source_type, source_pk) unique constraint.

Mirrors the estimate side, where revise_estimate re-points source rows so a
superseded estimate keeps its line items as a frozen snapshot but holds no
claims.
"""
from decimal import Decimal

from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.invoicing.models import Invoice, InvoiceLineItem, InvoiceLineItemSource
from apps.invoicing.services import InvoiceService, InvoiceWizardService
from apps.jobs.models import Job, RateScheme, Task


class CancelReleasesClaimsTest(TestCase):
    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.cat = AccountingCategory.objects.create(
            code='LAB', name='Labor', taxable=False)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        self.scheme = RateScheme.objects.create(
            name='Hourly', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('100'), unit_label='hour', accounting_category=self.cat)
        self.task = Task(
            job=self.job, name='Cut',
            status=Task.STATUS_COMPLETE, actual_qty=Decimal('2'))
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()

    def _open_invoice_claiming_task(self):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceWizardService.add_atoms_to_new_line_item(
            inv, [{'type': 'task', 'id': self.task.pk}])
        Invoice.objects.filter(pk=inv.pk).update(status=Invoice.STATUS_OPEN)
        return inv

    def test_cancel_deletes_the_invoices_source_rows(self):
        inv = self._open_invoice_claiming_task()
        self.assertTrue(InvoiceLineItemSource.objects.filter(
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk).exists())

        InvoiceService.cancel(inv.pk)

        self.assertFalse(InvoiceLineItemSource.objects.filter(
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk).exists())

    def test_cancelled_invoice_keeps_its_line_items_as_a_snapshot(self):
        # Same shape as a superseded estimate: the void document still shows
        # what it said (description/qty/price), it just holds no claims.
        inv = self._open_invoice_claiming_task()
        InvoiceService.cancel(inv.pk)
        lines = InvoiceLineItem.objects.filter(invoice=inv)
        self.assertEqual(lines.count(), 1)
        self.assertEqual(lines.first().sources.count(), 0)

    def test_atom_is_physically_reclaimable_after_cancel(self):
        # The bug: the pool showed the atom as available (the claim lookup
        # excludes cancelled invoices) but re-pulling it hit the DB unique
        # constraint on (source_type, source_pk) -> 409 atoms_already_claimed.
        inv = self._open_invoice_claiming_task()
        InvoiceService.cancel(inv.pk)

        fresh = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            fresh, [{'type': 'task', 'id': self.task.pk}])
        self.assertEqual(li.sources.count(), 1)

    def test_pool_and_physical_claim_agree_after_cancel(self):
        inv = self._open_invoice_claiming_task()
        InvoiceService.cancel(inv.pk)
        fresh = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        pool = InvoiceWizardService.get_source_pool(fresh)
        atom = next(a for g in pool['tasks'] for a in g['atoms']
                    if a['type'] == 'task' and a['id'] == self.task.pk)
        self.assertEqual(atom['state'], 'available')
        # ...and the pool's word is now good.
        InvoiceWizardService.add_atoms_to_new_line_item(
            fresh, [{'type': 'task', 'id': self.task.pk}])

    def test_live_invoice_claims_are_untouched(self):
        # Cancelling one invoice must not release another's claims.
        other_task = Task(
            job=self.job, name='Sand',
            status=Task.STATUS_COMPLETE, actual_qty=Decimal('1'))
        other_task.stamp_from_scheme(self.scheme)
        other_task.save()
        keeper = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceWizardService.add_atoms_to_new_line_item(
            keeper, [{'type': 'task', 'id': other_task.pk}])
        Invoice.objects.filter(pk=keeper.pk).update(status=Invoice.STATUS_OPEN)

        doomed = self._open_invoice_claiming_task()
        InvoiceService.cancel(doomed.pk)

        self.assertTrue(InvoiceLineItemSource.objects.filter(
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=other_task.pk).exists())


class DeadInvoiceStatusTest(CancelReleasesClaimsTest):
    """The release lives in Invoice.save(), not InvoiceService.cancel, so it
    covers every writer — and covers `superseded` ahead of the invoice-revision
    flow that will start writing it."""

    def test_release_fires_on_a_direct_save_not_just_the_service(self):
        inv = self._open_invoice_claiming_task()
        inv.status = Invoice.STATUS_CANCELLED
        inv.save()
        self.assertEqual(InvoiceLineItemSource.objects.filter(
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk).count(), 0)

    def test_superseding_an_invoice_releases_its_claims(self):
        # No writer sets superseded yet (there is no invoice-revision flow),
        # but the invariant "a dead document holds no claims" should not wait
        # for one. Whichever way a future revise works — moving rows like
        # revise_estimate, or re-claiming fresh — the superseded invoice must
        # end up holding none.
        inv = self._open_invoice_claiming_task()
        inv.status = Invoice.STATUS_SUPERSEDED
        inv.save()
        self.assertEqual(InvoiceLineItemSource.objects.filter(
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk).count(), 0)

    def test_atom_is_reclaimable_after_supersede(self):
        inv = self._open_invoice_claiming_task()
        inv.status = Invoice.STATUS_SUPERSEDED
        inv.save()
        fresh = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            fresh, [{'type': 'task', 'id': self.task.pk}])
        self.assertEqual(li.sources.count(), 1)

    def test_a_live_status_change_keeps_claims(self):
        # draft -> open -> paid must not release anything.
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceWizardService.add_atoms_to_new_line_item(
            inv, [{'type': 'task', 'id': self.task.pk}])
        inv.status = Invoice.STATUS_OPEN
        inv.save()
        inv.status = Invoice.STATUS_PAID
        inv.save()
        self.assertEqual(InvoiceLineItemSource.objects.filter(
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk).count(), 1)

    def test_superseded_claims_are_excluded_from_the_live_lookup(self):
        # Belt-and-braces for rows written before the release existed: the
        # claim reader must agree with the SPA's INVOICE_DEAD_STATUSES, which
        # has always counted superseded as dead.
        from apps.invoicing.claims import InvoiceClaimService
        inv = self._open_invoice_claiming_task()
        Invoice.objects.filter(pk=inv.pk).update(
            status=Invoice.STATUS_SUPERSEDED)   # bypasses save() on purpose
        self.assertFalse(InvoiceClaimService.is_invoiced(
            InvoiceLineItemSource.SOURCE_TASK, self.task.pk))


class CancelDepositDiscriminatorTest(TestCase):
    """A deposit CREDIT line is told apart from a deposit CHARGE line by the
    presence of a SOURCE_DEPOSIT row. Releasing claims on cancel removes that
    row, so the discriminator must not rest on it alone — otherwise a
    cancelled invoice's credit line starts reading as a deposit charge and the
    invoice reports is_deposit=true (a spurious DEPOSIT pill on the A/R list).
    """

    def setUp(self):
        Configuration.objects.create(key='invoice_number_sequence',
                                     value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')
        self.dep_cat = AccountingCategory.objects.create(
            code='DEP', name='Deposits', taxable=False, is_deposit=True)
        contact = Contact.objects.create(
            first_name='J', last_name='D', email='j@d.com', mobile_number='555')
        self.job = Job.objects.create(
            contact=contact, job_number='JOB-2026-0001',
            status=Job.STATUS_APPROVED)
        self.dep_invoice = Invoice.objects.create(
            job=self.job, status=Invoice.STATUS_OPEN, invoice_number='INV-1042')
        self.dep_line = InvoiceLineItem.objects.create(
            invoice=self.dep_invoice, description='Deposit',
            qty=Decimal('1'), price=Decimal('5000.00'),
            accounting_category=self.dep_cat)
        Invoice.objects.filter(pk=self.dep_invoice.pk).update(
            status=Invoice.STATUS_PAID)

    def test_credit_line_still_reads_as_a_deduction_after_cancel(self):
        draft = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        credit = InvoiceWizardService.add_atoms_to_new_line_item(
            draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        self.assertTrue(credit.is_deposit_deduction)
        self.assertFalse(credit.is_deposit_line)
        Invoice.objects.filter(pk=draft.pk).update(status=Invoice.STATUS_OPEN)

        InvoiceService.cancel(draft.pk)

        credit.refresh_from_db()
        # The claim row is gone, but a negative deposit-category line is still
        # a credit, not a charge.
        self.assertFalse(credit.is_deposit_line)

    def test_deposit_credit_is_physically_reclaimable_after_cancel(self):
        draft = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceWizardService.add_atoms_to_new_line_item(
            draft, [{'type': 'deposit', 'id': self.dep_line.pk}])
        Invoice.objects.filter(pk=draft.pk).update(status=Invoice.STATUS_OPEN)
        InvoiceService.cancel(draft.pk)

        fresh = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        li = InvoiceWizardService.add_atoms_to_new_line_item(
            fresh, [{'type': 'deposit', 'id': self.dep_line.pk}])
        self.assertTrue(li.is_deposit_deduction)

    def test_a_real_deposit_charge_still_reads_as_one(self):
        # Guard the other direction: the paid deposit charge line is
        # positive and unclaimed, and must keep reporting is_deposit_line.
        self.dep_line.refresh_from_db()
        self.assertTrue(self.dep_line.is_deposit_line)
