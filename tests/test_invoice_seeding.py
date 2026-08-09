"""Tests for InvoiceService agreement seeding/remaining/restore/remove and
the one-live-invoice-per-agreement-line invariant.

Fixture: an accepted estimate with three agreement lines —
  - backed_line: an atom-backed line (EstimateLineItemSource rows for a
    complete Task and an unconsumed Material)
  - hand_line: a bare hand line with no sources
  - adj_line: a percentage-adjustment line

Covers seed_from_agreement, remaining_agreement_lines, restore_agreement_line,
remove_line, and the select_for_update re-check that keeps an agreement line
on at most one live (non-cancelled) invoice.
"""
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.contacts.models import Contact
from apps.core.models import AccountingCategory, AppState, Configuration
from apps.estimates.models import Estimate, EstimateLineItem, EstimateLineItemSource
from apps.inventory.models import Material
from apps.invoicing.models import Invoice, InvoiceLineItem
from apps.invoicing.services import InvoiceService
from apps.jobs.models import Job, RateScheme, Task


class InvoiceSeedingTestCase(TestCase):
    def setUp(self):
        Configuration.objects.create(
            key='invoice_number_sequence', value='INV-{year}-{counter:04d}')
        AppState.objects.create(key='invoice_counter', value='0')

        self.cat = AccountingCategory.objects.create(
            code='LAB-SEED', name='Labor-Seed', taxable=False)
        self.cat2 = AccountingCategory.objects.create(
            code='MISC-SEED', name='Misc-Seed', taxable=False)
        contact = Contact.objects.create(
            first_name='Seed', last_name='Test', email='seed@test.com',
            mobile_number='555-0100',
        )
        self.job = Job.objects.create(
            contact=contact, status=Job.STATUS_APPROVED,
            job_number='JOB-SEED-0001',
        )

        self.est = Estimate.objects.create(
            job=self.job, estimate_number='EST-SEED-1', version=1,
            status=Estimate.STATUS_ACCEPTED,
        )

        # -- backed_line: atom-backed (task complete + unconsumed material)
        self.scheme = RateScheme.objects.create(
            name='Hourly-Seed', algorithm=RateScheme.ENTERED_QTY,
            rate=Decimal('100'), unit_label='hour',
            accounting_category=self.cat,
        )
        self.task = Task(
            job=self.job, name='Cut', status=Task.STATUS_COMPLETE,
            actual_qty=Decimal('2'),
        )
        self.task.stamp_from_scheme(self.scheme)
        self.task.save()

        self.material = Material.objects.create(
            job=self.job, description='Steel bar', quantity=Decimal('3'),
            sell_price=Decimal('5.00'), accounting_category=self.cat,
        )
        self.assertEqual(
            self.material.consumption_state,
            Material.CONSUMPTION_STATE_PENDING,
        )

        self.backed_line = EstimateLineItem.objects.create(
            estimate=self.est, line_number=1, qty=Decimal('2'),
            units='hour', description='Cut steel', price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.backed_line,
            source_type=EstimateLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.backed_line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=self.material.pk,
        )

        # -- hand_line: bare, no sources. A DIFFERENT accounting category
        # (cat2) from backed_line's (cat) so the adjustment's target-category
        # subset actually excludes something — the fixture would not catch
        # an untargeted-vs-targeted computation bug if every sibling shared
        # one category.
        self.hand_line = EstimateLineItem.objects.create(
            estimate=self.est, line_number=2, qty=Decimal('1'),
            units='ea', description='Misc hand line', price=Decimal('25.00'),
            accounting_category=self.cat2,
        )

        # -- adj_line: percentage adjustment, targeted at ONLY backed_line's
        # category (cat) — hand_line's 25.00 (cat2) must NOT count toward
        # the computed amount. Targeted: 200.00 (backed_line) * 10% = 20.00.
        # Untargeted (the bug): (200.00 + 25.00) * 10% = 22.50.
        self.rush_svc = RateScheme.objects.create(
            name='Rush-Seed', algorithm=RateScheme.PERCENTAGE,
            rate=Decimal('10.00'), unit_label='%',
            accounting_category=self.cat,
        )
        self.adj_line = EstimateLineItem.objects.create(
            estimate=self.est, line_number=3, qty=Decimal('1'),
            units='%', description='Rush 10%', price=Decimal('20.00'),
            adjustment_service=self.rush_svc,
            adjustment_percent=self.rush_svc.rate,
        )
        self.adj_line.adjustment_target_categories.set([self.cat])

    def _seeded(self):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceService.seed_from_agreement(inv)
        return inv

    def _send(self, invoice):
        """Flip a draft invoice to open via a direct status update — the
        one-draft-per-job DB constraint means a second draft cannot exist
        until the first is no longer draft."""
        Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.STATUS_OPEN)
        invoice.refresh_from_db()

    # ── seed_from_agreement ─────────────────────────────────────────────

    def test_seed_creates_one_line_per_remaining_agreement_line(self):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        n = InvoiceService.seed_from_agreement(inv)
        self.assertEqual(n, 3)
        li = inv.invoicelineitem_set.get(agreement_estimate_line=self.backed_line)
        self.assertEqual(li.qty, self.backed_line.qty)
        self.assertEqual(li.price, self.backed_line.price)

    def test_backed_line_mirrors_claims_for_billable_atoms_only(self):
        inv = self._seeded()
        li = inv.invoicelineitem_set.get(agreement_estimate_line=self.backed_line)
        types = set(li.sources.values_list('source_type', flat=True))
        self.assertEqual(types, {'task'})
        # the unconsumed material was NOT claimed
        self.assertFalse(li.sources.filter(source_type='material').exists())

    def test_hand_line_seeds_without_claims(self):
        inv = self._seeded()
        li = inv.invoicelineitem_set.get(agreement_estimate_line=self.hand_line)
        self.assertFalse(li.sources.exists())

    def test_adjustment_line_seeds_with_snapshot_percent(self):
        inv = self._seeded()
        li = inv.invoicelineitem_set.get(agreement_estimate_line=self.adj_line)
        self.assertEqual(li.adjustment_percent, self.adj_line.adjustment_percent)

    def test_seeded_adjustment_amount_uses_targeted_subtotal_only(self):
        # adj_line is line 3 (last) — the ordering bug this guards against
        # (M2M set after LineItemService.save_line_item's premature
        # recompute) only shows up when the adjustment line is the last one
        # processed, which is the normal compose_agreement ordering.
        inv = self._seeded()
        li = inv.invoicelineitem_set.get(agreement_estimate_line=self.adj_line)
        self.assertEqual(li.price, Decimal('20.00'))

    def test_restored_adjustment_amount_uses_targeted_subtotal_only(self):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceService.restore_agreement_line(
            inv, estimate_line_id=self.backed_line.pk)
        InvoiceService.restore_agreement_line(
            inv, estimate_line_id=self.hand_line.pk)
        InvoiceService.restore_agreement_line(
            inv, estimate_line_id=self.adj_line.pk)
        li = inv.invoicelineitem_set.get(agreement_estimate_line=self.adj_line)
        self.assertEqual(li.price, Decimal('20.00'))

    def test_seed_skips_atom_already_claimed_by_another_live_invoice(self):
        # A backed line's task atom was billed directly on an earlier
        # invoice (e.g. the defer -> bill-the-atom-directly -> next-invoice
        # path). Seeding a later draft from the agreement must not try to
        # re-claim it: InvoiceLineItemSource is globally unique on
        # (source_type, source_pk), so a naive re-claim would IntegrityError
        # and abort the whole seed. The line still arrives (referenced) but
        # unclaimed for that atom — the designed fallback.
        other_inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_OPEN)
        other_li = InvoiceLineItem.objects.create(
            invoice=other_inv, line_number=1, qty=Decimal('2'), units='hour',
            description='Billed directly', price=Decimal('100.00'),
            accounting_category=self.cat,
        )
        from apps.invoicing.models import InvoiceLineItemSource
        InvoiceLineItemSource.objects.create(
            invoice_line_item=other_li,
            source_type=InvoiceLineItemSource.SOURCE_TASK,
            source_pk=self.task.pk,
        )

        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        n = InvoiceService.seed_from_agreement(inv)
        self.assertEqual(n, 3)
        li = inv.invoicelineitem_set.get(agreement_estimate_line=self.backed_line)
        self.assertFalse(li.sources.filter(source_type='task').exists())

    def test_seed_skips_dangling_source_row(self):
        # An EstimateLineItemSource whose atom was deleted before its row
        # was purged (bad pre-existing data, same shape covered by
        # tests.test_source_row_purge_on_atom_delete's serializer tests)
        # must not 500 the seed — src.resolve() raises ObjectDoesNotExist
        # and that source is simply skipped.
        EstimateLineItemSource.objects.create(
            estimate_line_item=self.backed_line,
            source_type=EstimateLineItemSource.SOURCE_MATERIAL,
            source_pk=999999,
        )
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        n = InvoiceService.seed_from_agreement(inv)
        self.assertEqual(n, 3)
        li = inv.invoicelineitem_set.get(agreement_estimate_line=self.backed_line)
        self.assertFalse(li.sources.filter(source_pk=999999).exists())

    # ── restore_agreement_line double-click guard ───────────────────────

    def test_restoring_the_same_line_twice_raises_without_duplicating(self):
        inv = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        InvoiceService.restore_agreement_line(
            inv, estimate_line_id=self.hand_line.pk)
        with self.assertRaises(ValidationError):
            InvoiceService.restore_agreement_line(
                inv, estimate_line_id=self.hand_line.pk)
        self.assertEqual(
            inv.invoicelineitem_set.filter(
                agreement_estimate_line=self.hand_line).count(),
            1,
        )

    # ── remove_line ──────────────────────────────────────────────────────

    def test_remove_line_releases_reference_and_claims(self):
        inv = self._seeded()
        li = inv.invoicelineitem_set.get(agreement_estimate_line=self.backed_line)
        InvoiceService.remove_line(inv, li)
        self.assertIn(
            self.backed_line.pk,
            [l['estimate_line_id']
             for l in InvoiceService.remaining_agreement_lines(self.job)],
        )

    # ── the one-live-invoice invariant ──────────────────────────────────

    def test_agreement_line_on_at_most_one_live_invoice(self):
        inv1 = self._seeded()          # references all three lines
        # one-draft-per-job is DB-enforced: flip inv1 to open first so a
        # second draft can exist.
        self._send(inv1)
        inv2 = Invoice.objects.create(job=self.job, status=Invoice.STATUS_DRAFT)
        with self.assertRaises(ValidationError):
            InvoiceService.restore_agreement_line(
                inv2, estimate_line_id=self.backed_line.pk)

    def test_cancelled_invoice_releases_references(self):
        inv1 = self._seeded()
        self._send(inv1)
        InvoiceService.cancel(inv1.pk)
        self.assertEqual(
            len(InvoiceService.remaining_agreement_lines(self.job)), 3)

    # ── remaining_agreement_lines ────────────────────────────────────────

    def test_remaining_excludes_lines_already_held_by_a_live_invoice(self):
        # A line already on a live invoice — including the invoice that
        # holds it — must not reappear as "remaining". (Regression guard:
        # remaining_agreement_lines used to accept an exclude_invoice kwarg
        # that made the excluded invoice's OWN held lines reappear, the
        # opposite of what a restore picker or seed_from_agreement needs.)
        self._seeded()  # a single draft now holds all three agreement lines
        self.assertEqual(InvoiceService.remaining_agreement_lines(self.job), [])
